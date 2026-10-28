"""The Napper Baby Sleep Tracker integration."""

from __future__ import annotations

import logging
import pathlib

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
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


async def _async_register_lovelace_card(hass: HomeAssistant) -> None:
    """Serve and auto-register the custom Napper Circle Lovelace card."""
    if hass.data[DOMAIN].get("_card_registered"):
        return

    card_path = pathlib.Path(__file__).parent / "frontend" / CARD_FILENAME
    if not card_path.exists():
        return

    try:
        if hasattr(hass.http, "async_register_static_paths"):
            await hass.http.async_register_static_paths(
                [StaticPathConfig(CARD_URL, str(card_path), cache_headers=False)]
            )
        else:
            hass.http.register_static_path(CARD_URL, str(card_path), cache_headers=False)
        add_extra_js_url(hass, CARD_URL)

        # Also auto-register in Lovelace storage resources if available
        lovelace = hass.data.get("lovelace")
        resources = getattr(lovelace, "resources", None) or (
            lovelace.get("resources") if isinstance(lovelace, dict) else None
        )
        if resources is not None and hasattr(resources, "async_items"):
            if hasattr(resources, "loaded") and not resources.loaded:
                await resources.async_load()
                resources.loaded = True
            already_added = any(
                str(item.get("url", "")).startswith(CARD_URL)
                for item in resources.async_items()
            )
            if not already_added and hasattr(resources, "async_create_item"):
                await resources.async_create_item(
                    {"res_type": "module", "url": f"{CARD_URL}?v=1.2.0"}
                )

        hass.data[DOMAIN]["_card_registered"] = True
        _LOGGER.info("Registered Napper Circle Card at %s", CARD_URL)
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

    if not hass.services.has_service(DOMAIN, SERVICE_START_NAP):
        hass.services.async_register(
            DOMAIN, SERVICE_WAKE_UP, _handle_wake_up, schema=SERVICE_SCHEMA
        )
        hass.services.async_register(
            DOMAIN, SERVICE_START_NAP, _handle_start_nap, schema=SERVICE_SCHEMA
        )
        hass.services.async_register(
            DOMAIN, SERVICE_START_SLEEP, _handle_start_sleep, schema=SERVICE_SCHEMA
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
