"""Status LED for the SenseCap M1's onboard case LED (GPIO 22).

Glanceable box state, four states only (blink-code alphabets nobody
remembers are the classic failure mode of status LEDs):

  steady on    service running, all configured capture sources healthy
  off-flicker  a packet was captured (brief dip against the on baseline,
               like a router's traffic LED -- off-pulses read correctly
               for sparse and dense traffic alike)
  1 Hz blink   degraded: one or more configured capture sources down
  dark         service not running (free: when the process dies, lgpio
               releases the line and the LED goes dark -- no watchdog)

Plain on/off GPIO -- deliberately no PWM (GPIO 22 has no hardware PWM
channel, and brightness adds nothing to the four states).
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable

logger = logging.getLogger(__name__)

# How long the activity dip lasts. One tick at the default cadence.
FLICKER_SECS = 0.08


class LedController:
    """Drives the case LED from capture health + packet-count signals.

    ``health_fn`` returns True when every configured capture source is
    running; ``packet_count_fn`` returns a monotonically increasing
    total (any change = activity). Both are cheap sync callables polled
    at ``tick_interval_s`` -- the capture hot path is never touched.
    Same lifecycle pattern as ``FanController.run()``.
    """

    def __init__(
        self,
        pin: int,
        health_fn: Callable[[], bool],
        packet_count_fn: Callable[[], int],
        activity_blink: bool = True,
        tick_interval_s: float = 0.1,
    ):
        self._pin = pin
        self._health_fn = health_fn
        self._packet_count_fn = packet_count_fn
        self._activity_blink = activity_blink
        self._tick_interval_s = tick_interval_s
        self._led = None
        self._lit: bool | None = None  # None = never driven yet
        self._last_count: int | None = None
        self._flicker_until = 0.0

    async def run(self) -> None:
        try:
            from gpiozero import LED
        except ImportError:
            logger.error(
                "status LED enabled but gpiozero is not installed -- "
                "not driving GPIO%d", self._pin,
            )
            return

        try:
            self._led = LED(self._pin)
        except Exception:
            logger.exception(
                "Failed to open GPIO%d for the status LED", self._pin,
            )
            return

        logger.info(
            "Status LED started on GPIO%d (steady=healthy, flicker=packet, "
            "1Hz blink=source down)", self._pin,
        )
        try:
            while True:
                self._tick(time.monotonic())
                await asyncio.sleep(self._tick_interval_s)
        except asyncio.CancelledError:
            pass
        finally:
            self._led.off()
            self._led.close()

    def _tick(self, now: float) -> None:
        """One state evaluation; split out from run() for tests."""
        healthy = bool(self._health_fn())
        count = self._packet_count_fn()
        if self._last_count is None:
            # First tick: don't flicker for packets captured before start.
            self._last_count = count
        elif count != self._last_count:
            self._last_count = count
            if self._activity_blink and healthy:
                self._flicker_until = now + FLICKER_SECS

        if not healthy:
            # 1 Hz blink, phase-locked to the clock so the cadence is
            # steady regardless of when ticks land.
            self._set(now % 1.0 < 0.5)
        elif now < self._flicker_until:
            self._set(False)
        else:
            self._set(True)

    def _set(self, lit: bool) -> None:
        if self._led is None or lit == self._lit:
            return
        self._lit = lit
        if lit:
            self._led.on()
        else:
            self._led.off()
