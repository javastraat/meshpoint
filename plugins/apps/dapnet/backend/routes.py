"""DAPNET/POCSAG companion packet and capcode-roster endpoints.

Same shape as core's ``lorawan_routes.py`` (a one-way receive protocol
with no conversations) but keyed on ``capcode`` (DAPNET's addressing
unit) rather than ``dev_eui``/``dev_addr``, and with no RF signal
columns -- the companion board reports no RSSI/SNR over its JSON serial
protocol. Filters by the literal string ``protocol = 'dapnet'``, matching
whatever ``decode.adapt_event()`` stamps onto every Packet it builds
(``OpenProtocol("dapnet")`` -- see ``src.models.packet``), same as before
this was a plugin.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Query

from src.storage.packet_repository import PacketRepository

router = APIRouter(prefix="/api/dapnet", tags=["dapnet"])

_packet_repo: PacketRepository | None = None
_device_name: str = "meshpoint"


def init_routes(
    packet_repo: PacketRepository, device_name: str = "meshpoint",
) -> None:
    global _packet_repo, _device_name
    _packet_repo = packet_repo
    _device_name = device_name or "meshpoint"


def _decode_payload(row: dict) -> dict:
    raw = row.get("decoded_payload")
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


_PACKET_EXPORT_COLUMNS = [
    "timestamp", "packet_id", "capcode", "packet_type",
    "function", "text", "capture_source",
]


def _packet_flatten(row: dict) -> dict:
    payload = _decode_payload(row)
    row["capcode"] = row.get("destination_id")
    row["function"] = payload.get("function")
    row["text"] = payload.get("text", "")
    return row


@router.get("/export/packets.csv")
async def dapnet_packets_csv():
    """All captured DAPNET pages as a downloadable CSV."""
    if _packet_repo is None:
        raise HTTPException(503, "Routes not initialised")
    from src.api.csv_export import export_filename, streaming_csv, stream_query

    rows = stream_query(
        _packet_repo._db,
        """
        SELECT timestamp, packet_id, destination_id, packet_type,
               capture_source, decoded_payload
        FROM packets
        WHERE protocol = 'dapnet'
        ORDER BY timestamp DESC
        """,
        (),
        _PACKET_EXPORT_COLUMNS,
        transform=_packet_flatten,
    )
    return streaming_csv(
        _PACKET_EXPORT_COLUMNS, rows,
        export_filename(_device_name, "dapnet-packets"),
    )


_CAPCODE_EXPORT_COLUMNS = [
    "capcode", "packet_type", "last_text", "frame_count", "first_seen", "last_seen",
]


@router.get("/export/capcodes.csv")
async def dapnet_capcodes_csv():
    """One row per observed capcode, as CSV."""
    if _packet_repo is None:
        raise HTTPException(503, "Routes not initialised")
    from src.api.csv_export import export_filename, streaming_csv, stream_query

    rows = stream_query(
        _packet_repo._db,
        """
        SELECT p.destination_id AS capcode, p.packet_type,
               p.decoded_payload,
               agg.frame_count, agg.first_seen,
               p.timestamp AS last_seen
        FROM packets p
        JOIN (
            SELECT destination_id, COUNT(*) AS frame_count,
                   MIN(timestamp) AS first_seen, MAX(id) AS last_id
            FROM packets
            WHERE protocol = 'dapnet' AND destination_id != ''
            GROUP BY destination_id
        ) agg ON p.id = agg.last_id
        ORDER BY p.timestamp DESC
        """,
        (),
        _CAPCODE_EXPORT_COLUMNS,
        transform=lambda row: {**row, "last_text": _decode_payload(row).get("text", "")},
    )
    return streaming_csv(
        _CAPCODE_EXPORT_COLUMNS, rows,
        export_filename(_device_name, "dapnet-capcodes"),
    )


@router.get("/capcodes")
async def dapnet_capcodes():
    """One row per observed capcode -- last page's type/text + frame count + first/last seen."""
    if _packet_repo is None:
        raise HTTPException(503, "Routes not initialised")

    rows = await _packet_repo._db.fetch_all(
        """
        SELECT
            p.destination_id AS capcode,
            p.packet_type,
            p.decoded_payload,
            p.timestamp AS last_seen,
            agg.frame_count,
            agg.first_seen
        FROM packets p
        JOIN (
            SELECT
                destination_id,
                COUNT(*)       AS frame_count,
                MIN(timestamp) AS first_seen,
                MAX(id)        AS last_id
            FROM packets
            WHERE protocol = 'dapnet' AND destination_id != ''
            GROUP BY destination_id
        ) agg ON p.id = agg.last_id
        ORDER BY p.timestamp DESC
        """
    )

    capcodes = []
    for row in rows:
        payload = _decode_payload(row)
        capcodes.append({
            "capcode": row["capcode"],
            "packet_type": row["packet_type"],
            "frame_count": row["frame_count"],
            "first_seen": row["first_seen"],
            "last_seen": row["last_seen"],
            "last_text": payload.get("text", ""),
            "last_function": payload.get("function"),
        })
    return capcodes


@router.get("/packets")
async def dapnet_packets(
    limit: int = Query(100, ge=1, le=1000),
    capcode: str | None = Query(None, description="Only pages addressed to this capcode"),
):
    """Recent DAPNET pages, newest first.

    ``capcode``, when given, scopes this to one capcode's own message
    history -- the Capcodes tab's row-click detail popup uses this
    rather than a separate endpoint, same shape either way.
    """
    if _packet_repo is None:
        raise HTTPException(503, "Routes not initialised")

    if capcode:
        rows = await _packet_repo._db.fetch_all(
            """
            SELECT
                packet_id, source_id, destination_id, packet_type,
                capture_source, timestamp, decoded_payload, decrypted
            FROM packets
            WHERE protocol = 'dapnet' AND destination_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (capcode, limit),
        )
    else:
        rows = await _packet_repo._db.fetch_all(
            """
            SELECT
                packet_id, source_id, destination_id, packet_type,
                capture_source, timestamp, decoded_payload, decrypted
            FROM packets
            WHERE protocol = 'dapnet'
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (limit,),
        )

    packets = []
    for row in rows:
        payload = _decode_payload(row)
        packets.append({
            "packet_id": row.get("packet_id"),
            "protocol": "dapnet",
            "capcode": row["destination_id"],
            "source_id": row.get("source_id"),
            "packet_type": row["packet_type"],
            "capture_source": row.get("capture_source"),
            "timestamp": row["timestamp"],
            "function": payload.get("function"),
            "text": payload.get("text", ""),
            "decrypted": bool(row.get("decrypted")),
        })
    return packets


@router.get("/stats")
async def dapnet_stats():
    """Aggregate counts: total pages, unique capcodes, by packet type."""
    if _packet_repo is None:
        raise HTTPException(503, "Routes not initialised")

    totals = await _packet_repo._db.fetch_one(
        "SELECT COUNT(*) AS total, COUNT(DISTINCT destination_id) AS capcodes "
        "FROM packets WHERE protocol = 'dapnet'"
    )
    by_type = await _packet_repo._db.fetch_all(
        "SELECT packet_type, COUNT(*) AS cnt FROM packets "
        "WHERE protocol = 'dapnet' GROUP BY packet_type"
    )
    return {
        "total_packets": totals["total"] if totals else 0,
        "unique_capcodes": totals["capcodes"] if totals else 0,
        "by_type": {r["packet_type"]: r["cnt"] for r in by_type},
    }
