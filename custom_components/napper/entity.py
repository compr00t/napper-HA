"""Base entity helpers for Napper with API-timestamped state transitions."""

from __future__ import annotations

import datetime
from typing import Any

from homeassistant.helpers.entity import Entity


class _StateMachineTimestampProxy:
    """Proxy around hass.states to stamp state transitions with Napper API timestamps."""

    def __init__(self, real_states: Any, target_utc: datetime.datetime) -> None:
        self._real_states = real_states
        self._target_utc = target_utc
        self._target_ts = target_utc.timestamp()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real_states, name)

    def _should_apply_timestamp(self, entity_id: str, new_state: str) -> tuple[bool, bool]:
        """Return (apply_timestamp, force_update) for this state write."""
        old_state = self._real_states.get(entity_id)
        if old_state is None or old_state.state in ("unknown", "unavailable"):
            return True, False
        if old_state.state != new_state:
            return True, False
        if abs((old_state.last_changed - self._target_utc).total_seconds()) > 5:
            return True, True
        return False, False

    def async_set_internal(self, *args: Any, **kwargs: Any) -> Any:
        if len(args) >= 2 and isinstance(args[0], str) and isinstance(args[1], str):
            apply_ts, force_upd = self._should_apply_timestamp(args[0], args[1])
            if apply_ts:
                mutable_args = list(args)
                replaced = False
                for idx in range(len(mutable_args) - 1, 1, -1):
                    val = mutable_args[idx]
                    if (
                        isinstance(val, (int, float))
                        and not isinstance(val, bool)
                        and val > 1_000_000_000
                    ):
                        mutable_args[idx] = self._target_ts
                        replaced = True
                        break
                    if isinstance(val, datetime.datetime):
                        mutable_args[idx] = self._target_utc
                        replaced = True
                        break

                if not replaced and "timestamp" in kwargs:
                    orig_ts = kwargs["timestamp"]
                    if isinstance(orig_ts, (int, float)) and not isinstance(orig_ts, bool):
                        kwargs["timestamp"] = self._target_ts
                    else:
                        kwargs["timestamp"] = self._target_utc

                if force_upd:
                    if len(mutable_args) >= 4 and isinstance(mutable_args[3], bool):
                        mutable_args[3] = True
                    elif "force_update" in kwargs:
                        kwargs["force_update"] = True

                return self._real_states.async_set_internal(*mutable_args, **kwargs)

        return self._real_states.async_set_internal(*args, **kwargs)


class _HassStatesProxy:
    """Lightweight proxy around HomeAssistant exposing _StateMachineTimestampProxy as .states."""

    def __init__(self, real_hass: Any, target_utc: datetime.datetime) -> None:
        self._real_hass = real_hass
        self.states = _StateMachineTimestampProxy(real_hass.states, target_utc)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real_hass, name)


class NapperTimestampedEntity(Entity):
    """Mixin that stamps entity state changes using the actual Napper API event time."""

    def _state_changed_dt(self) -> datetime.datetime | None:
        """Return the timezone-aware datetime when the current state began in Napper (or None)."""
        return None

    def _async_write_ha_state(self) -> None:
        """Write state to HA, stamping last_changed from Napper API data when applicable."""
        real_hass = self.hass
        if real_hass is None or not self.entity_id:
            super()._async_write_ha_state()
            return

        event_dt = self._state_changed_dt()
        if event_dt is None:
            super()._async_write_ha_state()
            return

        if event_dt.tzinfo is None:
            event_dt = event_dt.astimezone()
        target_utc = event_dt.astimezone(datetime.timezone.utc)
        now_utc = datetime.datetime.now(datetime.timezone.utc)

        # Ignore future timestamps or stale timestamps older than 7 days
        if target_utc > now_utc or (now_utc - target_utc) > datetime.timedelta(days=7):
            super()._async_write_ha_state()
            return

        try:
            self.hass = _HassStatesProxy(real_hass, target_utc)  # type: ignore[assignment]
            super()._async_write_ha_state()
        except Exception:
            self.hass = real_hass
            super()._async_write_ha_state()
        finally:
            self.hass = real_hass
