"""Tests for NodeInfoBroadcaster lifecycle and resilience."""

from __future__ import annotations

import asyncio
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock

from src.transmit.nodeinfo_broadcaster import (
    INTERVAL_DISABLED,
    INTERVAL_MAX_MINUTES,
    INTERVAL_MIN_MINUTES,
    NodeInfoBroadcaster,
    clamp_interval_minutes,
)
from src.transmit.tx_service import SendResult


class _FakeTxService:
    """TxService stub recording calls to ``send_nodeinfo``."""

    def __init__(self, *, results=None, raises=None):
        self.calls: list[dict] = []
        self._results = list(results or [])
        self._raises = list(raises or [])
        self.send_nodeinfo = AsyncMock(side_effect=self._dispatch)

    async def _dispatch(self, **kwargs):
        self.calls.append(kwargs)
        if self._raises:
            exc = self._raises.pop(0)
            if exc is not None:
                raise exc
        if self._results:
            return self._results.pop(0)
        return SendResult(
            success=True, packet_id="00000001",
            protocol="meshtastic", airtime_ms=10,
        )


def _ok() -> SendResult:
    return SendResult(
        success=True, packet_id="abc", protocol="meshtastic", airtime_ms=12
    )


def _fail(error: str) -> SendResult:
    return SendResult(success=False, protocol="meshtastic", error=error)


class TestNodeInfoBroadcasterLifecycle(unittest.IsolatedAsyncioTestCase):

    async def test_start_creates_task_and_is_running(self):
        tx = _FakeTxService()
        b = NodeInfoBroadcaster(
            tx, "Long", "SHRT",
            startup_delay_seconds=10_000,
            interval_seconds=10_000,
        )
        await b.start()
        self.assertTrue(b.is_running)
        await b.stop()
        self.assertFalse(b.is_running)

    async def test_double_start_is_idempotent(self):
        tx = _FakeTxService()
        b = NodeInfoBroadcaster(
            tx, "Long", "SHRT",
            startup_delay_seconds=10_000,
            interval_seconds=10_000,
        )
        await b.start()
        first_task = b._task
        await b.start()
        self.assertIs(b._task, first_task)
        await b.stop()

    async def test_stop_without_start_is_safe(self):
        tx = _FakeTxService()
        b = NodeInfoBroadcaster(tx, "Long", "SHRT")
        await b.stop()
        self.assertFalse(b.is_running)

    async def test_startup_delay_is_honored(self):
        tx = _FakeTxService(results=[_ok()])
        b = NodeInfoBroadcaster(
            tx, "Long", "SHRT",
            startup_delay_seconds=0,
            interval_seconds=10_000,
        )
        await b.start()
        await asyncio.sleep(0.05)
        await b.stop()
        self.assertEqual(len(tx.calls), 1)

    async def test_interval_runs_multiple_broadcasts(self):
        tx = _FakeTxService(results=[_ok(), _ok(), _ok()])
        # 1ms interval lets the loop fire several times in a 50ms window.
        # Note: floats are accepted for fast tests; production callers
        # always pass clamped int minutes via set_interval().
        b = NodeInfoBroadcaster(
            tx, "Long", "SHRT",
            startup_delay_seconds=0,
            interval_seconds=0.001,
        )
        await b.start()
        await asyncio.sleep(0.05)
        await b.stop()
        self.assertGreaterEqual(len(tx.calls), 2)

    async def test_loop_survives_send_exception(self):
        tx = _FakeTxService(
            results=[_ok(), _ok()],
            raises=[RuntimeError("boom"), None, None],
        )
        b = NodeInfoBroadcaster(
            tx, "Long", "SHRT",
            startup_delay_seconds=0,
            interval_seconds=0.001,
        )
        await b.start()
        await asyncio.sleep(0.05)
        await b.stop()
        self.assertGreaterEqual(len(tx.calls), 2)

    async def test_loop_survives_failed_send_result(self):
        tx = _FakeTxService(
            results=[_fail("Duty cycle limit reached"), _ok()]
        )
        b = NodeInfoBroadcaster(
            tx, "Long", "SHRT",
            startup_delay_seconds=0,
            interval_seconds=0.001,
        )
        await b.start()
        await asyncio.sleep(0.05)
        await b.stop()
        self.assertGreaterEqual(len(tx.calls), 2)

    async def test_passes_long_and_short_name(self):
        tx = _FakeTxService(results=[_ok()])
        b = NodeInfoBroadcaster(
            tx, "MyMeshpoint", "MMP1",
            startup_delay_seconds=0,
            interval_seconds=10_000,
        )
        await b.start()
        await asyncio.sleep(0.05)
        await b.stop()
        self.assertEqual(tx.calls[0]["long_name"], "MyMeshpoint")
        self.assertEqual(tx.calls[0]["short_name"], "MMP1")

    async def test_default_hw_model_is_portduino(self):
        """v0.6.7 shipped PRIVATE_HW which renders as 'Private' on community maps."""
        from src.transmit.tx_service import HW_MODEL_PORTDUINO
        tx = _FakeTxService(results=[_ok()])
        b = NodeInfoBroadcaster(
            tx, "Long", "SHRT",
            startup_delay_seconds=0,
            interval_seconds=10_000,
        )
        await b.start()
        await asyncio.sleep(0.05)
        await b.stop()
        self.assertEqual(tx.calls[0]["hw_model"], HW_MODEL_PORTDUINO)
        self.assertEqual(tx.calls[0]["hw_model"], 37)

    async def test_hw_model_override_respected(self):
        from src.transmit.tx_service import HW_MODEL_PRIVATE_HW
        tx = _FakeTxService(results=[_ok()])
        b = NodeInfoBroadcaster(
            tx, "Long", "SHRT",
            startup_delay_seconds=0,
            interval_seconds=10_000,
            hw_model=HW_MODEL_PRIVATE_HW,
        )
        await b.start()
        await asyncio.sleep(0.05)
        await b.stop()
        self.assertEqual(tx.calls[0]["hw_model"], HW_MODEL_PRIVATE_HW)


class TestNodeInfoBroadcasterTelemetry(unittest.IsolatedAsyncioTestCase):
    """Live timing properties consumed by the Radio tab countdown card."""

    async def test_unstarted_broadcaster_reports_no_timing(self):
        tx = _FakeTxService()
        b = NodeInfoBroadcaster(
            tx, "Long", "SHRT",
            startup_delay_seconds=60,
            interval_seconds=10_800,
        )
        self.assertIsNone(b.last_sent_at)
        self.assertIsNone(b.next_due_at)
        self.assertEqual(b.interval_seconds, 10_800)
        self.assertEqual(b.startup_delay_seconds, 60)

    async def test_next_due_uses_startup_delay_before_first_send(self):
        tx = _FakeTxService(results=[_ok()])
        b = NodeInfoBroadcaster(
            tx, "Long", "SHRT",
            startup_delay_seconds=10_000,
            interval_seconds=10_000,
        )
        await b.start()
        self.assertIsNotNone(b.next_due_at)
        self.assertIsNone(b.last_sent_at)
        delta = (b.next_due_at - b._schedule._started_at).total_seconds()
        self.assertAlmostEqual(delta, 10_000, delta=1)
        await b.stop()

    async def test_next_due_uses_interval_after_first_send(self):
        tx = _FakeTxService(results=[_ok()])
        b = NodeInfoBroadcaster(
            tx, "Long", "SHRT",
            startup_delay_seconds=0,
            interval_seconds=10_000,
        )
        await b.start()
        try:
            await asyncio.sleep(0.05)
            self.assertIsNotNone(b.last_sent_at)
            self.assertIsNotNone(b.next_due_at)
            delta = (b.next_due_at - b.last_sent_at).total_seconds()
            self.assertAlmostEqual(delta, 10_000, delta=1)
        finally:
            await b.stop()

    async def test_next_due_clears_after_stop(self):
        tx = _FakeTxService()
        b = NodeInfoBroadcaster(
            tx, "Long", "SHRT",
            startup_delay_seconds=10_000,
            interval_seconds=10_000,
        )
        await b.start()
        self.assertIsNotNone(b.next_due_at)
        await b.stop()
        self.assertIsNone(b.next_due_at)

    async def test_next_due_is_none_when_paused(self):
        """interval=0 (paused) -> no scheduled broadcast, so None.

        Returning ``last_sent_at + 0`` would be a past timestamp and
        the dashboard countdown would render 'broadcasting...' for a
        loop that's actually idle.
        """
        tx = _FakeTxService(results=[_ok()])
        b = NodeInfoBroadcaster(
            tx, "Long", "SHRT",
            startup_delay_seconds=0,
            interval_seconds=10_000,
        )
        await b.start()
        try:
            await asyncio.sleep(0.05)
            self.assertIsNotNone(b.last_sent_at)
            self.assertIsNotNone(b.next_due_at)
            b.set_interval(0)
            self.assertIsNone(b.next_due_at)
        finally:
            await b.stop()


class TestClampIntervalMinutes(unittest.TestCase):
    """Bounds enforcement for transmit.nodeinfo.interval_minutes.

    Documented contract: ``0`` is the disable sentinel and passes
    through unchanged. Negative values become 0. Otherwise the value
    is clamped to the supported range.
    """

    def test_zero_passes_through_as_disabled(self):
        self.assertEqual(clamp_interval_minutes(0), INTERVAL_DISABLED)

    def test_negative_clamps_to_disabled(self):
        self.assertEqual(clamp_interval_minutes(-1), INTERVAL_DISABLED)
        self.assertEqual(clamp_interval_minutes(-100), INTERVAL_DISABLED)

    def test_below_minimum_clamps_to_minimum(self):
        self.assertEqual(clamp_interval_minutes(1), INTERVAL_MIN_MINUTES)
        self.assertEqual(clamp_interval_minutes(4), INTERVAL_MIN_MINUTES)

    def test_minimum_passes_through(self):
        self.assertEqual(clamp_interval_minutes(5), INTERVAL_MIN_MINUTES)

    def test_default_passes_through(self):
        self.assertEqual(clamp_interval_minutes(180), 180)

    def test_maximum_passes_through(self):
        self.assertEqual(clamp_interval_minutes(1440), INTERVAL_MAX_MINUTES)

    def test_above_maximum_clamps_to_maximum(self):
        self.assertEqual(clamp_interval_minutes(1441), INTERVAL_MAX_MINUTES)
        self.assertEqual(clamp_interval_minutes(99999), INTERVAL_MAX_MINUTES)


class TestNodeInfoConfigDefaults(unittest.TestCase):
    """Defaults for the new NodeInfoConfig dataclass on TransmitConfig."""

    def test_defaults_match_documented_contract(self):
        from src.config import NodeInfoConfig, TransmitConfig

        ni = NodeInfoConfig()
        self.assertEqual(ni.interval_minutes, 180)
        self.assertEqual(ni.startup_delay_seconds, 60)

        tx = TransmitConfig()
        self.assertEqual(tx.nodeinfo.interval_minutes, 180)
        self.assertEqual(tx.nodeinfo.startup_delay_seconds, 60)

    def test_no_enabled_field(self):
        """Single-knob design: only interval_minutes + startup_delay_seconds."""
        from src.config import NodeInfoConfig

        ni = NodeInfoConfig()
        self.assertFalse(hasattr(ni, "enabled"))


class TestNodeInfoBroadcasterHotReload(unittest.IsolatedAsyncioTestCase):
    """``set_interval()`` hot-reloads the running broadcast loop.

    No service restart needed for interval changes when the broadcaster
    is alive (v0.7.1+). Setting ``0`` pauses the loop without stopping
    it; restoring to a non-zero value resumes within milliseconds.
    """

    def test_set_interval_updates_interval_seconds(self):
        tx = _FakeTxService()
        b = NodeInfoBroadcaster(
            tx, "Long", "SHRT",
            startup_delay_seconds=10_000,
            interval_seconds=10_000,
        )
        b.set_interval(30)
        self.assertEqual(b.interval_seconds, 30 * 60)

    def test_set_interval_clamps_value(self):
        tx = _FakeTxService()
        b = NodeInfoBroadcaster(
            tx, "Long", "SHRT", interval_seconds=10_000,
        )
        b.set_interval(99999)
        self.assertEqual(b.interval_seconds, INTERVAL_MAX_MINUTES * 60)
        b.set_interval(1)
        self.assertEqual(b.interval_seconds, INTERVAL_MIN_MINUTES * 60)
        b.set_interval(0)
        self.assertEqual(b.interval_seconds, 0)

    def test_set_interval_returns_clamped_value(self):
        tx = _FakeTxService()
        b = NodeInfoBroadcaster(
            tx, "Long", "SHRT", interval_seconds=10_000,
        )
        self.assertEqual(b.set_interval(99999), INTERVAL_MAX_MINUTES)
        self.assertEqual(b.set_interval(0), INTERVAL_DISABLED)
        self.assertEqual(b.set_interval(30), 30)

    async def test_set_interval_to_zero_pauses_loop(self):
        """interval=0 is the documented pause sentinel; no broadcasts."""
        tx = _FakeTxService(results=[_ok()] * 10)
        b = NodeInfoBroadcaster(
            tx, "Long", "SHRT",
            startup_delay_seconds=0,
            interval_seconds=10_000,
        )
        await b.start()
        try:
            await asyncio.sleep(0.05)
            initial_calls = len(tx.calls)
            self.assertGreaterEqual(initial_calls, 1)
            b.set_interval(0)
            await asyncio.sleep(0.1)
            self.assertEqual(len(tx.calls), initial_calls)
        finally:
            await b.stop()

    async def test_set_interval_resume_wakes_paused_loop(self):
        """set_interval(>0) on a paused loop should wake it within ms."""
        tx = _FakeTxService(results=[_ok()] * 10)
        b = NodeInfoBroadcaster(
            tx, "Long", "SHRT",
            startup_delay_seconds=0,
            interval_seconds=0,
        )
        await b.start()
        try:
            await asyncio.sleep(0.05)
            self.assertEqual(len(tx.calls), 0)
            b.set_interval(10_000)
            await asyncio.sleep(0.05)
            self.assertGreaterEqual(len(tx.calls), 1)
        finally:
            await b.stop()

    async def test_set_interval_shorter_fires_immediately_when_overdue(self):
        """If new interval makes the next broadcast overdue, fire ASAP."""
        tx = _FakeTxService(results=[_ok()] * 10)
        b = NodeInfoBroadcaster(
            tx, "Long", "SHRT",
            startup_delay_seconds=0,
            interval_seconds=10_000,
        )
        await b.start()
        try:
            await asyncio.sleep(0.05)
            initial_calls = len(tx.calls)
            self.assertGreaterEqual(initial_calls, 1)
            # Bump interval to 1ms so last_sent + new_interval is in the past.
            b.set_interval(0)
            b._schedule._interval = 0.001
            b._schedule._interval_changed.set()
            await asyncio.sleep(0.05)
            self.assertGreater(len(tx.calls), initial_calls)
        finally:
            await b.stop()

    async def test_pause_during_startup_delay_transitions_cleanly(self):
        """set_interval(0) during the initial startup delay should
        wake the loop and transition to paused; no broadcasts fire."""
        tx = _FakeTxService(results=[_ok()] * 10)
        b = NodeInfoBroadcaster(
            tx, "Long", "SHRT",
            startup_delay_seconds=10,
            interval_seconds=10_000,
        )
        await b.start()
        try:
            await asyncio.sleep(0.02)
            self.assertEqual(len(tx.calls), 0)
            b.set_interval(0)
            await asyncio.sleep(0.05)
            self.assertEqual(len(tx.calls), 0)
            self.assertEqual(b.interval_seconds, 0)
        finally:
            await b.stop()

    async def test_resume_during_startup_delay_fires_immediately(self):
        """Pausing then resuming during the startup delay should not
        wait out the original startup deadline; it should fire ASAP."""
        tx = _FakeTxService(results=[_ok()] * 10)
        b = NodeInfoBroadcaster(
            tx, "Long", "SHRT",
            startup_delay_seconds=10,
            interval_seconds=10_000,
        )
        await b.start()
        try:
            await asyncio.sleep(0.02)
            b.set_interval(0)
            await asyncio.sleep(0.02)
            b.set_interval(5)
            await asyncio.sleep(0.05)
            self.assertGreaterEqual(len(tx.calls), 1)
        finally:
            await b.stop()

    async def test_change_interval_during_startup_delay_fires_immediately(self):
        """Changing the interval during startup delay (no pause) also
        wakes the loop and fires the first broadcast right away."""
        tx = _FakeTxService(results=[_ok()] * 10)
        b = NodeInfoBroadcaster(
            tx, "Long", "SHRT",
            startup_delay_seconds=10,
            interval_seconds=10_000,
        )
        await b.start()
        try:
            await asyncio.sleep(0.02)
            self.assertEqual(len(tx.calls), 0)
            b.set_interval(5)
            await asyncio.sleep(0.05)
            self.assertGreaterEqual(len(tx.calls), 1)
        finally:
            await b.stop()

    async def test_next_due_re_anchors_after_resume_in_startup_window(self):
        """next_due_at should reflect "imminent" after resume from
        pause during the pre-first-broadcast window, not the stale
        original startup deadline."""
        tx = _FakeTxService(results=[_ok()] * 10)
        b = NodeInfoBroadcaster(
            tx, "Long", "SHRT",
            startup_delay_seconds=10_000,
            interval_seconds=0,
        )
        await b.start()
        try:
            await asyncio.sleep(0.02)
            self.assertIsNone(b.next_due_at)
            b.set_interval(5)
            now = datetime.now(timezone.utc)
            self.assertIsNotNone(b.next_due_at)
            delta = (b.next_due_at - now).total_seconds()
            self.assertLess(abs(delta), 1.0)
        finally:
            await b.stop()


if __name__ == "__main__":
    unittest.main()
