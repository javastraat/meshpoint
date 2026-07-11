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
_repeater_poller = None

def init_routes(
    packet_repo: PacketRepository,
    self_node_id: str | None = None,
    self_name: str = "This box",
    anchor_node_id: str | None = None,
    repeater_poller=None,
) -> None:
    global _packet_repo, _self_node_id, _self_name, _anchor_node_id
    global _repeater_poller
    _packet_repo = packet_repo
    _self_node_id = (self_node_id or "").lower() or None
    _self_name = self_name or "This box"
    _anchor_node_id = (anchor_node_id or "").lower() or None
    _repeater_poller = repeater_poller


def _live_neighbour_rows() -> list[dict]:
    """Fresh neighbour rows from the repeater poller, one star per
    polled repeater. Shape matches the SQL rows plus an ``anchor``.

    last_seen is computed as poll-time minus the neighbour's secs_ago,
    anchored to our own clock (skew-immune, like the imports).
    """
    if _repeater_poller is None:
        return []
    rows: list[dict] = []
    from datetime import datetime, timedelta

    for key, entry in getattr(_repeater_poller, "latest", {}).items():
        data = (entry or {}).get("neighbours") or {}
        neighbours = data.get("neighbours")
        if not isinstance(neighbours, list):
            continue
        polled_at = None
        try:
            polled_at = datetime.fromisoformat(entry.get("updated_at"))
        except (TypeError, ValueError):
            pass
        for n in neighbours:
            if not isinstance(n, dict) or not n.get("pubkey"):
                continue
            last_seen = None
            if polled_at is not None and isinstance(n.get("secs_ago"), (int, float)):
                last_seen = (polled_at - timedelta(seconds=n["secs_ago"])).isoformat()
            rows.append({
                "anchor": key,
                "source_id": n["pubkey"],
                "cnt": 1,
                "last_seen": last_seen,
                "avg_snr": n.get("snr"),
            })
    return rows


@router.get("/graph")
async def get_graph(context: int = 0):
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
        "SELECT node_id, long_name, short_name, protocol, role, "
        "latitude, longitude FROM nodes"
    )

    graph = assemble_graph(
        traceroute_rows,
        direct_rows,
        list(neighbour_rows) + _live_neighbour_rows(),
        roster_rows,
        _self_node_id,
        _self_name,
        _anchor_node_id,
    )

    if context:
        # Positioned-but-unlinked nodes: known to exist somewhere, no link
        # evidence yet. Map-mode backdrop; opt-in so default loads stay light.
        linked = {n["id"] for n in graph["nodes"]}
        graph["context_nodes"] = [
            {
                "id": row["node_id"].lower(),
                "name": row["long_name"] or row["short_name"] or None,
                "protocol": row["protocol"],
                "lat": row["latitude"],
                "lon": row["longitude"],
            }
            for row in roster_rows
            if row["latitude"] and row["longitude"]
            and row["node_id"].lower() not in linked
        ]
    return graph
