"""Time platform for Napper ('Uhrzeit' time selector for actions, e.g. 17:37)."""

from __future__ import annotations

import datetime

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
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
    """Set up Napper time selector entities for each child."""
    coordinator: NapperCoordinator = hass.data[DOMAIN][entry.entry_id]
    ent_reg = er.async_get(hass)
    entities: list[TimeEntity] = []
    for baby_id in coordinator.babies:
        # Clean up legacy text entity if present in registry
        old_text_entity = ent_reg.async_get_entity_id(
            "text", DOMAIN, f"{baby_id}_absolute_time_input"
        )
        if old_text_entity:
            ent_reg.async_remove(old_text_entity)

        entities.append(NapperAbsoluteTimeEntity(coordinator, baby_id))
    async_add_entities(entities)


class NapperAbsoluteTimeEntity(CoordinatorEntity[NapperCoordinator], TimeEntity):
    """Time selector entity representing an absolute time (e.g. 17:37) when pressing action buttons."""

    _attr_has_entity_name = True
    _attr_name = "Uhrzeit"
    _attr_icon = "mdi:clock-edit-outline"

    def __init__(self, coordinator: NapperCoordinator, baby_id: str) -> None:
        """Initialize the time entity."""
        super().__init__(coordinator)
        self._baby_id = baby_id
        self._attr_unique_id = f"{baby_id}_absolute_time"

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
    def native_value(self) -> datetime.time | None:
        """Return the currently selected time (or None if not set)."""
        return self.coordinator.get_absolute_time_obj(self._baby_id)

    async def async_set_value(self, value: datetime.time) -> None:
        """Set the target time for the next action button press."""
        self.coordinator.set_absolute_time(self._baby_id, value.strftime("%H:%M"))
