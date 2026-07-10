"""LoRaWAN packet and device endpoints."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Query

from src.storage.packet_repository import PacketRepository

router = APIRouter(prefix="/api/lorawan", tags=["lorawan"])

_packet_repo: PacketRepository | None = None
_device_name: str = "meshpoint"


def init_routes(
    packet_repo: PacketRepository, device_name: str = "meshpoint",
) -> None:
    global _packet_repo, _device_name
    _packet_repo = packet_repo
    _device_name = device_name or "meshpoint"


_PACKET_EXPORT_COLUMNS = [
    "timestamp", "packet_id", "source_id", "packet_type",
    "dev_eui", "app_eui", "fcnt", "fport", "mic",
    "rssi", "snr", "frequency_mhz", "spreading_factor", "bandwidth_khz",
    "capture_source", "decoded_payload",
]


def _lorawan_flatten(row):
    """Lift dev_eui/fcnt/fport/mic out of the JSON payload into columns."""
    payload = {}
    raw = row.get("decoded_payload")
    if raw:
        try:
            payload = json.loads(raw)
        except (ValueError, TypeError):
            payload = {}
    row["dev_eui"] = payload.get("dev_eui")
    row["app_eui"] = payload.get("app_eui")
    row["fcnt"] = payload.get("fcnt")
    row["fport"] = payload.get("fport")
    row["mic"] = payload.get("mic")
    return row


@router.get("/export/packets.csv")
async def lorawan_packets_csv():
    """All captured LoRaWAN packets as a downloadable CSV.

    The LoRaWAN gold (DevEUI/FCnt/FPort/MIC) is flattened out of the
    decoded_payload JSON into its own columns so the export pivots
    straight into coverage/FCnt-gap analysis.
    """
    if _packet_repo is None:
        raise HTTPException(503, "Routes not initialised")
    from src.api.csv_export import export_filename, streaming_csv, stream_query

    rows = stream_query(
        _packet_repo._db,
        """
        SELECT timestamp, packet_id, source_id, packet_type,
               rssi, snr, frequency_mhz, spreading_factor, bandwidth_khz,
               capture_source, decoded_payload
        FROM packets
        WHERE protocol = 'lorawan'
        ORDER BY timestamp DESC
        """,
        (),
        _PACKET_EXPORT_COLUMNS,
        transform=_lorawan_flatten,
    )
    return streaming_csv(
        _PACKET_EXPORT_COLUMNS, rows,
        export_filename(_device_name, "lorawan-packets"),
    )


_DEVICE_EXPORT_COLUMNS = [
    "source_id", "packet_type", "frame_count", "first_seen", "last_seen",
    "last_rssi", "last_snr", "last_frequency_mhz", "last_sf",
]


@router.get("/export/devices.csv")
async def lorawan_devices_csv():
    """All LoRaWAN devices (one row per DevAddr/DevEUI) as CSV."""
    if _packet_repo is None:
        raise HTTPException(503, "Routes not initialised")
    from src.api.csv_export import export_filename, streaming_csv, stream_query

    rows = stream_query(
        _packet_repo._db,
        """
        SELECT p.source_id, p.packet_type,
               agg.frame_count, agg.first_seen,
               p.timestamp        AS last_seen,
               p.rssi             AS last_rssi,
               p.snr              AS last_snr,
               p.frequency_mhz    AS last_frequency_mhz,
               p.spreading_factor AS last_sf
        FROM packets p
        JOIN (
            SELECT source_id, COUNT(*) AS frame_count,
                   MIN(timestamp) AS first_seen, MAX(id) AS last_id
            FROM packets
            WHERE protocol = 'lorawan' AND source_id != ''
            GROUP BY source_id
        ) agg ON p.id = agg.last_id
        ORDER BY p.timestamp DESC
        """,
        (),
        _DEVICE_EXPORT_COLUMNS,
    )
    return streaming_csv(
        _DEVICE_EXPORT_COLUMNS, rows,
        export_filename(_device_name, "lorawan-devices"),
    )


@router.get("/devices")
async def lorawan_devices():
    """One row per observed LoRaWAN device (DevEUI or DevAddr).

    Returns last-packet signal metrics + total frame count + first/last seen.
    """
    if _packet_repo is None:
        raise HTTPException(503, "Routes not initialised")

    rows = await _packet_repo._db.fetch_all(
        """
        SELECT
            p.source_id,
            p.packet_type,
            p.rssi            AS last_rssi,
            p.snr             AS last_snr,
            p.frequency_mhz   AS last_frequency_mhz,
            p.spreading_factor AS last_sf,
            p.timestamp       AS last_seen,
            p.decoded_payload,
            agg.frame_count,
            agg.first_seen
        FROM packets p
        JOIN (
            SELECT
                source_id,
                COUNT(*)      AS frame_count,
                MIN(timestamp) AS first_seen,
                MAX(id)       AS last_id
            FROM packets
            WHERE protocol = 'lorawan' AND source_id != ''
            GROUP BY source_id
        ) agg ON p.id = agg.last_id
        ORDER BY p.timestamp DESC
        """
    )

    devices = []
    for row in rows:
        payload = {}
        if row.get("decoded_payload"):
            try:
                payload = json.loads(row["decoded_payload"])
            except (ValueError, TypeError):
                pass

        devices.append({
            "source_id": row["source_id"],
            "packet_type": row["packet_type"],
            "frame_count": row["frame_count"],
            "first_seen": row["first_seen"],
            "last_seen": row["last_seen"],
            "last_rssi": row["last_rssi"],
            "last_snr": row["last_snr"],
            "last_frequency_mhz": row["last_frequency_mhz"],
            "last_sf": row["last_sf"],
            "app_eui": payload.get("app_eui"),
            "dev_eui": payload.get("dev_eui"),
        })
    return devices


@router.get("/packets")
async def lorawan_packets(limit: int = Query(100, ge=1, le=1000)):
    """Recent LoRaWAN packets, newest first."""
    if _packet_repo is None:
        raise HTTPException(503, "Routes not initialised")

    rows = await _packet_repo._db.fetch_all(
        """
        SELECT
            packet_id, source_id, destination_id, packet_type,
            rssi, snr, frequency_mhz, spreading_factor, bandwidth_khz,
            capture_source, timestamp, decoded_payload, decrypted
        FROM packets
        WHERE protocol = 'lorawan'
        ORDER BY timestamp DESC
        LIMIT ?
        """,
        (limit,),
    )

    packets = []
    for row in rows:
        payload = {}
        if row.get("decoded_payload"):
            try:
                payload = json.loads(row["decoded_payload"])
            except (ValueError, TypeError):
                pass

        packets.append({
            "packet_id": row.get("packet_id"),
            "protocol": "lorawan",
            "source_id": row["source_id"],
            "destination_id": row.get("destination_id"),
            "packet_type": row["packet_type"],
            "rssi": row["rssi"],
            "snr": row["snr"],
            "frequency_mhz": row["frequency_mhz"],
            "spreading_factor": row["spreading_factor"],
            "bandwidth_khz": row["bandwidth_khz"],
            "capture_source": row.get("capture_source"),
            "timestamp": row["timestamp"],
            "decoded_payload": payload if isinstance(payload, dict) else None,
            "decrypted": bool(row.get("decrypted")),
            "app_eui": payload.get("app_eui"),
            "dev_eui": payload.get("dev_eui"),
            # Decoder stores these without underscores (fport/fcnt); the
            # response keeps the f_port/f_cnt names the frontend reads.
            "f_port": payload.get("fport"),
            "f_cnt": payload.get("fcnt"),
            "mic": payload.get("mic"),
        })
    return packets


@router.get("/stats")
async def lorawan_stats():
    """Aggregate counts: total packets, unique devices, by packet type."""
    if _packet_repo is None:
        raise HTTPException(503, "Routes not initialised")

    totals = await _packet_repo._db.fetch_one(
        "SELECT COUNT(*) AS total, COUNT(DISTINCT source_id) AS devices "
        "FROM packets WHERE protocol = 'lorawan'"
    )
    by_type = await _packet_repo._db.fetch_all(
        "SELECT packet_type, COUNT(*) AS cnt FROM packets "
        "WHERE protocol = 'lorawan' GROUP BY packet_type"
    )
    return {
        "total_packets": totals["total"] if totals else 0,
        "unique_devices": totals["devices"] if totals else 0,
        "by_type": {r["packet_type"]: r["cnt"] for r in by_type},
    }
