"""MeshCore contact/node endpoints for the MeshCore dashboard tab."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query

from src.storage.node_repository import NodeRepository
from src.storage.packet_repository import PacketRepository

router = APIRouter(prefix="/api/meshcore", tags=["meshcore"])

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
    "bandwidth_khz", "hops", "hop_start", "hop_limit", "capture_source",
    "decoded_payload",
]


@router.get("/export/packets.csv")
async def meshcore_packets_csv():
    """All captured MeshCore packets as a downloadable CSV."""
    if _packet_repo is None:
        raise HTTPException(503, "Routes not initialised")
    from src.api.csv_export import export_filename, streaming_csv, stream_query

    def _flatten(row):
        hs = row.get("hop_start") or 0
        hl = row.get("hop_limit") or 0
        row["hops"] = max(0, hs - hl) if hs else None
        return row

    rows = stream_query(
        _packet_repo._db,
        """
        SELECT p.timestamp, p.packet_id, p.source_id,
               COALESCE(NULLIF(n.long_name, ''), NULLIF(n.short_name, '')) AS source_name,
               p.destination_id, p.packet_type, p.rssi, p.snr,
               p.frequency_mhz, p.spreading_factor, p.bandwidth_khz,
               p.hop_start, p.hop_limit, p.capture_source, p.decoded_payload
        FROM packets p
        LEFT JOIN nodes n ON n.node_id = p.source_id
        WHERE p.protocol = 'meshcore'
        ORDER BY p.timestamp DESC
        """,
        (),
        _PACKET_EXPORT_COLUMNS,
        transform=_flatten,
    )
    return streaming_csv(
        _PACKET_EXPORT_COLUMNS, rows,
        export_filename(_device_name, "meshcore-packets"),
    )


_CONTACT_EXPORT_COLUMNS = [
    "node_id", "long_name", "short_name", "role", "latitude", "longitude",
    "first_seen", "last_heard", "packet_count", "latest_rssi", "latest_snr",
]


@router.get("/export/contacts.csv")
async def meshcore_contacts_csv():
    """All known MeshCore contacts as a downloadable CSV."""
    if _node_repo is None:
        raise HTTPException(503, "Routes not initialised")
    from src.api.csv_export import export_filename, streaming_csv, stream_query

    rows = stream_query(
        _node_repo._db,
        """
        SELECT n.node_id, n.long_name, n.short_name, n.role,
               n.latitude, n.longitude, n.first_seen, n.last_heard,
               n.packet_count,
               p.rssi AS latest_rssi, p.snr AS latest_snr
        FROM nodes n
        LEFT JOIN (
            SELECT source_id, rssi, snr,
                   ROW_NUMBER() OVER (PARTITION BY source_id ORDER BY timestamp DESC) AS rn
            FROM packets WHERE protocol = 'meshcore'
        ) p ON p.source_id = n.node_id AND p.rn = 1
        WHERE n.protocol = 'meshcore'
        ORDER BY n.last_heard DESC
        """,
        (),
        _CONTACT_EXPORT_COLUMNS,
    )
    return streaming_csv(
        _CONTACT_EXPORT_COLUMNS, rows,
        export_filename(_device_name, "meshcore-contacts"),
    )


@router.get("/nodes")
async def meshcore_nodes():
    """All known MeshCore nodes sorted by last_heard."""
    if _node_repo is None:
        raise HTTPException(503, "Routes not initialised")

    rows = await _node_repo._db.fetch_all(
        """
        SELECT n.node_id, n.long_name, n.short_name, n.role,
               n.latitude, n.longitude, n.last_heard, n.first_seen,
               n.packet_count, n.protocol,
               p.rssi AS latest_rssi, p.snr AS latest_snr
        FROM nodes n
        LEFT JOIN (
            SELECT source_id, rssi, snr,
                   ROW_NUMBER() OVER (PARTITION BY source_id ORDER BY timestamp DESC) AS rn
            FROM packets WHERE protocol = 'meshcore'
        ) p ON p.source_id = n.node_id AND p.rn = 1
        WHERE n.protocol = 'meshcore'
        ORDER BY n.last_heard DESC
        """
    )
    return [dict(r) for r in rows]


@router.get("/packets")
async def meshcore_packets(limit: int = Query(100, ge=1, le=500)):
    """Recent MeshCore packets, newest first."""
    if _packet_repo is None:
        raise HTTPException(503, "Routes not initialised")

    rows = await _packet_repo._db.fetch_all(
        """
        SELECT packet_id, source_id, destination_id, packet_type,
               hop_limit, hop_start, rssi, snr,
               frequency_mhz, spreading_factor, bandwidth_khz,
               decoded_payload, capture_source, timestamp
        FROM packets
        WHERE protocol = 'meshcore'
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
            "packet_id":        row["packet_id"],
            "protocol":         "meshcore",
            "source_id":        row["source_id"],
            "destination_id":   row["destination_id"],
            "packet_type":      row["packet_type"],
            "rssi":             row["rssi"],
            "snr":              row["snr"],
            "frequency_mhz":    row["frequency_mhz"],
            "spreading_factor": row["spreading_factor"],
            "bandwidth_khz":    row.get("bandwidth_khz"),
            "hops":             hops,
            "hop_start":        hop_start,
            "hop_limit":        hop_limit,
            "decoded_payload":  _parse_payload(row.get("decoded_payload")),
            "capture_source":   row.get("capture_source"),
            "timestamp":        row["timestamp"],
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
async def meshcore_stats():
    """Aggregate counts for the MeshCore tab."""
    if _packet_repo is None or _node_repo is None:
        raise HTTPException(503, "Routes not initialised")

    total_nodes = await _node_repo._db.fetch_one(
        "SELECT COUNT(*) AS cnt FROM nodes WHERE protocol = 'meshcore'"
    )

    cutoff_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    cutoff_7d  = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

    active_24h = await _node_repo._db.fetch_one(
        "SELECT COUNT(*) AS cnt FROM nodes WHERE protocol = 'meshcore' AND last_heard >= ?",
        (cutoff_24h,),
    )
    active_7d = await _node_repo._db.fetch_one(
        "SELECT COUNT(*) AS cnt FROM nodes WHERE protocol = 'meshcore' AND last_heard >= ?",
        (cutoff_7d,),
    )

    total_packets = await _packet_repo._db.fetch_one(
        "SELECT COUNT(*) AS cnt FROM packets WHERE protocol = 'meshcore'"
    )

    return {
        "total_nodes":   total_nodes["cnt"]   if total_nodes   else 0,
        "active_24h":    active_24h["cnt"]    if active_24h    else 0,
        "active_7d":     active_7d["cnt"]     if active_7d     else 0,
        "total_packets": total_packets["cnt"] if total_packets else 0,
    }
