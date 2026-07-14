#!/usr/bin/env python3
"""Relabel old bare "meshcore_usb" packet rows with their companion's label.

Packets captured before the per-companion capture_source fix (2026-07-14)
were all stored with the bare source name "meshcore_usb" regardless of
which companion heard them, so anything derived from those rows (the
Messages page's connection pills, per-source stats) shows a generic
"USB" instead of the real 433/868 label. The radio frequency was stored
correctly the whole time though, and each companion sits on its own
band -- so the old rows can be relabeled reliably by frequency.

The frequency -> label mapping is derived from the already-labeled rows
in the same database (e.g. meshcore_usb_433 rows all sit near 434 MHz),
not hardcoded, so it adapts to whatever labels/bands this box uses.

Dry-run by default; pass --apply to write.

Usage (on the Pi):
    python3 scripts/backfill_meshcore_capture_labels.py [--db PATH] [--apply]
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import defaultdict

DEFAULT_DB = "/opt/meshpoint/data/concentrator.db"
BARE = "meshcore_usb"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=DEFAULT_DB, help=f"database path (default: {DEFAULT_DB})")
    ap.add_argument("--apply", action="store_true", help="actually write (default: dry-run)")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # 1. Learn frequency -> label from rows that already carry a label.
    cur.execute(
        """SELECT capture_source, CAST(ROUND(frequency_mhz) AS INTEGER) AS f, COUNT(*) AS n
           FROM packets
           WHERE capture_source LIKE ? AND capture_source != ?
             AND frequency_mhz IS NOT NULL AND frequency_mhz > 0
           GROUP BY capture_source, f""",
        (BARE + "_%", BARE),
    )
    freq_labels: dict[int, set[str]] = defaultdict(set)
    for row in cur.fetchall():
        freq_labels[row["f"]].add(row["capture_source"])

    if not freq_labels:
        print("No labeled meshcore_usb_* rows found to learn from; nothing to do.")
        return 0

    collisions = {f: labels for f, labels in freq_labels.items() if len(labels) > 1}
    if collisions:
        print("REFUSING: two companions share a rounded frequency, mapping is ambiguous:")
        for f, labels in collisions.items():
            print(f"  {f} MHz -> {sorted(labels)}")
        return 1

    mapping = {f: labels.pop() for f, labels in freq_labels.items()}
    print("Learned frequency -> label mapping from labeled rows:")
    for f, label in sorted(mapping.items()):
        print(f"  ~{f} MHz -> {label}")

    # 2. Match bare rows against it.
    cur.execute(
        """SELECT CAST(ROUND(frequency_mhz) AS INTEGER) AS f, COUNT(*) AS n
           FROM packets
           WHERE capture_source = ?
           GROUP BY f""",
        (BARE,),
    )
    total_bare = 0
    plan: list[tuple[int, str, int]] = []
    unmatched: list[tuple[object, int]] = []
    for row in cur.fetchall():
        total_bare += row["n"]
        if row["f"] in mapping:
            plan.append((row["f"], mapping[row["f"]], row["n"]))
        else:
            unmatched.append((row["f"], row["n"]))

    print(f"\nBare '{BARE}' rows: {total_bare}")
    for f, label, n in plan:
        print(f"  {n} row(s) at ~{f} MHz -> {label}")
    for f, n in unmatched:
        print(f"  {n} row(s) at {f} MHz -> NO MATCH, left untouched")

    if not plan:
        print("Nothing to relabel.")
        return 0

    if not args.apply:
        print("\nDry-run only. Re-run with --apply to write.")
        return 0

    # 3. Apply.
    changed = 0
    for f, label, _n in plan:
        cur.execute(
            """UPDATE packets SET capture_source = ?
               WHERE capture_source = ?
                 AND CAST(ROUND(frequency_mhz) AS INTEGER) = ?""",
            (label, BARE, f),
        )
        changed += cur.rowcount
    conn.commit()
    print(f"\nRelabeled {changed} packet row(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
