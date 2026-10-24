"""Per-robot coordinator: holds the MQTT session and merges pushed status."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import datetime
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .api import StigaAuth, StigaError, StigaMqtt, robot_broker
from .const import (
    COMMAND_ACK_TIMEOUT,
    CONF_BLOCKS,
    DOMAIN,
    IDLE_POLL_TICKS,
    STALE_AFTER,
    TICK_INTERVAL,
)
from .protocol import (
    ACK_OK,
    ACTIVITY_CALIBRATING,
    CMD_CALIBRATE_BLADES,
    CMD_SCHEDULING_SETTINGS_REQUEST,
    CMD_SCHEDULING_SETTINGS_UPDATE,
    CMD_SETTINGS_REQUEST,
    CMD_SETTINGS_UPDATE,
    CMD_STATUS_REQUEST,
    DEFAULT_BLOCKS,
    STATUS_REQUEST_ALL,
    ScheduleBlock,
    StigaState,
    encode_command,
    pb_decode,
    with_schedule_block,
)

_LOGGER = logging.getLogger(__name__)

# LOG/* replies we ask for; each is acknowledged on <topic>/ACK once received.
LOG_REQUESTS = {
    "STATUS": (CMD_STATUS_REQUEST, STATUS_REQUEST_ALL),
    "SETTINGS": (CMD_SETTINGS_REQUEST, None),
    "SCHEDULING_SETTINGS": (CMD_SCHEDULING_SETTINGS_REQUEST, None),
}


def blocks_from_options(options: Mapping[str, Any]) -> tuple[ScheduleBlock, ...]:
    """Schedule blocks configured in the options, or the 9-13 / 13-17 defaults."""
    if (blocks := options.get(CONF_BLOCKS)) is None:
        return DEFAULT_BLOCKS
    return tuple(ScheduleBlock(**block) for block in blocks)


class StigaCoordinator(DataUpdateCoordinator[StigaState]):
    """Push-driven coordinator for one robot."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        auth: StigaAuth,
        client_cert: tuple[str, str],
        robot: dict[str, Any],
    ) -> None:
        """Initialize."""
        super().__init__(hass, _LOGGER, config_entry=entry, name=f"{DOMAIN} {robot['mac_address']}")
        self.auth = auth
        self.mac: str = robot["mac_address"]
        self.uuid: str = robot.get("uuid") or self.mac
        self.device_info = DeviceInfo(
            identifiers={(DOMAIN, self.uuid)},
            manufacturer="STIGA",
            name=robot.get("name") or "STIGA robot",
            model=robot.get("product_code"),
            serial_number=robot.get("serial_number"),
            sw_version=robot.get("firmware_version"),
        )
        self.data = StigaState(blocks=blocks_from_options(entry.options))
        self._mqtt = StigaMqtt(
            hass,
            robot_broker(robot),
            client_cert,
            [f"{self.mac}/LOG/+", f"CMD_ROBOT_ACK/{self.mac}"],
            self._handle_message,
            self._handle_connected,
        )
        self._pending_logs: set[str] = set()
        self._ack_waiters: dict[int, asyncio.Future[int]] = {}
        self._command_lock = asyncio.Lock()
        self._schedule_lock = asyncio.Lock()
        self._ticks = 0
        self._unsub_tick: CALLBACK_TYPE | None = None

    async def _async_update_data(self) -> StigaState:
        """Data arrives by push; nothing to fetch."""
        return self.data

    async def async_start(self) -> None:
        """Connect to the broker and start the status request timer."""
        await self._mqtt.async_connect(await self.auth.async_get_token())
        self._unsub_tick = async_track_time_interval(self.hass, self._async_tick, TICK_INTERVAL)

    async def async_stop(self) -> None:
        """Disconnect."""
        if self._unsub_tick:
            self._unsub_tick()
            self._unsub_tick = None
        await self._mqtt.async_disconnect()

    @property
    def available(self) -> bool:
        """Connected and the last status is recent."""
        updated = self.data.status_updated
        return self._mqtt.connected and updated is not None and dt_util.utcnow() - updated < STALE_AFTER

    async def _async_tick(self, now: datetime) -> None:
        if self.auth.needs_refresh:
            try:
                self._mqtt.update_token(await self.auth.async_get_token())
            except StigaError as err:
                _LOGGER.warning("STIGA token refresh failed: %s", err)
        self._ticks += 1
        if self.data.is_active or self._ticks % IDLE_POLL_TICKS == 0:
            self._request("STATUS")
        if self._ticks % 60 == 0:
            self._request("SETTINGS")
            self._request("SCHEDULING_SETTINGS")
        # Re-evaluate availability even when nothing arrives.
        self.async_update_listeners()

    @callback
    def _request(self, log: str) -> None:
        command, fields = LOG_REQUESTS[log]
        self._pending_logs.add(log)
        self._mqtt.publish(f"{self.mac}/CMD_ROBOT", encode_command(command, fields))

    @callback
    def _handle_connected(self) -> None:
        _LOGGER.debug("Connected to STIGA broker for %s", self.mac)
        for log in LOG_REQUESTS:
            self._request(log)

    @callback
    def _handle_message(self, topic: str, payload: bytes) -> None:
        try:
            decoded = pb_decode(payload) if payload and payload[0] else {}
        except (ValueError, IndexError) as err:
            _LOGGER.debug("Undecodable STIGA message on %s: %s (%s)", topic, payload.hex(), err)
            return
        if topic.startswith("CMD_ROBOT_ACK/"):
            if (waiter := self._ack_waiters.pop(decoded.get(1, 0), None)) and not waiter.done():
                waiter.set_result(decoded.get(2, 0))
            return
        log = topic.split("/LOG/", 1)[-1]
        if log in self._pending_logs:
            self._pending_logs.discard(log)
            self._mqtt.publish(f"{topic}/ACK", b"\x00")
        _LOGGER.debug("STIGA %s: %s", log, decoded)
        if log == "STATUS":
            self.data.apply_status(decoded, dt_util.utcnow())
        elif log == "SETTINGS":
            self.data.apply_settings(decoded)
        elif log == "SCHEDULING_SETTINGS":
            try:
                self.data.apply_scheduling_settings(decoded, payload)
            except (ValueError, IndexError) as err:
                _LOGGER.warning("Unexpected STIGA schedule %s: %s", payload.hex(), err)
                return
        else:
            return
        self.async_set_updated_data(self.data)

    async def async_send_command(
        self, command: int, fields: dict[int, Any] | None = None, refresh: str = "STATUS"
    ) -> None:
        """Send a robot command, wait for its acknowledgement, then re-read `refresh`."""
        if not self._mqtt.connected:
            raise HomeAssistantError("Not connected to the STIGA cloud")
        # One command in flight: ACKs only carry the command id.
        async with self._command_lock:
            waiter: asyncio.Future[int] = self.hass.loop.create_future()
            self._ack_waiters[command] = waiter
            self._mqtt.publish(f"{self.mac}/CMD_ROBOT", encode_command(command, fields))
            try:
                async with asyncio.timeout(COMMAND_ACK_TIMEOUT):
                    result = await waiter
            except TimeoutError as err:
                raise HomeAssistantError("The mower did not acknowledge the command") from err
            finally:
                self._ack_waiters.pop(command, None)
        if result != ACK_OK:
            raise HomeAssistantError(f"The mower rejected the command (result {result})")
        # Pick up the new state once the robot has acted on it.
        async_call_later(self.hass, 5, callback(lambda _now: self._request(refresh)))

    async def async_set_cutting_height(self, height_mm: int) -> None:
        """Change the cutting height (home only), then recalibrate the blades."""
        if not self.data.docked:
            raise HomeAssistantError("Blade height can only be changed while the mower is home")
        if self.data.activity == ACTIVITY_CALIBRATING:
            raise HomeAssistantError("Blade calibration is still running")
        try:
            settings = self.data.settings_with_cutting_height(height_mm)
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err
        await self.async_send_command(CMD_SETTINGS_UPDATE, settings, refresh="SETTINGS")
        self.data.apply_settings(settings)
        self.async_set_updated_data(self.data)
        # A new height needs a blade calibration, done in the dock.
        await self.async_send_command(CMD_CALIBRATE_BLADES)

    async def async_set_schedule_block(self, day: int, block: ScheduleBlock, enabled: bool) -> None:
        """Switch one schedule block of one weekday on or off."""
        async with self._schedule_lock:
            values = self.data.schedule_bytes
            if values is None:
                raise HomeAssistantError("Schedule not received yet")
            new = with_schedule_block(values, day, block.slots, enabled)
            try:
                scheduling = self.data.scheduling_with_bytes(new)
            except ValueError as err:
                raise HomeAssistantError(str(err)) from err
            await self.async_send_command(
                CMD_SCHEDULING_SETTINGS_UPDATE, scheduling, refresh="SCHEDULING_SETTINGS"
            )
            # Optimistic, so a quick second toggle builds on this one.
            self.data.schedule_bytes = new
            self.async_set_updated_data(self.data)
