"""DataUpdateCoordinator and day-circle schedule computation for the Napper integration."""

from __future__ import annotations

import datetime
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import NapperApiClient, NapperApiError, parse_absolute_time_str
from .const import DEFAULT_SCAN_INTERVAL_SECONDS, DOMAIN, NAP_ORDINAL_DE

_LOGGER = logging.getLogger(__name__)

ARC_START_DEG = -145.0
ARC_END_DEG = 145.0
ARC_SPAN_DEG = ARC_END_DEG - ARC_START_DEG  # 290 degrees


def parse_napper_iso(
    ts: str | None, default_tz: datetime.tzinfo | None = None
) -> datetime.datetime | None:
    """Parse a Napper ISO timestamp (aware or naive local) into a timezone-aware datetime."""
    if not ts:
        return None
    try:
        dt = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            tz = default_tz or datetime.datetime.now().astimezone().tzinfo
            dt = dt.replace(tzinfo=tz)
        else:
            tz = default_tz or datetime.datetime.now().astimezone().tzinfo
            if tz is not None:
                dt = dt.astimezone(tz)
        return dt
    except Exception:
        return None


def format_duration_short(minutes: int) -> str:
    """Format minutes like the Napper app (e.g. '44 min', '1h 56m')."""
    mins = abs(int(minutes))
    if mins < 60:
        return f"{mins} min"
    hours = mins // 60
    rem = mins % 60
    if rem == 0:
        return f"{hours}h"
    return f"{hours}h {rem}m"


def format_duration_de(minutes: int) -> str:
    """Format minutes in readable German (e.g. '44 Min.', '1 Std. 56 Min.')."""
    mins = abs(int(minutes))
    if mins < 60:
        return f"{mins} Min."
    hours = mins // 60
    rem = mins % 60
    if rem == 0:
        return f"{hours} Std."
    return f"{hours} Std. {rem} Min."


def nap_label_de(nap_number: int) -> str:
    """Return German ordinal nap name (e.g. 'Erstes Nickerchen')."""
    return NAP_ORDINAL_DE.get(nap_number, f"{nap_number}. Nickerchen")


def compute_day_summary(
    baby_info: dict[str, Any],
    logs: list[dict[str, Any]],
    schedule_items: list[dict[str, Any]],
    now: datetime.datetime | None = None,
) -> dict[str, Any]:
    """Compute the full Napper circular day view state and German texts."""
    if now is None:
        now = datetime.datetime.now().astimezone()
    elif now.tzinfo is None:
        now = now.astimezone()
    local_tz = now.tzinfo

    # 1. Inspect open sleep logs and latest BED_TIME / WOKE_UP timestamps
    open_nap_log: dict[str, Any] | None = None
    open_bedtime_log: dict[str, Any] | None = None
    open_night_waking_log: dict[str, Any] | None = None
    latest_bedtime_dt: datetime.datetime | None = None
    latest_woke_up_dt: datetime.datetime | None = None

    for entry in logs:
        if entry.get("skipped"):
            continue
        cat = entry.get("category")
        start_dt = parse_napper_iso(entry.get("start"), local_tz)
        if cat == "BED_TIME" and start_dt is not None:
            if latest_bedtime_dt is None or start_dt > latest_bedtime_dt:
                latest_bedtime_dt = start_dt
        elif cat == "WOKE_UP" and start_dt is not None:
            if latest_woke_up_dt is None or start_dt > latest_woke_up_dt:
                latest_woke_up_dt = start_dt

        if entry.get("isOpen"):
            if cat == "NAP" and open_nap_log is None:
                open_nap_log = entry
            elif cat == "BED_TIME" and open_bedtime_log is None:
                open_bedtime_log = entry
            elif cat == "NIGHT_WAKING" and open_night_waking_log is None:
                open_night_waking_log = entry

    # 2. Find today's WOKE_UP log (or estimate expected wake-up)
    today_woke_up_log: dict[str, Any] | None = None
    today_woke_up_dt: datetime.datetime | None = None
    recent_woke_up_minutes: list[int] = []

    for entry in logs:
        if entry.get("category") == "WOKE_UP" and not entry.get("skipped"):
            dt = parse_napper_iso(entry.get("start"), local_tz)
            if dt is None:
                continue
            recent_woke_up_minutes.append(dt.hour * 60 + dt.minute)
            if dt.date() == now.date() and (today_woke_up_dt is None or dt > today_woke_up_dt):
                today_woke_up_log = entry
                today_woke_up_dt = dt

    avg_wake_mins = (
        round(sum(recent_woke_up_minutes) / len(recent_woke_up_minutes))
        if recent_woke_up_minutes
        else 7 * 60
    )

    if today_woke_up_log is not None:
        wake_dt = parse_napper_iso(today_woke_up_log.get("start"), local_tz) or now
        wake_is_tracked = True
    else:
        # Check if scheduleItems contains a WAKE_UP / WOKE_UP item
        sched_wake_dt: datetime.datetime | None = None
        for item in schedule_items:
            if (item.get("type") or item.get("category")) in ("WAKE_UP", "WOKE_UP"):
                sched_wake_dt = parse_napper_iso(item.get("time") or item.get("start"), local_tz)
                break
        if sched_wake_dt is not None:
            wake_dt = sched_wake_dt
        else:
            wake_dt = now.replace(
                hour=avg_wake_mins // 60,
                minute=avg_wake_mins % 60,
                second=0,
                microsecond=0,
            )
        wake_is_tracked = False

    wake_up_info = {
        "time": wake_dt.strftime("%H:%M"),
        "iso": wake_dt.isoformat(),
        "is_tracked": wake_is_tracked,
        "status": "getrackt" if wake_is_tracked else "erwartet",
        "timestamp": wake_dt.timestamp(),
    }

    # 3. Collect today's NAP logs (occurring after today's wake_dt or on today's date)
    today_nap_logs: list[dict[str, Any]] = []
    for entry in logs:
        if entry.get("category") != "NAP" or entry.get("skipped"):
            continue
        start_dt = parse_napper_iso(entry.get("start"), local_tz)
        if start_dt is None:
            continue
        if (wake_is_tracked and start_dt >= wake_dt - datetime.timedelta(minutes=5)) or (
            not wake_is_tracked and start_dt.date() == now.date()
        ):
            today_nap_logs.append(entry)
    today_nap_logs.sort(key=lambda x: x.get("start", ""))

    # 4. Collect scheduleItems for NAP and BED_TIME
    sched_naps = [
        item
        for item in schedule_items
        if (item.get("type") or item.get("category")) == "NAP"
    ]
    sched_naps.sort(key=lambda x: (x.get("napNumber", 99), x.get("time", "")))

    # Build unified naps list (tracked + active + expected)
    naps_raw: list[dict[str, Any]] = []
    for idx, nap_log in enumerate(today_nap_logs):
        nap_num = idx + 1
        start_dt = parse_napper_iso(nap_log.get("start"), local_tz) or now
        is_open = bool(nap_log.get("isOpen"))
        # Look for matching schedule item to know expected duration if open
        matching_sched = next(
            (s for s in sched_naps if s.get("napNumber") == nap_num),
            sched_naps[idx] if idx < len(sched_naps) else None,
        )
        expected_dur = int((matching_sched or {}).get("duration") or 45)

        if is_open:
            elapsed_min = max(0, round((now - start_dt).total_seconds() / 60))
            expected_end_dt = start_dt + datetime.timedelta(minutes=expected_dur)
            display_end_dt = max(now, expected_end_dt)
            naps_raw.append(
                {
                    "nap_number": nap_num,
                    "label": nap_label_de(nap_num),
                    "start_dt": start_dt,
                    "end_dt": display_end_dt,
                    "start_time": start_dt.strftime("%H:%M"),
                    "end_time": expected_end_dt.strftime("%H:%M"),
                    "start_iso": start_dt.isoformat(),
                    "end_iso": expected_end_dt.isoformat(),
                    "duration_minutes": elapsed_min,
                    "expected_duration_minutes": expected_dur,
                    "duration_formatted": format_duration_de(elapsed_min),
                    "duration_short": format_duration_short(elapsed_min),
                    "is_tracked": True,
                    "is_open": True,
                    "status": "aktiv",
                    "log_id": nap_log.get("id"),
                }
            )
        else:
            end_dt = parse_napper_iso(nap_log.get("end"), local_tz) or start_dt
            dur_min = max(1, round((end_dt - start_dt).total_seconds() / 60))
            naps_raw.append(
                {
                    "nap_number": nap_num,
                    "label": nap_label_de(nap_num),
                    "start_dt": start_dt,
                    "end_dt": end_dt,
                    "start_time": start_dt.strftime("%H:%M"),
                    "end_time": end_dt.strftime("%H:%M"),
                    "start_iso": start_dt.isoformat(),
                    "end_iso": end_dt.isoformat(),
                    "duration_minutes": dur_min,
                    "expected_duration_minutes": expected_dur,
                    "duration_formatted": format_duration_de(dur_min),
                    "duration_short": format_duration_short(dur_min),
                    "is_tracked": True,
                    "is_open": False,
                    "status": "getrackt",
                    "log_id": nap_log.get("id"),
                }
            )

    # Append remaining uncompleted expected naps from schedule_items
    logged_count = len(today_nap_logs)
    for sched in sched_naps:
        sched_num = int(sched.get("napNumber") or 0)
        if sched.get("completed") or sched_num <= logged_count:
            continue
        start_dt = parse_napper_iso(sched.get("time") or sched.get("start"), local_tz)
        if start_dt is None:
            continue
        dur_min = int(sched.get("duration") or 45)
        end_dt = start_dt + datetime.timedelta(minutes=dur_min)
        nap_num = len(naps_raw) + 1
        naps_raw.append(
            {
                "nap_number": nap_num,
                "label": nap_label_de(nap_num),
                "start_dt": start_dt,
                "end_dt": end_dt,
                "start_time": start_dt.strftime("%H:%M"),
                "end_time": end_dt.strftime("%H:%M"),
                "start_iso": start_dt.isoformat(),
                "end_iso": end_dt.isoformat(),
                "duration_minutes": dur_min,
                "expected_duration_minutes": dur_min,
                "duration_formatted": format_duration_de(dur_min),
                "duration_short": format_duration_short(dur_min),
                "is_tracked": False,
                "is_open": False,
                "status": "erwartet",
                "log_id": None,
            }
        )

    # 5. Find today's BED_TIME (tracked or expected)
    today_bedtime_log: dict[str, Any] | None = None
    for entry in logs:
        if entry.get("category") != "BED_TIME" or entry.get("skipped"):
            continue
        dt = parse_napper_iso(entry.get("start"), local_tz)
        if dt is None:
            continue
        if (wake_is_tracked and dt >= wake_dt) or (dt.date() == now.date() and dt.hour >= 16):
            today_bedtime_log = entry
            break

    sched_bedtime = next(
        (
            item
            for item in reversed(schedule_items)
            if (item.get("type") or item.get("category")) == "BED_TIME"
        ),
        None,
    )

    if today_bedtime_log is not None:
        bed_dt = parse_napper_iso(today_bedtime_log.get("start"), local_tz) or now
        bed_is_tracked = True
        bed_is_open = bool(today_bedtime_log.get("isOpen"))
    elif sched_bedtime is not None:
        bed_dt = (
            parse_napper_iso(sched_bedtime.get("time") or sched_bedtime.get("start"), local_tz)
            or now.replace(hour=19, minute=30, second=0, microsecond=0)
        )
        bed_is_tracked = bool(sched_bedtime.get("completed"))
        bed_is_open = False
    else:
        bed_dt = wake_dt + datetime.timedelta(hours=12, minutes=30)
        bed_is_tracked = False
        bed_is_open = False

    bedtime_info = {
        "time": bed_dt.strftime("%H:%M"),
        "iso": bed_dt.isoformat(),
        "is_tracked": bed_is_tracked,
        "is_open": bed_is_open,
        "status": "getrackt" if bed_is_tracked else "erwartet",
        "timestamp": bed_dt.timestamp(),
    }

    # 6. Compute Circle Angles (-145° to +145°) for each nap & current time
    arc_start_ts = wake_dt.timestamp()
    arc_end_ts = max(arc_start_ts + 3600.0, bed_dt.timestamp())
    arc_span_sec = arc_end_ts - arc_start_ts

    def _ts_to_angle(ts: float) -> float:
        ratio = max(0.0, min(1.0, (ts - arc_start_ts) / arc_span_sec))
        return round(ARC_START_DEG + ratio * ARC_SPAN_DEG, 2)

    naps: list[dict[str, Any]] = []
    for n in naps_raw:
        s_dt: datetime.datetime = n.pop("start_dt")
        e_dt: datetime.datetime = n.pop("end_dt")
        s_ang = _ts_to_angle(s_dt.timestamp())
        e_ang = _ts_to_angle(e_dt.timestamp())
        mid_ang = round((s_ang + e_ang) / 2.0, 2)
        n["start_angle_deg"] = s_ang
        n["end_angle_deg"] = e_ang
        n["mid_angle_deg"] = mid_ang
        naps.append(n)

    now_ratio = max(0.0, min(1.0, (now.timestamp() - arc_start_ts) / arc_span_sec))
    now_angle_deg = _ts_to_angle(now.timestamp())

    # 7. Sleep state & awake duration
    unclosed_night_sleep = (
        latest_bedtime_dt is not None
        and (now - latest_bedtime_dt).total_seconds() <= 18 * 3600
        and (latest_woke_up_dt is None or latest_bedtime_dt > latest_woke_up_dt)
    )
    if open_nap_log is not None:
        sleep_state_de = "Nickerchen"
        is_sleeping = True
    elif open_bedtime_log is not None or unclosed_night_sleep:
        sleep_state_de = "Nachtschlaf"
        is_sleeping = True
    elif open_night_waking_log is not None:
        sleep_state_de = "Nächtliches Aufwachen"
        is_sleeping = False
    else:
        sleep_state_de = "Wach"
        is_sleeping = False

    # Awake time since last wake-up or end of last completed nap
    last_awake_since_dt = wake_dt
    for nap_log in today_nap_logs:
        if not nap_log.get("isOpen") and not nap_log.get("skipped"):
            e_dt = parse_napper_iso(nap_log.get("end"), local_tz)
            if e_dt and e_dt > last_awake_since_dt:
                last_awake_since_dt = e_dt

    if is_sleeping:
        awake_minutes = 0
    else:
        awake_minutes = max(0, round((now - last_awake_since_dt).total_seconds() / 60))

    total_tracked_sleep_minutes = sum(
        n["duration_minutes"] for n in naps if n["is_tracked"]
    )
    total_expected_sleep_minutes = sum(
        n["duration_minutes"] if (n["is_tracked"] and not n["is_open"]) else n["expected_duration_minutes"]
        for n in naps
    )

    # 8. Upcoming event (German labels matching the Napper app circle center)
    active_nap = next((n for n in naps if n["is_open"]), None)
    next_expected_nap = next((n for n in naps if not n["is_tracked"]), None)

    if active_nap is not None:
        target_dt = parse_napper_iso(active_nap["end_iso"], local_tz) or now
        mins_left = round((target_dt - now).total_seconds() / 60)
        target_hm = active_nap["end_time"]
        if mins_left >= 0:
            title_de = "Aufwachen in"
            countdown_text = format_duration_short(mins_left)
            state_text_de = f"Aufwachen in {format_duration_de(mins_left)} (um {target_hm})"
        else:
            title_de = f"{active_nap['label']} aktiv"
            countdown_text = format_duration_short(active_nap["duration_minutes"])
            state_text_de = f"{active_nap['label']} läuft seit {active_nap['duration_formatted']}"
        upcoming_event = {
            "type": "WAKE_UP",
            "title_de": title_de,
            "state_text_de": state_text_de,
            "minutes_until": max(0, mins_left),
            "raw_minutes_until": mins_left,
            "countdown_text": countdown_text,
            "subtitle_de": f"Um {target_hm}",
            "target_time": target_hm,
            "target_iso": target_dt.isoformat(),
        }
    elif sleep_state_de == "Nachtschlaf" or (not wake_is_tracked and now < wake_dt):
        # Waiting for morning wake-up
        if now >= wake_dt:
            next_wake_dt = (now + datetime.timedelta(days=1)).replace(
                hour=avg_wake_mins // 60,
                minute=avg_wake_mins % 60,
                second=0,
                microsecond=0,
            )
        else:
            next_wake_dt = wake_dt
        mins_left = max(0, round((next_wake_dt - now).total_seconds() / 60))
        target_hm = next_wake_dt.strftime("%H:%M")
        upcoming_event = {
            "type": "WAKE_UP",
            "title_de": "Aufwachen in",
            "state_text_de": f"Aufwachen in {format_duration_de(mins_left)} (um {target_hm})",
            "minutes_until": mins_left,
            "raw_minutes_until": mins_left,
            "countdown_text": format_duration_short(mins_left),
            "subtitle_de": f"Um {target_hm}",
            "target_time": target_hm,
            "target_iso": next_wake_dt.isoformat(),
        }
    elif next_expected_nap is not None:
        target_dt = parse_napper_iso(next_expected_nap["start_iso"], local_tz) or now
        mins_left = round((target_dt - now).total_seconds() / 60)
        target_hm = next_expected_nap["start_time"]
        label = next_expected_nap["label"]
        if mins_left >= 0:
            title_de = f"{label} in"
            state_text_de = f"{label} in {format_duration_de(mins_left)} (um {target_hm})"
        else:
            title_de = f"{label} überfällig"
            state_text_de = f"{label} seit {format_duration_de(abs(mins_left))} fällig (um {target_hm})"
        upcoming_event = {
            "type": "NAP",
            "nap_number": next_expected_nap["nap_number"],
            "title_de": title_de,
            "state_text_de": state_text_de,
            "minutes_until": max(0, mins_left),
            "raw_minutes_until": mins_left,
            "countdown_text": format_duration_short(mins_left),
            "subtitle_de": f"Um {target_hm}",
            "target_time": target_hm,
            "target_iso": target_dt.isoformat(),
        }
    else:
        # Next event is bedtime
        mins_left = round((bed_dt - now).total_seconds() / 60)
        target_hm = bedtime_info["time"]
        if mins_left >= 0:
            title_de = "Schlafenszeit in"
            state_text_de = f"Ins Bett gehen in {format_duration_de(mins_left)} (um {target_hm})"
        else:
            title_de = "Schlafenszeit überfällig"
            state_text_de = f"Schlafenszeit seit {format_duration_de(abs(mins_left))} fällig (um {target_hm})"
        upcoming_event = {
            "type": "BED_TIME",
            "title_de": title_de,
            "state_text_de": state_text_de,
            "minutes_until": max(0, mins_left),
            "raw_minutes_until": mins_left,
            "countdown_text": format_duration_short(mins_left),
            "subtitle_de": f"Um {target_hm}",
            "target_time": target_hm,
            "target_iso": bed_dt.isoformat(),
        }

    return {
        "baby_id": baby_info.get("id"),
        "baby_name": baby_info.get("name", "Baby"),
        "sleep_state_de": sleep_state_de,
        "is_sleeping": is_sleeping,
        "wake_up": wake_up_info,
        "bedtime": bedtime_info,
        "naps": naps,
        "naps_count": len(naps),
        "tracked_naps_count": sum(1 for n in naps if n["is_tracked"]),
        "expected_naps_count": sum(1 for n in naps if not n["is_tracked"]),
        "awake_minutes": awake_minutes,
        "awake_short": format_duration_short(awake_minutes),
        "awake_formatted": format_duration_de(awake_minutes),
        "last_awake_since_iso": last_awake_since_dt.isoformat(),
        "total_tracked_sleep_minutes": total_tracked_sleep_minutes,
        "total_tracked_sleep_short": format_duration_short(total_tracked_sleep_minutes),
        "total_tracked_sleep_formatted": format_duration_de(total_tracked_sleep_minutes),
        "total_expected_sleep_minutes": total_expected_sleep_minutes,
        "total_expected_sleep_short": format_duration_short(total_expected_sleep_minutes),
        "total_expected_sleep_formatted": format_duration_de(total_expected_sleep_minutes),
        "upcoming_event": upcoming_event,
        "circle": {
            "arc_start_deg": ARC_START_DEG,
            "arc_end_deg": ARC_END_DEG,
            "now_angle_deg": now_angle_deg,
            "now_progress_ratio": round(now_ratio, 4),
            "updated_at_iso": now.isoformat(),
        },
    }


class NapperCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Coordinator to fetch babies, today's logs, and predicted schedules from Napper."""

    def __init__(self, hass: HomeAssistant, client: NapperApiClient) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=datetime.timedelta(seconds=DEFAULT_SCAN_INTERVAL_SECONDS),
        )
        self.client = client
        self.babies: dict[str, dict[str, Any]] = {}
        self.minutes_ago_offset: dict[str, int] = {}
        self.absolute_time_input: dict[str, str] = {}

    def get_minutes_ago(self, baby_id: str) -> int:
        """Return the configured 'Zeitdifferenz' offset in minutes for a baby."""
        return int(self.minutes_ago_offset.get(baby_id, 0))

    def set_minutes_ago(self, baby_id: str, minutes: int) -> None:
        """Set the 'Zeitdifferenz' offset for a baby and notify listeners."""
        val = max(0, int(minutes))
        self.minutes_ago_offset[baby_id] = val
        if val > 0:
            self.absolute_time_input[baby_id] = ""
        self.async_update_listeners()

    def get_absolute_time(self, baby_id: str) -> str:
        """Return the configured absolute time string ('HH:MM') for a baby."""
        return str(self.absolute_time_input.get(baby_id, ""))

    def get_absolute_time_obj(self, baby_id: str) -> datetime.time | None:
        """Return the configured absolute time as a datetime.time object (or None)."""
        raw = self.get_absolute_time(baby_id)
        if not raw:
            return None
        try:
            dt = parse_absolute_time_str(raw)
            return dt.time().replace(second=0, microsecond=0) if dt else None
        except Exception:
            return None

    def set_absolute_time(self, baby_id: str, value: str) -> None:
        """Validate and set the absolute time string ('HH:MM') for a baby."""
        cleaned = str(value or "").strip()
        if cleaned:
            try:
                parse_absolute_time_str(cleaned)
            except ValueError as err:
                raise HomeAssistantError(str(err)) from err
            self.minutes_ago_offset[baby_id] = 0
        self.absolute_time_input[baby_id] = cleaned
        self.async_update_listeners()

    def pop_action_timing(
        self,
        baby_id: str,
        explicit_time: str | None = None,
        explicit_minutes_ago: int = 0,
    ) -> tuple[datetime.datetime | None, int]:
        """Read and reset both 'Uhrzeit' and 'Zeitdifferenz', returning (target_dt, minutes_ago)."""
        stored_time = self.get_absolute_time(baby_id)
        stored_minutes = self.get_minutes_ago(baby_id)
        self.absolute_time_input[baby_id] = ""
        self.minutes_ago_offset[baby_id] = 0
        self.async_update_listeners()

        chosen_time = (explicit_time or "").strip() or stored_time
        if chosen_time:
            try:
                target_dt = parse_absolute_time_str(chosen_time)
            except ValueError as err:
                raise HomeAssistantError(str(err)) from err
            return target_dt, 0

        chosen_minutes = int(explicit_minutes_ago) if int(explicit_minutes_ago) > 0 else stored_minutes
        return None, chosen_minutes

    def pop_minutes_ago(self, baby_id: str) -> int:
        """Read and reset the 'Zeitdifferenz' offset for a baby."""
        val = self.get_minutes_ago(baby_id)
        self.minutes_ago_offset[baby_id] = 0
        self.async_update_listeners()
        return val

    def is_child_sleeping(self, baby_id: str) -> bool:
        """Return True if the child is currently in a nap or night sleep."""
        if not self.data or baby_id not in self.data:
            return False
        return bool(self.data[baby_id].get("summary", {}).get("is_sleeping", False))

    async def async_start_nap(
        self,
        baby_id: str,
        minutes_ago: int = 0,
        target_dt: datetime.datetime | None = None,
    ) -> None:
        """Start a nap only if the child is not currently sleeping."""
        if self.is_child_sleeping(baby_id):
            raise HomeAssistantError(
                "Nickerchen kann nicht gestartet werden, da das Kind bereits schläft."
            )
        await self.client.async_start_open_nap(
            baby_id, start_dt=target_dt, minutes_ago=minutes_ago
        )
        await self.async_request_refresh()

    async def async_start_sleep(
        self,
        baby_id: str,
        minutes_ago: int = 0,
        target_dt: datetime.datetime | None = None,
    ) -> None:
        """Start night sleep only if the child is not currently sleeping."""
        if self.is_child_sleeping(baby_id):
            raise HomeAssistantError(
                "Nachtschlaf kann nicht gestartet werden, da das Kind bereits schläft."
            )
        await self.client.async_start_bedtime(
            baby_id, start_dt=target_dt, minutes_ago=minutes_ago
        )
        await self.async_request_refresh()

    async def async_wake_up(
        self,
        baby_id: str,
        minutes_ago: int = 0,
        target_dt: datetime.datetime | None = None,
    ) -> None:
        """Wake up (end active nap or night sleep) only if currently sleeping."""
        if not self.is_child_sleeping(baby_id):
            raise HomeAssistantError(
                "Aufwachen ist nur möglich, wenn gerade ein Nickerchen oder Nachtschlaf läuft."
            )
        logs = (self.data or {}).get(baby_id, {}).get("logs")
        await self.client.async_wake_up(
            baby_id, current_logs=logs, wake_dt=target_dt, minutes_ago=minutes_ago
        )
        await self.async_request_refresh()

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        """Fetch the latest logs and predicted schedule for each baby."""
        try:
            if not self.client.user_id:
                await self.client.async_get_user()
            babies_list = await self.client.async_get_babies()
            self.babies = {b["id"]: b for b in babies_list if "id" in b}

            result: dict[str, dict[str, Any]] = {}
            for baby_id, baby_info in self.babies.items():
                self.minutes_ago_offset.setdefault(baby_id, 0)
                self.absolute_time_input.setdefault(baby_id, "")
                today_data = await self.client.async_get_today(baby_id)
                logs = today_data.get("logs", today_data.get("allLogs", []))
                schedule_items = today_data.get("scheduleItems", [])
                summary = compute_day_summary(baby_info, logs, schedule_items)
                result[baby_id] = {
                    "baby": baby_info,
                    "logs": logs,
                    "scheduleItems": schedule_items,
                    "summary": summary,
                }
            return result
        except NapperApiError as err:
            raise UpdateFailed(f"Error communicating with Napper API: {err}") from err

