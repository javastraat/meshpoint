"""Config flow for the Meshpoint integration.

Single step: host, port, and an optional API key (generated from
Meshpoint's Configuration -> Metrics -> API keys panel). Validates by
actually polling /metrics before letting the entry be created, so a
typo'd host or a wrong key is caught at setup time, not as a silently
unavailable device afterward.
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CONF_API_KEY, DEFAULT_PORT, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Optional(CONF_API_KEY, default=""): str,
    }
)


class CannotConnect(Exception):
    """Could not reach the Meshpoint host at all."""


class InvalidAuth(Exception):
    """Meshpoint rejected the given API key."""


class MetricsDisabled(Exception):
    """Meshpoint reached, but /metrics is disabled on that box."""


async def _validate_input(hass, data: dict[str, Any]) -> None:
    session = async_get_clientsession(hass)
    url = f"http://{data[CONF_HOST]}:{data[CONF_PORT]}/metrics"
    api_key = data.get(CONF_API_KEY) or ""
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    try:
        async with session.get(
            url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)
        ) as resp:
            if resp.status == 401:
                raise InvalidAuth
            if resp.status == 404:
                raise MetricsDisabled
            resp.raise_for_status()
    except aiohttp.ClientError as err:
        raise CannotConnect from err


class MeshpointConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Meshpoint."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                await _validate_input(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except MetricsDisabled:
                errors["base"] = "metrics_disabled"
            except Exception:  # noqa: BLE001 - surfaced to the user as "unknown"
                _LOGGER.exception("Unexpected error validating Meshpoint connection")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(
                    f"{user_input[CONF_HOST]}:{user_input[CONF_PORT]}"
                )
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Meshpoint ({user_input[CONF_HOST]})",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )
