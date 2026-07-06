#!/usr/bin/env python3
"""Backfill frequency/SF/bandwidth on old MeshCore packet rows.

Before the capture-source fix, MeshCore packets were stored with
frequency_mhz=0, spreading_factor=0, bandwidth_khz=0 because the USB
companion's static radio config was never read at capture time. The
radio setting is constant per companion, so old rows can safely be
stamped with the companion's known values.

CAUTION: capture_source is stored as plain "meshcore_usb" for every
companion (no label), so rows from an 868 and a 433 companion are
indistinguishable. If more than one MeshCore companion has logged
packets, check the dry-run counts before applying.

Usage (on the M1):
    # dry run — shows what would change, writes nothing
    python3 backfill_meshcore_signal.py

    # apply with the 868 companion's current radio settings
    python3 backfill_meshcore_signal.py --apply --freq 869.618 --sf 8 --bw 62.5
"""

import argparse
import sqlite3
import sys

DB_PATH = "/opt/meshpoint/data/concentrator.db"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DB_PATH, help=f"database path (default: {DB_PATH})")
    parser.add_argument("--freq", type=float, default=869.618, help="frequency in MHz")
    parser.add_argument("--sf", type=int, default=8, help="spreading factor")
    parser.add_argument("--bw", type=float, default=62.5, help="bandwidth in kHz")
    parser.add_argument("--apply", action="store_true", help="write changes (default is dry run)")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    try:
        where = (
            "protocol = 'meshcore' "
            "AND (frequency_mhz IS NULL OR frequency_mhz = 0)"
        )

        total = conn.execute(
            "SELECT COUNT(*) FROM packets WHERE protocol = 'meshcore'"
        ).fetchone()[0]
        candidates = conn.execute(
            f"SELECT COUNT(*) FROM packets WHERE {where}"
        ).fetchone()[0]

        print(f"meshcore packets total:        {total}")
        print(f"rows with freq missing/zero:   {candidates}")

        if candidates == 0:
            print("Nothing to backfill.")
            return 0

        first, last = conn.execute(
            f"SELECT MIN(timestamp), MAX(timestamp) FROM packets WHERE {where}"
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
            (args.freq, args.sf, args.bw),
        )
        conn.commit()
        print(f"\nUpdated {cur.rowcount} rows.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
