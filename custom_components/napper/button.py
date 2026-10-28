"""Button platform for Napper (Nickerchen starten/beenden, Aufwachen, Schlafenszeit)."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
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
    """Set up Napper action buttons for each child."""
    coordinator: NapperCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[ButtonEntity] = []
    for baby_id in coordinator.babies:
        entities.extend(
            [
                NapperStartNapButton(coordinator, baby_id),
                NapperStopSleepButton(coordinator, baby_id),
                NapperBedtimeButton(coordinator, baby_id),
                NapperWakeUpButton(coordinator, baby_id),
            ]
        )
    async_add_entities(entities)


class NapperBaseButton(CoordinatorEntity[NapperCoordinator], ButtonEntity):
    """Base button for Napper actions (uses the child's 'Vor X Minuten' offset if > 0)."""

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


class NapperStartNapButton(NapperBaseButton):
    """Button to start an open nap timer (now or X minutes ago)."""

    _attr_name = "Nickerchen starten"
    _attr_icon = "mdi:play-circle-outline"

    def __init__(self, coordinator: NapperCoordinator, baby_id: str) -> None:
        super().__init__(coordinator, baby_id, "start_nap")

    async def async_press(self) -> None:
        minutes_ago = self.coordinator.pop_minutes_ago(self._baby_id)
        await self.coordinator.client.async_start_open_nap(
            self._baby_id, minutes_ago=minutes_ago
        )
        await self.coordinator.async_request_refresh()


class NapperStopSleepButton(NapperBaseButton):
    """Button to stop the currently active nap or sleep timer (now or X minutes ago)."""

    _attr_name = "Nickerchen / Schlaf beenden"
    _attr_icon = "mdi:stop-circle-outline"

    def __init__(self, coordinator: NapperCoordinator, baby_id: str) -> None:
        super().__init__(coordinator, baby_id, "stop_sleep")

    async def async_press(self) -> None:
        minutes_ago = self.coordinator.pop_minutes_ago(self._baby_id)
        logs = self.coordinator.data.get(self._baby_id, {}).get("logs")
        await self.coordinator.client.async_stop_open_sleep(
            self._baby_id, current_logs=logs, minutes_ago=minutes_ago
        )
        await self.coordinator.async_request_refresh()


class NapperBedtimeButton(NapperBaseButton):
    """Button to start nighttime sleep / BED_TIME (now or X minutes ago)."""

    _attr_name = "Schlafenszeit eintragen"
    _attr_icon = "mdi:bed-clock"

    def __init__(self, coordinator: NapperCoordinator, baby_id: str) -> None:
        super().__init__(coordinator, baby_id, "log_bedtime")

    async def async_press(self) -> None:
        minutes_ago = self.coordinator.pop_minutes_ago(self._baby_id)
        await self.coordinator.client.async_start_bedtime(
            self._baby_id, minutes_ago=minutes_ago
        )
        await self.coordinator.async_request_refresh()


class NapperWakeUpButton(NapperBaseButton):
    """Button to log morning wake-up / WOKE_UP (now or X minutes ago)."""

    _attr_name = "Aufwachen eintragen"
    _attr_icon = "mdi:weather-sunset-up"

    def __init__(self, coordinator: NapperCoordinator, baby_id: str) -> None:
        super().__init__(coordinator, baby_id, "log_wake_up")

    async def async_press(self) -> None:
        minutes_ago = self.coordinator.pop_minutes_ago(self._baby_id)
        logs = self.coordinator.data.get(self._baby_id, {}).get("logs")
        await self.coordinator.client.async_log_woke_up(
            self._baby_id, current_logs=logs, minutes_ago=minutes_ago
        )
        await self.coordinator.async_request_refresh()
