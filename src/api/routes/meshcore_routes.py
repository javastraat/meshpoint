"""MeshCore contact/node endpoints for the MeshCore dashboard tab."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query

from src.storage.node_repository import NodeRepository
from src.storage.packet_repository import PacketRepository

router = APIRouter(prefix="/api/meshcore", tags=["meshcore"])

_packet_repo: PacketRepository | None = None
_node_repo: NodeRepository | None = None


def init_routes(packet_repo: PacketRepository, node_repo: NodeRepository) -> None:
    global _packet_repo, _node_repo
    _packet_repo = packet_repo
    _node_repo = node_repo


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
               frequency_mhz, spreading_factor,
               capture_source, timestamp
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
            "source_id":        row["source_id"],
            "destination_id":   row["destination_id"],
            "packet_type":      row["packet_type"],
            "rssi":             row["rssi"],
            "snr":              row["snr"],
            "frequency_mhz":    row["frequency_mhz"],
            "spreading_factor": row["spreading_factor"],
            "hops":             hops,
            "capture_source":   row.get("capture_source"),
            "timestamp":        row["timestamp"],
        })
    return result


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
