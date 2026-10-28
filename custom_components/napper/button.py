"""Button platform for Napper (Aufwachen, Nickerchen starten, Schlafen starten)."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
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
    """Set up Napper action buttons for each child."""
    coordinator: NapperCoordinator = hass.data[DOMAIN][entry.entry_id]
    ent_reg = er.async_get(hass)
    entities: list[ButtonEntity] = []
    for baby_id in coordinator.babies:
        # Clean up legacy 4th button ('stop_sleep') if present in registry
        old_entity_id = ent_reg.async_get_entity_id("button", DOMAIN, f"{baby_id}_stop_sleep")
        if old_entity_id:
            ent_reg.async_remove(old_entity_id)

        entities.extend(
            [
                NapperWakeUpButton(coordinator, baby_id),
                NapperStartNapButton(coordinator, baby_id),
                NapperStartSleepButton(coordinator, baby_id),
            ]
        )
    async_add_entities(entities)


class NapperBaseButton(CoordinatorEntity[NapperCoordinator], ButtonEntity):
    """Base button for Napper actions (uses the child's 'Zeitdifferenz' offset if > 0)."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: NapperCoordinator, baby_id: str, key: str) -> None:
        super().__init__(coordinator)
        self._baby_id = baby_id
        self._attr_unique_id = f"{baby_id}_{key}"

    @property
    def device_info(self) -> DeviceInfo:
        baby = self.coordinator.babies.get(self._baby_id, {})
        return DeviceInfo(
            identifiers={(DOMAIN, self._baby_id)},
            name=baby.get("name", f"Baby {self._baby_id}"),
            manufacturer="Napper",
            model="Baby Schlafprofil",
        )


class NapperWakeUpButton(NapperBaseButton):
    """Button to end whichever sleep (nap or night sleep) is currently running."""

    _attr_name = "Aufwachen"
    _attr_icon = "mdi:weather-sunset-up"

    def __init__(self, coordinator: NapperCoordinator, baby_id: str) -> None:
        super().__init__(coordinator, baby_id, "log_wake_up")

    @property
    def available(self) -> bool:
        """Only available when a nap or night sleep is currently active."""
        return super().available and self.coordinator.is_child_sleeping(self._baby_id)

    async def async_press(self) -> None:
        target_dt, minutes_ago = self.coordinator.pop_action_timing(self._baby_id)
        await self.coordinator.async_wake_up(
            self._baby_id, minutes_ago=minutes_ago, target_dt=target_dt
        )


class NapperStartNapButton(NapperBaseButton):
    """Button to start an open nap timer (only when child is not sleeping)."""

    _attr_name = "Nickerchen starten"
    _attr_icon = "mdi:play-circle-outline"

    def __init__(self, coordinator: NapperCoordinator, baby_id: str) -> None:
        super().__init__(coordinator, baby_id, "start_nap")

    @property
    def available(self) -> bool:
        """Only available when the child is not currently sleeping."""
        return super().available and not self.coordinator.is_child_sleeping(self._baby_id)

    async def async_press(self) -> None:
        target_dt, minutes_ago = self.coordinator.pop_action_timing(self._baby_id)
        await self.coordinator.async_start_nap(
            self._baby_id, minutes_ago=minutes_ago, target_dt=target_dt
        )


class NapperStartSleepButton(NapperBaseButton):
    """Button to start nighttime sleep / BED_TIME (only when child is not sleeping)."""

    _attr_name = "Schlafen starten"
    _attr_icon = "mdi:bed-clock"

    def __init__(self, coordinator: NapperCoordinator, baby_id: str) -> None:
        super().__init__(coordinator, baby_id, "log_bedtime")

    @property
    def available(self) -> bool:
        """Only available when the child is not currently sleeping."""
        return super().available and not self.coordinator.is_child_sleeping(self._baby_id)

    async def async_press(self) -> None:
        target_dt, minutes_ago = self.coordinator.pop_action_timing(self._baby_id)
        await self.coordinator.async_start_sleep(
            self._baby_id, minutes_ago=minutes_ago, target_dt=target_dt
        )
