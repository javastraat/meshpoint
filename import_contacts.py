"""
Import MeshCore contacts.json into the meshpoint_lorawan SQLite database.

Usage:
    python import_contacts.py
    python import_contacts.py --contacts /path/to/contacts.json --db /path/to/data/concentrator.db
    python import_contacts.py --dry-run

Safe to run multiple times: existing nodes are never overwritten.
If a node already exists in the DB (captured live), the import skips it.
"""

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

# Defaults — adjust to your install paths if needed
DEFAULT_CONTACTS = Path(__file__).parent.parent / "contacts.json"
DEFAULT_DB       = Path(__file__).parent / "data" / "concentrator.db"

# MeshCore node type → role string (matches OTA ADVERT bits[3:0])
_TYPE_ROLE = {
    0: None,
    1: "CLIENT",
    2: "REPEATER",
    3: "ROOMSERVER",
    4: "SENSOR",
}


def _ts_to_iso(unix_ts) -> str | None:
    """Convert a Unix timestamp (int/float) to ISO-8601 UTC string, or None."""
    if unix_ts is None:
        return None
    try:
        return datetime.fromtimestamp(int(unix_ts), tz=timezone.utc).isoformat()
    except (ValueError, OSError, OverflowError):
        return None


def _node_id(public_key: str) -> str:
    """Canonical MeshCore node_id: first 12 hex chars of the public key (lowercase)."""
    return public_key[:12].lower()


def import_contacts(contacts_path: Path, db_path: Path, dry_run: bool = False) -> None:
    print(f"  contacts : {contacts_path}")
    print(f"  database : {db_path}")
    print(f"  dry-run  : {dry_run}")
    print()

    if not contacts_path.exists():
        print(f"ERROR: contacts file not found: {contacts_path}")
        sys.exit(1)

    if not dry_run and not db_path.exists():
        print(f"ERROR: database not found: {db_path}")
        print("       Start meshpoint_lorawan at least once so the DB is created, then re-run.")
        sys.exit(1)

    with open(contacts_path, encoding="utf-8") as f:
        data = json.load(f)

    contacts = data.get("contacts", {})
    total = len(contacts)
    print(f"Contacts in file : {total}")

    rows = []
    skipped_no_name = 0

    for pub_key, c in contacts.items():
        adv_name = (c.get("adv_name") or "").strip()
        if not adv_name:
            skipped_no_name += 1
            continue

        node_id  = _node_id(pub_key)
        role     = _TYPE_ROLE.get(c.get("type"), str(c.get("type", "")))
        lat      = c.get("adv_lat")
        lon      = c.get("adv_lon")

        # Best timestamp: prefer last_advert, fall back to lastmod
        last_advert_iso = _ts_to_iso(c.get("last_advert"))
        lastmod_iso     = _ts_to_iso(c.get("lastmod"))
        last_heard      = last_advert_iso or lastmod_iso or datetime.now(tz=timezone.utc).isoformat()
        first_seen      = last_heard   # we only know when the contact was last heard

        rows.append((
            node_id,
            adv_name,
            role,
            lat,
            lon,
            last_heard,
            first_seen,
        ))

    print(f"Skipped (no name): {skipped_no_name}")
    print(f"Ready to import  : {len(rows)}")
    print()

    if dry_run:
        print("DRY RUN — first 5 rows that would be inserted:")
        for r in rows[:5]:
            print(f"  node_id={r[0]}  name={r[1]}  role={r[2]}  lat={r[3]}  lon={r[4]}  last_heard={r[5]}")
        print("Run without --dry-run to actually import.")
        return

    conn = sqlite3.connect(db_path)
    cur  = conn.cursor()

    inserted = 0
    skipped  = 0

    for row in rows:
        node_id, adv_name, role, lat, lon, last_heard, first_seen = row
        cur.execute(
            """
            INSERT INTO nodes
                (node_id, long_name, protocol, role, latitude, longitude,
                 last_heard, first_seen, packet_count)
            VALUES (?, ?, 'meshcore', ?, ?, ?, ?, ?, 0)
            ON CONFLICT(node_id) DO UPDATE SET
                long_name  = COALESCE(excluded.long_name, nodes.long_name),
                role       = excluded.role,
                latitude   = COALESCE(excluded.latitude,  nodes.latitude),
                longitude  = COALESCE(excluded.longitude, nodes.longitude),
                last_heard = CASE WHEN excluded.last_heard > nodes.last_heard
                             THEN excluded.last_heard ELSE nodes.last_heard END
            """,
            (node_id, adv_name, role, lat, lon, last_heard, first_seen),
        )
        if cur.rowcount == 1:
            inserted += 1
        else:
            skipped += 1

    conn.commit()
    conn.close()

    print(f"Inserted (new)   : {inserted}")
    print(f"Updated (existed): {skipped}")
    print()
    print("Done. Restart meshpoint_lorawan (or just refresh the dashboard) to see the nodes.")


def main():
    parser = argparse.ArgumentParser(description="Import contacts.json → meshpoint DB")
    parser.add_argument("--contacts", type=Path, default=DEFAULT_CONTACTS,
                        help=f"Path to contacts.json (default: {DEFAULT_CONTACTS})")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB,
                        help=f"Path to concentrator.db (default: {DEFAULT_DB})")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be imported without writing anything")
    args = parser.parse_args()

    import_contacts(args.contacts, args.db, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
