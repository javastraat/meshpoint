"""Received packets report the coding rate they were actually sent with.

Ported from upstream KMX415/meshpoint 536a9149 (#163). Before, every
concentrator packet carried SignalMetrics' default "4/8", so LongFast and
MeshCore traffic (4/5) showed the wrong coding rate in the dashboard.
"""

from __future__ import annotations

import unittest
from unittest.mock import Mock

from src.capture.concentrator_source import ConcentratorCaptureSource
from src.config import RadioConfig
from src.hal.sx1302_wrapper import BW_250KHZ, ConcentratorPacket


class TestConcentratorCodingRate(unittest.IsolatedAsyncioTestCase):
    async def _capture(self, coderate: int, radio: RadioConfig):
        packet = ConcentratorPacket(
            payload=b"synthetic-frame",
            frequency_hz=906875000,
            rssi=-80.0,
            snr=7.5,
            spreading_factor=11,
            bandwidth=BW_250KHZ,
            coderate=coderate,
            crc_ok=True,
            timestamp_us=12345,
        )
        source = ConcentratorCaptureSource(radio_config=radio)
        source._wrapper = Mock()
        source._wrapper.receive.return_value = [packet]
        source._running = True
        stream = source.packets()
        try:
            capture = await anext(stream)
        finally:
            source._running = False
            await stream.aclose()
        source._wrapper.send.assert_not_called()
        self.assertEqual(capture.payload, packet.payload)
        self.assertEqual(capture.signal.spreading_factor, 11)
        self.assertEqual(capture.signal.bandwidth_khz, 250.0)
        return capture

    async def test_received_rates_reach_dashboard_metadata(self):
        # Our own TX setting is 4/8 on purpose: the received rate must not follow it.
        radio = RadioConfig(frequency_mhz=906.875, coding_rate="4/8")
        for hal_rate, expected in ((1, "4/5"), (2, "4/6"), (3, "4/7"), (4, "4/8")):
            with self.subTest(hal_rate=hal_rate):
                capture = await self._capture(hal_rate, radio)
                self.assertEqual(capture.signal.to_dict()["coding_rate"], expected)
                self.assertEqual(radio.coding_rate, "4/8")

    async def test_undefined_rates_are_not_reported_as_4_8(self):
        for hal_rate in (0, 5, 255):
            with self.subTest(hal_rate=hal_rate):
                capture = await self._capture(hal_rate, RadioConfig(frequency_mhz=906.875))
                self.assertEqual(capture.signal.to_dict()["coding_rate"], "Unknown")


class TestStoredPacketCodingRate(unittest.TestCase):
    """The packets table doesn't store the coding rate, so a packet loaded from
    the database must not claim one (it used to show the "4/8" default)."""

    def test_row_without_coding_rate_reports_none(self):
        import sys
        import types

        try:  # the real one on the Pi; a stub only where it isn't installed
            import aiosqlite  # noqa: F401
        except ImportError:
            sys.modules["aiosqlite"] = types.ModuleType("aiosqlite")
        from src.storage.packet_repository import PacketRepository

        packet = PacketRepository._row_to_packet({
            "packet_id": "8c19aac7", "source_id": "916fdd16",
            "destination_id": "ffffffff", "protocol": "meshtastic",
            "packet_type": "position", "rssi": -18.0, "snr": 7.3,
            "frequency_mhz": 869.525, "spreading_factor": 11,
            "bandwidth_khz": 250.0, "timestamp": "2026-11-26T16:27:31+00:00",
        })
        self.assertEqual(packet.signal.to_dict()["coding_rate"], "")


class TestCodingRateColumn(unittest.IsolatedAsyncioTestCase):
    """Ours, not upstream's: the packets table stores the received coding
    rate, so a reloaded packet shows it too. Real aiosqlite round trip."""

    async def asyncSetUp(self):
        from src.storage.database import DatabaseManager
        from src.storage.packet_repository import PacketRepository

        self.db = DatabaseManager(":memory:")
        await self.db.connect()
        self.repo = PacketRepository(self.db)

    async def asyncTearDown(self):
        await self.db.disconnect()

    async def _store(self, packet_id, coding_rate, protocol="meshtastic", payload=None):
        from src.models.packet import Packet, PacketType, Protocol
        from src.models.signal import SignalMetrics

        await self.repo.insert(Packet(
            packet_id=packet_id, source_id="916fdd16", destination_id="ffffffff",
            protocol=Protocol(protocol), packet_type=PacketType.TEXT,
            decoded_payload=payload,
            signal=SignalMetrics(rssi=-80.0, snr=6.5, frequency_mhz=869.525,
                                 spreading_factor=11, bandwidth_khz=250.0,
                                 coding_rate=coding_rate),
        ))

    async def _loaded(self, packet_id):
        for packet in await self.repo.get_recent(limit=20):
            if packet.packet_id == packet_id:
                return packet.signal.to_dict()["coding_rate"]
        self.fail(f"{packet_id} not stored")

    async def test_received_rate_survives_a_reload(self):
        await self._store("longfast", "4/5")
        await self._store("longslow", "4/8")
        self.assertEqual(await self._loaded("longfast"), "4/5")
        self.assertEqual(await self._loaded("longslow"), "4/8")

    async def test_placeholders_are_stored_as_null(self):
        for i, value in enumerate(("Unknown", "N/A", "")):
            await self._store(f"p{i}", value)
        rows = await self.db.fetch_all("SELECT packet_id, coding_rate FROM packets")
        self.assertEqual({r["coding_rate"] for r in rows}, {None})
        for i in range(3):
            self.assertEqual(await self._loaded(f"p{i}"), "")

    async def test_meshcore_payload_still_used_for_rows_without_the_column_value(self):
        await self._store("mc", "N/A", protocol="meshcore",
                          payload={"meshcore_receiver": {"coding_rate": "4/7"}})
        self.assertEqual(await self._loaded("mc"), "4/7")


class TestCodingRateMigration(unittest.IsolatedAsyncioTestCase):
    """An existing database without the column gets it at startup and keeps
    its rows; those old rows show no CR."""

    async def test_old_table_gets_the_column(self):
        import os
        import sqlite3
        import tempfile

        from src.storage.database import DatabaseManager
        from src.storage.packet_repository import PacketRepository

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "old.db")
            con = sqlite3.connect(path)
            con.execute(
                "CREATE TABLE packets (id INTEGER PRIMARY KEY AUTOINCREMENT, packet_id TEXT NOT NULL,"
                " source_id TEXT NOT NULL, destination_id TEXT NOT NULL, protocol TEXT NOT NULL,"
                " packet_type TEXT NOT NULL, hop_limit INTEGER DEFAULT 0, hop_start INTEGER DEFAULT 0,"
                " channel_hash INTEGER DEFAULT 0, want_ack INTEGER DEFAULT 0, via_mqtt INTEGER DEFAULT 0,"
                " relay_node INTEGER DEFAULT 0, decoded_payload TEXT, decrypted INTEGER DEFAULT 0,"
                " rssi REAL, snr REAL, frequency_mhz REAL, spreading_factor INTEGER, bandwidth_khz REAL,"
                " capture_source TEXT, timestamp TEXT NOT NULL)"
            )
            con.execute(
                "INSERT INTO packets (packet_id, source_id, destination_id, protocol, packet_type,"
                " rssi, snr, timestamp) VALUES ('old', 'a', 'b', 'meshtastic', 'text', -90, 5,"
                " '2026-11-26T12:00:00+00:00')"
            )
            con.commit()
            con.close()

            db = DatabaseManager(path)
            await db.connect()
            try:
                cols = {r["name"] for r in await db.fetch_all("PRAGMA table_info(packets)")}
                self.assertIn("coding_rate", cols)
                packets = await PacketRepository(db).get_recent(limit=5)
                self.assertEqual([p.packet_id for p in packets], ["old"])
                self.assertEqual(packets[0].signal.to_dict()["coding_rate"], "")
            finally:
                await db.disconnect()


if __name__ == "__main__":
    unittest.main()
