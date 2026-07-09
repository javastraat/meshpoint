"""Temperature-driven PWM fan control for the SenseCap M1's onboard fan.

GPIO 13 (confirmed live via scripts/test_gpio_hardware.py) is a genuine
hardware-PWM channel on the Pi 4 (BCM2711 PWM1), so the fan gets real
variable speed rather than a blunt on/off relay.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)


def read_cpu_temp_c() -> Optional[float]:
    """CPU temperature in Celsius from the thermal zone (Linux/RPi).

    Duplicated from system_metrics.py/executors.py rather than imported,
    matching this codebase's existing small-helper-duplication convention.
    """
    thermal = Path("/sys/class/thermal/thermal_zone0/temp")
    try:
        return int(thermal.read_text().strip()) / 1000.0
    except (OSError, ValueError):
        return None


@dataclass
class FanCurve:
    """Temperature -> PWM duty cycle (0.0-1.0), with hysteresis.

    Duty ramps linearly from ``min_duty`` at ``min_temp_c`` to 1.0 at
    ``max_temp_c``. Below ``min_temp_c - hysteresis_c`` the fan is fully
    off; the gap between "ramp starts" and "off" stops rapid on/off
    chatter right at the threshold. ``min_duty`` exists because most
    small fans stall below some duty rather than actually spinning
    slower -- jumping straight to that floor avoids a stalled motor
    drawing current without moving air.
    """

    min_temp_c: float = 45.0
    max_temp_c: float = 65.0
    min_duty: float = 0.35
    hysteresis_c: float = 5.0

    def duty_for(self, temp_c: float, currently_on: bool) -> float:
        off_threshold = self.min_temp_c - self.hysteresis_c
        if temp_c <= off_threshold:
            return 0.0
        if not currently_on and temp_c < self.min_temp_c:
            return 0.0
        if temp_c >= self.max_temp_c:
            return 1.0
        if temp_c <= self.min_temp_c:
            return self.min_duty
        span = self.max_temp_c - self.min_temp_c
        frac = (temp_c - self.min_temp_c) / span
        return self.min_duty + frac * (1.0 - self.min_duty)


class FanController:
    """Polls CPU temperature and drives a PWM fan pin accordingly.

    Runs for the lifetime of the FastAPI app via ``run()``, cancelled
    cleanly on shutdown -- same lifecycle pattern as
    ``_noise_floor_emitter_loop`` in api/server.py.
    """

    def __init__(
        self,
        pin: int,
        curve: FanCurve,
        temp_fn: Callable[[], Optional[float]] = read_cpu_temp_c,
        poll_interval_s: float = 10.0,
        pwm_frequency_hz: int = 100,
    ):
        self._pin = pin
        self._curve = curve
        self._temp_fn = temp_fn
        self._poll_interval_s = poll_interval_s
        self._pwm_frequency_hz = pwm_frequency_hz
        self._pwm = None
        self._on = False
        self.current_duty: float = 0.0
        self.previous_duty: float = 0.0

    async def run(self) -> None:
        try:
            from gpiozero import PWMOutputDevice
        except ImportError:
            logger.error(
                "fan control enabled but gpiozero is not installed -- "
                "not driving GPIO%d", self._pin,
            )
            return

        try:
            self._pwm = PWMOutputDevice(
                self._pin, frequency=self._pwm_frequency_hz, initial_value=0.0,
            )
        except Exception as exc:
            if type(exc).__name__ == "PinPWMUnsupported":
                # gpiozero's pure-Python NativeFactory fallback (used when
                # lgpio/RPi.GPIO/pigpio are all absent) only allows PWM on
                # pins it recognizes from a hardcoded per-board table --
                # this custom carrier board's GPIO13 isn't in it, even
                # though it's a real PWM1 hardware channel on the Pi 4 SoC.
                # A real pin-factory backend doesn't have that restriction.
                logger.error(
                    "GPIO%d PWM unsupported on gpiozero's fallback pin "
                    "factory (no lgpio/RPi.GPIO/pigpio installed) -- "
                    "run: sudo /opt/meshpoint/venv/bin/pip install lgpio, "
                    "then restart. Not driving the fan.", self._pin,
                )
            else:
                logger.exception(
                    "Failed to open GPIO%d for fan control", self._pin,
                )
            return

        logger.info(
            "Fan control started on GPIO%d (%.0f-%.0fC range, poll every %.0fs)",
            self._pin, self._curve.min_temp_c, self._curve.max_temp_c,
            self._poll_interval_s,
        )
        try:
            while True:
                self._poll_once()
                await asyncio.sleep(self._poll_interval_s)
        except asyncio.CancelledError:
            pass
        finally:
            self._pwm.close()

    def _poll_once(self) -> None:
        """Read temperature, compute duty, drive the pin once.

        Split out from ``run()``'s loop so the duty-tracking logic
        (``current_duty``/``previous_duty``, used by the dashboard fan
        card) is testable without real asyncio timing.
        """
        temp = self._temp_fn()
        if temp is None:
            return
        duty = self._curve.duty_for(temp, self._on)
        if duty != self._pwm.value:
            logger.info(
                "Fan: %.1fC -> duty %.2f (was %.2f)",
                temp, duty, self._pwm.value,
            )
            self.previous_duty = self.current_duty
        self._pwm.value = duty
        self._on = duty > 0.0
        self.current_duty = duty
