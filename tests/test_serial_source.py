"""Tests for SerialCaptureSource (Meshtastic USB capture).

Covers the T5 multi-stick support: per-device ``label`` -> ``name`` /
``capture_source`` tagging, and the pypubsub cross-talk guard needed
because meshtastic-python publishes every open SerialInterface's
packets on one process-wide topic ("meshtastic.receive").
"""

from __future__ import annotations

import asyncio
import unittest

from src.capture.serial_source import SerialCaptureSource


class SerialCaptureSourceNamingTest(unittest.TestCase):
    def test_unlabelled_name_is_plain_serial(self):
        source = SerialCaptureSource(port="/dev/ttyUSB0")
        self.assertEqual(source.name, "serial")

    def test_labelled_name_includes_label(self):
        source = SerialCaptureSource(port="/dev/ttyUSB0", label="433")
        self.assertEqual(source.name, "serial_433")

    def test_packet_capture_source_matches_name(self):
        source = SerialCaptureSource(port="/dev/ttyUSB1", label="868")
        raw = source._packet_to_raw_capture({"raw": "aabbccddeeff"})
        self.assertIsNotNone(raw)
        self.assertEqual(raw.capture_source, "serial_868")


class _FakeInterface:
    """Stand-in for meshtastic.serial_interface.SerialInterface."""


class SerialCaptureSourcePubsubGuardTest(unittest.IsolatedAsyncioTestCase):
    """Two SerialCaptureSource instances share one pypubsub topic.

    Without an identity check in ``_on_receive``, instance A's callback
    would also fire for instance B's packets (and vice versa), so a
    two-stick setup would duplicate and cross-attribute captures. This
    verifies the guard filters by interface identity.
    """

    async def test_ignores_packets_from_a_different_interface(self):
        source = SerialCaptureSource(port="/dev/ttyUSB0", label="433")
        source._running = True
        source._interface = _FakeInterface()
        other_interface = _FakeInterface()

        source._on_receive({"raw": "aabbcc"}, other_interface)

        self.assertTrue(source._queue.empty())

    async def test_accepts_packets_from_its_own_interface(self):
        source = SerialCaptureSource(port="/dev/ttyUSB0", label="433")
        source._running = True
        source._interface = _FakeInterface()

        source._on_receive({"raw": "aabbcc"}, source._interface)

        self.assertFalse(source._queue.empty())
        raw = await asyncio.wait_for(source._queue.get(), timeout=1.0)
        self.assertEqual(raw.capture_source, "serial_433")

    async def test_ignores_packets_when_not_running(self):
        source = SerialCaptureSource(port="/dev/ttyUSB0")
        source._interface = _FakeInterface()
        source._running = False

        source._on_receive({"raw": "aabbcc"}, source._interface)

        self.assertTrue(source._queue.empty())


if __name__ == "__main__":
    unittest.main()
