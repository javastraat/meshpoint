"""Accumulates per-packet stats in memory for periodic cloud reporting.

The cloud heartbeat carries a stats summary instead of the cloud doing
per-packet DynamoDB writes. This class mirrors the counters that
cloud/shared/stats_updater.py builds, but computes them locally.

Call record_packet() on every decoded packet. Call build_report() to
get the current snapshot, then reset() after a successful heartbeat send.
"""

from __future__ import annotations

import math
import time
from typing import Optional


class StatsReporter:
    """In-memory accumulator for heartbeat stats reporting."""

    def __init__(self) -> None:
        self._start_time = time.monotonic()
        self._total_packets = 0

        self._protocols: dict[str, int] = {}
        self._packet_types: dict[str, int] = {}

        self._rssi_excellent = 0
        self._rssi_good = 0
        self._rssi_fair = 0
        self._rssi_weak = 0
        self._rssi_sum = 0.0
        self._rssi_count = 0
        self._best_rssi: Optional[float] = None
        self._snr_sum = 0.0
        self._snr_count = 0
        self._best_snr: Optional[float] = None

        self._direct_count = 0
        self._relayed_count = 0

        self._farthest_direct_miles: float = 0.0
        self._farthest_direct_node_id: str = ""
        self._farthest_direct_rssi: Optional[float] = None

        self._changed_nodes: dict[str, dict] = {}

    def record_packet(
        self,
        protocol: str,
        packet_type: str,
        rssi: Optional[float],
        snr: Optional[float],
        hop_start: int,
        hop_limit: int,
    ) -> None:
        """Record one decoded packet into the accumulator."""
        self._total_packets += 1

        self._protocols[protocol] = self._protocols.get(protocol, 0) + 1
        self._packet_types[packet_type] = (
            self._packet_types.get(packet_type, 0) + 1
        )

        if rssi is not None and rssi < 0:
            self._classify_rssi(rssi)
            self._rssi_sum += rssi
            self._rssi_count += 1
            if self._best_rssi is None or rssi > self._best_rssi:
                self._best_rssi = rssi

        if snr is not None:
            self._snr_sum += snr
            self._snr_count += 1
            if self._best_snr is None or snr > self._best_snr:
                self._best_snr = snr

        hops_consumed = (hop_start - hop_limit) if hop_start > 0 else 0
        if hops_consumed == 0:
            self._direct_count += 1
        else:
            self._relayed_count += 1

    def record_farthest_direct(
        self,
        source_id: str,
        rssi: Optional[float],
        device_lat: float,
        device_lon: float,
        node_lat: float,
        node_lon: float,
        hop_start: int,
        hop_limit: int,
    ) -> None:
        """Check if a direct packet beats the current farthest record."""
        hops_consumed = (hop_start - hop_limit) if hop_start > 0 else 0
        if hops_consumed != 0:
            return

        dist = _haversine_mi(device_lat, device_lon, node_lat, node_lon)
        if dist < 0.1:
            return

        if dist > self._farthest_direct_miles:
            self._farthest_direct_miles = round(dist, 1)
            self._farthest_direct_node_id = source_id
            if rssi is not None and rssi < 0:
                self._farthest_direct_rssi = int(rssi)

    def record_node(self, node_data: dict) -> None:
        """Track a node that changed since the last report."""
        node_id = node_data.get("node_id", "")
        if node_id:
            self._changed_nodes[node_id] = node_data

    @property
    def total_packets(self) -> int:
        return self._total_packets

    @property
    def packets_per_minute(self) -> float:
        elapsed = time.monotonic() - self._start_time
        if elapsed <= 0 or self._total_packets == 0:
            return 0.0
        return round(self._total_packets / (elapsed / 60.0), 1)

    def build_report(self) -> dict:
        """Produce the stats payload for the heartbeat message."""
        report: dict = {
            "total_packets": self._total_packets,
            "packets_per_minute": self.packets_per_minute,
            "protocols": dict(self._protocols),
            "packet_types": dict(self._packet_types),
            "rssi_histogram": {
                "excellent": self._rssi_excellent,
                "good": self._rssi_good,
                "fair": self._rssi_fair,
                "weak": self._rssi_weak,
            },
            "direct_count": self._direct_count,
            "relayed_count": self._relayed_count,
            "rssi_sum": round(self._rssi_sum, 1),
            "rssi_count": self._rssi_count,
            "best_rssi": round(self._best_rssi, 1) if self._best_rssi is not None else None,
            "snr_sum": round(self._snr_sum, 1),
            "snr_count": self._snr_count,
            "best_snr": round(self._best_snr, 1) if self._best_snr is not None else None,
        }

        if self._farthest_direct_miles > 0:
            report["farthest_direct"] = {
                "miles": self._farthest_direct_miles,
                "node_id": self._farthest_direct_node_id,
                "rssi": self._farthest_direct_rssi,
            }

        return report

    def build_node_roster(self) -> list[dict]:
        """Return the list of nodes that changed since last report."""
        return list(self._changed_nodes.values())

    def reset(self) -> None:
        """Clear all accumulators after a successful heartbeat send."""
        self._start_time = time.monotonic()
        self._total_packets = 0
        self._protocols.clear()
        self._packet_types.clear()
        self._rssi_excellent = 0
        self._rssi_good = 0
        self._rssi_fair = 0
        self._rssi_weak = 0
        self._rssi_sum = 0.0
        self._rssi_count = 0
        self._best_rssi = None
        self._snr_sum = 0.0
        self._snr_count = 0
        self._best_snr = None
        self._direct_count = 0
        self._relayed_count = 0
        self._farthest_direct_miles = 0.0
        self._farthest_direct_node_id = ""
        self._farthest_direct_rssi = None
        self._changed_nodes.clear()

    def _classify_rssi(self, rssi: float) -> None:
        if rssi > -80:
            self._rssi_excellent += 1
        elif rssi > -100:
            self._rssi_good += 1
        elif rssi > -115:
            self._rssi_fair += 1
        else:
            self._rssi_weak += 1


def _haversine_mi(
    lat1: float, lon1: float, lat2: float, lon2: float,
) -> float:
    """Great-circle distance in miles."""
    r = 3958.8
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
