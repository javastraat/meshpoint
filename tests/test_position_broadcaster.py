"""Tests for PositionBroadcaster lifecycle and hot-reload."""

from __future__ import annotations

import asyncio
import unittest

from src.transmit.position_broadcaster import PositionBroadcaster
from src.transmit.tx_service import SendResult


class _FakeTxService:
    def __init__(self, results=None):
        self.calls = 0
        self._results = list(results or [])

    async def send_position(self, lat, lon, alt):
        self.calls += 1
        if self._results:
            return self._results.pop(0)
        return SendResult(
            success=True, packet_id="pos1",
            protocol="meshtastic", airtime_ms=10,
        )


def _ok():
    return SendResult(success=True, packet_id="p", protocol="meshtastic", airtime_ms=5)


class TestPositionBroadcaster(unittest.IsolatedAsyncioTestCase):
    async def test_broadcasts_when_coords_available(self):
        tx = _FakeTxService(results=[_ok()])
        b = PositionBroadcaster(
            tx,
            interval_minutes=10_000,
            startup_delay_seconds=0,
            coords_provider=lambda: (40.0, -74.0, 10.0),
        )
        await b.start()
        await asyncio.sleep(0.05)
        await b.stop()
        self.assertGreaterEqual(tx.calls, 1)

    async def test_skips_when_no_coords(self):
        tx = _FakeTxService(results=[_ok()])
        b = PositionBroadcaster(
            tx,
            interval_minutes=10_000,
            startup_delay_seconds=0,
            coords_provider=lambda: None,
        )
        await b.start()
        await asyncio.sleep(0.05)
        await b.stop()
        self.assertEqual(tx.calls, 0)

    async def test_set_interval_zero_pauses(self):
        tx = _FakeTxService(results=[_ok(), _ok()])
        b = PositionBroadcaster(
            tx,
            interval_minutes=10_000,
            startup_delay_seconds=0,
            coords_provider=lambda: (40.0, -74.0, None),
        )
        await b.start()
        await asyncio.sleep(0.05)
        initial = tx.calls
        self.assertGreaterEqual(initial, 1)
        b.set_interval(0)
        await asyncio.sleep(0.05)
        self.assertEqual(tx.calls, initial)
        await b.stop()

    async def test_resume_from_paused_fires(self):
        tx = _FakeTxService(results=[_ok(), _ok()])
        b = PositionBroadcaster(
            tx,
            interval_minutes=0,
            startup_delay_seconds=0,
            coords_provider=lambda: (40.0, -74.0, None),
        )
        await b.start()
        await asyncio.sleep(0.02)
        self.assertEqual(tx.calls, 0)
        b.set_interval(10_000)
        await asyncio.sleep(0.05)
        self.assertGreaterEqual(tx.calls, 1)
        await b.stop()
