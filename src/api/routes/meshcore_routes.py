"""MeshCore contact/node endpoints for the MeshCore dashboard tab."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query

from src.storage.node_repository import NodeRepository
from src.storage.packet_repository import PacketRepository
from src.storage.telemetry_repository import TelemetryRepository

router = APIRouter(prefix="/api/meshcore", tags=["meshcore"])

_packet_repo: PacketRepository | None = None
_node_repo: NodeRepository | None = None
_telemetry_repo: TelemetryRepository | None = None
_device_name: str = "meshpoint"
_repeater_poller = None


def init_routes(
    packet_repo: PacketRepository,
    node_repo: NodeRepository,
    device_name: str = "meshpoint",
    telemetry_repo: TelemetryRepository | None = None,
) -> None:
    global _packet_repo, _node_repo, _telemetry_repo, _device_name
    _packet_repo = packet_repo
    _node_repo = node_repo
    _telemetry_repo = telemetry_repo
    _device_name = device_name or "meshpoint"


def set_repeater_poller(poller) -> None:
    """Wire the repeater poller so /repeaters can serve its latest data."""
    global _repeater_poller
    _repeater_poller = poller


@router.get("/repeaters")
async def meshcore_repeaters():
    """Latest polled status/telemetry for configured MeshCore repeaters.

    ``available: false`` when repeater polling isn't enabled -- the page
    hides itself in that case. Each entry gets ``mesh_name`` -- the
    repeater's real advertised name from our contact roster -- so the
    card can show that instead of requiring a hand-typed config label.
    """
    if _repeater_poller is None:
        return {"available": False, "repeaters": []}

    names = await _repeater_names(list(_repeater_poller.latest.keys()))

    # Resolve neighbour pubkey prefixes against the roster too, one batch
    # query across all repeaters rather than N+1 -- lets the Repeaters
    # tab show a name instead of a bare prefix for neighbours we already
    # know from direct/relay reception elsewhere.
    neighbour_keys: set[str] = set()
    for entry in _repeater_poller.latest.values():
        nb_list = (entry.get("neighbours") or {}).get("neighbours")
        if isinstance(nb_list, list):
            neighbour_keys.update(
                n.get("pubkey") for n in nb_list if n.get("pubkey")
            )
    neighbour_names = await _repeater_names(list(neighbour_keys))

    reps = []
    for key, entry in _repeater_poller.latest.items():
        history = await _fetch_telemetry_history(key)
        out = dict(entry)
        nb_list = (entry.get("neighbours") or {}).get("neighbours")
        if isinstance(nb_list, list):
            out["neighbours"] = {
                **entry["neighbours"],
                "neighbours": [
                    {**n, "name": neighbour_names.get(n.get("pubkey"))}
                    for n in nb_list
                ],
            }
        farthest = await _farthest_neighbour_for_repeater(key)
        reps.append({
            **out,
            "mesh_name": names.get(key),
            "history": history,
            "farthest_neighbour": farthest,
        })
    return {"available": True, "repeaters": reps}


async def _farthest_neighbour_for_repeater(repeater_key: str) -> dict | None:
    """Farthest neighbour this specific repeater has reported, distance
    measured from THAT REPEATER's own position -- not Meshpoint's own
    antenna -- since a polled repeater can be a remote site with its own
    completely different local RF environment (see the poller-roster
    design notes). Reads the nb:<repeater_key>:<node_id>:<ts> packets
    RepeaterPoller._store_neighbour_reports() writes on each live poll.
    """
    if _node_repo is None:
        return None
    rep_row = await _node_repo._db.fetch_one(
        "SELECT latitude, longitude FROM nodes WHERE node_id = ?",
        (repeater_key,),
    )
    if not rep_row or rep_row.get("latitude") is None or rep_row.get("longitude") is None:
        return None
    rep_lat, rep_lon = rep_row["latitude"], rep_row["longitude"]

    rows = await _node_repo._db.fetch_all(
        """
        SELECT p.source_id, p.snr, n.long_name, n.latitude, n.longitude
        FROM packets p
        JOIN nodes n ON p.source_id = n.node_id
        WHERE p.packet_id LIKE ?
          AND n.latitude IS NOT NULL AND n.longitude IS NOT NULL
        ORDER BY p.timestamp DESC
        """,
        (f"nb:{repeater_key}:%",),
    )
    if not rows:
        return None

    from src.analytics.stats_reporter import _haversine_mi

    seen: set[str] = set()
    best = None
    for r in rows:
        node_id = r["source_id"]
        if node_id in seen:
            continue
        seen.add(node_id)
        dist_mi = _haversine_mi(rep_lat, rep_lon, r["latitude"], r["longitude"])
        if dist_mi < 0.1:
            continue
        if best is None or dist_mi > best["miles"]:
            best = {
                "miles": round(dist_mi, 1),
                "node_id": node_id,
                "node_name": r["long_name"] or node_id,
                "snr": round(r["snr"], 1) if r["snr"] is not None else None,
            }
    return best


async def _repeater_names(keys: list[str]) -> dict:
    """Real advertised names for the given node keys, from the roster."""
    if _node_repo is None or not keys:
        return {}
    placeholders = ",".join("?" for _ in keys)
    try:
        rows = await _node_repo._db.fetch_all(
            f"SELECT node_id, long_name, short_name FROM nodes "
            f"WHERE node_id IN ({placeholders})",
            tuple(keys),
        )
    except Exception:
        return {}
    out = {}
    for r in rows:
        name = (r.get("long_name") or r.get("short_name") or "").strip()
        if name:
            out[r["node_id"]] = name
    return out


async def _fetch_telemetry_history(node_id: str) -> dict:
    """Fetch min/max/avg telemetry for a repeater node, with date range."""
    if _telemetry_repo is None:
        return {}
    try:
        row = await _telemetry_repo._db.fetch_one(
            """
            SELECT
                MIN(timestamp) AS min_ts,
                MAX(timestamp) AS max_ts,
                COUNT(*) AS total_samples,
                MIN(voltage) AS min_voltage,
                MAX(voltage) AS max_voltage,
                AVG(voltage) AS avg_voltage,
                MIN(temperature) AS min_temperature,
                MAX(temperature) AS max_temperature,
                AVG(temperature) AS avg_temperature,
                MIN(humidity) AS min_humidity,
                MAX(humidity) AS max_humidity,
                AVG(humidity) AS avg_humidity
            FROM telemetry
            WHERE node_id = ?
            """,
            (node_id,),
        )
        if not row:
            return {}
        return {
            "min_ts": row.get("min_ts"),
            "max_ts": row.get("max_ts"),
            "total_samples": row.get("total_samples"),
            "voltage": {
                "min": row.get("min_voltage"),
                "max": row.get("max_voltage"),
                "avg": row.get("avg_voltage"),
            },
            "temperature": {
                "min": row.get("min_temperature"),
                "max": row.get("max_temperature"),
                "avg": row.get("avg_temperature"),
            },
            "humidity": {
                "min": row.get("min_humidity"),
                "max": row.get("max_humidity"),
                "avg": row.get("avg_humidity"),
            },
        }
    except Exception:
        return {}


_PACKET_EXPORT_COLUMNS = [
    "timestamp", "packet_id", "source_id", "source_name", "destination_id",
    "packet_type", "rssi", "snr", "frequency_mhz", "spreading_factor",
    "bandwidth_khz", "hops", "hop_start", "hop_limit", "capture_source",
    "decoded_payload",
]


@router.get("/export/packets.csv")
async def meshcore_packets_csv():
    """All captured MeshCore packets as a downloadable CSV."""
    if _packet_repo is None:
        raise HTTPException(503, "Routes not initialised")
    from src.api.csv_export import export_filename, streaming_csv, stream_query

    def _flatten(row):
        hs = row.get("hop_start") or 0
        hl = row.get("hop_limit") or 0
        row["hops"] = max(0, hs - hl) if hs else None
        return row

    rows = stream_query(
        _packet_repo._db,
        """
        SELECT p.timestamp, p.packet_id, p.source_id,
               COALESCE(NULLIF(n.long_name, ''), NULLIF(n.short_name, '')) AS source_name,
               p.destination_id, p.packet_type, p.rssi, p.snr,
               p.frequency_mhz, p.spreading_factor, p.bandwidth_khz,
               p.hop_start, p.hop_limit, p.capture_source, p.decoded_payload
        FROM packets p
        LEFT JOIN nodes n ON n.node_id = p.source_id
        WHERE p.protocol = 'meshcore'
        ORDER BY p.timestamp DESC
        """,
        (),
        _PACKET_EXPORT_COLUMNS,
        transform=_flatten,
    )
    return streaming_csv(
        _PACKET_EXPORT_COLUMNS, rows,
        export_filename(_device_name, "meshcore-packets"),
    )


_CONTACT_EXPORT_COLUMNS = [
    "node_id", "long_name", "short_name", "role", "latitude", "longitude",
    "first_seen", "last_heard", "packet_count", "latest_rssi", "latest_snr",
]


@router.get("/export/contacts.csv")
async def meshcore_contacts_csv():
    """All known MeshCore contacts as a downloadable CSV."""
    if _node_repo is None:
        raise HTTPException(503, "Routes not initialised")
    from src.api.csv_export import export_filename, streaming_csv, stream_query

    rows = stream_query(
        _node_repo._db,
        """
        SELECT n.node_id, n.long_name, n.short_name, n.role,
               n.latitude, n.longitude, n.first_seen, n.last_heard,
               n.packet_count,
               p.rssi AS latest_rssi, p.snr AS latest_snr
        FROM nodes n
        LEFT JOIN (
            SELECT source_id, rssi, snr,
                   ROW_NUMBER() OVER (PARTITION BY source_id ORDER BY timestamp DESC) AS rn
            FROM packets WHERE protocol = 'meshcore'
        ) p ON p.source_id = n.node_id AND p.rn = 1
        WHERE n.protocol = 'meshcore'
        ORDER BY n.last_heard DESC
        """,
        (),
        _CONTACT_EXPORT_COLUMNS,
    )
    return streaming_csv(
        _CONTACT_EXPORT_COLUMNS, rows,
        export_filename(_device_name, "meshcore-contacts"),
    )


@router.get("/nodes")
async def meshcore_nodes():
    """All known MeshCore nodes sorted by last_heard."""
    if _node_repo is None:
        raise HTTPException(503, "Routes not initialised")

    rows = await _node_repo._db.fetch_all(
        """
        SELECT n.node_id, n.long_name, n.short_name, n.role,
               n.latitude, n.longitude, n.last_heard, n.first_seen,
               n.packet_count, n.protocol,
               p.rssi AS latest_rssi, p.snr AS latest_snr
        FROM nodes n
        LEFT JOIN (
            SELECT source_id, rssi, snr,
                   ROW_NUMBER() OVER (PARTITION BY source_id ORDER BY timestamp DESC) AS rn
            FROM packets WHERE protocol = 'meshcore'
        ) p ON p.source_id = n.node_id AND p.rn = 1
        WHERE n.protocol = 'meshcore'
        ORDER BY n.last_heard DESC
        """
    )
    return [dict(r) for r in rows]


@router.get("/packets")
async def meshcore_packets(
    limit: int = Query(100, ge=1, le=500),
    include_imported: bool = Query(
        False,
        description=(
            "Include bulk-imported historical telemetry "
            "(capture_source='meshcore_db_import'). Off by default -- a "
            "single import_meshcore_db.py poll snapshot explodes into one "
            "row per sensor channel (10+ rows sharing one timestamp), which "
            "buries genuinely recent mesh activity in this feed. That data "
            "is still fully available via the repeater's own "
            "History/Trends cards and packet counts either way."
        ),
    ),
):
    """Recent MeshCore packets, newest first."""
    if _packet_repo is None:
        raise HTTPException(503, "Routes not initialised")

    import_filter = "" if include_imported else "AND capture_source != 'meshcore_db_import'"
    rows = await _packet_repo._db.fetch_all(
        f"""
        SELECT packet_id, source_id, destination_id, packet_type,
               hop_limit, hop_start, channel_hash, want_ack, relay_node,
               rssi, snr,
               frequency_mhz, spreading_factor, bandwidth_khz,
               decoded_payload, capture_source, timestamp
        FROM packets
        WHERE protocol = 'meshcore'
        {import_filter}
        ORDER BY timestamp DESC
        LIMIT ?
        """,
        (limit,),
    )

    result = []
    for row in rows:
        hop_start = row.get("hop_start") or 0
        hop_limit = row.get("hop_limit") or 0
        hops = max(0, hop_start - hop_limit) if hop_start else None
        result.append({
            "packet_id":        row["packet_id"],
            "protocol":         "meshcore",
            "source_id":        row["source_id"],
            "destination_id":   row["destination_id"],
            "packet_type":      row["packet_type"],
            "rssi":             row["rssi"],
            "snr":              row["snr"],
            "frequency_mhz":    row["frequency_mhz"],
            "spreading_factor": row["spreading_factor"],
            "bandwidth_khz":    row.get("bandwidth_khz"),
            "hops":             hops,
            "hop_start":        hop_start,
            "hop_limit":        hop_limit,
            "channel_hash":     row.get("channel_hash"),
            "want_ack":         bool(row.get("want_ack")),
            "relay_node":       row.get("relay_node"),
            "decoded_payload":  _parse_payload(row.get("decoded_payload")),
            "capture_source":   row.get("capture_source"),
            "timestamp":        row["timestamp"],
        })
    return result


def _parse_payload(raw) -> dict | None:
    """decoded_payload column is JSON text; the packet-detail modal
    wants the object."""
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except (ValueError, TypeError):
        return None


@router.get("/stats")
async def meshcore_stats():
    """Aggregate counts for the MeshCore tab."""
    if _packet_repo is None or _node_repo is None:
        raise HTTPException(503, "Routes not initialised")

    total_nodes = await _node_repo._db.fetch_one(
        "SELECT COUNT(*) AS cnt FROM nodes WHERE protocol = 'meshcore'"
    )

    cutoff_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    cutoff_7d  = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

    active_24h = await _node_repo._db.fetch_one(
        "SELECT COUNT(*) AS cnt FROM nodes WHERE protocol = 'meshcore' AND last_heard >= ?",
        (cutoff_24h,),
    )
    active_7d = await _node_repo._db.fetch_one(
        "SELECT COUNT(*) AS cnt FROM nodes WHERE protocol = 'meshcore' AND last_heard >= ?",
        (cutoff_7d,),
    )

    total_packets = await _packet_repo._db.fetch_one(
        "SELECT COUNT(*) AS cnt FROM packets WHERE protocol = 'meshcore'"
    )

    return {
        "total_nodes":   total_nodes["cnt"]   if total_nodes   else 0,
        "active_24h":    active_24h["cnt"]    if active_24h    else 0,
        "active_7d":     active_7d["cnt"]     if active_7d     else 0,
        "total_packets": total_packets["cnt"] if total_packets else 0,
    }
