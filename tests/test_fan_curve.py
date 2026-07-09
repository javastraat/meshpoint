import asyncio
import sys
import types
import unittest
from unittest.mock import patch

from src.hardware.fan_control import FanController, FanCurve


class FanCurveDutyForTest(unittest.TestCase):
    """Pure math -- no gpiozero/hardware needed, runs on Mac."""

    def setUp(self):
        self.curve = FanCurve(
            min_temp_c=45.0, max_temp_c=65.0, min_duty=0.35, hysteresis_c=5.0,
        )

    def test_below_off_threshold_is_off(self):
        self.assertEqual(self.curve.duty_for(30.0, currently_on=False), 0.0)
        self.assertEqual(self.curve.duty_for(30.0, currently_on=True), 0.0)

    def test_in_hysteresis_band_stays_off_if_not_already_on(self):
        # 42C is between (min-hyst)=40 and min=45 -- shouldn't kick on cold.
        self.assertEqual(self.curve.duty_for(42.0, currently_on=False), 0.0)

    def test_in_hysteresis_band_stays_on_if_already_running(self):
        self.assertEqual(self.curve.duty_for(42.0, currently_on=True), 0.35)

    def test_at_min_temp_is_min_duty(self):
        self.assertAlmostEqual(self.curve.duty_for(45.0, currently_on=False), 0.35)

    def test_at_max_temp_is_full_duty(self):
        self.assertEqual(self.curve.duty_for(65.0, currently_on=False), 1.0)

    def test_above_max_temp_stays_full_duty(self):
        self.assertEqual(self.curve.duty_for(80.0, currently_on=True), 1.0)

    def test_midpoint_ramps_linearly(self):
        # 55C is halfway between 45 and 65 -- duty halfway between 0.35 and 1.0.
        expected = 0.35 + 0.5 * (1.0 - 0.35)
        self.assertAlmostEqual(self.curve.duty_for(55.0, currently_on=True), expected)

    def test_exactly_at_off_threshold_is_off(self):
        self.assertEqual(self.curve.duty_for(40.0, currently_on=True), 0.0)


class FanControllerPinPwmUnsupportedTest(unittest.TestCase):
    """gpiozero's NativeFactory fallback (no lgpio/RPi.GPIO/pigpio) raises
    PinPWMUnsupported for pins outside its hardcoded per-board table, even
    on a real PWM-capable SoC pin repurposed by a custom carrier board.
    This must produce the specific actionable log line (pip install
    lgpio), not a generic exception dump -- verified with a fake
    gpiozero module so this runs without real hardware or the real
    gpiozero package installed.
    """

    def test_pin_pwm_unsupported_logs_actionable_hint(self):
        class FakePinPWMUnsupported(Exception):
            pass

        FakePinPWMUnsupported.__name__ = "PinPWMUnsupported"

        def _raise(*args, **kwargs):
            raise FakePinPWMUnsupported("PWM is not supported on pin GPIO13")

        fake_module = types.ModuleType("gpiozero")
        fake_module.PWMOutputDevice = _raise

        controller = FanController(pin=13, curve=FanCurve(), poll_interval_s=0.01)

        with patch.dict(sys.modules, {"gpiozero": fake_module}):
            with self.assertLogs("src.hardware.fan_control", level="ERROR") as captured:
                asyncio.run(controller.run())

        message = "\n".join(captured.output)
        self.assertIn("lgpio", message)
        self.assertNotIn("Traceback", message)


class FanControllerDutyTrackingTest(unittest.TestCase):
    """current_duty/previous_duty back the dashboard fan stat card --
    verified directly against _poll_once() rather than real asyncio
    timing, since it's the same logic run() calls every tick.
    """

    def setUp(self):
        class FakePWM:
            def __init__(self):
                self.value = 0.0

        self.pwm = FakePWM()
        self.controller = FanController(pin=13, curve=FanCurve())
        self.controller._pwm = self.pwm

    def _poll_at(self, temp_c: float) -> None:
        self.controller._temp_fn = lambda: temp_c
        self.controller._poll_once()

    def test_current_duty_tracks_latest_computed_value(self):
        self._poll_at(55.0)
        self.assertAlmostEqual(self.controller.current_duty, self.pwm.value)
        self.assertGreater(self.controller.current_duty, 0.0)

    def test_previous_duty_only_updates_on_a_change(self):
        self._poll_at(55.0)
        first_duty = self.controller.current_duty
        self._poll_at(60.0)
        second_duty = self.controller.current_duty
        self.assertEqual(self.controller.previous_duty, first_duty)
        self.assertNotEqual(second_duty, first_duty)

    def test_previous_duty_stays_put_across_unchanged_polls(self):
        self._poll_at(55.0)
        self._poll_at(60.0)
        prev_after_first_change = self.controller.previous_duty
        self._poll_at(60.0)  # same temp -> no change -> previous_duty untouched
        self.assertEqual(self.controller.previous_duty, prev_after_first_change)

    def test_missing_temp_reading_does_not_update_duty(self):
        self._poll_at(55.0)
        duty_before = self.controller.current_duty
        self.controller._temp_fn = lambda: None
        self.controller._poll_once()
        self.assertEqual(self.controller.current_duty, duty_before)


if __name__ == "__main__":
    unittest.main()
