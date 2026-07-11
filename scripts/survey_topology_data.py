#!/usr/bin/env python3
"""Read-only survey: how much mesh-topology data is in the database?

Decides how ambitious the topology-graph feature can be before any UI is
built. Counts every edge source we could draw:

- Meshtastic NEIGHBORINFO packets (reporter -> neighbour, with SNR)
- Meshtastic TRACEROUTE packets (multi-hop route chains)
- Direct RF receptions (hop_start == hop_limit > 0: our box heard the
  node first-hand -> an edge from us)
- MeshCore neighbour rows (nb:% from import_contacts.py and
  meshcoredb:neighbour:% from the archive import -- star around the
  generating repeater, SNR-only)

Prints counts, distinct nodes/edges, name-resolution rate, and time ranges.
Makes no writes; opens the database in read-only mode.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path

DEFAULT_DB = "/opt/meshpoint/data/concentrator.db"


def _connect_ro(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _name_map(cur: sqlite3.Cursor) -> dict[str, str]:
    names: dict[str, str] = {}
    for row in cur.execute(
        "SELECT node_id, COALESCE(long_name, short_name) AS name FROM nodes "
        "WHERE COALESCE(long_name, short_name, '') != ''"
    ):
        names[row["node_id"].lower()] = row["name"]
    return names


def _fmt_node(node_id: str, names: dict[str, str]) -> str:
    name = names.get((node_id or "").lower())
    return f"{name} ({node_id})" if name else node_id


def _section(title: str) -> None:
    print()
    print(f"== {title} ==")


def _time_range(cur: sqlite3.Cursor, where: str, params: tuple = ()) -> str:
    row = cur.execute(
        f"SELECT MIN(timestamp) AS lo, MAX(timestamp) AS hi FROM packets WHERE {where}",
        params,
    ).fetchone()
    if not row or not row["lo"]:
        return "-"
    return f"{row['lo'][:16]} .. {row['hi'][:16]}"


def survey(db_path: str) -> None:
    con = _connect_ro(db_path)
    cur = con.cursor()
    names = _name_map(cur)

    print(f"database : {db_path}")
    print(f"named nodes in roster: {len(names)}")

    _section("Overview")
    for row in cur.execute(
        "SELECT protocol, COUNT(*) AS cnt FROM packets GROUP BY protocol ORDER BY cnt DESC"
    ):
        print(f"  {row['protocol'] or '(null)':12s} {row['cnt']:>8} packets")

    # ---- Meshtastic NEIGHBORINFO ----------------------------------------
    _section("Meshtastic NEIGHBORINFO (reporter -> neighbour edges)")
    rows = cur.execute(
        "SELECT source_id, decoded_payload, timestamp FROM packets "
        "WHERE packet_type = 'neighborinfo'"
    ).fetchall()
    print(f"  packets           : {len(rows)}")
    edges: Counter[tuple[str, str]] = Counter()
    edges_with_snr = 0
    reporters: Counter[str] = Counter()
    undecoded = 0
    for row in rows:
        try:
            payload = json.loads(row["decoded_payload"] or "{}")
        except (json.JSONDecodeError, TypeError):
            payload = {}
        neighbors = payload.get("neighbors")
        if not isinstance(neighbors, list) or not neighbors:
            undecoded += 1
            continue
        src = (row["source_id"] or "").lower()
        reporters[src] += 1
        for n in neighbors:
            dst = (n.get("node_id") or "").lower()
            if not dst:
                continue
            edges[(src, dst)] += 1
            if n.get("snr") is not None:
                edges_with_snr += 1
    print(f"  without usable payload: {undecoded}")
    print(f"  distinct reporters : {len(reporters)}")
    print(f"  distinct edges     : {len(edges)}")
    print(f"  edge observations with SNR: {edges_with_snr}")
    print(f"  time range         : {_time_range(cur, 'packet_type = ?', ('neighborinfo',))}")
    if reporters:
        print("  top reporters:")
        for src, cnt in reporters.most_common(5):
            n_edges = sum(1 for (a, _b) in edges if a == src)
            print(f"    {_fmt_node(src, names):45s} {cnt:>4} reports, {n_edges} distinct neighbours")

    # ---- Meshtastic TRACEROUTE ------------------------------------------
    _section("Meshtastic TRACEROUTE (route chains)")
    rows = cur.execute(
        "SELECT source_id, destination_id, decoded_payload, timestamp FROM packets "
        "WHERE packet_type = 'traceroute'"
    ).fetchall()
    print(f"  packets           : {len(rows)}")
    routed = 0
    hop_edges: Counter[tuple[str, str]] = Counter()
    samples: list[str] = []
    for row in rows:
        try:
            payload = json.loads(row["decoded_payload"] or "{}")
        except (json.JSONDecodeError, TypeError):
            payload = {}
        route = payload.get("route")
        if not isinstance(route, list) or not route:
            continue
        routed += 1
        chain = [(row["source_id"] or "").lower()] + [r.lower() for r in route]
        for a, b in zip(chain, chain[1:]):
            if a and b:
                hop_edges[(a, b)] += 1
        if len(samples) < 5:
            samples.append(" -> ".join(_fmt_node(h, names) for h in chain))
    print(f"  with a route      : {routed}")
    print(f"  distinct hop edges: {len(hop_edges)}")
    print(f"  time range        : {_time_range(cur, 'packet_type = ?', ('traceroute',))}")
    for s in samples:
        print(f"    {s}")

    # ---- Direct RF receptions (our own box's edges) ----------------------
    _section("Direct RF receptions (hop_start == hop_limit > 0 -> edge from this box)")
    for proto in ("meshtastic", "meshcore"):
        row = cur.execute(
            "SELECT COUNT(DISTINCT source_id) AS nodes, COUNT(*) AS pkts FROM packets "
            "WHERE protocol = ? AND hop_start > 0 AND hop_start = hop_limit",
            (proto,),
        ).fetchone()
        total = cur.execute(
            "SELECT COUNT(DISTINCT source_id) AS n FROM packets WHERE protocol = ?",
            (proto,),
        ).fetchone()["n"]
        print(f"  {proto:11s} {row['nodes']:>5} direct nodes ({row['pkts']} packets) of {total} sources seen")

    # ---- MeshCore neighbour rows -----------------------------------------
    _section("MeshCore neighbour edges (star around the generating repeater)")
    for label, pattern in (("nb: (neighbours.json import)", "nb:%"),
                           ("meshcoredb: (archive import)", "meshcoredb:neighbour:%")):
        row = cur.execute(
            "SELECT COUNT(*) AS cnt, COUNT(DISTINCT source_id) AS nodes, "
            "SUM(snr IS NOT NULL) AS with_snr FROM packets WHERE packet_id LIKE ?",
            (pattern,),
        ).fetchone()
        rng = _time_range(cur, "packet_id LIKE ?", (pattern,))
        print(f"  {label:30s} {row['cnt']:>6} rows, {row['nodes']:>4} distinct nodes, "
              f"{row['with_snr'] or 0} with SNR, {rng}")

    # ---- Name resolution --------------------------------------------------
    _section("Name resolution (graph labels)")
    referenced: set[str] = set()
    referenced.update(a for (a, _b) in edges)
    referenced.update(b for (_a, b) in edges)
    referenced.update(a for (a, _b) in hop_edges)
    referenced.update(b for (_a, b) in hop_edges)
    if referenced:
        resolved = sum(1 for r in referenced if r in names)
        print(f"  meshtastic graph nodes: {len(referenced)}, with names: {resolved} "
              f"({100 * resolved // len(referenced)}%)")
    else:
        print("  meshtastic graph nodes: 0")
    row = cur.execute(
        "SELECT COUNT(DISTINCT source_id) AS n FROM packets WHERE packet_id LIKE 'nb:%'"
    ).fetchone()
    print(f"  meshcore star nodes   : {row['n']} (all from the named contact roster)")

    con.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DEFAULT_DB,
                        help=f"Meshpoint SQLite database (default: {DEFAULT_DB})")
    args = parser.parse_args()
    if not Path(args.db).exists():
        print(f"ERROR: database not found: {args.db}")
        return 1
    survey(args.db)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
