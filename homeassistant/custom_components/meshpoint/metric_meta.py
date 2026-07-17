"""Friendly display metadata for known Meshpoint /metrics series.

Anything not listed here still becomes a sensor -- ``MetricMeta.fallback()``
derives a readable name from the raw key. This means a metric Meshpoint
adds to /metrics later shows up automatically, just without a curated
name/unit/icon until this table is updated for it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTime


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
        if label.startswith("meshpoint_"):
            label = label[len("meshpoint_"):]
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
}
