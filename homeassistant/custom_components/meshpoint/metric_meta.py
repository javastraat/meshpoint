"""Friendly display metadata for known Meshpoint metric/stat series.

Covers keys from all three sources the coordinator polls: ``/metrics``
(bare ``meshpoint_*`` names), and the two JSON endpoints flattened with a
``device_``/``stats_`` prefix (system health, and richer stats-page data
like farthest contact and all-time best signal).

Anything not listed here still becomes a sensor -- ``MetricMeta.fallback()``
derives a readable name from the raw key. This means a metric Meshpoint
adds later shows up automatically, just without a curated name/unit/icon
until this table is updated for it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTemperature, UnitOfTime

_KNOWN_PREFIXES = ("meshpoint_", "device_", "stats_")


@dataclass(frozen=True)
class MetricMeta:
    name: str
    unit: Optional[str] = None
    device_class: Optional[str] = None
    state_class: Optional[str] = None
    icon: Optional[str] = None
    entity_category: Optional[str] = None

    @classmethod
    def fallback(cls, key: str) -> "MetricMeta":
        label = key
        for prefix in _KNOWN_PREFIXES:
            if label.startswith(prefix):
                label = label[len(prefix):]
                break
        label = label.replace("_", " ").strip().title()
        return cls(name=label or key)


METRIC_META: dict[str, MetricMeta] = {
    "meshpoint_uptime_seconds": MetricMeta(
        "Uptime",
        unit=UnitOfTime.SECONDS,
        device_class=SensorDeviceClass.DURATION,
        icon="mdi:timer-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "meshpoint_packets_session_total": MetricMeta(
        "Session Packets",
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:radio-tower",
    ),
    "meshpoint_packets_per_minute": MetricMeta(
        "Packet Rate",
        unit="packets/min",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:speedometer",
    ),
    "meshpoint_packets_database_total": MetricMeta(
        "Packets Stored",
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:database",
    ),
    "meshpoint_packets_last_hour": MetricMeta(
        "Packets (Last Hour)", state_class=SensorStateClass.MEASUREMENT,
    ),
    "meshpoint_packets_last_minute": MetricMeta(
        "Packets (Last Minute)", state_class=SensorStateClass.MEASUREMENT,
    ),
    "meshpoint_packets_direct_session_total": MetricMeta(
        "Direct Packets (Session)", state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    "meshpoint_packets_relayed_session_total": MetricMeta(
        "Relayed Packets (Session)", state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    "meshpoint_protocol_packets_session_total_meshtastic": MetricMeta(
        "Meshtastic Packets (Session)", state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    "meshpoint_protocol_packets_session_total_meshcore": MetricMeta(
        "MeshCore Packets (Session)", state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    "meshpoint_protocol_packets_session_total_lorawan": MetricMeta(
        "LoRaWAN Packets (Session)", state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    "meshpoint_rssi_average_dbm": MetricMeta(
        "RSSI (Session Average)",
        unit="dBm",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "meshpoint_snr_average_db": MetricMeta(
        "SNR (Session Average)", unit="dB", state_class=SensorStateClass.MEASUREMENT,
    ),
    "meshpoint_rssi_recent_average_dbm": MetricMeta(
        "RSSI (Recent Average)",
        unit="dBm",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "meshpoint_snr_recent_average_db": MetricMeta(
        "SNR (Recent Average)", unit="dB", state_class=SensorStateClass.MEASUREMENT,
    ),
    "meshpoint_nodes_total": MetricMeta(
        "Nodes Known", icon="mdi:radio-tower", state_class=SensorStateClass.MEASUREMENT,
    ),
    "meshpoint_nodes_active_24h": MetricMeta(
        "Nodes Active (24h)", icon="mdi:radio-tower", state_class=SensorStateClass.MEASUREMENT,
    ),
    "meshpoint_noise_floor_dbm_spectral_scan": MetricMeta(
        "Noise Floor", unit="dBm", state_class=SensorStateClass.MEASUREMENT,
    ),
    "meshpoint_noise_floor_stale": MetricMeta(
        "Noise Floor Stale",
        icon="mdi:alert-circle-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "meshpoint_relay_enabled": MetricMeta(
        "Relay Enabled",
        icon="mdi:swap-horizontal",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "meshpoint_relay_relayed_total": MetricMeta(
        "Packets Relayed",
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:swap-horizontal",
    ),
    "meshpoint_relay_rejected_total": MetricMeta(
        "Packets Rejected By Relay", state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    "meshpoint_relay_rate_per_minute": MetricMeta(
        "Relay Rate", unit="packets/min", state_class=SensorStateClass.MEASUREMENT,
    ),
    "meshpoint_relay_rate_remaining": MetricMeta(
        "Relay Rate Remaining", state_class=SensorStateClass.MEASUREMENT,
    ),
    "meshpoint_relay_duty_usage_percent": MetricMeta(
        "Relay Duty Usage", unit=PERCENTAGE, state_class=SensorStateClass.MEASUREMENT,
    ),
    "meshpoint_rx_crc_bad_total": MetricMeta(
        "CRC Bad Frames",
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:alert-circle-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "meshpoint_rx_no_crc_total": MetricMeta(
        "No-CRC Frames",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),

    # --- /api/device/metrics (host health -- CPU/RAM/disk/temp/fan) ---
    "device_cpu_percent": MetricMeta(
        "CPU Usage",
        unit=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:cpu-64-bit",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "device_memory_percent": MetricMeta(
        "Memory Usage",
        unit=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:memory",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "device_memory_used_mb": MetricMeta(
        "Memory Used",
        unit="MB",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "device_disk_percent": MetricMeta(
        "Disk Usage",
        unit=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:harddisk",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "device_disk_used_gb": MetricMeta(
        "Disk Used",
        unit="GB",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "device_cpu_temp_c": MetricMeta(
        "CPU Temperature",
        unit=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "device_system_uptime_seconds": MetricMeta(
        "System Uptime",
        unit=UnitOfTime.SECONDS,
        device_class=SensorDeviceClass.DURATION,
        icon="mdi:clock-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "device_fan_duty_percent": MetricMeta(
        "Fan Duty",
        unit=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:fan",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),

    # --- /api/stats/summary (richer stats-page data) ---
    "stats_first_packet_time": MetricMeta(
        "First Packet Ever Heard", icon="mdi:clock-start",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "stats_signal_best_rssi": MetricMeta(
        "Best RSSI Ever", unit="dBm", device_class=SensorDeviceClass.SIGNAL_STRENGTH,
    ),
    "stats_signal_best_snr": MetricMeta("Best SNR Ever", unit="dB"),
    "stats_farthest_mesh_miles": MetricMeta(
        "Farthest Relayed Contact", unit="mi", icon="mdi:map-marker-distance",
    ),
    "stats_farthest_mesh_node_name": MetricMeta(
        "Farthest Relayed Contact Name", icon="mdi:map-marker-distance",
    ),
    "stats_farthest_meshcore_miles": MetricMeta(
        "Farthest MeshCore Contact", unit="mi", icon="mdi:map-marker-distance",
    ),
    "stats_farthest_meshcore_node_name": MetricMeta(
        "Farthest MeshCore Contact Name", icon="mdi:map-marker-distance",
    ),
}
