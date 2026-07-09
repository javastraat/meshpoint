#!/usr/bin/env python3
"""Purge historical rows for a capture device's own phantom node ID.

A serial Meshtastic USB stick's own self-telemetry/nodeinfo (packets it
generates about itself, never actually received over the air) used to
be captured like any other packet before serial_source.py's
self-origin filter was added. That filter only stops FUTURE
self-packets -- old rows already in the database, and the phantom
"node" entry they created, are untouched by it. This script removes
both, plus any telemetry/message rows keyed to the same node ID.

Usage (on the M1):
    # dry run -- shows what would be removed, writes nothing
    python3 purge_self_originated_node.py 09d406f4

    # apply
    python3 purge_self_originated_node.py 09d406f4 --apply
"""

import argparse
import sqlite3
import sys

DB_PATH = "/opt/meshpoint/data/concentrator.db"


def _normalize_node_id(raw: str) -> str:
    node_id = raw.strip().lower()
    if node_id.startswith("!"):
        node_id = node_id[1:]
    if node_id.startswith("0x"):
        node_id = node_id[2:]
    return node_id


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "node_id",
        help="hex node ID to purge, e.g. 09d406f4 (a leading '!' or '0x' is stripped)",
    )
    parser.add_argument("--db", default=DB_PATH, help=f"database path (default: {DB_PATH})")
    parser.add_argument("--apply", action="store_true", help="write changes (default is dry run)")
    args = parser.parse_args()

    node_id = _normalize_node_id(args.node_id)

    conn = sqlite3.connect(args.db)
    try:
        packet_count = conn.execute(
            "SELECT COUNT(*) FROM packets WHERE source_id = ?", (node_id,),
        ).fetchone()[0]
        telemetry_count = conn.execute(
            "SELECT COUNT(*) FROM telemetry WHERE node_id = ?", (node_id,),
        ).fetchone()[0]
        message_count = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE node_id = ?", (node_id,),
        ).fetchone()[0]
        node_row = conn.execute(
            "SELECT long_name, packet_count FROM nodes WHERE node_id = ?", (node_id,),
        ).fetchone()

        print(f"node_id:               {node_id}")
        print(f"packets to remove:     {packet_count}")
        print(f"telemetry rows:        {telemetry_count}")
        print(f"message rows:          {message_count}")
        print(
            f"node row:              "
            + (f"long_name={node_row[0]!r} packet_count={node_row[1]}" if node_row else "(none)")
        )

        if not (packet_count or telemetry_count or message_count or node_row):
            print("\nNothing to purge.")
            return 0

        if not args.apply:
            print("\nDry run only. Re-run with --apply to remove all of the above.")
            return 0

        removed_packets = conn.execute(
            "DELETE FROM packets WHERE source_id = ?", (node_id,),
        ).rowcount
        removed_telemetry = conn.execute(
            "DELETE FROM telemetry WHERE node_id = ?", (node_id,),
        ).rowcount
        removed_messages = conn.execute(
            "DELETE FROM messages WHERE node_id = ?", (node_id,),
        ).rowcount
        removed_node = conn.execute(
            "DELETE FROM nodes WHERE node_id = ?", (node_id,),
        ).rowcount
        conn.commit()

        print(
            f"\nRemoved {removed_packets} packet row(s), {removed_telemetry} telemetry "
            f"row(s), {removed_messages} message row(s), {removed_node} node row(s)."
        )
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
