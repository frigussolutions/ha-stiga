"""Sensors for STIGA."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import StigaConfigEntry
from .coordinator import StigaCoordinator
from .entity import StigaEntity
from .protocol import ACTIVITIES, StigaState

NO_ERROR = "No error"


@dataclass(frozen=True, kw_only=True)
class StigaSensorDescription(SensorEntityDescription):
    """Sensor description with a value getter."""

    value_fn: Callable[[StigaState], Any]
    attrs_fn: Callable[[StigaState], dict[str, Any]] | None = None


SENSORS: tuple[StigaSensorDescription, ...] = (
    StigaSensorDescription(
        key="status",
        translation_key="status",
        device_class=SensorDeviceClass.ENUM,
        options=ACTIVITIES,
        value_fn=lambda s: s.activity,
        attrs_fn=lambda s: {
            "robot_state": s.robot_state,
            "docked": s.docked,
            "rain_detected": s.rain_detected,
            "rain_sensor_enabled": s.rain_sensor_enabled,
            "rain_delay_hours": s.rain_delay_hours,
            "schedule_enabled": s.schedule_enabled,
            "last_status": s.status_updated,
        },
    ),
    StigaSensorDescription(
        key="error",
        translation_key="error",
        value_fn=lambda s: s.error_message or NO_ERROR,
        attrs_fn=lambda s: {
            "error_code": f"{s.error[0]}/{s.error[1]}" if s.error else None,
            "info_code": f"0x{s.info_code:04X}" if s.info_code is not None else None,
            "intervention_required": s.intervention_required,
        },
    ),
    StigaSensorDescription(
        key="battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.battery,
    ),
    StigaSensorDescription(
        key="garden_coverage",
        translation_key="garden_coverage",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.garden_completed,
    ),
    StigaSensorDescription(
        key="zone_coverage",
        translation_key="zone_coverage",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.zone_completed,
        attrs_fn=lambda s: {"zone": s.zone},
    ),
    StigaSensorDescription(
        key="schedule",
        translation_key="schedule",
        value_fn=lambda s: s.schedule_summary,
        attrs_fn=lambda s: {
            "enabled": s.schedule_enabled,
            **(s.schedule or {}),
            "blocks": [block.as_dict() for block in s.blocks],
        },
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: StigaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors."""
    async_add_entities(
        StigaSensor(coordinator, description)
        for coordinator in entry.runtime_data
        for description in SENSORS
    )


class StigaSensor(StigaEntity, SensorEntity):
    """A STIGA sensor."""

    entity_description: StigaSensorDescription

    def __init__(self, coordinator: StigaCoordinator, description: StigaSensorDescription) -> None:
        """Initialize."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        """Sensor value."""
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Extra attributes."""
        if self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.coordinator.data)
