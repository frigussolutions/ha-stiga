from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.components.lovelace.resources import ResourceStorageCollection

from custom_components.stiga import frontend


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def setup(hass):
    hass.http = SimpleNamespace(async_register_static_paths=AsyncMock())
    hass.config.components.add("frontend")

    def with_resources(urls):
        resources = ResourceStorageCollection(hass, SimpleNamespace(async_load=AsyncMock(return_value={})))
        resources.async_load = AsyncMock()
        resources.loaded = True
        for index, url in enumerate(urls):
            resources.data[str(index)] = {"id": str(index), "type": "module", "url": url}
        hass.data[LOVELACE_DATA] = SimpleNamespace(resource_mode="storage", resources=resources)
        return resources

    return with_resources


async def _version(hass):
    from homeassistant.loader import async_get_integration
    return (await async_get_integration(hass, "stiga")).version


async def test_registers_resource(hass, setup):
    resources = setup(["/local/other-card.js"])
    await frontend.async_register_card(hass)
    urls = [item["url"] for item in resources.async_items()]
    assert urls == ["/local/other-card.js", f"/stiga_static/stiga-schedule-card.js?v={await _version(hass)}"]
    hass.http.async_register_static_paths.assert_awaited_once()


async def test_takes_over_legacy_and_stale_resources(hass, setup):
    for old in ("/local/stiga-schedule-card.js?v=1", "/stiga_static/stiga-schedule-card.js?v=0.0.1"):
        resources = setup([old])
        await frontend.async_register_card(hass)
        assert [item["url"] for item in resources.async_items()] == [
            f"/stiga_static/stiga-schedule-card.js?v={await _version(hass)}"
        ]


async def test_yaml_resources_fall_back_to_extra_js(hass, setup):
    setup([])
    hass.data[LOVELACE_DATA].resource_mode = "yaml"
    with patch.object(frontend, "add_extra_js_url") as add:
        await frontend.async_register_card(hass)
    add.assert_called_once()
    assert add.call_args[0][1].startswith("/stiga_static/stiga-schedule-card.js?v=")
