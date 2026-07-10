"""Button gesture state machine + advert sequence (Mac-runnable)."""

import asyncio
import unittest

from src.hardware.button_control import (
    ButtonController,
    WARN_AFTER_S,
    advert_all_radios,
)


class _FakeButton:
    def __init__(self):
        self.is_pressed = False


class _FakeLed:
    def __init__(self):
        self.flashes = []

    def flash(self, pattern, duration_s):
        self.flashes.append(pattern)


class ButtonGestureTest(unittest.TestCase):
    def setUp(self):
        self.shorts = 0
        self.longs = 0
        self.led = _FakeLed()
        self.ctl = ButtonController(
            pin=27,
            on_short_press=lambda: setattr(self, 'shorts', self.shorts + 1),
            on_long_press=lambda: setattr(self, 'longs', self.longs + 1),
            hold_time_s=3.0,
            advert_cooldown_s=30.0,
            led=self.led,
        )
        self.btn = _FakeButton()
        self.ctl._button = self.btn

    def _press(self, t):
        self.btn.is_pressed = True
        self.ctl._tick(t)

    def _release(self, t):
        self.btn.is_pressed = False
        self.ctl._tick(t)

    def test_starts_disarmed_when_held_at_boot(self):
        # Held straight through a restart: nothing may fire.
        self.btn.is_pressed = True
        self.ctl._tick(0.0)
        self.ctl._tick(5.0)   # would be a long press if armed
        self.assertEqual((self.shorts, self.longs), (0, 0))
        self._release(6.0)    # release arms it
        self._press(7.0)
        self._release(7.2)
        self.assertEqual((self.shorts, self.longs), (1, 0))

    def test_short_press_fires_on_release(self):
        self._release(0.0)    # arm
        self._press(1.0)
        self.assertEqual(self.shorts, 0)  # nothing until release
        self._release(1.3)
        self.assertEqual((self.shorts, self.longs), (1, 0))
        self.assertIn('fast', self.led.flashes)  # ack blink

    def test_second_press_in_cooldown_is_denied(self):
        self._release(0.0)
        self._press(1.0)
        self._release(1.2)
        self._press(5.0)
        self._release(5.2)
        self.assertEqual(self.shorts, 1)          # only the first fired
        self.assertIn('off', self.led.flashes)    # denied blink
        self._press(35.0)                          # cooldown (30s) expired
        self._release(35.2)
        self.assertEqual(self.shorts, 2)

    def test_hold_fires_restart_once_at_threshold(self):
        self._release(0.0)
        self._press(1.0)
        self.ctl._tick(2.0)   # 1.0s held: warning territory
        self.assertIn('fast', self.led.flashes)   # hold warning
        self.ctl._tick(4.1)   # 3.1s held
        self.assertEqual(self.longs, 1)
        self.ctl._tick(6.0)   # still held: must not re-fire
        self.assertEqual(self.longs, 1)
        self._release(7.0)    # release after long: no short press
        self.assertEqual(self.shorts, 0)

    def test_warning_blink_not_before_warn_threshold(self):
        self._release(0.0)
        self._press(1.0)
        self.ctl._tick(1.0 + WARN_AFTER_S / 2)
        self.assertEqual(self.led.flashes, [])    # too early to warn


class AdvertSequenceTest(unittest.TestCase):
    def test_steps_run_in_order_and_failures_dont_stop_the_rest(self):
        calls = []

        async def ok(name):
            calls.append(name)
            return 'ok'

        async def boom():
            calls.append('boom')
            raise RuntimeError('radio unplugged')

        steps = [
            ('a', lambda: ok('a')),
            ('b', boom),
            ('c', lambda: ok('c')),
        ]
        asyncio.run(advert_all_radios(steps, spacing_s=0))
        self.assertEqual(calls, ['a', 'boom', 'c'])


if __name__ == "__main__":
    unittest.main()
