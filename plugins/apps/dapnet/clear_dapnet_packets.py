#!/usr/bin/env python3
"""Remove all DAPNET/POCSAG packet rows from the packets table.

DAPNET pages come from the pocsag_companion Heltec board (capture_source
'dapnet_heltec', protocol 'dapnet') -- one-way broadcast paging traffic,
not mesh nodes, so it never touches the nodes/telemetry tables (capcodes
like '2041152' are just text in packets.destination_id). Safe to
wipe wholesale: deleting these rows doesn't orphan anything elsewhere.

Usage (on the Pi):
    # dry run - shows how many rows would be removed, writes nothing
    python3 clear_dapnet_packets.py

    # apply
    sudo python3 clear_dapnet_packets.py --apply
"""

import argparse
import sqlite3
import sys

DB_PATH = "/opt/meshpoint/data/concentrator.db"

_WHERE = "protocol = 'dapnet'"
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
            print("No dapnet packet rows found.")
            return 0

        if not args.apply:
            print(
                f"Dry run: {count} dapnet packet row(s) would be removed. "
                "Re-run with --apply to actually delete."
            )
            return 0

        con.execute(_DELETE_SQL)
        con.commit()
        print(f"Removed {count} dapnet packet row(s).")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
