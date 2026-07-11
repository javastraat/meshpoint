"""Pure topology graph assembly -- fastapi-free so Mac tests can run it.

See src/api/routes/topology_routes.py for the endpoint and the SQL that
feeds this. Row shapes are documented on assemble_graph.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

# Edges whose newest observation is older than this render dashed.
STALE_DAYS = 7


def _norm(node_id) -> str:
    return (node_id or "").strip().lower()


def _field(row, key):
    """Tolerant column access: sqlite3.Row has no .get(), and older row
    shapes (tests, callers) may lack newer optional columns."""
    try:
        return row[key]
    except (KeyError, IndexError):
        return None


def assemble_graph(
    traceroute_rows,
    direct_rows,
    neighbour_rows,
    roster_rows,
    self_node_id: str | None,
    self_name: str,
    anchor_node_id: str | None,
) -> dict:
    """Pure graph assembly -- separated from SQL for hardware-free tests.

    Row shapes (dict-like):
      traceroute_rows: source_id, decoded_payload (JSON), timestamp
      direct_rows:     source_id, protocol, cnt, last_seen, avg_rssi, avg_snr
      neighbour_rows:  source_id, cnt, last_seen, avg_snr
      roster_rows:     node_id, long_name, short_name, protocol, role,
                       latitude, longitude (optional)
    """
    edges: dict[tuple[str, str, str], dict] = {}
    node_proto_hint: dict[str, str] = {}

    def add_edge(a: str, b: str, kind: str, last_seen, count=1, snr=None, rssi=None):
        a, b = _norm(a), _norm(b)
        if not a or not b or a == b:
            return
        key = (min(a, b), max(a, b), kind)
        cur = edges.get(key)
        if cur is None:
            edges[key] = {
                "a": key[0], "b": key[1], "kind": kind,
                "count": count, "last_seen": last_seen,
                "snr": snr, "rssi": rssi,
            }
            return
        cur["count"] += count
        if last_seen and (not cur["last_seen"] or last_seen > cur["last_seen"]):
            cur["last_seen"] = last_seen
            if snr is not None:
                cur["snr"] = snr
            if rssi is not None:
                cur["rssi"] = rssi

    # Traceroute chains -> consecutive hop pairs.
    for row in traceroute_rows:
        try:
            payload = json.loads(row["decoded_payload"] or "{}")
        except (json.JSONDecodeError, TypeError):
            continue
        route = payload.get("route")
        if not isinstance(route, list) or not route:
            continue
        # Blank hops are dropped rather than allowed to break the chain.
        chain = [h for h in
                 ([_norm(row["source_id"])] + [_norm(r) for r in route]) if h]
        for a, b in zip(chain, chain[1:]):
            add_edge(a, b, "route", row["timestamp"])
            node_proto_hint.setdefault(a, "meshtastic")
            node_proto_hint.setdefault(b, "meshtastic")

    # Direct receptions -> edges from this box.
    if self_node_id:
        for row in direct_rows:
            src = _norm(row["source_id"])
            add_edge(
                self_node_id, src, "direct", row["last_seen"],
                count=row["cnt"],
                snr=round(row["avg_snr"], 1) if row["avg_snr"] is not None else None,
                rssi=round(row["avg_rssi"], 1) if row["avg_rssi"] is not None else None,
            )
            node_proto_hint.setdefault(src, row["protocol"] or "meshtastic")

    # Neighbour stars: each row may carry its own anchor (live poller rows,
    # one star per polled repeater); rows without one fall back to the
    # single config-derived anchor (static import rows).
    for row in neighbour_rows:
        anchor = _norm(_field(row, "anchor")) or anchor_node_id
        if not anchor:
            continue
        src = _norm(row["source_id"])
        add_edge(
            anchor, src, "neighbour", row["last_seen"],
            count=row["cnt"],
            snr=round(row["avg_snr"], 1) if row["avg_snr"] is not None else None,
        )
        node_proto_hint.setdefault(src, "meshcore")
        node_proto_hint.setdefault(anchor, "meshcore")

    roster = {_norm(r["node_id"]): r for r in roster_rows}

    node_ids: set[str] = set()
    for e in edges.values():
        node_ids.add(e["a"])
        node_ids.add(e["b"])
    if self_node_id:
        node_ids.add(self_node_id)

    nodes = []
    for nid in sorted(node_ids):
        info = roster.get(nid)
        name = None
        role = None
        lat = lon = None
        protocol = node_proto_hint.get(nid)
        if info is not None:
            name = info["long_name"] or info["short_name"] or None
            role = info["role"]
            protocol = info["protocol"] or protocol
            # 0,0 is the null island placeholder some nodes report -- treat
            # it as no position rather than mapping into the Atlantic.
            if _field(info, "latitude") and _field(info, "longitude"):
                lat = info["latitude"]
                lon = info["longitude"]
        entry = {
            "id": nid,
            "name": name,
            "protocol": protocol,
            "role": role,
            "lat": lat,
            "lon": lon,
            "is_self": nid == self_node_id,
            "is_anchor": nid == anchor_node_id,
        }
        if nid == self_node_id and not entry["name"]:
            entry["name"] = self_name
        nodes.append(entry)

    edge_list = sorted(
        edges.values(), key=lambda e: (e["a"], e["b"], e["kind"]),
    )
    counts = {
        "nodes": len(nodes),
        "edges": len(edge_list),
        "route": sum(1 for e in edge_list if e["kind"] == "route"),
        "direct": sum(1 for e in edge_list if e["kind"] == "direct"),
        "neighbour": sum(1 for e in edge_list if e["kind"] == "neighbour"),
    }
    return {
        "available": True,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "stale_days": STALE_DAYS,
        "counts": counts,
        "nodes": nodes,
        "edges": edge_list,
    }
