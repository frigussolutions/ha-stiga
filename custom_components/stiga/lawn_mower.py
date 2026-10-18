"""Lawn mower entity for STIGA."""

from __future__ import annotations

from homeassistant.components.lawn_mower import (
    LawnMowerActivity,
    LawnMowerEntity,
    LawnMowerEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import StigaConfigEntry
from .entity import StigaEntity
from .protocol import (
    ACTIVITY_ERROR,
    ACTIVITY_HOME,
    ACTIVITY_MOWING,
    ACTIVITY_RETURNING,
    CMD_GO_HOME,
    CMD_START,
    CMD_STOP,
)

ACTIVITY_MAP = {
    ACTIVITY_HOME: LawnMowerActivity.DOCKED,
    ACTIVITY_MOWING: LawnMowerActivity.MOWING,
    ACTIVITY_RETURNING: LawnMowerActivity.RETURNING,
    ACTIVITY_ERROR: LawnMowerActivity.ERROR,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: StigaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the mower entities."""
    async_add_entities(StigaLawnMower(coordinator) for coordinator in entry.runtime_data)


class StigaLawnMower(StigaEntity, LawnMowerEntity):
    """The robot itself."""

    _attr_name = None
    _attr_supported_features = (
        LawnMowerEntityFeature.START_MOWING
        | LawnMowerEntityFeature.PAUSE
        | LawnMowerEntityFeature.DOCK
    )

    def __init__(self, coordinator) -> None:
        """Initialize."""
        super().__init__(coordinator, "mower")

    @property
    def activity(self) -> LawnMowerActivity | None:
        """Current activity; rain pause and updating map to docked or paused."""
        state = self.coordinator.data
        if (activity := state.activity) is None:
            return None
        if activity in ACTIVITY_MAP:
            return ACTIVITY_MAP[activity]
        return LawnMowerActivity.DOCKED if state.docked else LawnMowerActivity.PAUSED

    async def async_start_mowing(self) -> None:
        """Start mowing now, regardless of the schedule."""
        await self.coordinator.async_send_command(CMD_START)

    async def async_pause(self) -> None:
        """Stop where it is."""
        await self.coordinator.async_send_command(CMD_STOP)

    async def async_dock(self) -> None:
        """Return to the charging station."""
        await self.coordinator.async_send_command(CMD_GO_HOME)
