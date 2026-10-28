"""Number platform for Napper ('Zeitdifferenz' time offset for actions)."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
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
    """Set up Napper number entities for each child."""
    coordinator: NapperCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [
        NapperMinutesAgoNumber(coordinator, baby_id)
        for baby_id in coordinator.babies
    ]
    async_add_entities(entities)


class NapperMinutesAgoNumber(CoordinatorEntity[NapperCoordinator], NumberEntity):
    """Number entity representing 'Zeitdifferenz' (minutes in the past) when pressing action buttons."""

    _attr_has_entity_name = True
    _attr_name = "Zeitdifferenz"
    _attr_icon = "mdi:history"
    _attr_native_min_value = 0
    _attr_native_max_value = 120
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator: NapperCoordinator, baby_id: str) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator)
        self._baby_id = baby_id
        self._attr_unique_id = f"{baby_id}_minutes_ago_offset"

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
    def native_value(self) -> float:
        """Return the current offset in minutes."""
        return float(self.coordinator.get_minutes_ago(self._baby_id))

    async def async_set_native_value(self, value: float) -> None:
        """Update the minutes-ago offset for this child."""
        self.coordinator.set_minutes_ago(self._baby_id, int(value))
