from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from datetime import timedelta

from src.models.node import Node
from src.storage.database import DatabaseManager

logger = logging.getLogger(__name__)

# Rows created from corrupted RX (no decoded NodeInfo). Matches COMMON-ERRORS
# manual cleanup minus the 7-day guard (dashboard wipe is explicit user intent).
PHANTOM_ROW_PREDICATE = """
    packet_count = 0
    AND (long_name IS NULL OR TRIM(long_name) = '')
    AND (short_name IS NULL OR TRIM(short_name) = '')
"""


class NodeRepository:
    """CRUD operations for mesh nodes."""

    def __init__(self, db: DatabaseManager):
        self._db = db

    async def upsert(self, node: Node) -> None:
        await self._db.execute(
            """
            INSERT INTO nodes (
                node_id, long_name, short_name, hardware_model,
                firmware_version, protocol, role, public_key, latitude, longitude,
                altitude, last_heard, first_seen, packet_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(node_id) DO UPDATE SET
                long_name = CASE
                    WHEN excluded.long_name IS NULL OR excluded.long_name = ''
                        THEN nodes.long_name
                    WHEN excluded.protocol = 'meshtastic'
                        THEN excluded.long_name
                    WHEN nodes.long_name IS NULL OR nodes.long_name = ''
                        THEN excluded.long_name
                    WHEN nodes.protocol = 'meshcore'
                         AND LOWER(nodes.long_name) = LOWER(nodes.node_id)
                        THEN excluded.long_name
                    ELSE nodes.long_name
                END,
                short_name = COALESCE(excluded.short_name, nodes.short_name),
                hardware_model = COALESCE(excluded.hardware_model, nodes.hardware_model),
                firmware_version = COALESCE(excluded.firmware_version, nodes.firmware_version),
                role = COALESCE(excluded.role, nodes.role),
                public_key = COALESCE(excluded.public_key, nodes.public_key),
                latitude = COALESCE(excluded.latitude, nodes.latitude),
                longitude = COALESCE(excluded.longitude, nodes.longitude),
                altitude = COALESCE(excluded.altitude, nodes.altitude),
                last_heard = excluded.last_heard,
                packet_count = nodes.packet_count + 1
            """,
            (
                node.node_id, node.long_name, node.short_name,
                node.hardware_model, node.firmware_version, node.protocol,
                node.role, node.public_key, node.latitude, node.longitude, node.altitude,
                node.last_heard.isoformat(), node.first_seen.isoformat(),
                node.packet_count,
            ),
        )
        await self._db.commit()

    async def upsert_from_neighbour_report(
        self, node_id: str, last_heard: datetime
    ) -> None:
        """Create/refresh a placeholder node from a repeater's live
        neighbour report (RepeaterPoller). Mirrors import_contacts.py's
        neighbour-import upsert (same MAX()-guarded last_heard so a
        secondhand report can never un-freshen a node we've genuinely
        heard more recently), but more conservative: the live poll only
        ever gives a bare pubkey + SNR, no name/role/position like the
        neighbours.json import has, so this never overwrites an
        already-known role/name/position -- only fills them in if
        unset. Never touches packet_count (this isn't a packet
        Meshpoint's own radio received).
        """
        last_heard_iso = last_heard.isoformat()
        await self._db.execute(
            """
            INSERT INTO nodes (
                node_id, long_name, protocol, last_heard, first_seen,
                packet_count
            ) VALUES (?, ?, 'meshcore', ?, ?, 0)
            ON CONFLICT(node_id) DO UPDATE SET
                long_name = CASE
                    WHEN nodes.long_name IS NULL OR nodes.long_name = ''
                        THEN excluded.long_name
                    WHEN LOWER(nodes.long_name) = LOWER(nodes.node_id)
                        THEN excluded.long_name
                    ELSE nodes.long_name
                END,
                last_heard = MAX(
                    excluded.last_heard,
                    COALESCE(
                        (SELECT MAX(p.timestamp) FROM packets p
                          WHERE p.source_id = nodes.node_id
                            AND p.packet_id NOT LIKE 'nb:%'
                            AND p.packet_id NOT LIKE 'meshcoredb:%'),
                        excluded.last_heard
                    )
                )
            """,
            (node_id, node_id, last_heard_iso, last_heard_iso),
        )
        await self._db.commit()

    async def get_by_id(self, node_id: str) -> Optional[Node]:
        row = await self._db.fetch_one(
            "SELECT * FROM nodes WHERE node_id = ?", (node_id,)
        )
        if not row:
            return None
        return self._row_to_node(row)

    async def get_all(self, limit: int = 500) -> list[Node]:
        rows = await self._db.fetch_all(
            "SELECT * FROM nodes ORDER BY last_heard DESC LIMIT ?", (limit,)
        )
        return [self._row_to_node(r) for r in rows]

    async def get_count(self) -> int:
        row = await self._db.fetch_one("SELECT COUNT(*) as cnt FROM nodes")
        return row["cnt"] if row else 0

    async def get_active_count(self, hours: int = 24) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        row = await self._db.fetch_one(
            "SELECT COUNT(*) as cnt FROM nodes WHERE last_heard >= ?", (cutoff,)
        )
        return row["cnt"] if row else 0

    async def get_network_totals(self) -> dict:
        """Whole-table aggregates for the stats summary's network block.

        SQL-side so no LIMIT applies (summing over ``get_all()`` capped
        every figure at its default 500 rows).
        """
        row = await self._db.fetch_one(
            "SELECT COUNT(*) AS total_nodes, "
            "SUM(CASE WHEN latitude IS NOT NULL AND longitude IS NOT NULL "
            "    THEN 1 ELSE 0 END) AS nodes_with_position, "
            "COALESCE(SUM(packet_count), 0) AS total_packets_seen "
            "FROM nodes"
        )
        protocol_rows = await self._db.fetch_all(
            "SELECT protocol, COUNT(*) AS cnt FROM nodes GROUP BY protocol"
        )
        return {
            "total_nodes": row["total_nodes"] if row else 0,
            "nodes_with_position": (row["nodes_with_position"] or 0) if row else 0,
            "total_packets_seen": (row["total_packets_seen"] or 0) if row else 0,
            "protocols": {r["protocol"]: r["cnt"] for r in protocol_rows},
        }

    async def get_all_with_signal(self, limit: int = 500) -> list[dict]:
        """Return nodes with latest signal and telemetry from joined tables."""
        rows = await self._db.fetch_all(
            """
            SELECT n.*,
                   p.rssi AS latest_rssi,
                   p.snr AS latest_snr,
                   p.hop_limit AS latest_hop_limit,
                   p.hop_start AS latest_hop_start,
                   p.capture_source AS latest_capture_source,
                   t.battery_level AS latest_battery,
                   t.voltage AS latest_voltage,
                   t.temperature AS latest_temperature,
                   t.humidity AS latest_humidity,
                   t.channel_utilization AS latest_channel_util,
                   t.air_util_tx AS latest_air_util
            FROM nodes n
            LEFT JOIN (
                SELECT source_id,
                       rssi, snr, hop_limit, hop_start, capture_source,
                       ROW_NUMBER() OVER (PARTITION BY source_id ORDER BY timestamp DESC) AS rn
                FROM packets
            ) p ON p.source_id = n.node_id AND p.rn = 1
            LEFT JOIN (
                SELECT node_id,
                       battery_level, voltage, temperature, humidity,
                       channel_utilization, air_util_tx,
                       ROW_NUMBER() OVER (PARTITION BY node_id ORDER BY timestamp DESC) AS rn
                FROM telemetry
            ) t ON t.node_id = n.node_id AND t.rn = 1
            ORDER BY n.last_heard DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [self._enrich_row(row) for row in rows]

    @staticmethod
    def _enrich_row(row: dict) -> dict:
        """Build an enriched node dict from a joined query row."""
        node = NodeRepository._row_to_node(row)
        d = node.to_dict()
        d["latest_rssi"] = row.get("latest_rssi")
        d["latest_snr"] = row.get("latest_snr")
        d["latest_capture_source"] = row.get("latest_capture_source")
        d["latest_battery"] = row.get("latest_battery")
        d["latest_voltage"] = row.get("latest_voltage")
        d["latest_temperature"] = row.get("latest_temperature")
        d["latest_humidity"] = row.get("latest_humidity")
        d["latest_channel_util"] = row.get("latest_channel_util")
        d["latest_air_util"] = row.get("latest_air_util")
        hop_start = row.get("latest_hop_start", 0) or 0
        hop_limit = row.get("latest_hop_limit", 0) or 0
        d["latest_hops"] = max(0, hop_start - hop_limit)
        return d

    async def increment_packet_count(self, node_id: str) -> None:
        await self._db.execute(
            "UPDATE nodes SET packet_count = packet_count + 1, last_heard = ? WHERE node_id = ?",
            (datetime.now(timezone.utc).isoformat(), node_id),
        )
        await self._db.commit()

    async def count_phantom_rows(self) -> int:
        """Count node rows with no packets and no identifying names."""
        row = await self._db.fetch_one(
            f"SELECT COUNT(*) AS cnt FROM nodes WHERE {PHANTOM_ROW_PREDICATE}"
        )
        return int(row["cnt"]) if row else 0

    async def delete_phantom_rows(self) -> int:
        """Delete phantom node rows; returns number of rows removed."""
        result = await self._db.execute(
            f"DELETE FROM nodes WHERE {PHANTOM_ROW_PREDICATE}"
        )
        await self._db.commit()
        return int(getattr(result, "rowcount", 0) or 0)

    @staticmethod
    def _row_to_node(row: dict) -> Node:
        return Node(
            node_id=row["node_id"],
            long_name=row.get("long_name"),
            short_name=row.get("short_name"),
            hardware_model=row.get("hardware_model"),
            firmware_version=row.get("firmware_version"),
            protocol=row.get("protocol", "meshtastic"),
            role=row.get("role"),
            public_key=row.get("public_key"),
            latitude=row.get("latitude"),
            longitude=row.get("longitude"),
            altitude=row.get("altitude"),
            last_heard=datetime.fromisoformat(row["last_heard"]),
            first_seen=datetime.fromisoformat(row["first_seen"]),
            packet_count=row.get("packet_count", 0),
        )
