"""Binary sensor platform for Napper (Schläft gerade)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
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
    """Set up Napper binary sensors."""
    coordinator: NapperCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [
        NapperSleepingBinarySensor(coordinator, baby_id)
        for baby_id in coordinator.babies
    ]
    async_add_entities(entities)


class NapperSleepingBinarySensor(CoordinatorEntity[NapperCoordinator], BinarySensorEntity):
    """Binary sensor indicating whether the child is currently sleeping."""

    _attr_has_entity_name = True
    _attr_name = "Schläft gerade"
    _attr_icon = "mdi:sleep"

    def __init__(self, coordinator: NapperCoordinator, baby_id: str) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self._baby_id = baby_id
        self._attr_unique_id = f"{baby_id}_sleeping"

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

    def _get_open_sleep_log(self) -> dict[str, Any] | None:
        logs = self.coordinator.data.get(self._baby_id, {}).get("logs", [])
        for entry in logs:
            if entry.get("isOpen") and entry.get("category") in ("NAP", "BED_TIME"):
                return entry
        return None

    @property
    def is_on(self) -> bool:
        """Return true if an open NAP or BED_TIME timer is active."""
        summary = self.coordinator.data.get(self._baby_id, {}).get("summary", {})
        if "is_sleeping" in summary:
            return bool(summary["is_sleeping"])
        return self._get_open_sleep_log() is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return details about the active sleep session."""
        open_log = self._get_open_sleep_log()
        summary = self.coordinator.data.get(self._baby_id, {}).get("summary", {})
        if not open_log:
            return {
                "baby_id": self._baby_id,
                "schlafstatus": summary.get("sleep_state_de", "Wach"),
                "category": None,
                "log_id": None,
                "started_at": None,
            }
        return {
            "baby_id": self._baby_id,
            "schlafstatus": summary.get("sleep_state_de", "Schläft"),
            "category": open_log.get("category"),
            "log_id": open_log.get("id"),
            "started_at": open_log.get("start"),
            "pauses": open_log.get("pauses", []),
        }
