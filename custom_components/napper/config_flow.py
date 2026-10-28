"""Config flow for Napper Baby Sleep Tracker integration."""

from __future__ import annotations

from typing import Any
import uuid

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import NapperApiClient, NapperApiError
from .const import (
    CONF_DEVICE_ID,
    CONF_EMAIL,
    CONF_ID_TOKEN,
    CONF_OTP,
    CONF_REFRESH_TOKEN,
    CONF_USER_ID,
    DOMAIN,
)


class NapperConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Napper."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._email: str = ""
        self._device_id: str = str(uuid.uuid4())
        self._client: NapperApiClient | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 1: Ask for the user's Napper email and send a 6-digit OTP."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._email = user_input[CONF_EMAIL].strip()
            session = async_get_clientsession(self.hass)
            self._client = NapperApiClient(session=session, device_id=self._device_id)
            try:
                await self._client.async_send_email_otp(self._email)
                return await self.async_step_otp()
            except NapperApiError:
                errors["base"] = "cannot_connect"
            except Exception:
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_EMAIL): str}),
            errors=errors,
        )

    async def async_step_otp(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 2: Verify the 6-digit OTP and create the config entry."""
        errors: dict[str, str] = {}
        if user_input is not None and self._client is not None:
            otp = user_input[CONF_OTP].strip()
            try:
                tokens = await self._client.async_login_with_email(self._email, otp)
                user = await self._client.async_get_user()
                user_id = user.get("id", self._email)
                await self.async_set_unique_id(str(user_id))
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Napper ({self._email})",
                    data={
                        CONF_EMAIL: self._email,
                        CONF_ID_TOKEN: tokens["idToken"],
                        CONF_REFRESH_TOKEN: tokens["refreshToken"],
                        CONF_DEVICE_ID: self._device_id,
                        CONF_USER_ID: user_id,
                    },
                )
            except NapperApiError:
                errors["base"] = "invalid_auth"
            except Exception:
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="otp",
            data_schema=vol.Schema({vol.Required(CONF_OTP): str}),
            errors=errors,
            description_placeholders={"email": self._email},
        )
