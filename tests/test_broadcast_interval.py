"""Tests for shared broadcast interval scheduling."""

from __future__ import annotations

import asyncio
import unittest

from src.transmit.broadcast_interval import (
    INTERVAL_DISABLED,
    INTERVAL_MAX_MINUTES,
    INTERVAL_MIN_MINUTES,
    BroadcastIntervalController,
    clamp_interval_minutes,
)


class TestClampIntervalMinutes(unittest.TestCase):
    def test_zero_is_disabled(self):
        self.assertEqual(clamp_interval_minutes(0), INTERVAL_DISABLED)

    def test_negative_becomes_disabled(self):
        self.assertEqual(clamp_interval_minutes(-3), INTERVAL_DISABLED)

    def test_below_minimum_clamps(self):
        self.assertEqual(clamp_interval_minutes(4), INTERVAL_MIN_MINUTES)

    def test_above_maximum_clamps(self):
        self.assertEqual(clamp_interval_minutes(2000), INTERVAL_MAX_MINUTES)


class TestBroadcastIntervalController(unittest.IsolatedAsyncioTestCase):
    async def test_set_interval_wakes_paused_loop(self):
        state = BroadcastIntervalController(
            startup_delay_seconds=10_000,
            interval_seconds=0,
        )
        fired = asyncio.Event()

        async def on_due():
            fired.set()

        state.begin()
        task = asyncio.create_task(
            state.run_loop(
                is_running=lambda: True,
                on_due=on_due,
                loop_name="test",
            )
        )
        await asyncio.sleep(0.02)
        self.assertFalse(fired.is_set())
        state.set_interval(5)
        await asyncio.wait_for(fired.wait(), timeout=0.2)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def test_interval_zero_pauses_callbacks(self):
        state = BroadcastIntervalController(
            startup_delay_seconds=0,
            interval_seconds=1,
        )
        count = 0

        async def on_due():
            nonlocal count
            count += 1

        state.begin()
        task = asyncio.create_task(
            state.run_loop(
                is_running=lambda: True,
                on_due=on_due,
                loop_name="test",
            )
        )
        await asyncio.sleep(0.05)
        initial = count
        self.assertGreaterEqual(initial, 1)
        state.set_interval(0)
        await asyncio.sleep(0.05)
        self.assertEqual(count, initial)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
