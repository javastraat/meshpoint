#!/usr/bin/env python3
"""Collapse exact packet_id duplicates left by import_meshcore_db.py.

The packets table has no UNIQUE constraint on packet_id, and
import_meshcore_db.py's own dedup only guards against re-running the
script itself (it wipes its own prior 'meshcoredb:%' rows first) -- it
does nothing about the SOURCE archive containing the same
node/timestamp/channel/type row more than once. Since packet_id is
built deterministically from those fields, a genuine source-side
duplicate produces two rows sharing the identical packet_id. This
keeps the earliest (lowest rowid) copy of each and removes the rest.

Nothing else is touched: rows with distinct packet_ids (different
channel/type/value from the same poll) are legitimate separate
telemetry readings, not duplicates, and are left alone.

Usage (on the Pi):
    # dry run - shows how many rows would be removed, writes nothing
    python3 dedupe_meshcoredb_packets.py

    # apply
    sudo python3 dedupe_meshcoredb_packets.py --apply
"""

import argparse
import sqlite3
import sys

DB_PATH = "/opt/meshpoint/data/concentrator.db"

_COUNT_SQL = """
    SELECT COUNT(*) FROM packets
    WHERE packet_id LIKE 'meshcoredb:%'
      AND rowid NOT IN (
        SELECT MIN(rowid) FROM packets
        WHERE packet_id LIKE 'meshcoredb:%'
        GROUP BY packet_id
      )
"""

_DELETE_SQL = """
    DELETE FROM packets
    WHERE packet_id LIKE 'meshcoredb:%'
      AND rowid NOT IN (
        SELECT MIN(rowid) FROM packets
        WHERE packet_id LIKE 'meshcoredb:%'
        GROUP BY packet_id
      )
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", default=DB_PATH)
    parser.add_argument(
        "--apply", action="store_true",
        help="Actually delete the duplicate rows (default: dry run only).",
    )
    args = parser.parse_args()

    con = sqlite3.connect(args.db_path)
    try:
        dup_count = con.execute(_COUNT_SQL).fetchone()[0]
        if dup_count == 0:
            print("No duplicate meshcoredb: packet rows found.")
            return 0

        if not args.apply:
            print(
                f"Dry run: {dup_count} duplicate meshcoredb: packet row(s) "
                "would be removed. Re-run with --apply to actually delete."
            )
            return 0

        con.execute(_DELETE_SQL)
        con.commit()
        print(f"Removed {dup_count} duplicate meshcoredb: packet row(s).")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
