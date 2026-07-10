"""User button on the SenseCap M1 (GPIO 27): physical advert + restart.

Two gestures, chosen for what only a physical control can do:

  short press   announce this box on every TX-capable radio (concentrator
                Meshtastic NodeInfo, MeshCore companion advert, Meshtastic
                USB sticks), serialized with spacing -- the two 868
                signals overlap outright (Meshtastic 869.525/BW250
                contains MeshCore 869.618/BW62.5) and same-box TX
                desensitizes the neighbouring receivers.
  hold 3 s      restart the meshpoint service -- the recovery action you
                need exactly when the dashboard can't give it to you.

Poll-based state machine (no gpiozero callback threads), same lifecycle
and testable ``_tick(now)`` pattern as the fan and LED controllers.
Starts DISARMED: a release must be seen before any press counts, so
booting with the button held (e.g. held straight through a restart)
never re-triggers.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess  # nosec B404 -- fixed argv, no shell
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)

DEBOUNCE_S = 0.05        # matches the probe script's working settings
WARN_AFTER_S = 0.5       # hold this long before the LED warning starts
ADVERT_SPACING_S = 2.0   # gap between radios in the advert sequence


class ButtonController:
    """Polls the button and translates gestures into callbacks.

    ``on_short_press``/``on_long_press`` are plain sync callables (the
    server wiring schedules async work from them); ``led`` is an
    optional LedController used for feedback via its ``flash()``.
    """

    def __init__(
        self,
        pin: int,
        on_short_press: Callable[[], None],
        on_long_press: Callable[[], None],
        hold_time_s: float = 3.0,
        advert_cooldown_s: float = 30.0,
        led=None,
        tick_interval_s: float = 0.05,
    ):
        self._pin = pin
        self._on_short_press = on_short_press
        self._on_long_press = on_long_press
        self._hold_time_s = hold_time_s
        self._advert_cooldown_s = advert_cooldown_s
        self._led = led
        self._tick_interval_s = tick_interval_s
        self._button = None
        self._armed = False
        self._pressed_at: Optional[float] = None
        self._long_fired = False
        self._cooldown_until = 0.0

    async def run(self) -> None:
        try:
            from gpiozero import Button
        except ImportError:
            logger.error(
                "button control enabled but gpiozero is not installed -- "
                "not reading GPIO%d", self._pin,
            )
            return

        try:
            self._button = Button(
                self._pin, pull_up=True, bounce_time=DEBOUNCE_S,
            )
        except Exception:
            logger.exception(
                "Failed to open GPIO%d for button control", self._pin,
            )
            return

        logger.info(
            "Button control started on GPIO%d (short press=advert all "
            "radios, hold %.0fs=service restart)",
            self._pin, self._hold_time_s,
        )
        try:
            while True:
                self._tick(time.monotonic())
                await asyncio.sleep(self._tick_interval_s)
        except asyncio.CancelledError:
            pass
        finally:
            self._button.close()

    def _tick(self, now: float) -> None:
        """One gesture evaluation; split out from run() for tests."""
        pressed = bool(self._button.is_pressed)

        if not self._armed:
            # Held at startup (e.g. straight through a restart we
            # triggered): ignore everything until a release is seen.
            if not pressed:
                self._armed = True
            return

        if pressed:
            if self._pressed_at is None:
                self._pressed_at = now
                self._long_fired = False
                return
            held = now - self._pressed_at
            if self._long_fired:
                return
            if held >= self._hold_time_s:
                self._long_fired = True
                logger.warning(
                    "Button held %.1fs -- triggering service restart", held,
                )
                self._on_long_press()
            elif held >= WARN_AFTER_S and self._led is not None:
                # Re-issued every tick while held; self-expires on release.
                self._led.flash('fast', 0.3)
        else:
            if self._pressed_at is None:
                return
            held = now - self._pressed_at
            self._pressed_at = None
            fired = self._long_fired
            self._long_fired = False
            if not fired and held >= DEBOUNCE_S:
                self._short_press(now)

    def _short_press(self, now: float) -> None:
        if now < self._cooldown_until:
            logger.info(
                "Button: advert cooldown active (%.0fs left)",
                self._cooldown_until - now,
            )
            if self._led is not None:
                self._led.flash('off', 1.0)  # "heard you, already announced"
            return
        self._cooldown_until = now + self._advert_cooldown_s
        logger.info("Button: advert on all TX-capable radios")
        if self._led is not None:
            self._led.flash('fast', 0.5)  # double-blink ack
        self._on_short_press()


async def advert_all_radios(steps, spacing_s: float = ADVERT_SPACING_S) -> None:
    """Run the advert sequence: one radio at a time, spaced apart.

    ``steps`` is a list of ``(name, async_callable)``; each is attempted
    independently so one radio failing never silences the others.
    """
    first = True
    for name, send in steps:
        if not first:
            await asyncio.sleep(spacing_s)
        first = False
        try:
            result = await send()
            logger.info("Button advert on %s: %s", name, result)
        except Exception:
            logger.exception("Button advert on %s failed", name)


def restart_service() -> None:
    """Restart the meshpoint service, detached.

    Detached (own session, no wait) because the restart kills this very
    process -- same lesson the update apply chain learned. The sudoers
    file already whitelists exactly this argv.
    """
    try:
        subprocess.Popen(  # nosec B603 B607 -- fixed argv, no shell
            ["sudo", "systemctl", "restart", "meshpoint"],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        logger.exception("Button-triggered service restart failed to spawn")
