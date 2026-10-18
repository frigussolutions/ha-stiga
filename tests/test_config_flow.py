from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType

from custom_components.stiga.const import DOMAIN, STIGA_API_URL


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


async def test_attribution_shown_during_and_after_setup(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["description_placeholders"] == {"stiga_api_url": STIGA_API_URL}

    with patch(
        "custom_components.stiga.config_flow.StigaConfigFlow._async_validate", return_value=None
    ), patch("custom_components.stiga.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"email": "a@b.c", "password": "x"}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["description_placeholders"] == {"stiga_api_url": STIGA_API_URL}
