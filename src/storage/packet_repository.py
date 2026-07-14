from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from src.models.packet import Packet, PacketType, Protocol
from src.models.signal import SignalMetrics
from src.storage.database import DatabaseManager
from src.storage.time_bucket import bucket_seconds

logger = logging.getLogger(__name__)


class PacketRepository:
    """CRUD operations for captured mesh packets."""

    def __init__(self, db: DatabaseManager):
        self._db = db

    async def insert(self, packet: Packet) -> None:
        payload_json = (
            json.dumps(packet.decoded_payload)
            if packet.decoded_payload
            else None
        )
        await self._db.execute(
            """
            INSERT INTO packets (
                packet_id, source_id, destination_id, protocol,
                packet_type, hop_limit, hop_start, channel_hash,
                want_ack, via_mqtt, relay_node, decoded_payload, decrypted,
                rssi, snr, frequency_mhz, spreading_factor,
                bandwidth_khz, capture_source, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                packet.packet_id, packet.source_id,
                packet.destination_id, packet.protocol.value,
                packet.packet_type.value, packet.hop_limit,
                packet.hop_start, packet.channel_hash,
                int(packet.want_ack), int(packet.via_mqtt),
                packet.relay_node, payload_json, int(packet.decrypted),
                packet.signal.rssi if packet.signal else None,
                packet.signal.snr if packet.signal else None,
                packet.signal.frequency_mhz if packet.signal else None,
                packet.signal.spreading_factor if packet.signal else None,
                packet.signal.bandwidth_khz if packet.signal else None,
                packet.capture_source, packet.timestamp.isoformat(),
            ),
        )
        await self._db.commit()

    async def get_recent(self, limit: int = 100) -> list[Packet]:
        rows = await self._db.fetch_all(
            "SELECT * FROM packets ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        )
        return [self._row_to_packet(r) for r in rows]

    async def get_signal_history(
        self,
        source_id: str,
        limit: int = 500,
        hours: float | None = 24,
    ) -> list[dict]:
        """RSSI/SNR samples from any packet by this node, oldest-first.

        Bucketed into ``limit`` evenly-sized time windows the same way as
        TelemetryRepository.get_history() (see its docstring) -- keeps the
        returned row count bounded regardless of how long or dense the
        window is, instead of a plain LIMIT silently dropping the newest
        samples once history within the window exceeds it.
        """
        if hours is not None and hours > 0:
            since = (
                datetime.now(timezone.utc) - timedelta(hours=hours)
            ).isoformat()
            span_row = await self._db.fetch_one(
                "SELECT MIN(timestamp) AS lo, MAX(timestamp) AS hi FROM packets "
                "WHERE source_id = ? AND rssi IS NOT NULL AND timestamp >= ?",
                (source_id, since),
            )
            bucket_secs = bucket_seconds(span_row, limit, hours)
            rows = await self._db.fetch_all(
                """
                SELECT MIN(timestamp) AS timestamp, AVG(rssi) AS rssi, AVG(snr) AS snr
                FROM packets
                WHERE source_id = ? AND rssi IS NOT NULL AND timestamp >= ?
                GROUP BY CAST(strftime('%s', timestamp) AS INTEGER) / ?
                ORDER BY timestamp ASC
                LIMIT ?
                """,
                (source_id, since, bucket_secs, limit),
            )
        else:
            rows = await self._db.fetch_all(
                """
                SELECT timestamp, rssi, snr FROM packets
                WHERE source_id = ? AND rssi IS NOT NULL
                ORDER BY timestamp ASC
                LIMIT ?
                """,
                (source_id, limit),
            )
        return [
            {
                "timestamp": row["timestamp"],
                "rssi": row["rssi"],
                "snr": row.get("snr"),
            }
            for row in rows
        ]

    async def get_source_id_by_packet_id(self, packet_id: str) -> str:
        if not packet_id:
            return ""
        row = await self._db.fetch_one(
            "SELECT source_id FROM packets WHERE packet_id = ? LIMIT 1",
            (packet_id,),
        )
        return row["source_id"] if row else ""

    async def get_by_source(
        self, source_id: str, limit: int = 100
    ) -> list[Packet]:
        rows = await self._db.fetch_all(
            "SELECT * FROM packets WHERE source_id = ? ORDER BY timestamp DESC LIMIT ?",
            (source_id, limit),
        )
        return [self._row_to_packet(r) for r in rows]

    async def get_count(self) -> int:
        row = await self._db.fetch_one("SELECT COUNT(*) as cnt FROM packets")
        return row["cnt"] if row else 0

    async def get_count_since(self, since: datetime) -> int:
        row = await self._db.fetch_one(
            "SELECT COUNT(*) as cnt FROM packets WHERE timestamp >= ?",
            (since.isoformat(),),
        )
        return row["cnt"] if row else 0

    async def get_protocol_distribution(self) -> dict[str, int]:
        rows = await self._db.fetch_all(
            "SELECT protocol, COUNT(*) as cnt FROM packets GROUP BY protocol"
        )
        return {r["protocol"]: r["cnt"] for r in rows}

    async def get_protocol_distribution_by_source(
        self, protocol: str
    ) -> dict[str, int]:
        """Packet counts for one protocol, split by capture_source.

        Meshtastic can be received on two simultaneous radios (the
        concentrator's own channel and a USB serial stick, each on a
        different frequency/mesh) -- this lets callers show a per-radio
        breakdown instead of merging both into one total.
        """
        rows = await self._db.fetch_all(
            "SELECT capture_source, COUNT(*) as cnt FROM packets "
            "WHERE protocol = ? GROUP BY capture_source",
            (protocol,),
        )
        return {(r["capture_source"] or "unknown"): r["cnt"] for r in rows}

    async def get_distinct_node_count_by_source(
        self, protocol: str
    ) -> dict[str, int]:
        """Distinct source_id counts for one protocol, split by capture_source."""
        rows = await self._db.fetch_all(
            "SELECT capture_source, COUNT(DISTINCT source_id) as cnt FROM packets "
            "WHERE protocol = ? GROUP BY capture_source",
            (protocol,),
        )
        return {(r["capture_source"] or "unknown"): r["cnt"] for r in rows}

    async def insert_neighbour_report(
        self, repeater_key: str, node_id: str, snr: float | None, last_heard
    ) -> None:
        """Synthetic neighbour_advert packet from a repeater's own RF
        observation of ``node_id`` (RepeaterPoller). Mirrors
        import_contacts.py's ``nb:<node_id>:<timestamp>`` tagging, but
        scoped per-repeater (``nb:<repeater_key>:<node_id>:<timestamp>``)
        so the Repeaters page can attribute "farthest neighbour" to the
        specific repeater that reported it. Deletes any previous
        synthetic row for this (repeater, node) pair first, same as the
        original script -- packets has no UNIQUE constraint on
        packet_id, so re-polling would otherwise pile up duplicates.
        """
        last_heard_iso = last_heard.isoformat()
        packet_id = f"nb:{repeater_key}:{node_id}:{last_heard_iso}"
        await self._db.execute(
            "DELETE FROM packets WHERE packet_id LIKE ?",
            (f"nb:{repeater_key}:{node_id}:%",),
        )
        await self._db.execute(
            """
            INSERT INTO packets
                (packet_id, source_id, destination_id, protocol,
                 packet_type, snr, timestamp)
            VALUES (?, ?, 'broadcast', 'meshcore', 'neighbour_advert', ?, ?)
            """,
            (packet_id, node_id, snr, last_heard_iso),
        )
        await self._db.commit()

    async def get_type_distribution(self) -> dict[str, int]:
        rows = await self._db.fetch_all(
            "SELECT packet_type, COUNT(*) as cnt FROM packets GROUP BY packet_type"
        )
        return {r["packet_type"]: r["cnt"] for r in rows}

    async def cleanup_old(self, max_retained: int) -> int:
        total = await self.get_count()
        if total <= max_retained:
            return 0
        excess = total - max_retained
        await self._db.execute(
            "DELETE FROM packets WHERE id IN (SELECT id FROM packets ORDER BY timestamp ASC LIMIT ?)",
            (excess,),
        )
        await self._db.commit()
        logger.info("Cleaned up %d old packets", excess)
        return excess

    @staticmethod
    def _row_to_packet(row: dict) -> Packet:
        signal = None
        if row.get("rssi") is not None:
            signal = SignalMetrics(
                rssi=row["rssi"],
                snr=row.get("snr", 0.0),
                frequency_mhz=row.get("frequency_mhz", 906.875),
                spreading_factor=row.get("spreading_factor", 11),
                bandwidth_khz=row.get("bandwidth_khz", 250.0),
            )

        decoded = None
        if row.get("decoded_payload"):
            decoded = json.loads(row["decoded_payload"])

        return Packet(
            packet_id=row["packet_id"],
            source_id=row["source_id"],
            destination_id=row["destination_id"],
            protocol=Protocol(row["protocol"]),
            packet_type=PacketType(row["packet_type"]),
            hop_limit=row.get("hop_limit", 0),
            hop_start=row.get("hop_start", 0),
            channel_hash=row.get("channel_hash", 0),
            want_ack=bool(row.get("want_ack", 0)),
            via_mqtt=bool(row.get("via_mqtt", 0)),
            relay_node=row.get("relay_node", 0),
            decoded_payload=decoded,
            decrypted=bool(row.get("decrypted", 0)),
            signal=signal,
            capture_source=row.get("capture_source", "unknown"),
            timestamp=datetime.fromisoformat(row["timestamp"]),
        )
