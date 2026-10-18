"""Schedule block switches for STIGA: one per weekday and configured block."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import StigaConfigEntry
from .coordinator import StigaCoordinator
from .entity import StigaEntity
from .protocol import WEEKDAYS, ScheduleBlock, schedule_block_enabled


async def async_setup_entry(
    hass: HomeAssistant,
    entry: StigaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one switch per weekday and block; drop switches of removed blocks."""
    entities = [
        StigaScheduleBlock(coordinator, day, block)
        for coordinator in entry.runtime_data
        for day in range(len(WEEKDAYS))
        for block in coordinator.data.blocks
    ]
    wanted = {entity.unique_id for entity in entities}
    registry = er.async_get(hass)
    for reg_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        if reg_entry.domain == "switch" and reg_entry.unique_id not in wanted:
            registry.async_remove(reg_entry.entity_id)
    async_add_entities(entities)


class StigaScheduleBlock(StigaEntity, SwitchEntity):
    """One block (e.g. Monday morning) of the weekly schedule."""

    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator: StigaCoordinator, day: int, block: ScheduleBlock) -> None:
        """Initialize."""
        super().__init__(coordinator, f"schedule_{WEEKDAYS[day]}_{block.key}")
        self._day = day
        self._block = block
        self._attr_name = f"{WEEKDAYS[day].capitalize()} {block.name.lower()}"

    @property
    def is_on(self) -> bool | None:
        """Every slot of the block is scheduled."""
        values = self.coordinator.data.schedule_bytes
        if values is None:
            return None
        return schedule_block_enabled(values, self._day, self._block.slots)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Mow in this block."""
        await self.coordinator.async_set_schedule_block(self._day, self._block, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Don't mow in this block."""
        await self.coordinator.async_set_schedule_block(self._day, self._block, False)
