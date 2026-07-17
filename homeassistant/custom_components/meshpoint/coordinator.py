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
from .json_flatten import flatten_json
from .prometheus import parse_prometheus_text

_LOGGER = logging.getLogger(__name__)

_TIMEOUT = aiohttp.ClientTimeout(total=10)

# (path, key prefix) -- these two are a bonus on top of /metrics: the same
# API key was extended server-side to also cover them (see
# docs/CONFIGURATION.md), but an older Meshpoint or a key minted before
# that change won't have access. Best-effort: skipped silently on any
# non-200, never fails the whole update -- /metrics alone is still a
# fully working integration.
_BONUS_ENDPOINTS = (
    ("/api/device/metrics", "device"),
    ("/api/stats/summary", "stats"),
)


class MeshpointDataUpdateCoordinator(DataUpdateCoordinator[dict]):
    """Polls Meshpoint's /metrics, /api/device/metrics, and
    /api/stats/summary endpoints and merges them into one flat dict.

    ``data`` is the flat ``{metric_key: value}`` dict -- sensor.py watches
    it for keys it hasn't turned into an entity yet, so a metric Meshpoint
    adds later shows up automatically without this integration being
    updated. Keys from the two JSON endpoints are prefixed ``device_``/
    ``stats_`` (via ``flatten_json``) so they can never collide with the
    already-unique ``meshpoint_*`` names from /metrics.
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

    def _bonus_url(self, path: str) -> str:
        return f"http://{self._host}:{self._port}{path}"

    async def _async_update_data(self) -> dict:
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

        for path, prefix in _BONUS_ENDPOINTS:
            try:
                async with session.get(
                    self._bonus_url(path), headers=headers, timeout=_TIMEOUT
                ) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json(content_type=None)
            except (aiohttp.ClientError, ValueError):
                # Network hiccup or non-JSON body -- skip this endpoint for
                # this cycle, don't fail sensors that don't need it.
                continue

            for key, value in flatten_json(data).items():
                metrics[f"{prefix}_{key}"] = value

        return metrics
