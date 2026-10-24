"""STIGA cloud access: Firebase login, garage REST call and the robot MQTT broker."""

from __future__ import annotations

from collections.abc import Callable
import logging
from pathlib import Path
import secrets
import ssl
import tempfile
import time
from typing import Any

import aiohttp
import paho.mqtt.client as mqtt

from homeassistant.core import HomeAssistant

from .const import (
    API_URL,
    FIREBASE_API_KEY,
    FIREBASE_AUTH_URL,
    MQTT_HOST,
    MQTT_PORT,
    MQTT_USERNAME,
)

_LOGGER = logging.getLogger(__name__)

CERT_DIR = Path(__file__).parent / "certs"
# Brokers whose self-signed CA is pinned in certs/ca_<broker>.pem. These are all the STIGA
# brokers that answer on the MQTT port; a robot on any other broker is refused.
PINNED_BROKERS = frozenset({"broker", "broker2", "broker3", "broker4"})
# Firebase answers these for a bad email/password; anything else is treated as transient.
AUTH_ERRORS = {
    "EMAIL_NOT_FOUND",
    "INVALID_EMAIL",
    "INVALID_LOGIN_CREDENTIALS",
    "INVALID_PASSWORD",
    "USER_DISABLED",
}
TOKEN_REFRESH_MARGIN = 600


class StigaError(Exception):
    """Base STIGA error."""


class CannotConnect(StigaError):
    """The STIGA cloud could not be reached."""


class InvalidAuth(StigaError):
    """The STIGA.GO credentials were rejected."""


class UnknownBroker(StigaError):
    """The robot's broker has no pinned CA, so its certificate cannot be verified."""


def robot_broker(robot: dict[str, Any]) -> str:
    """MQTT broker a robot from the garage is attached to."""
    return robot.get("broker_id") or "broker"


class StigaAuth:
    """Firebase ID token for the STIGA.GO account, renewed by logging in again."""

    def __init__(self, session: aiohttp.ClientSession, email: str, password: str) -> None:
        """Initialize."""
        self._session = session
        self._email = email
        self._password = password
        self._token: str | None = None
        self._expires = 0.0

    @property
    def needs_refresh(self) -> bool:
        """Token is missing or about to expire."""
        return self._token is None or time.monotonic() > self._expires - TOKEN_REFRESH_MARGIN

    async def async_get_token(self) -> str:
        """Return a valid ID token, logging in when needed."""
        if self.needs_refresh:
            await self._async_login()
        assert self._token is not None
        return self._token

    async def _async_login(self) -> None:
        payload = {"email": self._email, "password": self._password, "returnSecureToken": True}
        try:
            async with self._session.post(
                FIREBASE_AUTH_URL,
                params={"key": FIREBASE_API_KEY},
                json=payload,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                data = await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise CannotConnect(f"Login request failed: {err}") from err
        if resp.status != 200:
            message = str((data.get("error") or {}).get("message", ""))
            if message.split(" ")[0] in AUTH_ERRORS:
                raise InvalidAuth(message)
            raise CannotConnect(f"Login failed ({resp.status}): {message}")
        self._token = data["idToken"]
        self._expires = time.monotonic() + int(data.get("expiresIn", 3600))

    async def async_get_robots(self) -> list[dict[str, Any]]:
        """Return the attributes of every robot in the account's garage."""
        token = await self.async_get_token()
        try:
            async with self._session.get(
                f"{API_URL}/api/garage",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                if resp.status == 401:
                    raise InvalidAuth("Garage request unauthorized")
                resp.raise_for_status()
                garage = await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise CannotConnect(f"Garage request failed: {err}") from err
        return [
            item["attributes"]
            for item in garage.get("data", [])
            if item.get("type") == "devices" and item.get("attributes", {}).get("mac_address")
        ]


def _build_ssl_context(broker: str, client_cert: tuple[str, str]) -> ssl.SSLContext:
    """Client certificate from the STIGA.GO app; broker verified against its pinned CA."""
    if broker not in PINNED_BROKERS:
        raise UnknownBroker(f"No pinned CA for STIGA {broker}")
    ctx = ssl.create_default_context(cafile=str(CERT_DIR / f"ca_{broker}.pem"))
    # STIGA's CA lacks the key usage extension that strict mode (3.13+ default) demands.
    ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
    # ssl only loads a key pair from files: materialise them privately, just for the load.
    with tempfile.TemporaryDirectory(prefix="stiga_") as tmp:
        cert_file, key_file = Path(tmp) / "client.crt", Path(tmp) / "client.key"
        cert_file.write_text(client_cert[0])
        key_file.write_text(client_cert[1])
        ctx.load_cert_chain(str(cert_file), str(key_file))
    return ctx


class StigaMqtt:
    """Paho client on its own thread; callbacks are marshalled onto the HA loop."""

    def __init__(
        self,
        hass: HomeAssistant,
        broker: str,
        client_cert: tuple[str, str],
        topics: list[str],
        on_message: Callable[[str, bytes], None],
        on_connected: Callable[[], None],
    ) -> None:
        """Initialize."""
        self._hass = hass
        self._broker = broker
        self._client_cert = client_cert
        self._topics = topics
        self._on_message = on_message
        self._on_connected = on_connected
        self._client: mqtt.Client | None = None
        self.connected = False

    async def async_connect(self, token: str) -> None:
        """Start connecting in the background; paho keeps reconnecting by itself."""
        ctx = await self._hass.async_add_executor_job(
            _build_ssl_context, self._broker, self._client_cert
        )
        client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"ha_stiga_{secrets.token_hex(4)}",
            clean_session=True,
        )
        client.username_pw_set(MQTT_USERNAME, token)
        client.tls_set_context(ctx)
        client.reconnect_delay_set(min_delay=5, max_delay=300)
        client.enable_logger(_LOGGER)
        client.on_connect = self._handle_connect
        client.on_disconnect = self._handle_disconnect
        client.on_message = self._handle_message
        self._client = client
        client.connect_async(MQTT_HOST.format(broker=self._broker), MQTT_PORT, keepalive=60)
        client.loop_start()

    def update_token(self, token: str) -> None:
        """Use a fresh token as broker password from the next (re)connect on."""
        if self._client is not None:
            self._client.username_pw_set(MQTT_USERNAME, token)

    async def async_disconnect(self) -> None:
        """Stop the client thread."""
        if (client := self._client) is None:
            return
        self._client = None
        self.connected = False

        def _stop() -> None:
            client.disconnect()
            client.loop_stop()

        await self._hass.async_add_executor_job(_stop)

    def publish(self, topic: str, payload: bytes) -> None:
        """Publish with QoS 2, like the app."""
        if self._client is not None:
            self._client.publish(topic, payload, qos=2)

    def _handle_connect(self, client, userdata, flags, reason_code, properties) -> None:
        if reason_code.is_failure:
            _LOGGER.warning("STIGA broker refused connection: %s", reason_code)
            return
        for topic in self._topics:
            client.subscribe(topic, qos=0)
        self.connected = True
        self._hass.loop.call_soon_threadsafe(self._on_connected)

    def _handle_disconnect(self, client, userdata, flags, reason_code, properties) -> None:
        if self.connected:
            _LOGGER.info("Disconnected from STIGA broker: %s", reason_code)
        self.connected = False

    def _handle_message(self, client, userdata, message: mqtt.MQTTMessage) -> None:
        self._hass.loop.call_soon_threadsafe(self._on_message, message.topic, bytes(message.payload))
