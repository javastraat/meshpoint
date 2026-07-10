"""
Import MeshCore contacts.json and neighbours.json into the meshpoint_lorawan SQLite database.

Usage:
    python import_contacts.py
    python import_contacts.py --contacts /path/to/contacts.json --db /path/to/data/concentrator.db
    python import_contacts.py --dry-run
    python import_contacts.py --skip-neighbours   # contacts only
    python import_contacts.py --skip-contacts     # neighbours only

Safe to run multiple times: existing nodes are updated, not duplicated.
Neighbours are matched against existing contacts by node_id prefix to avoid duplicates.
"""

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Defaults — adjust to your install paths if needed
DEFAULT_CONTACTS   = Path(__file__).parent / "contacts.json"
DEFAULT_NEIGHBOURS = Path(__file__).parent / "neighbours.json"
DEFAULT_DB         = Path("/opt/meshpoint/data/concentrator.db")
CONTACTS_URL       = "https://einstein.amsterdam/meshcore/contacts.json"
NEIGHBOURS_URL     = "https://einstein.amsterdam/meshcore/neighbours.json"


SERVICE_NAME = "meshpoint_lorawan"


def _service_active() -> bool:
    result = subprocess.run(
        ["systemctl", "is-active", "--quiet", SERVICE_NAME],
        capture_output=True,
    )
    return result.returncode == 0


def stop_service() -> bool:
    """Stop the service if running. Returns True if we stopped it (so we can restart)."""
    if not _service_active():
        return False
    print(f"Stopping {SERVICE_NAME} ...")
    subprocess.run(["systemctl", "stop", SERVICE_NAME], check=True)
    time.sleep(1)
    print(f"{SERVICE_NAME} stopped.")
    print()
    return True


def start_service() -> None:
    print(f"Starting {SERVICE_NAME} ...")
    subprocess.run(["systemctl", "start", SERVICE_NAME], check=True)
    print(f"{SERVICE_NAME} started.")
    print()


def backup_database(db_path: Path) -> None:
    """Create a timestamped backup of the database before importing."""
    if not db_path.exists():
        return
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_path = db_path.with_name(f"{db_path.stem}_backup_{ts}{db_path.suffix}")
    shutil.copy2(db_path, backup_path)
    print(f"Backup created : {backup_path}")
    print()


def fetch_json(url: str, dest: Path) -> None:
    """Remove stale file and download a fresh copy."""
    if dest.exists():
        dest.unlink()
        print(f"Removed old {dest.name}")
    print(f"Downloading {dest.name} from {url} ...")
    urllib.request.urlretrieve(url, dest)
    print(f"Saved to {dest}")
    print()


def fetch_contacts(contacts_path: Path) -> None:
    fetch_json(CONTACTS_URL, contacts_path)

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


def _clamp_future(iso_str: str | None) -> str | None:
    """Cap a timestamp at 'now'.

    Some MeshCore nodes run clocks minutes-to-hours ahead of real time, so
    their self-reported last_advert lands in the future. Left alone, the
    synthetic neighbour row sorts to the very top as if just heard. Clamp
    anything ahead of now (plus a small skew tolerance) back to now.
    """
    if not iso_str:
        return iso_str
    try:
        ts = datetime.fromisoformat(iso_str)
    except ValueError:
        return iso_str
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    now = datetime.now(tz=timezone.utc)
    if ts > now + timedelta(minutes=2):
        return now.isoformat()
    return iso_str


def _node_id(public_key: str) -> str:
    """Canonical MeshCore node_id: first 12 hex chars of the public key (lowercase)."""
    return public_key[:12].lower()


def import_contacts(contacts_path: Path, db_path: Path, dry_run: bool = False, no_fetch: bool = False) -> None:
    if not no_fetch:
        fetch_contacts(contacts_path)

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
        last_heard      = _clamp_future(
            last_advert_iso or lastmod_iso or datetime.now(tz=timezone.utc).isoformat()
        )
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

    backup_database(db_path)
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
                role       = excluded.role,
                long_name  = CASE WHEN excluded.last_heard > nodes.last_heard
                             THEN COALESCE(excluded.long_name, nodes.long_name) ELSE nodes.long_name END,
                latitude   = CASE WHEN excluded.last_heard > nodes.last_heard
                             THEN COALESCE(excluded.latitude,  nodes.latitude)  ELSE nodes.latitude  END,
                longitude  = CASE WHEN excluded.last_heard > nodes.last_heard
                             THEN COALESCE(excluded.longitude, nodes.longitude) ELSE nodes.longitude END,
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
    print(f"Skipped (existed): {skipped}")
    print()
    print("Done. Restart meshpoint_lorawan (or just refresh the dashboard) to see the nodes.")


def import_neighbours(
    neighbours_path: Path,
    db_path: Path,
    dry_run: bool = False,
    no_fetch: bool = False,
    freq_mhz: float = 869.618,
    spreading_factor: int = 8,
    bandwidth_khz: float = 62.5,
) -> None:
    if not no_fetch:
        fetch_json(NEIGHBOURS_URL, neighbours_path)

    print(f"  neighbours : {neighbours_path}")
    print(f"  database   : {db_path}")
    print(f"  dry-run    : {dry_run}")
    print()

    if not neighbours_path.exists():
        print(f"ERROR: neighbours file not found: {neighbours_path}")
        sys.exit(1)

    if not dry_run and not db_path.exists():
        print(f"ERROR: database not found: {db_path}")
        sys.exit(1)

    with open(neighbours_path, encoding="utf-8") as f:
        data = json.load(f)

    # secs_ago is a reliable RELATIVE measure ("heard N seconds before the file
    # was generated"), but we anchor it to our own trusted clock rather than the
    # file's "generated" field: that generator machine's clock has been observed
    # running ~2h fast, which would push every last_heard into the future. Since
    # the file is downloaded fresh immediately before import, "now" ~= the real
    # generation time, so (now - secs_ago) is immune to both the generator's and
    # the neighbour node's clock skew.
    anchor_dt = datetime.now(tz=timezone.utc)

    neighbours = data.get("neighbours", [])
    print(f"Neighbours in file : {len(neighbours)}")

    rows = []
    for n in neighbours:
        pubkey = (n.get("pubkey") or "").strip().lower()
        name   = (n.get("name") or "").strip()
        if not pubkey or not name:
            continue

        role = _TYPE_ROLE.get(n.get("type"), "REPEATER")
        lat  = n.get("lat")
        lon  = n.get("lon")
        snr  = n.get("snr")

        # Best timestamp: prefer 'now - secs_ago' (see anchor_dt note above),
        # which is immune to both the generator's and the neighbour's clock
        # skew. last_advert is the node's self-reported time and can be hours
        # off (fast OR stale years-old), so only use it when secs_ago is
        # missing. _clamp_future is a final safety net.
        last_heard = None
        if n.get("secs_ago") is not None:
            last_heard = (anchor_dt - timedelta(seconds=int(n["secs_ago"]))).isoformat()
        if not last_heard:
            last_heard = _ts_to_iso(n.get("last_advert"))
        last_heard = _clamp_future(last_heard or datetime.now(tz=timezone.utc).isoformat())

        rows.append((pubkey, name, role, lat, lon, snr, last_heard))

    print(f"Ready to import    : {len(rows)}")
    print()

    if dry_run:
        print("DRY RUN — first 5 rows that would be inserted/updated:")
        for r in rows[:5]:
            print(f"  pubkey={r[0]}  name={r[1]}  role={r[2]}  lat={r[3]}  lon={r[4]}  snr={r[5]}  last_heard={r[6]}")
        print("Run without --dry-run to actually import.")
        return

    conn = sqlite3.connect(db_path)
    cur  = conn.cursor()

    # Build a prefix map: first 8 chars of existing meshcore node_ids → full node_id
    cur.execute("SELECT node_id FROM nodes WHERE protocol = 'meshcore'")
    prefix_map: dict[str, str] = {}
    for (existing_id,) in cur.fetchall():
        prefix_map[existing_id[:8].lower()] = existing_id

    inserted = updated = skipped = 0

    for pubkey, name, role, lat, lon, snr, last_heard in rows:
        # Check if an existing contact starts with this 8-char pubkey
        existing_id = prefix_map.get(pubkey)
        node_id = existing_id if existing_id else pubkey

        cur.execute(
            """
            INSERT INTO nodes
                (node_id, long_name, protocol, role, latitude, longitude,
                 last_heard, first_seen, packet_count)
            VALUES (?, ?, 'meshcore', ?, ?, ?, ?, ?, 0)
            ON CONFLICT(node_id) DO UPDATE SET
                role       = excluded.role,
                long_name  = COALESCE(excluded.long_name, nodes.long_name),
                latitude   = COALESCE(excluded.latitude,  nodes.latitude),
                longitude  = COALESCE(excluded.longitude, nodes.longitude),
                -- Authoritative for neighbour-heard nodes: take the freshly
                -- computed (now - secs_ago) time, but never below a real
                -- captured packet. Plain "advance only" can't fix a value
                -- that was previously poisoned too-high (future / clamp-to-now).
                last_heard = MAX(
                    excluded.last_heard,
                    COALESCE(
                        (SELECT MAX(p.timestamp) FROM packets p
                          WHERE p.source_id = nodes.node_id
                            AND p.packet_id NOT LIKE 'nb:%'),
                        excluded.last_heard
                    )
                )
            """,
            (node_id, name, role, lat, lon, last_heard, last_heard),
        )

        if existing_id:
            updated += 1
        elif cur.lastrowid:
            inserted += 1
        else:
            skipped += 1

        # Insert a synthetic packet to carry the SNR so signal shows in panels.
        # Delete any previous synthetic packet for this node first (packets table
        # has no UNIQUE on packet_id, so INSERT OR IGNORE would always insert).
        # Stamp the companion's radio settings (freq/SF/BW) so these rows show
        # freq/SF in the dashboard like real captures -- otherwise they render
        # blank and each re-import undoes any one-time backfill.
        if snr is not None:
            cur.execute("DELETE FROM packets WHERE packet_id LIKE ?", (f"nb:{node_id}:%",))
            cur.execute(
                """
                INSERT INTO packets
                    (packet_id, source_id, destination_id, protocol, packet_type,
                     snr, frequency_mhz, spreading_factor, bandwidth_khz, timestamp)
                VALUES (?, ?, 'broadcast', 'meshcore', 'neighbour_advert', ?, ?, ?, ?, ?)
                """,
                (f"nb:{node_id}:{last_heard}", node_id, snr,
                 freq_mhz, spreading_factor, bandwidth_khz, last_heard),
            )

    conn.commit()
    conn.close()

    print(f"Inserted (new)            : {inserted}")
    print(f"Updated (matched contact) : {updated}")
    print(f"Skipped                   : {skipped}")
    print()
    print("Done. Refresh the dashboard to see the neighbours.")


def main():
    if os.geteuid() != 0:
        print("ERROR: please run with sudo.")
        sys.exit(1)

    parser = argparse.ArgumentParser(description="Import contacts.json + neighbours.json → meshpoint DB")
    parser.add_argument("--contacts", type=Path, default=DEFAULT_CONTACTS,
                        help=f"Path to contacts.json (default: {DEFAULT_CONTACTS})")
    parser.add_argument("--neighbours", type=Path, default=DEFAULT_NEIGHBOURS,
                        help=f"Path to neighbours.json (default: {DEFAULT_NEIGHBOURS})")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB,
                        help=f"Path to concentrator.db (default: {DEFAULT_DB})")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be imported without writing anything")
    parser.add_argument("--no-fetch", action="store_true",
                        help="Skip downloading fresh JSON files (use existing files)")
    parser.add_argument("--skip-contacts", action="store_true",
                        help="Skip importing contacts.json")
    parser.add_argument("--skip-neighbours", action="store_true",
                        help="Skip importing neighbours.json")
    parser.add_argument("--freq", type=float, default=869.618,
                        help="Companion frequency in MHz stamped on neighbour rows (default: 869.618)")
    parser.add_argument("--sf", type=int, default=8,
                        help="Companion spreading factor stamped on neighbour rows (default: 8)")
    parser.add_argument("--bw", type=float, default=62.5,
                        help="Companion bandwidth in kHz stamped on neighbour rows (default: 62.5)")
    args = parser.parse_args()

    we_stopped_service = False
    if not args.dry_run:
        we_stopped_service = stop_service()

    try:
        if not args.skip_contacts:
            print("=== Contacts ===")
            import_contacts(args.contacts, args.db, dry_run=args.dry_run, no_fetch=args.no_fetch)

        if not args.skip_neighbours:
            print("=== Neighbours ===")
            import_neighbours(args.neighbours, args.db, dry_run=args.dry_run,
                              no_fetch=args.no_fetch, freq_mhz=args.freq,
                              spreading_factor=args.sf, bandwidth_khz=args.bw)
    finally:
        if we_stopped_service:
            start_service()


if __name__ == "__main__":
    main()
