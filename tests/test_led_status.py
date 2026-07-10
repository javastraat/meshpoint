"""Status LED state machine (Mac-runnable -- fake LED, no gpiozero)."""

import unittest

from src.capture.capture_coordinator import CaptureCoordinator
from src.hardware.led_status import FLICKER_SECS, LedController


class _FakeLed:
    def __init__(self):
        self.lit = False
        self.calls = []

    def on(self):
        self.lit = True
        self.calls.append("on")

    def off(self):
        self.lit = False
        self.calls.append("off")


class LedControllerTickTest(unittest.TestCase):
    def _controller(self, activity_blink=True):
        self.healthy = True
        self.count = 0
        ctl = LedController(
            pin=22,
            health_fn=lambda: self.healthy,
            packet_count_fn=lambda: self.count,
            activity_blink=activity_blink,
        )
        self.led = _FakeLed()
        ctl._led = self.led
        return ctl

    def test_steady_on_when_healthy(self):
        ctl = self._controller()
        ctl._tick(10.0)
        ctl._tick(10.1)
        self.assertTrue(self.led.lit)
        # No redundant re-driving of an already-lit pin.
        self.assertEqual(self.led.calls, ["on"])

    def test_packet_causes_a_brief_off_dip(self):
        ctl = self._controller()
        ctl._tick(10.0)
        self.count += 1
        ctl._tick(10.1)
        self.assertFalse(self.led.lit)
        ctl._tick(10.1 + FLICKER_SECS + 0.01)
        self.assertTrue(self.led.lit)

    def test_first_tick_does_not_flicker_for_preexisting_packets(self):
        self.healthy = True
        self.count = 500  # captured before the LED started
        ctl = self._controller()
        ctl._tick(10.0)
        self.assertTrue(self.led.lit)

    def test_no_dip_when_activity_blink_disabled(self):
        ctl = self._controller(activity_blink=False)
        ctl._tick(10.0)
        self.count += 1
        ctl._tick(10.1)
        self.assertTrue(self.led.lit)

    def test_degraded_blinks_at_one_hz(self):
        ctl = self._controller()
        self.healthy = False
        ctl._tick(20.1)   # 20.1 % 1.0 = 0.1 -> on half
        self.assertTrue(self.led.lit)
        ctl._tick(20.6)   # 0.6 -> off half
        self.assertFalse(self.led.lit)
        ctl._tick(21.1)   # on again
        self.assertTrue(self.led.lit)

    def test_packets_while_degraded_do_not_flicker_after_recovery(self):
        ctl = self._controller()
        self.healthy = False
        ctl._tick(20.1)
        self.count += 1
        ctl._tick(20.2)   # activity during degraded: no flicker armed
        self.healthy = True
        ctl._tick(20.3)
        self.assertTrue(self.led.lit)

    def test_recovery_returns_to_steady_on(self):
        ctl = self._controller()
        self.healthy = False
        ctl._tick(20.6)
        self.assertFalse(self.led.lit)
        self.healthy = True
        ctl._tick(20.7)
        self.assertTrue(self.led.lit)


class _FakeSource:
    def __init__(self, running):
        self._r = running
        self.name = "fake"

    @property
    def is_running(self):
        return self._r


class AllSourcesRunningTest(unittest.TestCase):
    def test_health_over_source_states(self):
        coord = CaptureCoordinator()
        self.assertTrue(coord.all_sources_running())  # vacuously healthy
        coord._sources.append(_FakeSource(True))
        self.assertTrue(coord.all_sources_running())
        coord._sources.append(_FakeSource(False))
        self.assertFalse(coord.all_sources_running())


if __name__ == "__main__":
    unittest.main()
