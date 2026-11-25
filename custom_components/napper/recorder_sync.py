"""Authoritative timeline builder and Home Assistant Recorder history sync for Napper."""

from __future__ import annotations

import datetime
import logging
import os
from typing import Any

from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, MAX_NAP_SENSORS

_LOGGER = logging.getLogger(__name__)


def _parse_iso(
    ts: str | None, default_tz: datetime.tzinfo | None = None
) -> datetime.datetime | None:
    """Parse a Napper ISO timestamp into a timezone-aware datetime."""
    if not ts:
        return None
    try:
        dt = datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        tz = default_tz or datetime.datetime.now().astimezone().tzinfo
        if dt.tzinfo is None:
            return dt.replace(tzinfo=tz)
        return dt.astimezone(tz) if tz is not None else dt
    except Exception:
        return None


def _format_duration_de(minutes: int) -> str:
    mins = abs(int(minutes))
    if mins < 60:
        return f"{mins} Min."
    hours = mins // 60
    rem = mins % 60
    if rem == 0:
        return f"{hours} Std."
    return f"{hours} Std. {rem} Min."


def build_authoritative_timelines(
    logs: list[dict[str, Any]],
    now: datetime.datetime | None = None,
) -> dict[str, Any]:
    """Build exact chronological state timelines directly from Napper's merged allLogs.

    Returns:
        {
            "window_start_ts": float | None,
            "sleep_status": list[tuple[float, str]],
            "sleeping_binary": list[tuple[float, str]],
        }
    """
    if now is None:
        now = datetime.datetime.now().astimezone()
    elif now.tzinfo is None:
        now = now.astimezone()
    local_tz = now.tzinfo
    now_ts = now.timestamp()

    valid_logs = [
        entry
        for entry in logs
        if isinstance(entry, dict)
        and not entry.get("skipped")
        and entry.get("category") in ("BED_TIME", "NIGHT_WAKING", "WOKE_UP", "NAP")
    ]
    if not valid_logs:
        return {
            "window_start_ts": None,
            "sleep_status": [],
            "sleeping_binary": [],
        }

    # Find all WOKE_UP timestamps so any orphaned "isOpen" BED_TIME / NIGHT_WAKING
    # from a previous night is properly bounded by the subsequent morning wake-up.
    woke_up_timestamps: list[float] = []
    anchor_candidates: list[float] = []
    for entry in valid_logs:
        cat = entry.get("category")
        s_dt = _parse_iso(entry.get("start"), local_tz)
        if s_dt is None or s_dt.timestamp() > now_ts:
            continue
        if cat == "WOKE_UP":
            woke_up_timestamps.append(s_dt.timestamp())
            anchor_candidates.append(s_dt.timestamp())
        elif cat == "BED_TIME":
            anchor_candidates.append(s_dt.timestamp())

    woke_up_timestamps.sort()

    def _next_woke_up_after(ts_val: float) -> float | None:
        for w_ts in woke_up_timestamps:
            if w_ts > ts_val + 1.0:
                return w_ts
        return None

    # Raw events: (timestamp_sec, priority, sleep_status_de, binary_on_off)
    raw_events: list[tuple[float, int, str, str]] = []

    for entry in valid_logs:
        cat = entry.get("category")
        s_dt = _parse_iso(entry.get("start"), local_tz)
        if s_dt is None:
            continue
        s_ts = s_dt.timestamp()
        if s_ts > now_ts:
            continue

        e_dt = _parse_iso(entry.get("end") or entry.get("start"), local_tz) or s_dt
        e_ts = min(now_ts, max(s_ts, e_dt.timestamp()))
        is_open = bool(entry.get("isOpen"))

        if cat == "BED_TIME":
            subsequent_wake = _next_woke_up_after(s_ts)
            if is_open and subsequent_wake is None and (now_ts - s_ts) <= 18 * 3600:
                raw_events.append((s_ts, 10, "Einschlafbegleitung", "off"))
            elif not is_open:
                if (e_ts - s_ts) >= 30.0:
                    raw_events.append((s_ts, 10, "Einschlafbegleitung", "off"))
                    raw_events.append((e_ts, 15, "Nachtschlaf", "on"))
                else:
                    raw_events.append((e_ts, 15, "Nachtschlaf", "on"))

        elif cat == "NIGHT_WAKING":
            subsequent_wake = _next_woke_up_after(s_ts)
            if is_open and subsequent_wake is not None:
                # Ignore orphaned unclosed NIGHT_WAKING from before a logged morning WOKE_UP
                continue
            raw_events.append((s_ts, 16, "Nachtschlaf (pausiert)", "on"))
            if not is_open:
                # If night waking ended before morning wake-up, resume Nachtschlaf
                if subsequent_wake is None or e_ts < subsequent_wake - 1.0:
                    raw_events.append((e_ts, 17, "Nachtschlaf", "on"))

        elif cat == "WOKE_UP":
            raw_events.append((s_ts, 30, "Wach", "off"))

        elif cat == "NAP":
            raw_events.append((s_ts, 20, "Nickerchen", "on"))
            pauses = [
                p
                for p in (entry.get("pauses") or [])
                if isinstance(p, dict) and p.get("start")
            ]
            pauses.sort(key=lambda p: int(p["start"]))
            for p in pauses:
                p_start_ts = int(p["start"]) / 1000.0
                if s_ts <= p_start_ts <= now_ts:
                    raw_events.append((p_start_ts, 21, "Nickerchen (pausiert)", "on"))
                if p.get("end"):
                    p_end_ts = int(p["end"]) / 1000.0
                    if max(s_ts, p_start_ts) <= p_end_ts <= now_ts:
                        raw_events.append((p_end_ts, 22, "Nickerchen", "on"))
            if not is_open:
                raw_events.append((e_ts, 25, "Wach", "off"))

    if not raw_events:
        return {
            "window_start_ts": None,
            "sleep_status": [],
            "sleeping_binary": [],
        }

    raw_events.sort(key=lambda item: (item[0], item[1]))

    # Start the authoritative reconciliation window at the earliest BED_TIME or WOKE_UP
    # in allLogs so we have complete context from that anchor point onwards.
    window_start_ts = min(anchor_candidates) if anchor_candidates else raw_events[0][0]
    filtered = [ev for ev in raw_events if ev[0] >= window_start_ts - 1.0]
    if not filtered:
        filtered = raw_events
        window_start_ts = filtered[0][0]

    # Collapse simultaneous events within < 1.0 second to the final/highest-priority event
    collapsed: list[tuple[float, int, str, str]] = []
    for ev in filtered:
        if collapsed and abs(ev[0] - collapsed[-1][0]) < 1.0:
            collapsed[-1] = ev
        else:
            collapsed.append(ev)

    sleep_status_timeline: list[tuple[float, str]] = []
    sleeping_binary_timeline: list[tuple[float, str]] = []

    for ts_val, _prio, st_text, bin_text in collapsed:
        if not sleep_status_timeline or sleep_status_timeline[-1][1] != st_text:
            # Ensure strictly monotonic timestamps (+0.001s if needed)
            adj_ts = (
                max(ts_val, sleep_status_timeline[-1][0] + 0.001)
                if sleep_status_timeline
                else ts_val
            )
            sleep_status_timeline.append((adj_ts, st_text))

        if not sleeping_binary_timeline or sleeping_binary_timeline[-1][1] != bin_text:
            adj_b_ts = (
                max(ts_val, sleeping_binary_timeline[-1][0] + 0.001)
                if sleeping_binary_timeline
                else ts_val
            )
            sleeping_binary_timeline.append((adj_b_ts, bin_text))

    return {
        "window_start_ts": window_start_ts,
        "sleep_status": sleep_status_timeline,
        "sleeping_binary": sleeping_binary_timeline,
    }


def build_today_nap_and_wake_timelines(
    summary: dict[str, Any],
    logs: list[dict[str, Any]],
    now: datetime.datetime | None = None,
) -> dict[str, tuple[float, list[tuple[float, str]]]]:
    """Build today's authoritative timelines for Aufwachzeit and 1..4. Nickerchen."""
    if now is None:
        now = datetime.datetime.now().astimezone()
    elif now.tzinfo is None:
        now = now.astimezone()
    local_tz = now.tzinfo
    now_ts = now.timestamp()

    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    out: dict[str, tuple[float, list[tuple[float, str]]]] = {}

    wake = summary.get("wake_up") or {}
    if wake.get("is_tracked") and wake.get("iso") and wake.get("time"):
        w_dt = _parse_iso(wake.get("iso"), local_tz)
        if w_dt and w_dt.timestamp() <= now_ts:
            out["wake_up_time"] = (day_start, [(w_dt.timestamp(), str(wake["time"]))])

    # Build per-nap timelines for tracked naps today
    logs_by_id = {
        entry.get("id"): entry
        for entry in logs
        if isinstance(entry, dict) and entry.get("id")
    }
    for nap in summary.get("naps") or []:
        nap_num = nap.get("nap_number")
        if not nap_num or nap_num > MAX_NAP_SENSORS or not nap.get("is_tracked"):
            continue
        s_dt = _parse_iso(nap.get("start_iso"), local_tz)
        if s_dt is None or s_dt.timestamp() > now_ts:
            continue
        s_ts = s_dt.timestamp()
        start_hm = nap.get("start_time")
        end_hm = nap.get("end_time")
        dur_fmt = nap.get("duration_formatted") or _format_duration_de(
            int(nap.get("duration_minutes") or 0)
        )

        nap_events: list[tuple[float, str]] = [(s_ts, f"Aktiv seit {start_hm}")]
        raw_log = logs_by_id.get(nap.get("log_id")) or {}
        pauses = [
            p
            for p in (raw_log.get("pauses") or [])
            if isinstance(p, dict) and p.get("start")
        ]
        pauses.sort(key=lambda p: int(p["start"]))
        for p in pauses:
            p_s = int(p["start"]) / 1000.0
            if s_ts < p_s <= now_ts:
                nap_events.append((p_s, f"Pausiert (seit {start_hm})"))
            if p.get("end"):
                p_e = int(p["end"]) / 1000.0
                if max(s_ts, p_s) < p_e <= now_ts:
                    nap_events.append((p_e, f"Aktiv seit {start_hm}"))

        if not nap.get("is_open"):
            e_dt = _parse_iso(nap.get("end_iso"), local_tz)
            if e_dt and e_dt.timestamp() <= now_ts:
                e_ts = max(nap_events[-1][0] + 0.001, e_dt.timestamp())
                nap_events.append((e_ts, f"{start_hm} – {end_hm} ({dur_fmt})"))

        # Deduplicate consecutive identical states
        deduped: list[tuple[float, str]] = []
        for ts_v, st_v in nap_events:
            if not deduped or deduped[-1][1] != st_v:
                adj = max(ts_v, deduped[-1][0] + 0.001) if deduped else ts_v
                deduped.append((adj, st_v))
        if deduped:
            out[f"nap_{nap_num}"] = (min(day_start, deduped[0][0] - 1.0), deduped)

    return out


def _update_in_memory_last_changed(
    hass: HomeAssistant, entity_id: str, last_changed_ts: float
) -> None:
    """Update the live in-memory State.last_changed without emitting a new recorder event."""
    try:
        cur = hass.states.get(entity_id)
        if cur is None or cur.state in ("unknown", "unavailable"):
            return
        target_utc = datetime.datetime.fromtimestamp(
            last_changed_ts, tz=datetime.timezone.utc
        )
        if abs((cur.last_changed - target_utc).total_seconds()) <= 2.0:
            return
        states_dict = getattr(hass.states, "_states", None)
        if isinstance(states_dict, dict) and entity_id in states_dict:
            last_upd = max(target_utc, cur.last_updated)
            states_dict[entity_id] = State(
                entity_id,
                cur.state,
                cur.attributes,
                last_changed=target_utc,
                last_updated=last_upd,
                context=cur.context,
            )
    except Exception as err:
        _LOGGER.debug("Could not adjust in-memory last_changed for %s: %s", entity_id, err)


async def async_reconcile_baby_recorder(
    hass: HomeAssistant,
    baby_id: str,
    logs: list[dict[str, Any]],
    summary: dict[str, Any],
) -> bool:
    """Reconcile Home Assistant Recorder state history for a baby against Napper's source of truth.

    Returns True when sync succeeded (or recorder is disabled), False if entities are not in Recorder yet.
    """
    if "recorder" not in hass.config.components:
        return True

    try:
        from homeassistant.components.recorder import get_instance
        from homeassistant.components.recorder.db_schema import States, StatesMeta
        from homeassistant.components.recorder.util import session_scope
    except Exception as err:
        _LOGGER.debug("Recorder imports unavailable, skipping history sync: %s", err)
        return True

    try:
        recorder_instance = get_instance(hass)
    except Exception:
        return False

    now = datetime.datetime.now().astimezone()
    timelines = build_authoritative_timelines(logs, now=now)
    window_start_ts = timelines.get("window_start_ts")
    sleep_timeline: list[tuple[float, str]] = timelines.get("sleep_status") or []
    binary_timeline: list[tuple[float, str]] = timelines.get("sleeping_binary") or []

    ent_reg = er.async_get(hass)
    entity_plans: dict[str, tuple[float, list[tuple[float, str]]]] = {}

    if window_start_ts is not None and sleep_timeline:
        sleep_eid = ent_reg.async_get_entity_id(
            "sensor", DOMAIN, f"{baby_id}_sleep_status"
        )
        if sleep_eid:
            entity_plans[sleep_eid] = (window_start_ts, sleep_timeline)

    if window_start_ts is not None and binary_timeline:
        bin_eid = ent_reg.async_get_entity_id(
            "binary_sensor", DOMAIN, f"{baby_id}_sleeping"
        )
        if bin_eid:
            entity_plans[bin_eid] = (window_start_ts, binary_timeline)

    extra_timelines = build_today_nap_and_wake_timelines(summary, logs, now=now)
    for key_suffix, (w_start, tl) in extra_timelines.items():
        eid = ent_reg.async_get_entity_id("sensor", DOMAIN, f"{baby_id}_{key_suffix}")
        if eid and tl:
            entity_plans[eid] = (w_start, tl)

    # Also collect remaining sensors on this child to heal any out-of-order rows
    repair_only_eids: list[str] = []
    for suffix in (
        "upcoming_event",
        "predicted_bedtime",
        "awake_duration",
        "total_day_sleep",
        "nap_1",
        "nap_2",
        "nap_3",
        "nap_4",
    ):
        eid = ent_reg.async_get_entity_id("sensor", DOMAIN, f"{baby_id}_{suffix}")
        if eid and eid not in entity_plans:
            repair_only_eids.append(eid)

    if not entity_plans and not repair_only_eids:
        return False

    # Ensure all pending state_changed events are flushed to Recorder DB first
    try:
        await hass.async_block_till_done()
        await recorder_instance.async_block_till_done()
    except Exception:
        pass

    valid_state_cols = {col.name for col in States.__table__.columns}

    def _sync_db() -> tuple[bool, dict[str, int | None]]:
        committed_ids: dict[str, int | None] = {}
        found_all_planned = True
        with session_scope(hass=hass) as session:
            # 1. Reconcile authoritative Napper timelines
            for entity_id, (win_start, desired_tl) in entity_plans.items():
                meta = (
                    session.query(StatesMeta)
                    .filter(StatesMeta.entity_id == entity_id)
                    .first()
                )
                if meta is None:
                    found_all_planned = False
                    continue
                meta_id = meta.metadata_id

                anchor_row = (
                    session.query(States)
                    .filter(
                        States.metadata_id == meta_id,
                        States.last_updated_ts < win_start - 0.5,
                    )
                    .order_by(States.last_updated_ts.desc(), States.state_id.desc())
                    .first()
                )
                window_rows = (
                    session.query(States)
                    .filter(
                        States.metadata_id == meta_id,
                        States.last_updated_ts >= win_start - 0.5,
                    )
                    .order_by(States.last_updated_ts.asc(), States.state_id.asc())
                    .all()
                )

                # Build effective desired transitions relative to anchor_row
                effective_tl: list[tuple[float, str]] = []
                running_state = anchor_row.state if anchor_row is not None else None
                for ts_val, st_val in desired_tl:
                    if st_val != running_state:
                        effective_tl.append((ts_val, st_val))
                        running_state = st_val

                # Check if existing DB rows already match effective_tl with valid monotonic chain
                already_matches = len(window_rows) == len(effective_tl)
                if already_matches:
                    expected_prev_id = (
                        anchor_row.state_id if anchor_row is not None else None
                    )
                    for row, (exp_ts, exp_st) in zip(window_rows, effective_tl):
                        row_ts = row.last_updated_ts or 0.0
                        if (
                            row.state != exp_st
                            or abs(row_ts - exp_ts) > 2.0
                            or row.old_state_id != expected_prev_id
                        ):
                            already_matches = False
                            break
                        expected_prev_id = row.state_id

                if already_matches:
                    continue

                # Pick template attributes_id & origin_idx from most recent existing row
                template_row = window_rows[-1] if window_rows else anchor_row
                attrs_id = (
                    getattr(template_row, "attributes_id", None)
                    if template_row is not None
                    else None
                )
                for r in reversed(window_rows):
                    if getattr(r, "attributes_id", None) is not None:
                        attrs_id = r.attributes_id
                        break
                origin_idx = (
                    getattr(template_row, "origin_idx", 0)
                    if template_row is not None
                    else 0
                )

                ids_to_delete = [r.state_id for r in window_rows]
                if ids_to_delete:
                    session.query(States).filter(
                        States.metadata_id == meta_id,
                        States.old_state_id.in_(ids_to_delete),
                    ).update({States.old_state_id: None}, synchronize_session=False)
                    session.query(States).filter(
                        States.state_id.in_(ids_to_delete)
                    ).update({States.old_state_id: None}, synchronize_session=False)
                    session.flush()
                    session.query(States).filter(
                        States.state_id.in_(ids_to_delete)
                    ).delete(synchronize_session=False)
                    session.flush()

                prev_id = anchor_row.state_id if anchor_row is not None else None
                for ts_val, st_val in effective_tl:
                    kwargs: dict[str, Any] = {
                        "metadata_id": meta_id,
                        "state": st_val,
                        "attributes_id": attrs_id,
                        "last_updated_ts": float(ts_val),
                        "last_changed_ts": None,
                        "old_state_id": prev_id,
                    }
                    if "last_reported_ts" in valid_state_cols:
                        kwargs["last_reported_ts"] = float(ts_val)
                    if "origin_idx" in valid_state_cols:
                        kwargs["origin_idx"] = origin_idx
                    if "context_id_bin" in valid_state_cols:
                        kwargs["context_id_bin"] = os.urandom(16)

                    filtered_kwargs = {
                        k: v for k, v in kwargs.items() if k in valid_state_cols
                    }
                    new_row = States(**filtered_kwargs)
                    session.add(new_row)
                    session.flush()
                    prev_id = new_row.state_id

                committed_ids[entity_id] = prev_id

            # 2. Repair any out-of-order rows on remaining sensors from earlier backdating
            cutoff_ts = now.timestamp() - 48 * 3600
            for entity_id in repair_only_eids:
                meta = (
                    session.query(StatesMeta)
                    .filter(StatesMeta.entity_id == entity_id)
                    .first()
                )
                if meta is None:
                    continue
                meta_id = meta.metadata_id
                recent_rows = (
                    session.query(States)
                    .filter(
                        States.metadata_id == meta_id,
                        States.last_updated_ts >= cutoff_ts,
                    )
                    .order_by(States.state_id.asc())
                    .all()
                )
                by_id = {r.state_id: r for r in recent_rows}
                bad_ids = [
                    r.state_id
                    for r in recent_rows
                    if r.old_state_id in by_id
                    and (r.last_updated_ts or 0.0)
                    < (by_id[r.old_state_id].last_updated_ts or 0.0) - 1.0
                ]
                if bad_ids:
                    session.query(States).filter(
                        States.metadata_id == meta_id,
                        States.old_state_id.in_(bad_ids),
                    ).update({States.old_state_id: None}, synchronize_session=False)
                    session.query(States).filter(
                        States.state_id.in_(bad_ids)
                    ).update({States.old_state_id: None}, synchronize_session=False)
                    session.flush()
                    session.query(States).filter(
                        States.state_id.in_(bad_ids)
                    ).delete(synchronize_session=False)
                    session.flush()
                    latest_remaining = (
                        session.query(States)
                        .filter(States.metadata_id == meta_id)
                        .order_by(States.last_updated_ts.desc(), States.state_id.desc())
                        .first()
                    )
                    committed_ids[entity_id] = (
                        latest_remaining.state_id if latest_remaining else None
                    )

        return found_all_planned, committed_ids

    try:
        all_ready, committed_map = await recorder_instance.async_add_executor_job(_sync_db)
    except Exception as err:
        _LOGGER.warning("Failed to reconcile Napper history in Recorder: %s", err)
        return False

    # Update Recorder's in-memory StatesManager._last_committed_id cache
    sm = getattr(recorder_instance, "states_manager", None)
    if sm is not None and committed_map:
        last_comm = getattr(sm, "_last_committed_id", None)
        if isinstance(last_comm, dict):
            for eid, sid in committed_map.items():
                if sid is not None:
                    last_comm[eid] = sid
                else:
                    last_comm.pop(eid, None)

    # Update live in-memory State.last_changed so dashboard cards show exact relative time
    for eid, (_w_start, tl) in entity_plans.items():
        if tl:
            _update_in_memory_last_changed(hass, eid, tl[-1][0])

    return all_ready
