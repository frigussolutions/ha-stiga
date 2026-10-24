from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.stiga.api import CERT_DIR, PINNED_BROKERS, UnknownBroker, _build_ssl_context
from custom_components.stiga.const import DOMAIN

ROBOT = {"mac_address": "3C:22:7F:00:00:01", "broker_id": "broker9"}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


def test_pinned_brokers_match_shipped_cas():
    assert {p.stem.removeprefix("ca_") for p in CERT_DIR.glob("ca_*.pem")} == PINNED_BROKERS


def test_no_unverified_tls():
    with pytest.raises(UnknownBroker):
        _build_ssl_context("broker9", ("", ""))


async def test_setup_refuses_unknown_broker(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={"email": "a@b.c", "password": "x"})
    entry.add_to_hass(hass)
    with patch(
        "custom_components.stiga.StigaAuth.async_get_robots", AsyncMock(return_value=[ROBOT])
    ), patch("custom_components.stiga.StigaCoordinator") as coordinator:
        await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert "broker9" in entry.reason
    coordinator.assert_not_called()


async def test_config_flow_refuses_unknown_broker(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with patch(
        "custom_components.stiga.config_flow.StigaAuth.async_get_robots",
        AsyncMock(return_value=[ROBOT]),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"email": "a@b.c", "password": "x"}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "unknown_broker"}
