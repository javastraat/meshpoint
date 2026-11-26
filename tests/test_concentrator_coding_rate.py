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

        sys.modules.setdefault("aiosqlite", types.ModuleType("aiosqlite"))  # Mac dev box
        from src.storage.packet_repository import PacketRepository

        packet = PacketRepository._row_to_packet({
            "packet_id": "8c19aac7", "source_id": "916fdd16",
            "destination_id": "ffffffff", "protocol": "meshtastic",
            "packet_type": "position", "rssi": -18.0, "snr": 7.3,
            "frequency_mhz": 869.525, "spreading_factor": 11,
            "bandwidth_khz": 250.0, "timestamp": "2026-11-26T16:27:31+00:00",
        })
        self.assertEqual(packet.signal.to_dict()["coding_rate"], "")


if __name__ == "__main__":
    unittest.main()
