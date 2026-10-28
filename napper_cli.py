#!/usr/bin/env python3
"""
Standalone CLI & API client for the Napper baby sleep tracker app (https://api.napper.app).
Uses only the Python standard library.

Verwendung / Usage:
  python3 napper_cli.py login <email>
  python3 napper_cli.py status [baby_name_oder_id] [--json]
  python3 napper_cli.py start-nap [baby_name_oder_id] [-m MINUTEN_VORHER]
  python3 napper_cli.py stop-sleep [baby_name_oder_id] [-m MINUTEN_VORHER]
  python3 napper_cli.py bedtime [baby_name_oder_id] [-m MINUTEN_VORHER]
  python3 napper_cli.py wakeup [baby_name_oder_id] [-m MINUTEN_VORHER]
"""

from __future__ import annotations

import argparse
import base64
import datetime
import json
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any

API_BASE_URL = "https://api.napper.app"
APP_VERSION = "6.84.0"
AUTH_FILE = pathlib.Path(__file__).with_name("napper_auth.json")
FALLBACK_AUTH_FILE = pathlib.Path("/tmp/napper_auth.json")

NAP_ORDINAL_DE: dict[int, str] = {
    1: "Erstes Nickerchen",
    2: "Zweites Nickerchen",
    3: "Drittes Nickerchen",
    4: "Viertes Nickerchen",
    5: "Fünftes Nickerchen",
}


def resolve_target_datetime(
    dt: datetime.datetime | None = None,
    minutes_ago: int = 0,
) -> datetime.datetime:
    """Resolve a target timestamp, optionally subtracting minutes_ago."""
    if dt is None:
        base = datetime.datetime.now().astimezone()
    elif dt.tzinfo is None:
        base = dt.astimezone()
    else:
        base = dt
    if minutes_ago:
        base = base - datetime.timedelta(minutes=int(minutes_ago))
    return base


def get_time_with_timezone(dt: datetime.datetime | None = None) -> str:
    """Format a datetime as ISO-8601 with local timezone offset (e.g. 2026-10-28T14:30:00.000+01:00)."""
    if dt is None:
        dt = datetime.datetime.now().astimezone()
    elif dt.tzinfo is None:
        dt = dt.astimezone()
    return dt.isoformat(timespec="milliseconds")


def get_start_minutes_after_midnight(category: str, dt: datetime.datetime) -> int:
    """Match Napper's getStartMinutesAfterMidnight(category, start)."""
    local_dt = dt.astimezone() if dt.tzinfo else dt
    minutes = local_dt.hour * 60 + local_dt.minute
    if category == "BED_TIME" and local_dt.hour < 12:
        minutes += 1440
    return minutes


def create_log_id(category: str, start_iso: str) -> str:
    """Match Napper's createLogId(category, start)."""
    if category in ("WOKE_UP", "BED_TIME"):
        day_str = start_iso.split("T")[0]
        return f"LOG_{day_str}_{category}"
    return f"LOG_{uuid.uuid4()}_{category}"


def build_empty_log(
    log_id: str,
    category: str,
    start_iso: str,
    end_iso: str,
    start_minutes_after_midnight: int,
    user_id: str | None,
    is_open: bool = False,
) -> dict[str, Any]:
    """Construct a complete Napper log payload for PUT /logs/{babyId}."""
    return {
        "id": log_id,
        "start": start_iso,
        "end": end_iso,
        "category": category,
        "startMinutesAfterMidnight": start_minutes_after_midnight,
        "overallHappiness": None,
        "babyMoodOnWakeUp": None,
        "babyMoodOnSleep": None,
        "diaperWeight": None,
        "diaperContent": None,
        "breastLeftMinutes": None,
        "breastRightMinutes": None,
        "feedingAmount": None,
        "amountPumpedLeft": None,
        "amountPumpedRight": None,
        "bottleFeedingType": None,
        "comment": None,
        "isOpen": is_open,
        "activeBreast": None,
        "skipped": False,
        "createdByUserId": user_id,
        "temperature": None,
        "pauses": [],
        "howBabySlept": None,
        "howBabyWoke": None,
        "timeToFallAsleep": None,
        "source": None,
    }


def is_jwt_expired(token: str, leeway_seconds: int = 300) -> bool:
    """Check if a JWT idToken is expired or within leeway_seconds of expiring."""
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return True
        payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64).decode("utf-8"))
        exp = payload.get("exp")
        if not exp:
            return False
        return time.time() + leeway_seconds >= float(exp)
    except Exception:
        return True


def parse_napper_iso(ts: str | None) -> datetime.datetime | None:
    """Parse an ISO timestamp (aware or naive local) into a local timezone-aware datetime."""
    if not ts:
        return None
    try:
        dt = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        local_tz = datetime.datetime.now().astimezone().tzinfo
        if dt.tzinfo is None:
            return dt.replace(tzinfo=local_tz)
        return dt.astimezone(local_tz)
    except Exception:
        return None


def format_duration_de(minutes: int) -> str:
    """Format minutes in German (e.g. '44 Min.', '1 Std. 56 Min.')."""
    mins = abs(int(minutes))
    if mins < 60:
        return f"{mins} Min."
    hours = mins // 60
    rem = mins % 60
    if rem == 0:
        return f"{hours} Std."
    return f"{hours} Std. {rem} Min."


class NapperClient:
    def __init__(
        self,
        id_token: str = "",
        refresh_token: str = "",
        device_id: str | None = None,
        user_id: str | None = None,
        language: str = "de",
        locale: str = "de-DE",
    ) -> None:
        self.id_token = id_token
        self.refresh_token = refresh_token
        self.device_id = device_id or str(uuid.uuid4())
        self.user_id = user_id
        self.language = language
        self.locale = locale

    def _headers(self, authenticated: bool = True) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {self.id_token}" if (authenticated and self.id_token) else "",
            "source": "APP",
            "platform": "android",
            "device": self.device_id,
            "version": APP_VERSION,
            "native-version": APP_VERSION,
            "bundle-version": APP_VERSION,
            "language": self.language,
            "locale": self.locale,
            "local-timestamp": get_time_with_timezone(),
        }

    def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        authenticated: bool = True,
        retry_auth: bool = True,
    ) -> Any:
        if authenticated and self.id_token and self.refresh_token and is_jwt_expired(self.id_token):
            self.refresh_tokens()

        url = f"{API_BASE_URL}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(
            url,
            data=data,
            headers=self._headers(authenticated=authenticated),
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as err:
            if err.code == 401 and authenticated and retry_auth and self.refresh_token:
                self.refresh_tokens()
                return self._request(method, path, body=body, authenticated=authenticated, retry_auth=False)
            err_body = err.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {err.code} on {method} {path}: {err_body}") from err

    def send_email_otp(self, email: str) -> Any:
        return self._request(
            "POST",
            "/auth/send-otp",
            body={
                "email": email,
                "useDeviceId": True,
                "source": "APP",
                "language": self.language,
            },
            authenticated=False,
        )

    def _extract_tokens(self, item: dict[str, Any]) -> dict[str, str]:
        id_tok = item["idToken"]
        ref_tok = item["refreshToken"]
        if isinstance(id_tok, dict):
            sub = id_tok.get("payload", {}).get("sub")
            if sub and not self.user_id:
                self.user_id = sub
            id_tok = id_tok["token"]
        if isinstance(ref_tok, dict):
            ref_tok = ref_tok["token"]
        self.id_token = id_tok
        self.refresh_token = ref_tok
        self.save_to_disk()
        return {"idToken": self.id_token, "refreshToken": self.refresh_token}

    def login_with_email(self, email: str, otp: str) -> dict[str, str]:
        resp = self._request(
            "POST",
            "/auth/email-login",
            body={
                "email": email,
                "otp": otp.strip(),
                "useDeviceId": True,
            },
            authenticated=False,
        )
        item = resp.get("item", resp)
        return self._extract_tokens(item)

    def refresh_tokens(self) -> dict[str, str]:
        resp = self._request(
            "POST",
            "/auth/refresh-token",
            body={
                "idToken": self.id_token,
                "refreshToken": self.refresh_token,
            },
            authenticated=False,
            retry_auth=False,
        )
        item = resp.get("item", resp)
        return self._extract_tokens(item)

    def get_user(self) -> dict[str, Any]:
        resp = self._request("GET", "/users")
        item = resp.get("item", resp)
        if isinstance(item, dict) and "id" in item:
            self.user_id = item["id"]
        return item

    def get_babies(self) -> list[dict[str, Any]]:
        resp = self._request("GET", "/babies")
        return resp.get("items", resp.get("item", []))

    def get_today(self, baby_id: str, dt: datetime.datetime | None = None) -> dict[str, Any]:
        date_str = urllib.parse.quote(get_time_with_timezone(dt), safe="")
        resp = self._request("GET", f"/today/{baby_id}/{date_str}")
        return resp.get("item", resp)

    def get_logs_by_day(self, baby_id: str, day_yyyy_mm_dd: str) -> list[dict[str, Any]]:
        resp = self._request("GET", f"/logs-by-day/{baby_id}/{day_yyyy_mm_dd}")
        item = resp.get("item", resp)
        return item.get("allLogs", item.get("logs", []))

    def get_predicted_schedule(self, baby_id: str, dt: datetime.datetime | None = None) -> Any:
        date_str = urllib.parse.quote(get_time_with_timezone(dt), safe="")
        resp = self._request("GET", f"/predict-schedule/{baby_id}/{date_str}")
        return resp.get("item", resp)

    def put_log(self, baby_id: str, log_payload: dict[str, Any]) -> Any:
        return self._request("PUT", f"/logs/{baby_id}", body=log_payload)

    def delete_log(self, baby_id: str, log_id: str, cascade_night_wakings: bool = False) -> Any:
        suffix = "?cascadeNightWakings=true" if cascade_night_wakings else ""
        return self._request("DELETE", f"/logs/{baby_id}/{log_id}{suffix}")

    def start_open_nap(
        self,
        baby_id: str,
        start_dt: datetime.datetime | None = None,
        minutes_ago: int = 0,
    ) -> dict[str, Any]:
        dt = resolve_target_datetime(start_dt, minutes_ago)
        iso = get_time_with_timezone(dt)
        log = build_empty_log(
            log_id=create_log_id("NAP", iso),
            category="NAP",
            start_iso=iso,
            end_iso=iso,
            start_minutes_after_midnight=get_start_minutes_after_midnight("NAP", dt),
            user_id=self.user_id,
            is_open=True,
        )
        self.put_log(baby_id, log)
        return log

    def stop_open_sleep(
        self,
        baby_id: str,
        end_dt: datetime.datetime | None = None,
        minutes_ago: int = 0,
    ) -> dict[str, Any] | None:
        today = self.get_today(baby_id)
        logs = today.get("logs", today.get("allLogs", []))
        open_logs = [
            entry
            for entry in logs
            if entry.get("isOpen") and entry.get("category") in ("NAP", "BED_TIME", "NIGHT_WAKING")
        ]
        if not open_logs:
            return None
        current = open_logs[0]
        dt = resolve_target_datetime(end_dt, minutes_ago)
        end_iso = get_time_with_timezone(dt)
        updated = dict(current)
        updated["end"] = end_iso
        updated["isOpen"] = False
        self.put_log(baby_id, updated)
        return updated

    def start_bedtime(
        self,
        baby_id: str,
        start_dt: datetime.datetime | None = None,
        minutes_ago: int = 0,
    ) -> dict[str, Any]:
        dt = resolve_target_datetime(start_dt, minutes_ago)
        iso = get_time_with_timezone(dt)
        log = build_empty_log(
            log_id=create_log_id("BED_TIME", iso),
            category="BED_TIME",
            start_iso=iso,
            end_iso=iso,
            start_minutes_after_midnight=get_start_minutes_after_midnight("BED_TIME", dt),
            user_id=self.user_id,
            is_open=True,
        )
        self.put_log(baby_id, log)
        return log

    def log_woke_up(
        self,
        baby_id: str,
        wake_dt: datetime.datetime | None = None,
        minutes_ago: int = 0,
    ) -> dict[str, Any]:
        dt = resolve_target_datetime(wake_dt, minutes_ago)
        iso = get_time_with_timezone(dt)
        today = self.get_today(baby_id)
        for entry in today.get("logs", today.get("allLogs", [])):
            if entry.get("isOpen") and entry.get("category") in ("BED_TIME", "NIGHT_WAKING"):
                closed = dict(entry)
                closed["end"] = iso
                closed["isOpen"] = False
                self.put_log(baby_id, closed)

        log = build_empty_log(
            log_id=create_log_id("WOKE_UP", iso),
            category="WOKE_UP",
            start_iso=iso,
            end_iso=iso,
            start_minutes_after_midnight=get_start_minutes_after_midnight("WOKE_UP", dt),
            user_id=self.user_id,
            is_open=False,
        )
        self.put_log(baby_id, log)
        return log

    def save_to_disk(self, extra: dict[str, Any] | None = None) -> pathlib.Path:
        existing: dict[str, Any] = {}
        for candidate in (AUTH_FILE, FALLBACK_AUTH_FILE):
            if candidate.exists():
                try:
                    existing = json.loads(candidate.read_text(encoding="utf-8"))
                    break
                except Exception:
                    pass
        existing.update(
            {
                "idToken": self.id_token,
                "refreshToken": self.refresh_token,
                "deviceId": self.device_id,
                "userId": self.user_id,
            }
        )
        if extra:
            existing.update(extra)
        serialized = json.dumps(existing, indent=2)
        try:
            AUTH_FILE.write_text(serialized, encoding="utf-8")
            AUTH_FILE.chmod(0o600)
            return AUTH_FILE
        except PermissionError:
            FALLBACK_AUTH_FILE.write_text(serialized, encoding="utf-8")
            FALLBACK_AUTH_FILE.chmod(0o600)
            return FALLBACK_AUTH_FILE

    @classmethod
    def load_from_disk(cls) -> tuple["NapperClient", dict[str, Any]]:
        target = AUTH_FILE if AUTH_FILE.exists() else FALLBACK_AUTH_FILE
        if not target.exists():
            raise SystemExit(
                f"Anmeldedaten nicht gefunden unter {AUTH_FILE}. Bitte ausführen: python3 napper_cli.py login <email>"
            )
        data = json.loads(target.read_text(encoding="utf-8"))
        client = cls(
            id_token=data.get("idToken", ""),
            refresh_token=data.get("refreshToken", ""),
            device_id=data.get("deviceId"),
            user_id=data.get("userId"),
        )
        return client, data


def print_german_status(baby: dict[str, Any], today: dict[str, Any]) -> None:
    """Print a readable German summary of the child's day schedule."""
    now = datetime.datetime.now().astimezone()
    logs = today.get("logs", today.get("allLogs", []))
    schedule_items = today.get("scheduleItems", [])

    # Wake-up
    woke_log = next(
        (
            e
            for e in logs
            if e.get("category") == "WOKE_UP"
            and not e.get("skipped")
            and (parse_napper_iso(e.get("start")) or now).date() == now.date()
        ),
        None,
    )
    if woke_log:
        wake_dt = parse_napper_iso(woke_log.get("start")) or now
        wake_status = "getrackt"
    else:
        wake_dt = now.replace(hour=7, minute=0, second=0, microsecond=0)
        wake_status = "erwartet"

    # Today's naps
    nap_logs = [
        e
        for e in logs
        if e.get("category") == "NAP"
        and not e.get("skipped")
        and (parse_napper_iso(e.get("start")) or now) >= wake_dt - datetime.timedelta(minutes=5)
    ]
    nap_logs.sort(key=lambda x: x.get("start", ""))

    sched_naps = [
        s for s in schedule_items if (s.get("type") or s.get("category")) == "NAP"
    ]
    sched_naps.sort(key=lambda x: (x.get("napNumber", 99), x.get("time", "")))

    print(f"=== Napper Tagesübersicht für {baby.get('name')} ({baby.get('id')}) ===")
    print(f"Aufwachzeit:   {wake_dt.strftime('%H:%M')} Uhr ({wake_status})")

    total_tracked = 0
    for idx, nlog in enumerate(nap_logs, start=1):
        label = NAP_ORDINAL_DE.get(idx, f"{idx}. Nickerchen")
        s_dt = parse_napper_iso(nlog.get("start")) or now
        if nlog.get("isOpen"):
            dur = max(0, round((now - s_dt).total_seconds() / 60))
            total_tracked += dur
            print(f"{label:18s}: seit {s_dt.strftime('%H:%M')} Uhr ({format_duration_de(dur)}, aktiv)")
        else:
            e_dt = parse_napper_iso(nlog.get("end")) or s_dt
            dur = max(1, round((e_dt - s_dt).total_seconds() / 60))
            total_tracked += dur
            print(
                f"{label:18s}: {s_dt.strftime('%H:%M')}–{e_dt.strftime('%H:%M')} Uhr "
                f"({format_duration_de(dur)}, getrackt)"
            )

    logged_count = len(nap_logs)
    next_event_str: str | None = None
    for s in sched_naps:
        s_num = int(s.get("napNumber") or 0)
        if s.get("completed") or s_num <= logged_count:
            continue
        s_dt = parse_napper_iso(s.get("time") or s.get("start"))
        if not s_dt:
            continue
        dur = int(s.get("duration") or 45)
        e_dt = s_dt + datetime.timedelta(minutes=dur)
        label = NAP_ORDINAL_DE.get(s_num, f"{s_num}. Nickerchen")
        print(
            f"{label:18s}: {s_dt.strftime('%H:%M')}–{e_dt.strftime('%H:%M')} Uhr "
            f"({format_duration_de(dur)}, erwartet)"
        )
        if next_event_str is None:
            mins_left = round((s_dt - now).total_seconds() / 60)
            next_event_str = f"{label} in {format_duration_de(mins_left)} (um {s_dt.strftime('%H:%M')} Uhr)"

    sched_bed = next(
        (
            s
            for s in reversed(schedule_items)
            if (s.get("type") or s.get("category")) == "BED_TIME"
        ),
        None,
    )
    if sched_bed:
        bed_dt = parse_napper_iso(sched_bed.get("time") or sched_bed.get("start")) or now
        bed_status = "getrackt" if sched_bed.get("completed") else "erwartet"
        print(f"Schlafenszeit: {bed_dt.strftime('%H:%M')} Uhr ({bed_status})")
        if next_event_str is None:
            mins_left = round((bed_dt - now).total_seconds() / 60)
            next_event_str = f"Ins Bett gehen in {format_duration_de(mins_left)} (um {bed_dt.strftime('%H:%M')} Uhr)"

    print(f"Tagesschlaf:   {format_duration_de(total_tracked)} (getrackt)")
    if next_event_str:
        print(f"Nächstes:      {next_event_str}")


def resolve_baby(babies: list[dict[str, Any]], query: str | None) -> dict[str, Any]:
    """Resolve baby by ID or name (case-insensitive), or return the first baby."""
    if not query:
        return babies[0]
    q = query.strip().lower()
    for b in babies:
        if str(b.get("id", "")).lower() == q or str(b.get("name", "")).lower() == q:
            return b
    raise SystemExit(
        f"Kind '{query}' nicht gefunden. Verfügbare Kinder: "
        + ", ".join(f"{b.get('name')} ({b.get('id')})" for b in babies)
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Napper Baby-Schlaftracker CLI (Deutsch)"
    )
    parser.add_argument(
        "command",
        choices=[
            "login",
            "status",
            "start-nap",
            "stop-nap",
            "stop-sleep",
            "bedtime",
            "wakeup",
            "woke-up",
        ],
        help="Auszuführender Befehl",
    )
    parser.add_argument(
        "target",
        nargs="?",
        default=None,
        help="E-Mail (bei login) oder Name/ID des Kindes (optional)",
    )
    parser.add_argument(
        "-m",
        "--minutes-ago",
        type=int,
        default=0,
        help="Ereignis vor X Minuten in der Vergangenheit eintragen (Standard: 0 = jetzt)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Rohe JSON-Antwort ausgeben (bei status)",
    )
    args = parser.parse_args()

    cmd = args.command.lower()
    if cmd == "login":
        if not args.target:
            raise SystemExit("Verwendung: python3 napper_cli.py login <email>")
        email = args.target.strip()
        client = NapperClient()
        print(f"Fordere Einmalcode (OTP) für {email} an...")
        client.send_email_otp(email)
        otp = input("Bitte den 6-stelligen Code aus der E-Mail eingeben: ").strip()
        client.login_with_email(email, otp)
        user = client.get_user()
        babies = client.get_babies()
        saved_path = client.save_to_disk({"email": email, "babies": babies})
        print(f"\nErfolgreich angemeldet als Benutzer {user.get('id')}!")
        print(f"Zugangsdaten gespeichert unter {saved_path}")
        print("\nKinder im Konto:")
        for b in babies:
            print(f"  - {b.get('name')} (babyId: {b.get('id')}, Geburtsdatum: {b.get('birthday')})")
        return

    client, saved = NapperClient.load_from_disk()
    babies = saved.get("babies") or client.get_babies()
    if not babies:
        raise SystemExit("Keine Kinder in diesem Napper-Konto gefunden.")

    baby = resolve_baby(babies, args.target)
    baby_id = baby["id"]
    baby_name = baby.get("name", baby_id)
    minutes_ago = max(0, int(args.minutes_ago or 0))
    offset_note = f" (vor {minutes_ago} Min.)" if minutes_ago else " (jetzt)"

    if cmd == "status":
        today = client.get_today(baby_id)
        if args.json:
            print(json.dumps(today, indent=2, ensure_ascii=False))
        else:
            print_german_status(baby, today)
    elif cmd == "start-nap":
        log = client.start_open_nap(baby_id, minutes_ago=minutes_ago)
        print(f"Nickerchen gestartet für {baby_name}{offset_note}: {log['id']} um {log['start']}")
    elif cmd in ("stop-nap", "stop-sleep"):
        updated = client.stop_open_sleep(baby_id, minutes_ago=minutes_ago)
        if updated:
            print(f"Schlaf beendet für {baby_name}{offset_note}: {updated['id']} um {updated['end']}")
        else:
            print(f"Kein aktiver Schlaf-Timer für {baby_name} gefunden.")
    elif cmd == "bedtime":
        log = client.start_bedtime(baby_id, minutes_ago=minutes_ago)
        print(f"Schlafenszeit eingetragen für {baby_name}{offset_note}: {log['id']} um {log['start']}")
    elif cmd in ("wakeup", "woke-up"):
        log = client.log_woke_up(baby_id, minutes_ago=minutes_ago)
        print(f"Aufwachen eingetragen für {baby_name}{offset_note}: {log['id']} um {log['start']}")


if __name__ == "__main__":
    main()
