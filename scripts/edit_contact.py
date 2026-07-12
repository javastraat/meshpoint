#!/usr/bin/env python3
"""Interactively look up and edit a node's stored details.

Useful for correcting a node you know the real details for -- e.g. a
stale GPS fix on a node whose physical location you actually know.

Usage (on the M1):
    python3 edit_contact.py                # prompts for a node ID
    python3 edit_contact.py 09d406f4        # node ID given directly
    python3 edit_contact.py !09d406f4       # leading '!'/'0x' is stripped

Flow: looks the node up and shows its current data, asks whether to
edit it (n/Enter cancels), then prompts for each editable field with
the current DB value shown in brackets as the default -- press Enter
to keep it. Confirms the full set of changes before writing.
"""

import argparse
import sqlite3
import sys

DB_PATH = "/opt/meshpoint/data/concentrator.db"

# (column, prompt label, type) -- str fields empty-string-normalize to
# NULL; latitude/longitude/altitude parse as float, retrying on bad input.
EDITABLE_FIELDS = [
    ("long_name", "Long name", str),
    ("short_name", "Short name", str),
    ("latitude", "Latitude", float),
    ("longitude", "Longitude", float),
    ("altitude", "Altitude (m)", float),
]


def _normalize_node_id(raw: str) -> str:
    node_id = raw.strip().lower()
    if node_id.startswith("!"):
        node_id = node_id[1:]
    if node_id.startswith("0x"):
        node_id = node_id[2:]
    return node_id


def _prompt_field(label: str, current, value_type):
    default_display = "none" if current is None else current
    while True:
        raw = input(f"{label} [{default_display}]: ").strip()
        if not raw:
            return current
        if value_type is str:
            return raw
        try:
            return float(raw)
        except ValueError:
            print(f"  Not a number, try again (or press Enter to keep {default_display}).")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "node_id", nargs="?",
        help="hex node ID to edit, e.g. 09d406f4 (prompted if omitted)",
    )
    parser.add_argument("--db", default=DB_PATH, help=f"database path (default: {DB_PATH})")
    args = parser.parse_args()

    raw_id = args.node_id or input("Node ID: ").strip()
    if not raw_id:
        print("No node ID given.")
        return 1
    node_id = _normalize_node_id(raw_id)

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT node_id, long_name, short_name, hardware_model, protocol, role, "
            "latitude, longitude, altitude, last_heard, first_seen, packet_count "
            "FROM nodes WHERE node_id = ?", (node_id,),
        ).fetchone()

        if row is None:
            print(f"No node found with node_id={node_id!r}.")
            return 1

        print(f"\nnode_id:        {row['node_id']}")
        print(f"long_name:      {row['long_name']}")
        print(f"short_name:     {row['short_name']}")
        print(f"hardware_model: {row['hardware_model']}")
        print(f"protocol:       {row['protocol']}")
        print(f"role:           {row['role']}")
        print(f"latitude:       {row['latitude']}")
        print(f"longitude:      {row['longitude']}")
        print(f"altitude:       {row['altitude']}")
        print(f"last_heard:     {row['last_heard']}")
        print(f"first_seen:     {row['first_seen']}")
        print(f"packet_count:   {row['packet_count']}")

        answer = input("\nEdit this node? [y/N]: ").strip().lower()
        if answer != "y":
            print("Cancelled.")
            return 0

        print("\nPress Enter on any field to keep its current value.\n")
        new_values = {}
        for column, label, value_type in EDITABLE_FIELDS:
            new_values[column] = _prompt_field(label, row[column], value_type)

        changes = {
            col: (row[col], val)
            for col, val in new_values.items()
            if val != row[col]
        }
        if not changes:
            print("\nNo changes.")
            return 0

        print("\nChanges:")
        for col, (old, new) in changes.items():
            print(f"  {col}: {old!r} -> {new!r}")

        confirm = input("\nWrite these changes? [y/N]: ").strip().lower()
        if confirm != "y":
            print("Cancelled, nothing written.")
            return 0

        set_clause = ", ".join(f"{col} = ?" for col in new_values)
        conn.execute(
            f"UPDATE nodes SET {set_clause} WHERE node_id = ?",
            (*new_values.values(), node_id),
        )
        conn.commit()
        print(f"\nUpdated node {node_id}.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
