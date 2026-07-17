"""Sensor platform for Meshpoint.

Entities are created dynamically from whatever keys the coordinator's
parsed /metrics data contains -- there's no fixed sensor list. On every
coordinator update, any key not yet turned into an entity gets one, so
a metric Meshpoint adds later just shows up (with a generic name until
metric_meta.py is updated for it) instead of requiring this integration
to be updated first.
"""

from __future__ import annotations

import logging

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import MeshpointDataUpdateCoordinator
from .metric_meta import METRIC_META, MetricMeta

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: MeshpointDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    known_keys: set[str] = set()

    def _add_new_entities() -> None:
        current_keys = set(coordinator.data or {})
        new_keys = current_keys - known_keys
        if not new_keys:
            return
        known_keys.update(new_keys)
        async_add_entities(
            MeshpointSensor(coordinator, entry, key) for key in sorted(new_keys)
        )

    _add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_entities))


class MeshpointSensor(CoordinatorEntity[MeshpointDataUpdateCoordinator], SensorEntity):
    """A single /metrics series, dynamically discovered."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: MeshpointDataUpdateCoordinator,
        entry: ConfigEntry,
        metric_key: str,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._metric_key = metric_key

        meta = METRIC_META.get(metric_key) or MetricMeta.fallback(metric_key)
        self._attr_unique_id = f"{entry.entry_id}_{metric_key}"
        self._attr_name = meta.name
        self._attr_native_unit_of_measurement = meta.unit
        self._attr_device_class = meta.device_class
        self._attr_state_class = meta.state_class
        self._attr_icon = meta.icon
        self._attr_entity_category = meta.entity_category

    @property
    def native_value(self) -> float | int | None:
        value = (self.coordinator.data or {}).get(self._metric_key)
        if value is None:
            return None
        # Prometheus values are always floats on the wire; render whole
        # numbers (packet counts, node counts) without a trailing ".0".
        return int(value) if value == int(value) else value

    @property
    def available(self) -> bool:
        return super().available and self._metric_key in (self.coordinator.data or {})

    @property
    def device_info(self) -> DeviceInfo:
        info = self.coordinator.info or {}
        host = self._entry.data.get(CONF_HOST)
        port = self._entry.data.get(CONF_PORT)
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=f"Meshpoint ({host})",
            manufacturer="Meshpoint",
            model=info.get("region") or "Meshpoint gateway",
            sw_version=info.get("version"),
            configuration_url=f"http://{host}:{port}",
        )
