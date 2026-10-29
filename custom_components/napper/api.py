"""Async API Client for Napper (https://api.napper.app)."""

from __future__ import annotations

import base64
from collections.abc import Callable
import datetime
import json
import time
import urllib.parse
import uuid
from typing import Any

import aiohttp

from .const import API_BASE_URL, APP_VERSION


def get_time_with_timezone(dt: datetime.datetime | None = None) -> str:
    """Format a datetime as ISO-8601 with local timezone offset (e.g. 2026-10-28T14:30:00.000+01:00)."""
    if dt is None:
        dt = datetime.datetime.now().astimezone()
    elif dt.tzinfo is None:
        dt = dt.astimezone()
    return dt.isoformat(timespec="milliseconds")


def parse_absolute_time_str(
    time_str: str | None, now: datetime.datetime | None = None
) -> datetime.datetime | None:
    """Parse an absolute time string like '17:37' or '07:05' into a timezone-aware datetime."""
    if not time_str or not str(time_str).strip():
        return None
    raw = str(time_str).strip()
    if now is None:
        now = datetime.datetime.now().astimezone()
    elif now.tzinfo is None:
        now = now.astimezone()

    # Check if full ISO datetime was passed
    if "T" in raw:
        try:
            dt = datetime.datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return dt.astimezone(now.tzinfo) if dt.tzinfo else dt.replace(tzinfo=now.tzinfo)
        except Exception:
            pass

    parts = raw.split(":")
    if len(parts) not in (2, 3):
        raise ValueError(f"Ungültiges Uhrzeit-Format '{raw}'. Erwartet wird HH:MM (z. B. 17:37).")
    try:
        hour = int(parts[0])
        minute = int(parts[1])
        second = int(parts[2]) if len(parts) == 3 else 0
    except ValueError as err:
        raise ValueError(
            f"Ungültiges Uhrzeit-Format '{raw}'. Erwartet wird HH:MM (z. B. 17:37)."
        ) from err

    if not (0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59):
        raise ValueError(
            f"Ungültige Uhrzeit '{raw}'. Stunde muss 0–23 und Minute 0–59 sein."
        )

    target_dt = now.replace(hour=hour, minute=minute, second=second, microsecond=0)
    # If the entered time is more than 5 minutes in the future (e.g. entering 23:50 at 00:05),
    # assume it refers to the previous calendar day.
    if target_dt > now + datetime.timedelta(minutes=5):
        target_dt -= datetime.timedelta(days=1)
    return target_dt


def resolve_target_datetime(
    dt: datetime.datetime | None = None,
    minutes_ago: int | float = 0,
) -> datetime.datetime:
    """Resolve a target datetime from an explicit datetime or a minutes_ago offset."""
    if dt is not None:
        return dt.astimezone() if dt.tzinfo else dt.astimezone()
    now = datetime.datetime.now().astimezone()
    if minutes_ago and minutes_ago > 0:
        return now - datetime.timedelta(minutes=float(minutes_ago))
    return now


def get_start_minutes_after_midnight(category: str, dt: datetime.datetime) -> int:
    """Match Napper's getStartMinutesAfterMidnight(start, category).

    When `start` is passed as the unadjusted ISO timestamp, `startMinutesAfterMidnight`
    must be 0 so Napper's `mapLog` does not add an extra offset on top of `start`.
    """
    return 0


def create_log_id(category: str, start_iso: str) -> str:
    """Match Napper's createLogId(category, start)."""
    if category in ("WOKE_UP", "BED_TIME"):
        day_str = start_iso.split("T")[0]
        return f"LOG_{day_str}_{category}"
    return f"LOG_{uuid.uuid4()}_{category}"


def is_nap_log_paused(log: dict[str, Any] | None) -> bool:
    """Return True if an open NAP log currently has an active (open) pause."""
    if not log or not log.get("isOpen"):
        return False
    pauses = log.get("pauses")
    if not isinstance(pauses, list) or not pauses:
        return False
    last_pause = pauses[-1]
    return isinstance(last_pause, dict) and not last_pause.get("end")


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


class NapperApiError(Exception):
    """Exception raised for Napper API errors."""


class NapperAuthError(NapperApiError):
    """Exception raised for Napper authentication errors."""


class NapperApiClient:
    """Async client for Napper REST API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        id_token: str = "",
        refresh_token: str = "",
        device_id: str | None = None,
        user_id: str | None = None,
        language: str = "de",
        locale: str = "de-DE",
        token_update_callback: Callable[[str, str], None] | None = None,
    ) -> None:
        self._session = session
        self.id_token = id_token
        self.refresh_token = refresh_token
        self.device_id = device_id or str(uuid.uuid4())
        self.user_id = user_id
        self.language = language
        self.locale = locale
        self._token_update_callback = token_update_callback

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

    async def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        authenticated: bool = True,
        retry_auth: bool = True,
    ) -> Any:
        if authenticated and self.id_token and self.refresh_token and is_jwt_expired(self.id_token):
            await self.async_refresh_tokens()

        url = f"{API_BASE_URL}{path}"
        async with self._session.request(
            method,
            url,
            json=body,
            headers=self._headers(authenticated=authenticated),
            timeout=aiohttp.ClientTimeout(total=20),
        ) as resp:
            if resp.status == 401 and authenticated and retry_auth and self.refresh_token:
                await self.async_refresh_tokens()
                return await self._request(
                    method, path, body=body, authenticated=authenticated, retry_auth=False
                )
            if resp.status == 401:
                raise NapperAuthError(f"Unauthorized (401) on {method} {path}")
            if resp.status >= 400:
                text = await resp.text()
                raise NapperApiError(f"HTTP {resp.status} on {method} {path}: {text}")
            text = await resp.text()
            return json.loads(text) if text else {}

    async def async_send_email_otp(self, email: str) -> Any:
        return await self._request(
            "POST",
            "/auth/send-otp",
            body={
                "email": email.strip(),
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
        if self._token_update_callback:
            self._token_update_callback(self.id_token, self.refresh_token)
        return {"idToken": self.id_token, "refreshToken": self.refresh_token}

    async def async_login_with_email(self, email: str, otp: str) -> dict[str, str]:
        resp = await self._request(
            "POST",
            "/auth/email-login",
            body={
                "email": email.strip(),
                "otp": otp.strip(),
                "useDeviceId": True,
            },
            authenticated=False,
        )
        item = resp.get("item", resp)
        return self._extract_tokens(item)

    async def async_refresh_tokens(self) -> dict[str, str]:
        resp = await self._request(
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

    async def async_get_user(self) -> dict[str, Any]:
        resp = await self._request("GET", "/users")
        item = resp.get("item", resp)
        if isinstance(item, dict) and "id" in item:
            self.user_id = item["id"]
        return item

    async def async_get_babies(self) -> list[dict[str, Any]]:
        resp = await self._request("GET", "/babies")
        return resp.get("items", resp.get("item", []))

    async def async_get_today(self, baby_id: str, dt: datetime.datetime | None = None) -> dict[str, Any]:
        date_str = urllib.parse.quote(get_time_with_timezone(dt), safe="")
        resp = await self._request("GET", f"/today/{baby_id}/{date_str}")
        return resp.get("item", resp)

    async def async_put_log(self, baby_id: str, log_payload: dict[str, Any]) -> Any:
        return await self._request("PUT", f"/logs/{baby_id}", body=log_payload)

    async def async_delete_log(
        self, baby_id: str, log_id: str, cascade_night_wakings: bool = False
    ) -> Any:
        suffix = "?cascadeNightWakings=true" if cascade_night_wakings else ""
        return await self._request("DELETE", f"/logs/{baby_id}/{log_id}{suffix}")

    async def async_start_open_nap(
        self,
        baby_id: str,
        start_dt: datetime.datetime | None = None,
        minutes_ago: int | float = 0,
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
        await self.async_put_log(baby_id, log)
        return log

    async def async_stop_open_sleep(
        self,
        baby_id: str,
        current_logs: list[dict[str, Any]] | None = None,
        end_dt: datetime.datetime | None = None,
        minutes_ago: int | float = 0,
    ) -> dict[str, Any] | None:
        if current_logs is None:
            today = await self.async_get_today(baby_id)
            current_logs = today.get("logs", today.get("allLogs", []))
        open_logs = [
            entry
            for entry in current_logs
            if entry.get("isOpen") and entry.get("category") in ("NAP", "BED_TIME", "NIGHT_WAKING")
        ]
        if not open_logs:
            return None
        # current_logs in /today is sorted newest first; pick the most recent open log
        current = open_logs[0]
        dt = resolve_target_datetime(end_dt, minutes_ago)
        try:
            start_parsed = datetime.datetime.fromisoformat(current["start"].replace("Z", "+00:00"))
            if dt < start_parsed:
                dt = start_parsed + datetime.timedelta(minutes=1)
        except Exception:
            pass
        end_iso = get_time_with_timezone(dt)
        updated = dict(current)
        updated["end"] = end_iso
        updated["isOpen"] = False
        await self.async_put_log(baby_id, updated)
        return updated

    async def async_start_bedtime(
        self,
        baby_id: str,
        current_logs: list[dict[str, Any]] | None = None,
        start_dt: datetime.datetime | None = None,
        minutes_ago: int | float = 0,
    ) -> dict[str, Any]:
        """Start night sleep directly (or finish open pre-bedtime tracking so night sleep starts)."""
        dt = resolve_target_datetime(start_dt, minutes_ago)
        if current_logs is None:
            today = await self.async_get_today(baby_id)
            current_logs = today.get("logs", today.get("allLogs", []))

        # If pre-bedtime routine tracking (an open BED_TIME log) is currently running,
        # close it (isOpen=False) so actual night sleep starts immediately.
        open_bedtimes = [
            entry
            for entry in current_logs
            if entry.get("isOpen")
            and not entry.get("skipped")
            and entry.get("category") == "BED_TIME"
        ]
        if open_bedtimes:
            current_bed = open_bedtimes[0]
            try:
                start_parsed = datetime.datetime.fromisoformat(
                    current_bed["start"].replace("Z", "+00:00")
                )
                if dt < start_parsed:
                    dt = start_parsed
            except Exception:
                pass
            end_iso = get_time_with_timezone(dt)
            updated = dict(current_bed)
            updated["end"] = end_iso
            updated["isOpen"] = False
            await self.async_put_log(baby_id, updated)
            return updated

        iso = get_time_with_timezone(dt)
        log = build_empty_log(
            log_id=create_log_id("BED_TIME", iso),
            category="BED_TIME",
            start_iso=iso,
            end_iso=iso,
            start_minutes_after_midnight=get_start_minutes_after_midnight("BED_TIME", dt),
            user_id=self.user_id,
            is_open=False,
        )
        await self.async_put_log(baby_id, log)
        return log

    async def async_pause_nap(
        self,
        baby_id: str,
        current_logs: list[dict[str, Any]] | None = None,
        pause_dt: datetime.datetime | None = None,
        minutes_ago: int | float = 0,
    ) -> dict[str, Any]:
        """Pause the currently active open NAP log."""
        dt = resolve_target_datetime(pause_dt, minutes_ago)
        if current_logs is None:
            today = await self.async_get_today(baby_id)
            current_logs = today.get("logs", today.get("allLogs", []))

        open_naps = [
            entry
            for entry in current_logs
            if entry.get("isOpen") and not entry.get("skipped") and entry.get("category") == "NAP"
        ]
        if not open_naps:
            raise NapperApiError("Kein aktives Nickerchen zum Pausieren gefunden.")

        current_nap = open_naps[0]
        if is_nap_log_paused(current_nap):
            raise NapperApiError("Das aktuelle Nickerchen ist bereits pausiert.")

        try:
            start_parsed = datetime.datetime.fromisoformat(
                current_nap["start"].replace("Z", "+00:00")
            )
            if dt <= start_parsed:
                dt = start_parsed + datetime.timedelta(seconds=1)
        except Exception:
            pass

        pause_start_ms = int(dt.timestamp() * 1000)
        pauses = [dict(p) for p in (current_nap.get("pauses") or []) if isinstance(p, dict)]
        if pauses and pauses[-1].get("end"):
            last_end_ms = int(pauses[-1]["end"])
            if pause_start_ms <= last_end_ms:
                pause_start_ms = last_end_ms + 1000

        pauses.append({"start": pause_start_ms})
        updated = dict(current_nap)
        updated["pauses"] = pauses
        await self.async_put_log(baby_id, updated)
        return updated

    async def async_resume_nap(
        self,
        baby_id: str,
        current_logs: list[dict[str, Any]] | None = None,
        resume_dt: datetime.datetime | None = None,
        minutes_ago: int | float = 0,
    ) -> dict[str, Any]:
        """Resume a paused open NAP log by setting 'end' on the last open pause."""
        dt = resolve_target_datetime(resume_dt, minutes_ago)
        if current_logs is None:
            today = await self.async_get_today(baby_id)
            current_logs = today.get("logs", today.get("allLogs", []))

        open_naps = [
            entry
            for entry in current_logs
            if entry.get("isOpen") and not entry.get("skipped") and entry.get("category") == "NAP"
        ]
        if not open_naps or not is_nap_log_paused(open_naps[0]):
            raise NapperApiError("Kein pausiertes Nickerchen zum Fortsetzen gefunden.")

        current_nap = open_naps[0]
        pauses = [dict(p) for p in (current_nap.get("pauses") or []) if isinstance(p, dict)]
        last_pause = pauses[-1]
        start_ms = int(last_pause.get("start") or int(dt.timestamp() * 1000))
        end_ms = int(dt.timestamp() * 1000)
        if end_ms <= start_ms:
            end_ms = start_ms + 1000
        last_pause["end"] = end_ms

        updated = dict(current_nap)
        updated["pauses"] = pauses
        await self.async_put_log(baby_id, updated)
        return updated

    async def async_pause_sleep(
        self,
        baby_id: str,
        current_logs: list[dict[str, Any]] | None = None,
        start_dt: datetime.datetime | None = None,
        minutes_ago: int | float = 0,
    ) -> dict[str, Any]:
        """Pause night sleep by starting an open NIGHT_WAKING log (nightly wake-up)."""
        dt = resolve_target_datetime(start_dt, minutes_ago)
        if current_logs is None:
            today = await self.async_get_today(baby_id)
            current_logs = today.get("logs", today.get("allLogs", []))

        open_wakings = [
            entry
            for entry in current_logs
            if entry.get("isOpen")
            and not entry.get("skipped")
            and entry.get("category") == "NIGHT_WAKING"
        ]
        if open_wakings:
            raise NapperApiError("Der Nachtschlaf ist bereits pausiert.")

        for entry in current_logs:
            if not entry.get("skipped") and entry.get("category") == "BED_TIME":
                raw_ts = entry.get("end") or entry.get("start")
                if raw_ts:
                    try:
                        bed_parsed = datetime.datetime.fromisoformat(
                            str(raw_ts).replace("Z", "+00:00")
                        )
                        if dt <= bed_parsed:
                            dt = bed_parsed + datetime.timedelta(seconds=1)
                    except Exception:
                        pass
                break

        iso = get_time_with_timezone(dt)
        log = build_empty_log(
            log_id=create_log_id("NIGHT_WAKING", iso),
            category="NIGHT_WAKING",
            start_iso=iso,
            end_iso=iso,
            start_minutes_after_midnight=get_start_minutes_after_midnight("NIGHT_WAKING", dt),
            user_id=self.user_id,
            is_open=True,
        )
        await self.async_put_log(baby_id, log)
        return log

    async def async_resume_sleep(
        self,
        baby_id: str,
        current_logs: list[dict[str, Any]] | None = None,
        end_dt: datetime.datetime | None = None,
        minutes_ago: int | float = 0,
    ) -> dict[str, Any]:
        """Resume night sleep by ending the currently open NIGHT_WAKING log."""
        dt = resolve_target_datetime(end_dt, minutes_ago)
        if current_logs is None:
            today = await self.async_get_today(baby_id)
            current_logs = today.get("logs", today.get("allLogs", []))

        open_wakings = [
            entry
            for entry in current_logs
            if entry.get("isOpen")
            and not entry.get("skipped")
            and entry.get("category") == "NIGHT_WAKING"
        ]
        if not open_wakings:
            raise NapperApiError("Kein pausierter Nachtschlaf zum Fortsetzen gefunden.")

        current_waking = open_wakings[0]
        try:
            start_parsed = datetime.datetime.fromisoformat(
                current_waking["start"].replace("Z", "+00:00")
            )
            if dt <= start_parsed:
                dt = start_parsed + datetime.timedelta(seconds=1)
        except Exception:
            pass

        end_iso = get_time_with_timezone(dt)
        updated = dict(current_waking)
        updated["end"] = end_iso
        updated["isOpen"] = False
        await self.async_put_log(baby_id, updated)
        return updated

    async def async_wake_up(
        self,
        baby_id: str,
        current_logs: list[dict[str, Any]] | None = None,
        wake_dt: datetime.datetime | None = None,
        minutes_ago: int | float = 0,
    ) -> dict[str, Any]:
        """Wake up from whatever sleep is currently running (ends open nap OR ends night sleep & logs WOKE_UP)."""
        dt = resolve_target_datetime(wake_dt, minutes_ago)
        if current_logs is None:
            today = await self.async_get_today(baby_id)
            current_logs = today.get("logs", today.get("allLogs", []))

        # 1. If an open NAP is running, end that nap
        open_naps = [
            entry
            for entry in current_logs
            if entry.get("isOpen") and not entry.get("skipped") and entry.get("category") == "NAP"
        ]
        if open_naps:
            current_nap = open_naps[0]
            try:
                start_parsed = datetime.datetime.fromisoformat(
                    current_nap["start"].replace("Z", "+00:00")
                )
                if dt < start_parsed:
                    dt = start_parsed + datetime.timedelta(minutes=1)
            except Exception:
                pass
            end_iso = get_time_with_timezone(dt)
            updated = dict(current_nap)
            # Remove any open pause when stopping a nap (matching Napper's removeLastOpenPause)
            pauses = [
                dict(p)
                for p in (current_nap.get("pauses") or [])
                if isinstance(p, dict) and p.get("end")
            ]
            updated["pauses"] = pauses
            updated["end"] = end_iso
            updated["isOpen"] = False
            await self.async_put_log(baby_id, updated)
            return updated

        # 2. Otherwise, end night sleep (close any open BED_TIME/NIGHT_WAKING) and create WOKE_UP log
        for entry in current_logs:
            if not entry.get("skipped") and entry.get("category") in ("BED_TIME", "NIGHT_WAKING"):
                raw_ts = entry.get("end") or entry.get("start")
                if raw_ts:
                    try:
                        parsed_ts = datetime.datetime.fromisoformat(
                            str(raw_ts).replace("Z", "+00:00")
                        )
                        if dt <= parsed_ts:
                            dt = parsed_ts + datetime.timedelta(seconds=1)
                    except Exception:
                        pass

        iso = get_time_with_timezone(dt)
        for entry in current_logs:
            if (
                entry.get("isOpen")
                and not entry.get("skipped")
                and entry.get("category") in ("BED_TIME", "NIGHT_WAKING")
            ):
                closed = dict(entry)
                closed["end"] = iso
                closed["isOpen"] = False
                await self.async_put_log(baby_id, closed)

        log = build_empty_log(
            log_id=create_log_id("WOKE_UP", iso),
            category="WOKE_UP",
            start_iso=iso,
            end_iso=iso,
            start_minutes_after_midnight=get_start_minutes_after_midnight("WOKE_UP", dt),
            user_id=self.user_id,
            is_open=False,
        )
        await self.async_put_log(baby_id, log)
        return log

    async def async_log_woke_up(
        self,
        baby_id: str,
        current_logs: list[dict[str, Any]] | None = None,
        wake_dt: datetime.datetime | None = None,
        minutes_ago: int | float = 0,
    ) -> dict[str, Any]:
        """Alias for async_wake_up."""
        return await self.async_wake_up(
            baby_id, current_logs=current_logs, wake_dt=wake_dt, minutes_ago=minutes_ago
        )
