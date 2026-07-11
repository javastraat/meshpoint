"""Mesh topology graph endpoint.

Assembles a node/edge graph at request time from data already stored --
no new tables, no capture-path changes. Edge sources:

- ``route``     Meshtastic traceroute chains (consecutive hop pairs)
- ``direct``    packets this box heard first-hand (hop_start == hop_limit > 0)
- ``neighbour`` MeshCore neighbour rows (``nb:`` / ``meshcoredb:neighbour:``
                imports -- a star around the repeater that reported them)

NEIGHBORINFO is intentionally absent: modern Meshtastic firmware doesn't
broadcast it over RF by default and this mesh has zero such packets.
"""

from __future__ import annotations

from fastapi import APIRouter

from src.api.topology_graph import STALE_DAYS, assemble_graph  # noqa: F401
from src.storage.packet_repository import PacketRepository

router = APIRouter(prefix="/api/topology", tags=["topology"])

_packet_repo: PacketRepository | None = None
_self_node_id: str | None = None
_self_name: str = "This box"
_anchor_node_id: str | None = None

def init_routes(
    packet_repo: PacketRepository,
    self_node_id: str | None = None,
    self_name: str = "This box",
    anchor_node_id: str | None = None,
) -> None:
    global _packet_repo, _self_node_id, _self_name, _anchor_node_id
    _packet_repo = packet_repo
    _self_node_id = (self_node_id or "").lower() or None
    _self_name = self_name or "This box"
    _anchor_node_id = (anchor_node_id or "").lower() or None


@router.get("/graph")
async def get_graph():
    if not _packet_repo:
        return {"available": False, "nodes": [], "edges": []}
    db = _packet_repo._db

    traceroute_rows = await db.fetch_all(
        "SELECT source_id, decoded_payload, timestamp FROM packets "
        "WHERE packet_type = 'traceroute'"
    )
    direct_rows = await db.fetch_all(
        "SELECT source_id, protocol, COUNT(*) AS cnt, MAX(timestamp) AS last_seen, "
        "AVG(rssi) AS avg_rssi, AVG(snr) AS avg_snr FROM packets "
        "WHERE hop_start > 0 AND hop_start = hop_limit "
        "AND protocol IN ('meshtastic', 'meshcore') "
        "GROUP BY source_id, protocol"
    )
    neighbour_rows = await db.fetch_all(
        "SELECT source_id, COUNT(*) AS cnt, MAX(timestamp) AS last_seen, "
        "AVG(snr) AS avg_snr FROM packets "
        "WHERE packet_id LIKE 'nb:%' OR packet_id LIKE 'meshcoredb:neighbour:%' "
        "GROUP BY source_id"
    )
    roster_rows = await db.fetch_all(
        "SELECT node_id, long_name, short_name, protocol, role FROM nodes"
    )

    return assemble_graph(
        traceroute_rows,
        direct_rows,
        neighbour_rows,
        roster_rows,
        _self_node_id,
        _self_name,
        _anchor_node_id,
    )
