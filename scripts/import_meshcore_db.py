#!/usr/bin/env python3
"""Import historical MeshCore SQLite data into Meshpoint.

This script reads a ``meshcore.db`` archive and maps it into the current
Meshpoint schema in two ways:

- contacts / neighbours -> ``nodes``
- raw history rows -> synthetic ``packets`` rows so nothing is lost
- clean telemetry fields -> ``telemetry`` rows for the dashboard charts

It is intentionally conservative: only fields that fit Meshpoint's current
telemetry model are copied into the chartable telemetry table. Everything else
is preserved in packet ``decoded_payload`` JSON for later inspection.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
import tempfile
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_URL = "https://einstein.amsterdam/meshcore/meshcore.db"
#DEFAULT_DEST_DB = REPO_ROOT / "data" / "concentrator.db"
DEFAULT_DEST_DB = "/opt/meshpoint/data/concentrator.db"

_CONTACT_ROLE = {
    1: "CLIENT",
    2: "ROUTER",
    3: "CLIENT_MUTE",
    4: "REPEATER",
}

_NEIGHBOUR_ROLE = {
    0: None,
    1: "CLIENT",
    2: "REPEATER",
    3: "ROOMSERVER",
    4: "SENSOR",
}


def _iso_from_unix(value) -> str | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _slug(text: str) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", text.strip())
    return text.strip("_") or "unknown"


def _packets_payload(table: str, row: sqlite3.Row, node_id: str) -> dict:
    payload = dict(row)
    payload["meshcore_source_table"] = table
    payload["meshcore_node_id"] = node_id
    return payload


def _open_source_db(source: str) -> tuple[sqlite3.Connection, Path | None]:
    if source.startswith(("http://", "https://")):
        with urllib.request.urlopen(source, timeout=30) as response:
            with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
                tmp.write(response.read())
                tmp_path = Path(tmp.name)
        con = sqlite3.connect(tmp_path)
        con.row_factory = sqlite3.Row
        return con, tmp_path

    src_path = Path(source).expanduser()
    con = sqlite3.connect(src_path)
    con.row_factory = sqlite3.Row
    return con, None


def _telemetry_row_exists(cur: sqlite3.Cursor, sample: dict) -> bool:
    return cur.execute(
        """
        SELECT 1
        FROM telemetry
        WHERE node_id = ?
          AND timestamp = ?
          AND battery_level IS ?
          AND voltage IS ?
          AND temperature IS ?
          AND humidity IS ?
          AND barometric_pressure IS ?
          AND channel_utilization IS ?
          AND air_util_tx IS ?
          AND uptime_seconds IS ?
        LIMIT 1
        """,
        (
            sample["node_id"],
            sample["timestamp"],
            sample.get("battery_level"),
            sample.get("voltage"),
            sample.get("temperature"),
            sample.get("humidity"),
            sample.get("barometric_pressure"),
            sample.get("channel_utilization"),
            sample.get("air_util_tx"),
            sample.get("uptime_seconds"),
        ),
    ).fetchone() is not None


def _insert_telemetry(cur: sqlite3.Cursor, sample: dict) -> bool:
    if _telemetry_row_exists(cur, sample):
        return False
    cur.execute(
        """
        INSERT INTO telemetry (
            node_id, battery_level, voltage, temperature,
            humidity, barometric_pressure, channel_utilization,
            air_util_tx, uptime_seconds, timestamp
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            sample["node_id"],
            sample.get("battery_level"),
            sample.get("voltage"),
            sample.get("temperature"),
            sample.get("humidity"),
            sample.get("barometric_pressure"),
            sample.get("channel_utilization"),
            sample.get("air_util_tx"),
            sample.get("uptime_seconds"),
            sample["timestamp"],
        ),
    )
    return True


def _resolve_node_id(source: str, name_to_node_id: dict[str, str], prefix_map: dict[str, str]) -> str:
    key = (source or "").strip()
    if not key:
        return "unknown"

    lowered = key.lower()
    if lowered in name_to_node_id:
        return name_to_node_id[lowered]

    for prefix_len in (12, 8):
        prefix = lowered[:prefix_len]
        if prefix in prefix_map:
            return prefix_map[prefix]

    return _slug(key)


def _build_identity_maps(src: sqlite3.Connection) -> tuple[dict[str, str], dict[str, str]]:
    name_to_node_id: dict[str, str] = {}
    prefix_map: dict[str, str] = {}

    for row in src.execute("SELECT pubkey, name FROM contacts"):
        pubkey = (row["pubkey"] or "").strip().lower()
        name = (row["name"] or "").strip()
        if not pubkey or not name:
            continue
        node_id = pubkey[:12]
        prefix_map[pubkey[:12]] = node_id
        prefix_map[pubkey[:8]] = node_id
        name_to_node_id.setdefault(name.lower(), node_id)

    for row in src.execute("SELECT pubkey, name FROM neighbours"):
        pubkey = (row["pubkey"] or "").strip().lower()
        name = (row["name"] or "").strip()
        if not pubkey:
            continue
        node_id = prefix_map.get(pubkey[:12]) or prefix_map.get(pubkey[:8]) or pubkey[:12] or pubkey
        prefix_map.setdefault(pubkey[:12], node_id)
        prefix_map.setdefault(pubkey[:8], node_id)
        if name:
            name_to_node_id.setdefault(name.lower(), node_id)

    return name_to_node_id, prefix_map


def _import_nodes(
    src: sqlite3.Connection,
    dst: sqlite3.Connection,
    name_to_node_id: dict[str, str],
    prefix_map: dict[str, str],
) -> tuple[int, int]:
    cur = dst.cursor()
    upserted = skipped = 0

    def upsert(node_id: str, name: str, role: str | None, lat, lon, last_heard: str | None):
        nonlocal upserted, skipped
        if not name or not last_heard:
            skipped += 1
            return
        cur.execute(
            """
            INSERT INTO nodes
                (node_id, long_name, protocol, role, latitude, longitude,
                 last_heard, first_seen, packet_count)
            VALUES (?, ?, 'meshcore', ?, ?, ?, ?, ?, 0)
            ON CONFLICT(node_id) DO UPDATE SET
                role = excluded.role,
                long_name = CASE
                    WHEN excluded.last_heard > nodes.last_heard THEN excluded.long_name
                    ELSE nodes.long_name
                END,
                latitude = CASE
                    WHEN excluded.last_heard > nodes.last_heard THEN excluded.latitude
                    ELSE nodes.latitude
                END,
                longitude = CASE
                    WHEN excluded.last_heard > nodes.last_heard THEN excluded.longitude
                    ELSE nodes.longitude
                END,
                last_heard = CASE
                    WHEN excluded.last_heard > nodes.last_heard THEN excluded.last_heard
                    ELSE nodes.last_heard
                END
            """,
            (node_id, name, role, lat, lon, last_heard, last_heard),
        )
        upserted += 1

    for row in src.execute("SELECT * FROM contacts"):
        pubkey = (row["pubkey"] or "").strip().lower()
        name = (row["name"] or "").strip()
        if not pubkey or not name:
            skipped += 1
            continue
        node_id = pubkey[:12]
        role = _CONTACT_ROLE.get(row["type"], str(row["type"]) if row["type"] is not None else None)
        last_heard = _iso_from_unix(row["last_advert"] or row["lastmod"] or row["updated_at"])
        upsert(node_id, name, role, row["lat"], row["lon"], last_heard)

    for row in src.execute("SELECT * FROM neighbours"):
        pubkey = (row["pubkey"] or "").strip().lower()
        name = (row["name"] or "").strip()
        if not pubkey or not name:
            skipped += 1
            continue
        node_id = prefix_map.get(pubkey[:12]) or prefix_map.get(pubkey[:8]) or pubkey[:12] or pubkey
        role = _NEIGHBOUR_ROLE.get(row["type"], "REPEATER")
        last_heard = _iso_from_unix(row["last_advert"] or row["updated_at"])
        upsert(node_id, name, role, row["lat"], row["lon"], last_heard)

    dst.commit()
    return upserted, skipped


def _import_packets(
    src: sqlite3.Connection,
    dst: sqlite3.Connection,
    name_to_node_id: dict[str, str],
    prefix_map: dict[str, str],
    freq_mhz: float = 869.618,
    spreading_factor: int = 8,
    bandwidth_khz: float = 62.5,
) -> tuple[int, int]:
    cur = dst.cursor()
    cur.execute("DELETE FROM packets WHERE packet_id LIKE 'meshcoredb:%'")

    inserted = skipped = 0

    def insert_packet(packet_id: str, source: str, packet_type: str, ts_iso: str, payload: dict, snr=None, rssi=None):
        nonlocal inserted, skipped
        if not ts_iso:
            skipped += 1
            return
        # Stamp the companion's radio settings (freq/SF/BW) so these rows show
        # freq/SF in the dashboard like real captures -- same treatment as the
        # nb: rows in import_contacts.py. RSSI stays NULL unless the source
        # row carries one (status_history last_rssi): the archive only
        # records SNR for neighbour observations.
        cur.execute(
            """
            INSERT INTO packets (
                packet_id, source_id, destination_id, protocol,
                packet_type, hop_limit, hop_start, channel_hash,
                want_ack, via_mqtt, relay_node, decoded_payload, decrypted,
                rssi, snr, frequency_mhz, spreading_factor,
                bandwidth_khz, capture_source, timestamp
            ) VALUES (?, ?, 'ffff', 'meshcore', ?, 0, 0, 0, 0, 0, 0, ?, 0,
                     ?, ?, ?, ?, ?, 'meshcore_db_import', ?)
            """,
            (
                packet_id,
                source,
                packet_type,
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                rssi,
                snr,
                freq_mhz,
                spreading_factor,
                bandwidth_khz,
                ts_iso,
            ),
        )
        inserted += 1

    for row in src.execute("SELECT * FROM neighbour_history ORDER BY ts ASC, id ASC"):
        source = _resolve_node_id(row["pubkey"], name_to_node_id, prefix_map)
        ts_iso = _iso_from_unix(row["ts"])
        payload = _packets_payload("neighbour_history", row, source)
        packet_id = f"meshcoredb:neighbour:{_slug(source)}:{row['ts']}"
        insert_packet(packet_id, source, "neighbour_advert", ts_iso, payload, snr=row["snr"])

    for row in src.execute("SELECT * FROM telemetry_history ORDER BY ts ASC, id ASC"):
        source = _resolve_node_id(row["node"], name_to_node_id, prefix_map)
        ts_iso = _iso_from_unix(row["ts"])
        payload = _packets_payload("telemetry_history", row, source)
        packet_id = f"meshcoredb:telemetry:{_slug(source)}:{row['ts']}:{row['channel']}:{_slug(row['type'])}"
        insert_packet(packet_id, source, "telemetry", ts_iso, payload)

    for row in src.execute("SELECT * FROM status_history ORDER BY ts ASC, id ASC"):
        source = _resolve_node_id(row["node"], name_to_node_id, prefix_map)
        ts_iso = _iso_from_unix(row["ts"])
        payload = _packets_payload("status_history", row, source)
        packet_id = f"meshcoredb:status:{_slug(source)}:{row['ts']}:{_slug(row['name'])}"
        rssi = row["value"] if row["name"] == "last_rssi" else None
        snr = row["value"] if row["name"] == "last_snr" else None
        insert_packet(packet_id, source, "telemetry", ts_iso, payload, snr=snr, rssi=rssi)

    dst.commit()
    return inserted, skipped


def _import_telemetry_samples(
    src: sqlite3.Connection,
    dst: sqlite3.Connection,
    name_to_node_id: dict[str, str],
    prefix_map: dict[str, str],
    include_status_history: bool = True,
) -> tuple[int, int, dict[str, int]]:
    cur = dst.cursor()
    inserted = skipped = 0
    field_counts: dict[str, int] = defaultdict(int)
    temp_rank = {4: 0, 3: 1, 1: 2}
    best_temperatures: dict[tuple[str, str], tuple[int, dict, float | int]] = {}
    temp_candidates = 0

    def record(sample: dict, field_name: str, field_value):
        nonlocal inserted, skipped
        if field_value is None:
            skipped += 1
            return
        row = {
            "node_id": sample["node_id"],
            "timestamp": sample["timestamp"],
            "battery_level": None,
            "voltage": None,
            "temperature": None,
            "humidity": None,
            "barometric_pressure": None,
            "channel_utilization": None,
            "air_util_tx": None,
            "uptime_seconds": None,
        }
        row[field_name] = field_value
        if _insert_telemetry(cur, row):
            inserted += 1
            field_counts[field_name] += 1
        else:
            skipped += 1

    for row in src.execute("SELECT * FROM telemetry_history ORDER BY ts ASC, id ASC"):
        node_id = _resolve_node_id(row["node"], name_to_node_id, prefix_map)
        sample = {"node_id": node_id, "timestamp": _iso_from_unix(row["ts"])}
        channel = row["channel"]
        kind = row["type"]
        value = row["value"]

        if channel == 1 and kind == "voltage":
            record(sample, "voltage", value)
        elif channel == 3 and kind == "barometer":
            record(sample, "barometric_pressure", value)
        elif channel == 4 and kind == "humidity":
            record(sample, "humidity", value)
        elif kind == "temperature" and channel in temp_rank:
            temp_candidates += 1
            key = (sample["node_id"], sample["timestamp"])
            rank = temp_rank[channel]
            current = best_temperatures.get(key)
            if current is None or rank < current[0]:
                best_temperatures[key] = (rank, sample, value)
        else:
            skipped += 1

    for _rank, sample, value in best_temperatures.values():
        record(sample, "temperature", value)

    skipped += max(0, temp_candidates - len(best_temperatures))

    if include_status_history:
        for row in src.execute("SELECT * FROM status_history ORDER BY ts ASC, id ASC"):
            node_id = _resolve_node_id(row["node"], name_to_node_id, prefix_map)
            sample = {"node_id": node_id, "timestamp": _iso_from_unix(row["ts"])}
            name = row["name"]
            kind = row["type"]
            value = row["value"]

            if name == "bat" and kind == "voltage":
                record(sample, "voltage", value)
            elif name == "uptime" and kind == "duration":
                record(sample, "uptime_seconds", int(value) if value is not None else None)
            else:
                skipped += 1

    dst.commit()
    return inserted, skipped, dict(field_counts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-db",
        default=DEFAULT_SOURCE_URL,
        help=f"MeshCore archive URL or SQLite path (default: {DEFAULT_SOURCE_URL})",
    )
    parser.add_argument(
        "--dest-db",
        type=Path,
        default=DEFAULT_DEST_DB,
        help=f"Meshpoint SQLite database (default: {DEFAULT_DEST_DB})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="show what would be imported without writing anything",
    )
    parser.add_argument(
        "--telemetry-only",
        action="store_true",
        help="import only telemetry history rows and skip nodes / packet history",
    )
    parser.add_argument(
        "--contacts-only",
        action="store_true",
        help="import only contacts / neighbours and skip packet + telemetry history",
    )
    parser.add_argument("--freq", type=float, default=869.618,
                        help="Companion frequency in MHz stamped on history rows (default: 869.618)")
    parser.add_argument("--sf", type=int, default=8,
                        help="Companion spreading factor stamped on history rows (default: 8)")
    parser.add_argument("--bw", type=float, default=62.5,
                        help="Companion bandwidth in kHz stamped on history rows (default: 62.5)")
    args = parser.parse_args()

    if args.telemetry_only and args.contacts_only:
        print("ERROR: --telemetry-only and --contacts-only are mutually exclusive")
        return 1

    src, tmp_path = _open_source_db(args.source_db)
    try:
        name_to_node_id, prefix_map = _build_identity_maps(src)

        print(f"source : {args.source_db}")
        print(f"dest   : {args.dest_db}")
        print(f"dryrun : {args.dry_run}")
        print()

        contact_count = src.execute("SELECT COUNT(*) FROM contacts").fetchone()[0]
        neighbour_count = src.execute("SELECT COUNT(*) FROM neighbours").fetchone()[0]
        telemetry_hist_count = src.execute("SELECT COUNT(*) FROM telemetry_history").fetchone()[0]
        status_hist_count = src.execute("SELECT COUNT(*) FROM status_history").fetchone()[0]
        neighbour_hist_count = src.execute("SELECT COUNT(*) FROM neighbour_history").fetchone()[0]

        print(f"contacts          : {contact_count}")
        print(f"neighbours        : {neighbour_count}")
        print(f"telemetry_history  : {telemetry_hist_count}")
        print(f"status_history     : {status_hist_count}")
        print(f"neighbour_history  : {neighbour_hist_count}")
        print(f"telemetry_only    : {args.telemetry_only}")
        print(f"contacts_only     : {args.contacts_only}")

        if args.dry_run:
            print("\nDry run only. Re-run without --dry-run to write the import.")
            return 0

        if not args.dest_db.exists():
            print(f"ERROR: destination database not found: {args.dest_db}")
            return 1

        dst = sqlite3.connect(args.dest_db)
        dst.row_factory = sqlite3.Row
        try:
            if args.telemetry_only:
                nodes_inserted = nodes_skipped = 0
                packets_inserted = packets_skipped = 0
                telemetry_inserted, telemetry_skipped, field_counts = _import_telemetry_samples(
                    src,
                    dst,
                    name_to_node_id,
                    prefix_map,
                    include_status_history=not args.telemetry_only,
                )
            elif args.contacts_only:
                nodes_inserted, nodes_skipped = _import_nodes(src, dst, name_to_node_id, prefix_map)
                packets_inserted = packets_skipped = 0
                telemetry_inserted = telemetry_skipped = 0
                field_counts = {}
            else:
                nodes_inserted, nodes_skipped = _import_nodes(src, dst, name_to_node_id, prefix_map)
                packets_inserted, packets_skipped = _import_packets(
                    src, dst, name_to_node_id, prefix_map,
                    freq_mhz=args.freq, spreading_factor=args.sf, bandwidth_khz=args.bw,
                )
                telemetry_inserted, telemetry_skipped, field_counts = _import_telemetry_samples(
                    src,
                    dst,
                    name_to_node_id,
                    prefix_map,
                    include_status_history=True,
                )

            print()
            print(f"nodes upserted   : {nodes_inserted}")
            print(f"nodes skipped    : {nodes_skipped}")
            print(f"packets inserted : {packets_inserted}")
            print(f"packets skipped  : {packets_skipped}")
            print(f"telemetry rows   : {telemetry_inserted}")
            print(f"telemetry skip   : {telemetry_skipped}")
            if field_counts:
                print("mapped telemetry fields:")
                for field_name, count in sorted(field_counts.items()):
                    print(f"  {field_name:20s} {count}")
            print("\nDone.")
            return 0
        finally:
            dst.close()
    finally:
        src.close()
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())