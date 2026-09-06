#!/usr/bin/env python3
"""Remove Reticulum/LXMF test data: messages and/or the peer roster.

Reticulum messages reuse the shared `messages` table (protocol
'reticulum'), and the peer roster lives in its own `reticulum_peers`
table (built from announces, keyed on destination_hash) -- see
src/storage/reticulum_peer_repository.py. Clears both by default;
--messages-only/--peers-only narrow it to one. Neither table is
referenced by anything else (no foreign keys pointing at reticulum_peers
from packets/nodes/telemetry), so wiping either is safe in isolation --
same "nothing orphaned elsewhere" property clear_dapnet_packets.py
documents for its own table.

Usage (on the Pi):
    # dry run - shows how many rows would be removed, writes nothing
    python3 clear_reticulum_packets.py

    # apply
    sudo python3 clear_reticulum_packets.py --apply

    # only one or the other
    python3 clear_reticulum_packets.py --messages-only --apply
    python3 clear_reticulum_packets.py --peers-only --apply
"""

import argparse
import sqlite3
import sys

DB_PATH = "/opt/meshpoint/data/concentrator.db"

_MESSAGES_WHERE = "protocol = 'reticulum'"
_MESSAGES_COUNT_SQL = f"SELECT COUNT(*) FROM messages WHERE {_MESSAGES_WHERE}"
_MESSAGES_DELETE_SQL = f"DELETE FROM messages WHERE {_MESSAGES_WHERE}"

_PEERS_COUNT_SQL = "SELECT COUNT(*) FROM reticulum_peers"
_PEERS_DELETE_SQL = "DELETE FROM reticulum_peers"


def _clear(con, label: str, count_sql: str, delete_sql: str, apply: bool) -> None:
    count = con.execute(count_sql).fetchone()[0]
    if count == 0:
        print(f"No {label} rows found.")
        return

    if not apply:
        print(
            f"Dry run: {count} {label} row(s) would be removed. "
            "Re-run with --apply to actually delete."
        )
        return

    con.execute(delete_sql)
    con.commit()
    print(f"Removed {count} {label} row(s).")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", default=DB_PATH)
    parser.add_argument(
        "--apply", action="store_true",
        help="Actually delete the rows (default: dry run only).",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--messages-only", action="store_true",
        help="Only clear reticulum messages, leave the peer roster alone.",
    )
    group.add_argument(
        "--peers-only", action="store_true",
        help="Only clear the peer roster, leave messages alone.",
    )
    args = parser.parse_args()

    con = sqlite3.connect(args.db_path)
    try:
        if not args.peers_only:
            _clear(con, "reticulum message", _MESSAGES_COUNT_SQL, _MESSAGES_DELETE_SQL, args.apply)
        if not args.messages_only:
            _clear(con, "reticulum_peers", _PEERS_COUNT_SQL, _PEERS_DELETE_SQL, args.apply)
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
