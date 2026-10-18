"""Client certificate of the STIGA.GO app, which the robot broker requires.

The certificate is not shipped with this integration. It is taken, in order of preference, from:
1. <config>/stiga/client.crt + client.key (extracted from the APK by the user), or
2. a one-time download of the stiga-api project's copy, pinned to a commit and SHA-256 checked,
   then kept in Home Assistant's storage so later starts need no network.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
import re

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store

from .api import CannotConnect, StigaError

_LOGGER = logging.getLogger(__name__)

UPSTREAM_COMMIT = "9e27147e3c7fe145f9bcf090bee0906534185e0d"
UPSTREAM_URL = (
    "https://raw.githubusercontent.com/matthewgream/stiga-api/"
    f"{UPSTREAM_COMMIT}/api/StigaAPICertificates.js"
)
UPSTREAM_SHA256 = "b7678b28849c139e10b94b1f0ee3a2e906206f33469c485c4d6726e175a9de12"

STORAGE_KEY = "stiga.client_certificate"
STORAGE_VERSION = 1


def _read_manual(directory: Path) -> tuple[str, str] | None:
    cert, key = directory / "client.crt", directory / "client.key"
    if cert.is_file() and key.is_file():
        return cert.read_text(), key.read_text()
    return None


def _parse_upstream(source: str) -> tuple[str, str]:
    cert = re.search(r"clientCert: `(-----BEGIN CERTIFICATE-----.*?)`", source, re.S)
    key = re.search(r"clientKey: `(-----BEGIN [A-Z ]*PRIVATE KEY-----.*?)`", source, re.S)
    if not cert or not key:
        raise StigaError("Client certificate not found in the downloaded file")
    return cert.group(1) + "\n", key.group(1) + "\n"


async def async_get_client_certificate(hass: HomeAssistant) -> tuple[str, str]:
    """Return (certificate PEM, private key PEM)."""
    if manual := await hass.async_add_executor_job(_read_manual, Path(hass.config.path("stiga"))):
        return manual

    store: Store[dict[str, str]] = Store(hass, STORAGE_VERSION, STORAGE_KEY, private=True)
    if (cached := await store.async_load()) and cached.get("commit") == UPSTREAM_COMMIT:
        return cached["cert"], cached["key"]

    _LOGGER.info("Downloading the STIGA.GO client certificate from %s", UPSTREAM_URL)
    try:
        async with async_get_clientsession(hass).get(
            UPSTREAM_URL, timeout=aiohttp.ClientTimeout(total=30)
        ) as resp:
            resp.raise_for_status()
            body = await resp.read()
    except (aiohttp.ClientError, TimeoutError) as err:
        raise CannotConnect(f"Client certificate download failed: {err}") from err
    if hashlib.sha256(body).hexdigest() != UPSTREAM_SHA256:
        raise StigaError("Downloaded client certificate failed its SHA-256 check")

    cert, key = _parse_upstream(body.decode())
    await store.async_save({"commit": UPSTREAM_COMMIT, "cert": cert, "key": key})
    return cert, key
