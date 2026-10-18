"""Number entities for STIGA."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import UnitOfLength
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import StigaConfigEntry
from .coordinator import StigaCoordinator
from .entity import StigaEntity
from .protocol import CUTTING_HEIGHT_MAX, CUTTING_HEIGHT_MIN, CUTTING_HEIGHT_STEP


async def async_setup_entry(
    hass: HomeAssistant,
    entry: StigaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the number entities."""
    async_add_entities(StigaCuttingHeight(coordinator) for coordinator in entry.runtime_data)


class StigaCuttingHeight(StigaEntity, NumberEntity):
    """Blade height for the whole garden."""

    _attr_translation_key = "cutting_height"
    _attr_native_min_value = CUTTING_HEIGHT_MIN
    _attr_native_max_value = CUTTING_HEIGHT_MAX
    _attr_native_step = CUTTING_HEIGHT_STEP
    _attr_native_unit_of_measurement = UnitOfLength.MILLIMETERS
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator: StigaCoordinator) -> None:
        """Initialize."""
        super().__init__(coordinator, "cutting_height")

    @property
    def native_value(self) -> int | None:
        """Current height."""
        return self.coordinator.data.cutting_height

    async def async_set_native_value(self, value: float) -> None:
        """Set a new height."""
        await self.coordinator.async_set_cutting_height(int(value))
