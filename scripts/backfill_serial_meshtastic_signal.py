#!/usr/bin/env python3
"""Backfill frequency/SF/bandwidth on old `serial` Meshtastic packet rows.

Before the connect-time radio handshake was added, every packet captured
via the `serial` Meshtastic USB source (capture_source `serial` or
`serial_<label>`, e.g. `serial_433`) was stamped with a hardcoded
frequency_mhz=906.875 (a US915 placeholder, never the stick's real
region) plus spreading_factor=11 and bandwidth_khz=250 (correct only for
the LongFast preset). Old rows can be corrected with the values the
handshake now reads for that specific device.

906.875 is not a value any other capture path in this codebase ever
produces, so it's a safe, unambiguous marker for "written by the old
buggy code" -- the --capture-source filter narrows it further to a
specific labelled device if you have more than one.

Usage (on the M1):
    # dry run -- shows what would change, writes nothing
    python3 backfill_serial_meshtastic_signal.py --capture-source serial_433

    # apply with this device's real region/preset values
    python3 backfill_serial_meshtastic_signal.py --capture-source serial_433 \\
        --freq 433.875 --sf 11 --bw 250 --apply
"""

import argparse
import sqlite3
import sys

DB_PATH = "/opt/meshpoint/data/concentrator.db"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DB_PATH, help=f"database path (default: {DB_PATH})")
    parser.add_argument(
        "--capture-source", default="serial%",
        help="exact capture_source (e.g. serial_433) or a LIKE pattern "
             "(default: serial%%, matches any serial device)",
    )
    parser.add_argument("--freq", type=float, default=433.875, help="frequency in MHz")
    parser.add_argument("--sf", type=int, default=11, help="spreading factor")
    parser.add_argument("--bw", type=float, default=250.0, help="bandwidth in kHz")
    parser.add_argument("--apply", action="store_true", help="write changes (default is dry run)")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    try:
        where = (
            "capture_source LIKE ? AND frequency_mhz = 906.875"
        )
        params = (args.capture_source,)

        total = conn.execute(
            "SELECT COUNT(*) FROM packets WHERE capture_source LIKE ?",
            params,
        ).fetchone()[0]
        candidates = conn.execute(
            f"SELECT COUNT(*) FROM packets WHERE {where}", params,
        ).fetchone()[0]

        print(f"rows matching capture_source '{args.capture_source}': {total}")
        print(f"rows with the old 906.875 placeholder:  {candidates}")

        if candidates == 0:
            print("Nothing to backfill.")
            return 0

        first, last = conn.execute(
            f"SELECT MIN(timestamp), MAX(timestamp) FROM packets WHERE {where}",
            params,
        ).fetchone()
        print(f"candidate time range:          {first} .. {last}")

        if not args.apply:
            print(
                f"\nDry run only. Re-run with --apply to set "
                f"freq={args.freq} MHz, SF{args.sf}, BW {args.bw} kHz "
                f"on those {candidates} rows."
            )
            return 0

        cur = conn.execute(
            f"UPDATE packets SET frequency_mhz = ?, spreading_factor = ?, "
            f"bandwidth_khz = ? WHERE {where}",
            (args.freq, args.sf, args.bw, args.capture_source),
        )
        conn.commit()
        print(f"\nUpdated {cur.rowcount} rows.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
