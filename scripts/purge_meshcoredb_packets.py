#!/usr/bin/env python3
"""Remove bulk-imported historical telemetry/status packets from
import_meshcore_db.py -- NOT its neighbour rows, which are still used.

Unlike dedupe_meshcoredb_packets.py (which only removes exact
packet_id duplicates), this deletes every 'meshcoredb:telemetry:%' and
'meshcoredb:status:%' row regardless of uniqueness -- the whole point
being that a single historical telemetry/status poll snapshot
legitimately explodes into 10-20+ distinct packet rows (one per
sensor channel), which is by design, not a bug, but still buries
genuinely recent mesh activity in the live packet feed and CSV export.

Deliberately leaves 'meshcoredb:neighbour:%' rows alone: unlike the
telemetry/status rows, src/api/routes/topology_routes.py's graph query
actively matches this exact prefix (alongside the live poller's own
'nb:%' rows) to draw historical neighbour-star edges on the Topology
page. Deleting those would thin out that graph until the live poller
re-observes the same neighbours itself.

Safe to run otherwise: the repeater/node History, Sensors, and Trends
cards are powered by the separate `telemetry` table (written by
import_meshcore_db.py's own _import_telemetry_samples step), which
this script never touches -- only the raw `packets` rows disappear.
Re-running import_meshcore_db.py afterward regenerates the exact same
deterministic packet_ids, so this is not a one-way loss of the
underlying data, just of these specific packet-table rows until the
next import.

Usage (on the Pi):
    # dry run - shows how many rows would be removed, writes nothing
    python3 purge_meshcoredb_packets.py

    # apply
    sudo python3 purge_meshcoredb_packets.py --apply
"""

import argparse
import sqlite3
import sys

DB_PATH = "/opt/meshpoint/data/concentrator.db"

_WHERE = (
    "capture_source = 'meshcore_db_import' "
    "AND (packet_id LIKE 'meshcoredb:telemetry:%' "
    "OR packet_id LIKE 'meshcoredb:status:%')"
)
_COUNT_SQL = f"SELECT COUNT(*) FROM packets WHERE {_WHERE}"
_DELETE_SQL = f"DELETE FROM packets WHERE {_WHERE}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", default=DB_PATH)
    parser.add_argument(
        "--apply", action="store_true",
        help="Actually delete the rows (default: dry run only).",
    )
    args = parser.parse_args()

    con = sqlite3.connect(args.db_path)
    try:
        count = con.execute(_COUNT_SQL).fetchone()[0]
        if count == 0:
            print("No meshcore_db_import packet rows found.")
            return 0

        if not args.apply:
            print(
                f"Dry run: {count} meshcore_db_import packet row(s) would "
                "be removed. Re-run with --apply to actually delete."
            )
            return 0

        con.execute(_DELETE_SQL)
        con.commit()
        print(f"Removed {count} meshcore_db_import packet row(s).")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
