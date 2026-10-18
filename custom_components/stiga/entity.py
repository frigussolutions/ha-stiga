"""Base entity for STIGA."""

from __future__ import annotations

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import StigaCoordinator


class StigaEntity(CoordinatorEntity[StigaCoordinator]):
    """Entity bound to one robot."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: StigaCoordinator, key: str) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.uuid}_{key}"
        self._attr_device_info = coordinator.device_info

    @property
    def available(self) -> bool:
        """Available while the robot reports in."""
        return self.coordinator.available
