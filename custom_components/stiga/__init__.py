"""The STIGA robot mower integration (A-series, STIGA.GO cloud)."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryError, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import CannotConnect, InvalidAuth, StigaAuth, StigaError
from .certs import async_get_client_certificate
from .coordinator import StigaCoordinator

PLATFORMS = [Platform.LAWN_MOWER, Platform.NUMBER, Platform.SENSOR, Platform.SWITCH]

type StigaConfigEntry = ConfigEntry[list[StigaCoordinator]]


async def async_setup_entry(hass: HomeAssistant, entry: StigaConfigEntry) -> bool:
    """Set up STIGA from a config entry."""
    auth = StigaAuth(async_get_clientsession(hass), entry.data[CONF_EMAIL], entry.data[CONF_PASSWORD])
    try:
        robots = await auth.async_get_robots()
    except InvalidAuth as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except CannotConnect as err:
        raise ConfigEntryNotReady(str(err)) from err

    try:
        client_cert = await async_get_client_certificate(hass)
    except CannotConnect as err:
        raise ConfigEntryNotReady(str(err)) from err
    except StigaError as err:
        raise ConfigEntryError(str(err)) from err

    coordinators = [StigaCoordinator(hass, entry, auth, client_cert, robot) for robot in robots]
    for coordinator in coordinators:
        await coordinator.async_start()
    entry.runtime_data = coordinators

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Changed schedule blocks rebuild the switches.
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(hass: HomeAssistant, entry: StigaConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: StigaConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        for coordinator in entry.runtime_data:
            await coordinator.async_stop()
    return unloaded
