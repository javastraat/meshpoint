#!/usr/bin/env python3
"""Repair synthetic neighbour_advert rows that carry bogus timestamps.

import_contacts.py inserts synthetic packets (packet_id 'nb:<node>:<ts>')
to surface neighbour SNR in the dashboard, stamped with the neighbour's
self-reported advert time. Nodes with unsynced clocks produce bad
timestamps in TWO directions:
  - years in the PAST   -> distorts MIN(timestamp) ("days since first pkt")
  - hours in the FUTURE -> node sorts to the top of the list as "now"
                           (clock running ahead of real time)

Fix, per bad synthetic row (timestamp before --cutoff OR in the future):
  - node has real captured packets  -> re-stamp to its latest real packet
  - node heard, packet aged out      -> nodes.last_heard, if that's itself
                                        sane (not future, not pre-cutoff)
  - node was never actually heard    -> re-stamp to the DB's earliest real
                                        packet time (a safe, non-distorting
                                        date; keeps the row and its SNR)

Nothing is deleted. Every branch only rewrites the bogus timestamp.

Usage (on the M1):
    # dry run - shows what would change, writes nothing
    python3 repair_neighbour_timestamps.py

    # apply
    sudo python3 repair_neighbour_timestamps.py --apply
"""

import argparse
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

DB_PATH = "/opt/meshpoint/data/concentrator.db"
CUTOFF = "2026-01-01"
# Rows stamped more than this far ahead of now are treated as future-bad.
FUTURE_SKEW = timedelta(minutes=2)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DB_PATH, help=f"database path (default: {DB_PATH})")
    parser.add_argument("--cutoff", default=CUTOFF,
                        help=f"synthetic rows older than this are bad (default: {CUTOFF})")
    parser.add_argument("--apply", action="store_true", help="write changes (default is dry run)")
    args = parser.parse_args()

    now_iso = datetime.now(tz=timezone.utc).isoformat()
    future_iso = (datetime.now(tz=timezone.utc) + FUTURE_SKEW).isoformat()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        bad_rows = conn.execute(
            """
            SELECT p.rowid AS rowid,
                   p.source_id,
                   p.timestamp AS bad_ts,
                   (SELECT MAX(p2.timestamp) FROM packets p2
                     WHERE p2.source_id = p.source_id
                       AND p2.packet_id NOT LIKE 'nb:%') AS last_real,
                   n.last_heard AS node_last_heard
            FROM packets p
            LEFT JOIN nodes n ON n.node_id = p.source_id
            WHERE p.packet_id LIKE 'nb:%'
              AND (p.timestamp < ? OR p.timestamp > ?)
            ORDER BY p.timestamp
            """,
            (args.cutoff, future_iso),
        ).fetchall()

        # Last-resort date: the earliest REAL packet in the DB. Equal to the
        # existing MIN once bad rows are fixed, so it can't distort stats.
        earliest_real = conn.execute(
            "SELECT MIN(timestamp) FROM packets WHERE packet_id NOT LIKE 'nb:%'"
        ).fetchone()[0]

        # Per node, pick the best available real date:
        #   1. latest real captured packet         (heard, packet still in DB;
        #                                            always <= now, so safe)
        #   2. else nodes.last_heard IF it's sane   (>= cutoff and not future;
        #                                            packet aged out)
        #   3. else clamp to earliest real packet   (genuinely unknown)
        plan = []  # (rowid, source_id, bad_ts, new_ts, reason)
        for r in bad_rows:
            node_lh = r["node_last_heard"]
            lh_sane = node_lh and args.cutoff <= node_lh <= now_iso
            if r["last_real"]:
                plan.append((r["rowid"], r["source_id"], r["bad_ts"],
                             r["last_real"], "packet"))
            elif lh_sane:
                plan.append((r["rowid"], r["source_id"], r["bad_ts"],
                             node_lh, "last_heard"))
            else:
                plan.append((r["rowid"], r["source_id"], r["bad_ts"],
                             earliest_real, "clamp"))

        if plan:
            print(f"bad synthetic rows (pre-{args.cutoff} or future): {len(plan)}\n")
            for _rowid, src, bad_ts, new_ts, reason in plan:
                tag = {"packet": "REPAIR", "last_heard": "REPAIR", "clamp": "CLAMP "}[reason]
                note = {
                    "packet": "latest real packet",
                    "last_heard": "node last_heard (packet aged out)",
                    "clamp": "no real date known - clamped, not deleted",
                }[reason]
                print(f"  {tag}  {src}  {bad_ts}  ->  {new_ts}  ({note})")

        # nodes.last_heard is what the node list sorts by, and the import only
        # ever RAISES it -- so a node poisoned with a future last_heard stays
        # pinned to the top even after its packet row is fixed. Reset any
        # future nodes.last_heard to that node's latest real packet (or now).
        future_nodes = conn.execute(
            """
            SELECT n.node_id, n.last_heard,
                   (SELECT MAX(p.timestamp) FROM packets p
                     WHERE p.source_id = n.node_id
                       AND p.packet_id NOT LIKE 'nb:%') AS last_real
            FROM nodes n
            WHERE n.last_heard > ?
            ORDER BY n.last_heard DESC
            """,
            (future_iso,),
        ).fetchall()

        node_plan = []  # (node_id, old_lh, new_lh)
        for r in future_nodes:
            new_lh = r["last_real"] or now_iso
            node_plan.append((r["node_id"], r["last_heard"], new_lh))

        if node_plan:
            print(f"\nfuture nodes.last_heard: {len(node_plan)}\n")
            for node_id, old_lh, new_lh in node_plan:
                print(f"  NODE    {node_id}  {old_lh}  ->  {new_lh}")

        if not plan and not node_plan:
            print("No bad timestamps found (past or future). Nothing to do.")
            return 0

        if not args.apply:
            print("\nDry run only. Re-run with --apply to write these changes.")
            return 0

        for rowid, src, _bad_ts, new_ts, _reason in plan:
            conn.execute(
                "UPDATE packets SET timestamp = ?, packet_id = ? WHERE rowid = ?",
                (new_ts, f"nb:{src}:{new_ts}", rowid),
            )
        for node_id, _old_lh, new_lh in node_plan:
            conn.execute(
                "UPDATE nodes SET last_heard = ? WHERE node_id = ?",
                (new_lh, node_id),
            )
        conn.commit()

        repaired = sum(1 for p in plan if p[4] != "clamp")
        clamped = sum(1 for p in plan if p[4] == "clamp")
        first = conn.execute("SELECT MIN(timestamp) FROM packets").fetchone()[0]
        print(f"\nRe-stamped {repaired} rows from real data, clamped {clamped}, "
              f"fixed {len(node_plan)} future node last_heard. Nothing deleted.")
        print(f"First packet is now: {first}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
