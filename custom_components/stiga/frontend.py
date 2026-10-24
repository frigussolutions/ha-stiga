"""Serve the schedule card from the integration and register it as a dashboard resource."""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.components.lovelace.const import LOVELACE_DATA, MODE_STORAGE
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

CARD_FILE = "stiga-schedule-card.js"
CARD_URL_BASE = f"/{DOMAIN}_static"
CARD_URL = f"{CARD_URL_BASE}/{CARD_FILE}"
# Where earlier versions told users to copy the card; such a resource is taken over.
LEGACY_CARD_URL = f"/local/{CARD_FILE}"


async def async_register_card(hass: HomeAssistant) -> None:
    """Serve www/ and make sure dashboards load the card, versioned to bust caches."""
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL_BASE, str(Path(__file__).parent / "www"), cache_headers=False)]
    )
    if "frontend" not in hass.config.components:
        return
    integration = await async_get_integration(hass, DOMAIN)
    url = f"{CARD_URL}?v={integration.version}"

    lovelace = hass.data.get(LOVELACE_DATA)
    if lovelace is None or lovelace.resource_mode != MODE_STORAGE:
        # YAML-mode resources cannot be changed at runtime: load the card on every page instead.
        add_extra_js_url(hass, url)
        return

    resources = lovelace.resources
    await resources.async_get_info()  # loads the stored resources
    for item in resources.async_items():
        if item["url"].split("?")[0] in (CARD_URL, LEGACY_CARD_URL):
            if item["url"] != url:
                _LOGGER.debug("Updating dashboard resource %s to %s", item["url"], url)
                await resources.async_update_item(item["id"], {"res_type": "module", "url": url})
            return
    _LOGGER.debug("Registering dashboard resource %s", url)
    await resources.async_create_item({"res_type": "module", "url": url})
