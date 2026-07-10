"""Meshtastic packet and node endpoints."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query

from src.storage.node_repository import NodeRepository
from src.storage.packet_repository import PacketRepository

router = APIRouter(prefix="/api/meshtastic", tags=["meshtastic"])

_packet_repo: PacketRepository | None = None
_node_repo: NodeRepository | None = None
_device_name: str = "meshpoint"


def init_routes(
    packet_repo: PacketRepository,
    node_repo: NodeRepository,
    device_name: str = "meshpoint",
) -> None:
    global _packet_repo, _node_repo, _device_name
    _packet_repo = packet_repo
    _node_repo = node_repo
    _device_name = device_name or "meshpoint"


_PACKET_EXPORT_COLUMNS = [
    "timestamp", "packet_id", "source_id", "source_name", "destination_id",
    "packet_type", "rssi", "snr", "frequency_mhz", "spreading_factor",
    "bandwidth_khz", "hops", "hop_start", "hop_limit", "decrypted",
    "capture_source", "decoded_payload",
]


@router.get("/export/packets.csv")
async def meshtastic_packets_csv():
    """All captured Meshtastic packets as a downloadable CSV."""
    if _packet_repo is None:
        raise HTTPException(503, "Routes not initialised")
    from src.api.csv_export import export_filename, streaming_csv, stream_query

    def _flatten(row):
        hs = row.get("hop_start") or 0
        hl = row.get("hop_limit") or 0
        row["hops"] = max(0, hs - hl) if hs else None
        row["decrypted"] = bool(row.get("decrypted"))
        return row

    rows = stream_query(
        _packet_repo._db,
        """
        SELECT p.timestamp, p.packet_id, p.source_id,
               COALESCE(NULLIF(n.long_name, ''), NULLIF(n.short_name, '')) AS source_name,
               p.destination_id, p.packet_type, p.rssi, p.snr,
               p.frequency_mhz, p.spreading_factor, p.bandwidth_khz,
               p.hop_start, p.hop_limit, p.decrypted, p.capture_source,
               p.decoded_payload
        FROM packets p
        LEFT JOIN nodes n ON n.node_id = p.source_id
        WHERE p.protocol = 'meshtastic'
        ORDER BY p.timestamp DESC
        """,
        (),
        _PACKET_EXPORT_COLUMNS,
        transform=_flatten,
    )
    return streaming_csv(
        _PACKET_EXPORT_COLUMNS, rows,
        export_filename(_device_name, "meshtastic-packets"),
    )


_NODE_EXPORT_COLUMNS = [
    "node_id", "long_name", "short_name", "hardware_model", "role",
    "latitude", "longitude", "first_seen", "last_heard", "packet_count",
    "latest_rssi", "latest_snr",
]


@router.get("/export/nodes.csv")
async def meshtastic_nodes_csv():
    """All known Meshtastic nodes as a downloadable CSV."""
    if _node_repo is None:
        raise HTTPException(503, "Routes not initialised")
    from src.api.csv_export import export_filename, streaming_csv, stream_query

    rows = stream_query(
        _node_repo._db,
        """
        SELECT n.node_id, n.long_name, n.short_name, n.hardware_model, n.role,
               n.latitude, n.longitude, n.first_seen, n.last_heard,
               n.packet_count,
               p.rssi AS latest_rssi, p.snr AS latest_snr
        FROM nodes n
        LEFT JOIN (
            SELECT source_id, rssi, snr,
                   ROW_NUMBER() OVER (PARTITION BY source_id ORDER BY timestamp DESC) AS rn
            FROM packets WHERE protocol = 'meshtastic'
        ) p ON p.source_id = n.node_id AND p.rn = 1
        WHERE n.protocol = 'meshtastic'
        ORDER BY n.last_heard DESC
        """,
        (),
        _NODE_EXPORT_COLUMNS,
    )
    return streaming_csv(
        _NODE_EXPORT_COLUMNS, rows,
        export_filename(_device_name, "meshtastic-nodes"),
    )


@router.get("/nodes")
async def meshtastic_nodes():
    """All known Meshtastic nodes with latest signal and packet stats."""
    if _node_repo is None:
        raise HTTPException(503, "Routes not initialised")

    rows = await _node_repo._db.fetch_all(
        """
        SELECT n.node_id, n.long_name, n.short_name, n.hardware_model, n.role,
               n.latitude, n.longitude, n.last_heard, n.first_seen,
               n.packet_count, n.protocol,
               p.rssi AS latest_rssi, p.snr AS latest_snr,
               CASE WHEN p.hop_start IS NOT NULL AND p.hop_start > 0
                    THEN MAX(0, p.hop_start - COALESCE(p.hop_limit, 0))
                    ELSE NULL END AS latest_hops
        FROM nodes n
        LEFT JOIN (
            SELECT source_id, rssi, snr, hop_start, hop_limit,
                   ROW_NUMBER() OVER (PARTITION BY source_id ORDER BY timestamp DESC) AS rn
            FROM packets WHERE protocol = 'meshtastic'
        ) p ON p.source_id = n.node_id AND p.rn = 1
        WHERE n.protocol = 'meshtastic'
        ORDER BY n.last_heard DESC
        """
    )
    return [dict(r) for r in rows]


@router.get("/packets")
async def meshtastic_packets(limit: int = Query(100, ge=1, le=500)):
    """Recent Meshtastic packets, newest first."""
    if _packet_repo is None:
        raise HTTPException(503, "Routes not initialised")

    rows = await _packet_repo._db.fetch_all(
        """
        SELECT
            packet_id, source_id, destination_id, packet_type,
            hop_limit, hop_start, rssi, snr,
            frequency_mhz, spreading_factor, bandwidth_khz,
            decoded_payload, decrypted, capture_source, timestamp
        FROM packets
        WHERE protocol = 'meshtastic'
        ORDER BY timestamp DESC
        LIMIT ?
        """,
        (limit,),
    )

    result = []
    for row in rows:
        hop_start = row.get("hop_start") or 0
        hop_limit = row.get("hop_limit") or 0
        hops = max(0, hop_start - hop_limit) if hop_start else None
        result.append({
            "packet_id": row["packet_id"],
            "protocol": "meshtastic",
            "source_id": row["source_id"],
            "destination_id": row["destination_id"],
            "packet_type": row["packet_type"],
            "rssi": row["rssi"],
            "snr": row["snr"],
            "frequency_mhz": row["frequency_mhz"],
            "spreading_factor": row["spreading_factor"],
            "bandwidth_khz": row.get("bandwidth_khz"),
            "hops": hops,
            "hop_start": hop_start,
            "hop_limit": hop_limit,
            "decoded_payload": _parse_payload(row.get("decoded_payload")),
            "decrypted": bool(row.get("decrypted")),
            "capture_source": row.get("capture_source"),
            "timestamp": row["timestamp"],
        })
    return result


def _parse_payload(raw) -> dict | None:
    """decoded_payload column is JSON text; the packet-detail modal
    wants the object."""
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except (ValueError, TypeError):
        return None


@router.get("/stats")
async def meshtastic_stats():
    """Aggregate counts for the Meshtastic panel."""
    if _packet_repo is None or _node_repo is None:
        raise HTTPException(503, "Routes not initialised")

    totals = await _packet_repo._db.fetch_one(
        "SELECT COUNT(*) AS total, COUNT(DISTINCT source_id) AS nodes "
        "FROM packets WHERE protocol = 'meshtastic'"
    )

    cutoff_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    active_24h = await _packet_repo._db.fetch_one(
        "SELECT COUNT(DISTINCT source_id) AS cnt FROM packets "
        "WHERE protocol = 'meshtastic' AND timestamp >= ?",
        (cutoff_24h,),
    )

    by_type = await _packet_repo._db.fetch_all(
        "SELECT packet_type, COUNT(*) AS cnt FROM packets "
        "WHERE protocol = 'meshtastic' GROUP BY packet_type ORDER BY cnt DESC"
    )

    return {
        "total_packets": totals["total"] if totals else 0,
        "unique_nodes": totals["nodes"] if totals else 0,
        "active_24h": active_24h["cnt"] if active_24h else 0,
        "by_type": {r["packet_type"]: r["cnt"] for r in by_type},
    }
