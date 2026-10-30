"""The Napper Baby Sleep Tracker integration."""

from __future__ import annotations

import logging
import pathlib

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, Platform
from homeassistant.core import CoreState, Event, HomeAssistant, ServiceCall
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import voluptuous as vol

from .api import NapperApiClient
from .const import (
    CARD_FILENAME,
    CARD_URL,
    CONF_DEVICE_ID,
    CONF_ID_TOKEN,
    CONF_REFRESH_TOKEN,
    CONF_USER_ID,
    DOMAIN,
    SERVICE_LOG_BEDTIME,
    SERVICE_LOG_WAKE_UP,
    SERVICE_PAUSE_NAP,
    SERVICE_PAUSE_SLEEP,
    SERVICE_RESUME_NAP,
    SERVICE_RESUME_SLEEP,
    SERVICE_START_NAP,
    SERVICE_START_SLEEP,
    SERVICE_STOP_SLEEP,
    SERVICE_WAKE_UP,
    STATIC_URL_PATH,
)
from .coordinator import NapperCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.TIME,
]

SERVICE_SCHEMA = vol.Schema(
    {
        vol.Optional("baby_id"): str,
        vol.Optional("minutes_ago", default=0): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=720)
        ),
        vol.Optional("time"): str,
    }
)


CARD_VERSION = "2.6.0"


async def _async_ensure_lovelace_resource(hass: HomeAssistant, target_url: str) -> bool:
    """Ensure the custom card URL is registered in Lovelace storage resources."""
    try:
        lovelace = hass.data.get("lovelace")
        resources = getattr(lovelace, "resources", None) or (
            lovelace.get("resources") if isinstance(lovelace, dict) else None
        )
        if resources is None or not hasattr(resources, "async_items"):
            return False

        if hasattr(resources, "loaded") and not resources.loaded:
            await resources.async_load()
            resources.loaded = True

        matching_items = [
            item
            for item in resources.async_items()
            if str(item.get("url", "")).split("?")[0] == CARD_URL
            or str(item.get("url", "")).startswith(CARD_URL)
        ]
        if not matching_items:
            if hasattr(resources, "async_create_item"):
                await resources.async_create_item(
                    {"res_type": "module", "url": target_url}
                )
        else:
            primary = matching_items[0]
            if primary.get("url") != target_url and hasattr(
                resources, "async_update_item"
            ):
                await resources.async_update_item(
                    primary["id"], {"res_type": "module", "url": target_url}
                )
            # Remove any duplicate stale entries for the same card
            if len(matching_items) > 1 and hasattr(resources, "async_delete_item"):
                for dup in matching_items[1:]:
                    if dup.get("id"):
                        await resources.async_delete_item(dup["id"])
        return True
    except Exception as err:
        _LOGGER.debug("Lovelace resource registration deferred/failed: %s", err)
        return False


async def _async_register_lovelace_card(hass: HomeAssistant) -> None:
    """Serve and auto-register the custom Napper Lovelace card."""
    if hass.data[DOMAIN].get("_card_registered"):
        return

    card_path = pathlib.Path(__file__).parent / "frontend" / CARD_FILENAME
    if not card_path.exists():
        return

    target_url = f"{CARD_URL}?v={CARD_VERSION}"
    try:
        # Enable cache_headers=True with versioned query string (?v=...) so the
        # Home Assistant Mobile App WebView caches the JS module locally and defines
        # <napper-card> immediately on cold start without hitting Lovelace's 2s timeout.
        if hasattr(hass.http, "async_register_static_paths"):
            await hass.http.async_register_static_paths(
                [StaticPathConfig(CARD_URL, str(card_path), cache_headers=True)]
            )
        else:
            hass.http.register_static_path(CARD_URL, str(card_path), cache_headers=True)

        add_extra_js_url(hass, target_url)

        registered_in_lovelace = await _async_ensure_lovelace_resource(hass, target_url)
        if not registered_in_lovelace and hass.state is not CoreState.running:
            async def _on_ha_started(_event: Event) -> None:
                await _async_ensure_lovelace_resource(hass, target_url)

            hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _on_ha_started)

        hass.data[DOMAIN]["_card_registered"] = True
        _LOGGER.info("Registered Napper Card at %s", target_url)
    except Exception as err:
        _LOGGER.warning("Could not auto-register Napper Lovelace card: %s", err)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Napper from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    await _async_register_lovelace_card(hass)

    def _update_tokens(new_id_token: str, new_refresh_token: str) -> None:
        new_data = dict(entry.data)
        new_data[CONF_ID_TOKEN] = new_id_token
        new_data[CONF_REFRESH_TOKEN] = new_refresh_token
        hass.config_entries.async_update_entry(entry, data=new_data)

    session = async_get_clientsession(hass)
    client = NapperApiClient(
        session=session,
        id_token=entry.data[CONF_ID_TOKEN],
        refresh_token=entry.data[CONF_REFRESH_TOKEN],
        device_id=entry.data.get(CONF_DEVICE_ID),
        user_id=entry.data.get(CONF_USER_ID),
        token_update_callback=_update_tokens,
    )

    coordinator = NapperCoordinator(hass, client)
    await coordinator.async_config_entry_first_refresh()
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    def _resolve_coordinator_and_baby(call: ServiceCall) -> tuple[NapperCoordinator, str]:
        requested: str | None = call.data.get("baby_id")
        coordinators = [
            c for k, c in hass.data[DOMAIN].items() if isinstance(c, NapperCoordinator)
        ]
        for coord in coordinators:
            if requested:
                if requested in coord.babies:
                    return coord, requested
                # Also allow matching by baby name (case-insensitive)
                for bid, binfo in coord.babies.items():
                    if str(binfo.get("name", "")).lower() == requested.strip().lower():
                        return coord, bid
            elif coord.babies:
                first_baby_id = next(iter(coord.babies.keys()))
                return coord, first_baby_id
        raise ValueError(f"Kein passendes Kind (baby_id={requested}) in Napper gefunden.")

    async def _handle_wake_up(call: ServiceCall) -> None:
        coord, baby_id = _resolve_coordinator_and_baby(call)
        target_dt, minutes_ago = coord.pop_action_timing(
            baby_id,
            explicit_time=call.data.get("time"),
            explicit_minutes_ago=int(call.data.get("minutes_ago", 0)),
        )
        await coord.async_wake_up(
            baby_id, minutes_ago=minutes_ago, target_dt=target_dt
        )

    async def _handle_start_nap(call: ServiceCall) -> None:
        coord, baby_id = _resolve_coordinator_and_baby(call)
        target_dt, minutes_ago = coord.pop_action_timing(
            baby_id,
            explicit_time=call.data.get("time"),
            explicit_minutes_ago=int(call.data.get("minutes_ago", 0)),
        )
        await coord.async_start_nap(
            baby_id, minutes_ago=minutes_ago, target_dt=target_dt
        )

    async def _handle_start_sleep(call: ServiceCall) -> None:
        coord, baby_id = _resolve_coordinator_and_baby(call)
        target_dt, minutes_ago = coord.pop_action_timing(
            baby_id,
            explicit_time=call.data.get("time"),
            explicit_minutes_ago=int(call.data.get("minutes_ago", 0)),
        )
        await coord.async_start_sleep(
            baby_id, minutes_ago=minutes_ago, target_dt=target_dt
        )

    async def _handle_pause_nap(call: ServiceCall) -> None:
        coord, baby_id = _resolve_coordinator_and_baby(call)
        target_dt, minutes_ago = coord.pop_action_timing(
            baby_id,
            explicit_time=call.data.get("time"),
            explicit_minutes_ago=int(call.data.get("minutes_ago", 0)),
        )
        await coord.async_pause_nap(
            baby_id, minutes_ago=minutes_ago, target_dt=target_dt
        )

    async def _handle_resume_nap(call: ServiceCall) -> None:
        coord, baby_id = _resolve_coordinator_and_baby(call)
        target_dt, minutes_ago = coord.pop_action_timing(
            baby_id,
            explicit_time=call.data.get("time"),
            explicit_minutes_ago=int(call.data.get("minutes_ago", 0)),
        )
        await coord.async_resume_nap(
            baby_id, minutes_ago=minutes_ago, target_dt=target_dt
        )

    async def _handle_pause_sleep(call: ServiceCall) -> None:
        coord, baby_id = _resolve_coordinator_and_baby(call)
        target_dt, minutes_ago = coord.pop_action_timing(
            baby_id,
            explicit_time=call.data.get("time"),
            explicit_minutes_ago=int(call.data.get("minutes_ago", 0)),
        )
        await coord.async_pause_sleep(
            baby_id, minutes_ago=minutes_ago, target_dt=target_dt
        )

    async def _handle_resume_sleep(call: ServiceCall) -> None:
        coord, baby_id = _resolve_coordinator_and_baby(call)
        target_dt, minutes_ago = coord.pop_action_timing(
            baby_id,
            explicit_time=call.data.get("time"),
            explicit_minutes_ago=int(call.data.get("minutes_ago", 0)),
        )
        await coord.async_resume_sleep(
            baby_id, minutes_ago=minutes_ago, target_dt=target_dt
        )

    if not hass.services.has_service(DOMAIN, SERVICE_START_NAP):
        hass.services.async_register(
            DOMAIN, SERVICE_WAKE_UP, _handle_wake_up, schema=SERVICE_SCHEMA
        )
        hass.services.async_register(
            DOMAIN, SERVICE_START_NAP, _handle_start_nap, schema=SERVICE_SCHEMA
        )
        hass.services.async_register(
            DOMAIN, SERVICE_PAUSE_NAP, _handle_pause_nap, schema=SERVICE_SCHEMA
        )
        hass.services.async_register(
            DOMAIN, SERVICE_RESUME_NAP, _handle_resume_nap, schema=SERVICE_SCHEMA
        )
        hass.services.async_register(
            DOMAIN, SERVICE_START_SLEEP, _handle_start_sleep, schema=SERVICE_SCHEMA
        )
        hass.services.async_register(
            DOMAIN, SERVICE_PAUSE_SLEEP, _handle_pause_sleep, schema=SERVICE_SCHEMA
        )
        hass.services.async_register(
            DOMAIN, SERVICE_RESUME_SLEEP, _handle_resume_sleep, schema=SERVICE_SCHEMA
        )
        # Keep legacy service names mapped to the unified handlers
        hass.services.async_register(
            DOMAIN, SERVICE_STOP_SLEEP, _handle_wake_up, schema=SERVICE_SCHEMA
        )
        hass.services.async_register(
            DOMAIN, SERVICE_LOG_WAKE_UP, _handle_wake_up, schema=SERVICE_SCHEMA
        )
        hass.services.async_register(
            DOMAIN, SERVICE_LOG_BEDTIME, _handle_start_sleep, schema=SERVICE_SCHEMA
        )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
