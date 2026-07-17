"""Data update coordinator for the Meshpoint integration."""

from __future__ import annotations

import logging
from datetime import timedelta

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN
from .prometheus import parse_prometheus_text

_LOGGER = logging.getLogger(__name__)

_TIMEOUT = aiohttp.ClientTimeout(total=10)


class MeshpointDataUpdateCoordinator(DataUpdateCoordinator[dict[str, float]]):
    """Polls Meshpoint's /metrics endpoint and parses it into a flat dict.

    ``data`` is the flat ``{metric_key: value}`` dict from
    ``parse_prometheus_text`` -- sensor.py watches it for keys it hasn't
    turned into an entity yet, so a metric Meshpoint adds later shows up
    automatically without this integration being updated.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        host: str,
        port: int,
        api_key: str,
        scan_interval: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )
        self._host = host
        self._port = port
        self._api_key = api_key
        self.info: dict[str, str] = {}

    @property
    def url(self) -> str:
        return f"http://{self._host}:{self._port}/metrics"

    async def _async_update_data(self) -> dict[str, float]:
        session = async_get_clientsession(self.hass)
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}

        try:
            async with session.get(self.url, headers=headers, timeout=_TIMEOUT) as resp:
                if resp.status == 401:
                    raise ConfigEntryAuthFailed(
                        "Meshpoint rejected the configured API key"
                    )
                if resp.status == 404:
                    raise UpdateFailed(
                        "Meshpoint's /metrics endpoint is disabled -- enable it "
                        "under Configuration -> Metrics on the Meshpoint dashboard"
                    )
                resp.raise_for_status()
                text = await resp.text()
        except aiohttp.ClientError as err:
            raise UpdateFailed(f"Error communicating with Meshpoint: {err}") from err

        metrics, info = parse_prometheus_text(text)
        if info:
            self.info = info
        return metrics
