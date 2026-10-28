"""Sensor platform for Napper (German labels, circle schedule data, naps, countdowns)."""

from __future__ import annotations

import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MAX_NAP_SENSORS
from .coordinator import NapperCoordinator, nap_label_de, parse_napper_iso


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Napper sensors for each child."""
    coordinator: NapperCoordinator = hass.data[DOMAIN][entry.entry_id]
    ent_reg = er.async_get(hass)
    entities: list[SensorEntity] = []
    for baby_id in coordinator.babies:
        # Remove obsolete countdown sensor if present in registry
        old_countdown = ent_reg.async_get_entity_id(
            "sensor", DOMAIN, f"{baby_id}_next_event_countdown"
        )
        if old_countdown:
            ent_reg.async_remove(old_countdown)

        entities.extend(
            [
                NapperUpcomingEventSensor(coordinator, baby_id),
                NapperSleepStatusSensor(coordinator, baby_id),
                NapperWakeUpSensor(coordinator, baby_id),
                NapperBedtimeSensor(coordinator, baby_id),
                NapperAwakeDurationSensor(coordinator, baby_id),
                NapperTotalDaySleepSensor(coordinator, baby_id),
            ]
        )
        for nap_num in range(1, MAX_NAP_SENSORS + 1):
            entities.append(NapperNapSensor(coordinator, baby_id, nap_num))
    async_add_entities(entities)


class NapperBaseSensor(CoordinatorEntity[NapperCoordinator], SensorEntity):
    """Base class for Napper sensors."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: NapperCoordinator, baby_id: str, key: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._baby_id = baby_id
        self._attr_unique_id = f"{baby_id}_{key}"

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

    def _summary(self) -> dict[str, Any]:
        return self.coordinator.data.get(self._baby_id, {}).get("summary", {})


class NapperUpcomingEventSensor(NapperBaseSensor):
    """Timestamp sensor showing the upcoming event so Home Assistant renders relative time ('in 2 Stunden')."""

    _attr_name = "Nächstes Ereignis"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:clock-fast"

    def __init__(self, coordinator: NapperCoordinator, baby_id: str) -> None:
        super().__init__(coordinator, baby_id, "upcoming_event")

    @property
    def native_value(self) -> datetime.datetime | None:
        upcoming = self._summary().get("upcoming_event", {})
        return parse_napper_iso(upcoming.get("target_iso"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        summary = self._summary()
        upcoming = summary.get("upcoming_event", {})
        return {
            "baby_id": self._baby_id,
            "baby_name": summary.get("baby_name"),
            "ereignis_typ": upcoming.get("type"),
            "titel": upcoming.get("title_de"),
            "beschreibung": upcoming.get("state_text_de"),
            "countdown": upcoming.get("countdown_text"),
            "untertitel": upcoming.get("subtitle_de"),
            "minuten_bis": upcoming.get("minutes_until"),
            "uhrzeit": upcoming.get("target_time"),
            "zeitpunkt_iso": upcoming.get("target_iso"),
            "summary": summary,
        }


class NapperSleepStatusSensor(NapperBaseSensor):
    """Current sleep status in German (Wach, Nickerchen, Nachtschlaf, Nächtliches Aufwachen) + full circle data."""

    _attr_name = "Schlafstatus"
    _attr_icon = "mdi:baby-face-outline"

    def __init__(self, coordinator: NapperCoordinator, baby_id: str) -> None:
        super().__init__(coordinator, baby_id, "sleep_status")

    @property
    def native_value(self) -> str:
        return self._summary().get("sleep_state_de", "Wach")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        summary = self._summary()
        return {
            "baby_id": self._baby_id,
            "baby_name": summary.get("baby_name"),
            "aufwachzeit": summary.get("wake_up", {}).get("time"),
            "aufwachzeit_status": summary.get("wake_up", {}).get("status"),
            "schlafenszeit": summary.get("bedtime", {}).get("time"),
            "schlafenszeit_status": summary.get("bedtime", {}).get("status"),
            "wachzeit": summary.get("awake_short"),
            "tagesschlaf_getrackt": summary.get("total_tracked_sleep_short"),
            "tagesschlaf_erwartet": summary.get("total_expected_sleep_short"),
            "naechstes_ereignis": summary.get("upcoming_event", {}).get("state_text_de"),
            "nickerchen": summary.get("naps", []),
            "summary": summary,
        }


class NapperWakeUpSensor(NapperBaseSensor):
    """Today's morning wake-up time (tracked or expected)."""

    _attr_name = "Aufwachzeit"
    _attr_icon = "mdi:weather-sunset-up"

    def __init__(self, coordinator: NapperCoordinator, baby_id: str) -> None:
        super().__init__(coordinator, baby_id, "wake_up_time")

    @property
    def native_value(self) -> str | None:
        wake = self._summary().get("wake_up", {})
        return wake.get("time")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        wake = self._summary().get("wake_up", {})
        return {
            "baby_id": self._baby_id,
            "uhrzeit": wake.get("time"),
            "status": wake.get("status"),
            "is_tracked": wake.get("is_tracked"),
            "iso": wake.get("iso"),
        }


class NapperBedtimeSensor(NapperBaseSensor):
    """Today's bedtime (tracked or expected)."""

    _attr_name = "Schlafenszeit"
    _attr_icon = "mdi:weather-sunset-down"

    def __init__(self, coordinator: NapperCoordinator, baby_id: str) -> None:
        super().__init__(coordinator, baby_id, "predicted_bedtime")

    @property
    def native_value(self) -> str | None:
        bed = self._summary().get("bedtime", {})
        return bed.get("time")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        bed = self._summary().get("bedtime", {})
        return {
            "baby_id": self._baby_id,
            "uhrzeit": bed.get("time"),
            "status": bed.get("status"),
            "is_tracked": bed.get("is_tracked"),
            "iso": bed.get("iso"),
        }


class NapperAwakeDurationSensor(NapperBaseSensor):
    """Awake time since morning wake-up or end of last nap (matches '1h 56m' below the circle)."""

    _attr_name = "Wachzeit"
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:sunny"

    def __init__(self, coordinator: NapperCoordinator, baby_id: str) -> None:
        super().__init__(coordinator, baby_id, "awake_duration")

    @property
    def native_value(self) -> int:
        return int(self._summary().get("awake_minutes", 0))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        summary = self._summary()
        return {
            "baby_id": self._baby_id,
            "anzeige_kurz": summary.get("awake_short"),
            "anzeige_deutsch": summary.get("awake_formatted"),
            "wach_seit_iso": summary.get("last_awake_since_iso"),
        }


class NapperTotalDaySleepSensor(NapperBaseSensor):
    """Total daytime nap sleep today (tracked + expected attributes)."""

    _attr_name = "Tagesschlaf"
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:timer-sand"

    def __init__(self, coordinator: NapperCoordinator, baby_id: str) -> None:
        super().__init__(coordinator, baby_id, "total_day_sleep")

    @property
    def native_value(self) -> int:
        return int(self._summary().get("total_tracked_sleep_minutes", 0))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        summary = self._summary()
        return {
            "baby_id": self._baby_id,
            "getrackt_minuten": summary.get("total_tracked_sleep_minutes"),
            "getrackt_kurz": summary.get("total_tracked_sleep_short"),
            "getrackt_deutsch": summary.get("total_tracked_sleep_formatted"),
            "erwartet_gesamt_minuten": summary.get("total_expected_sleep_minutes"),
            "erwartet_gesamt_kurz": summary.get("total_expected_sleep_short"),
            "erwartet_gesamt_deutsch": summary.get("total_expected_sleep_formatted"),
            "anzahl_nickerchen_getrackt": summary.get("tracked_naps_count"),
            "anzahl_nickerchen_erwartet": summary.get("expected_naps_count"),
        }


class NapperNapSensor(NapperBaseSensor):
    """Per-nap sensor (1. Nickerchen .. 4. Nickerchen) showing start, end, duration, and tracked/expected status."""

    _attr_icon = "mdi:weather-partly-cloudy"

    def __init__(
        self, coordinator: NapperCoordinator, baby_id: str, nap_number: int
    ) -> None:
        super().__init__(coordinator, baby_id, f"nap_{nap_number}")
        self._nap_number = nap_number
        self._attr_name = f"{nap_number}. Nickerchen"

    def _nap_data(self) -> dict[str, Any] | None:
        for nap in self._summary().get("naps", []):
            if nap.get("nap_number") == self._nap_number:
                return nap
        return None

    @property
    def native_value(self) -> str:
        nap = self._nap_data()
        if not nap:
            return "Nicht geplant"
        start = nap.get("start_time")
        end = nap.get("end_time")
        dur = nap.get("duration_formatted")
        if nap.get("is_open"):
            return f"Aktiv seit {start} ({dur})"
        return f"{start} – {end} ({dur})"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        nap = self._nap_data()
        if not nap:
            return {
                "baby_id": self._baby_id,
                "nap_number": self._nap_number,
                "bezeichnung": nap_label_de(self._nap_number),
                "geplant": False,
                "status": "nicht_geplant",
            }
        return {
            "baby_id": self._baby_id,
            "nap_number": self._nap_number,
            "bezeichnung": nap.get("label"),
            "geplant": True,
            "start": nap.get("start_time"),
            "ende": nap.get("end_time"),
            "start_iso": nap.get("start_iso"),
            "ende_iso": nap.get("end_iso"),
            "dauer_minuten": nap.get("duration_minutes"),
            "erwartete_dauer_minuten": nap.get("expected_duration_minutes"),
            "dauer_kurz": nap.get("duration_short"),
            "dauer_deutsch": nap.get("duration_formatted"),
            "status": nap.get("status"),
            "is_tracked": nap.get("is_tracked"),
            "is_open": nap.get("is_open"),
            "start_angle_deg": nap.get("start_angle_deg"),
            "end_angle_deg": nap.get("end_angle_deg"),
        }
