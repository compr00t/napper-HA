"""Text platform for Napper ('Uhrzeit' absolute time input for actions, e.g. '17:37')."""

from __future__ import annotations

from homeassistant.components.text import TextEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import NapperCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Napper text entities for each child."""
    coordinator: NapperCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [
        NapperAbsoluteTimeText(coordinator, baby_id)
        for baby_id in coordinator.babies
    ]
    async_add_entities(entities)


class NapperAbsoluteTimeText(CoordinatorEntity[NapperCoordinator], TextEntity):
    """Text entity representing an absolute time ('HH:MM', e.g. '17:37') when pressing action buttons."""

    _attr_has_entity_name = True
    _attr_name = "Uhrzeit"
    _attr_icon = "mdi:clock-edit-outline"
    _attr_native_min = 0
    _attr_native_max = 8
    _attr_pattern = r"^([01]?[0-9]|2[0-3]):[0-5][0-9](:[0-5][0-9])?$|^$"

    def __init__(self, coordinator: NapperCoordinator, baby_id: str) -> None:
        """Initialize the text entity."""
        super().__init__(coordinator)
        self._baby_id = baby_id
        self._attr_unique_id = f"{baby_id}_absolute_time_input"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info for this child."""
        baby = self.coordinator.babies.get(self._baby_id, {})
        return DeviceInfo(
            identifiers={(DOMAIN, self._baby_id)},
            name=baby.get("name", f"Baby {self._baby_id}"),
            manufacturer="Napper",
            model="Baby Schlafprofil",
        )

    @property
    def native_value(self) -> str:
        """Return the current absolute time string ('HH:MM' or '')."""
        return self.coordinator.get_absolute_time(self._baby_id)

    async def async_set_value(self, value: str) -> None:
        """Update the absolute time string for this child."""
        self.coordinator.set_absolute_time(self._baby_id, value)
