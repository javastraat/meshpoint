#!/usr/bin/env python3
"""Diagnostic probe for the SenseCap M1's onboard LED/button/fan.

Run directly on the Pi (needs `gpiozero`, preinstalled on Raspberry Pi OS —
this is NOT a Meshpoint runtime dependency, just a one-off hardware check).

Pin numbers below are BCM GPIO numbers, NOT physical header pin numbers.
Only GPIO 22 (LED) is corroborated by outside sources (a community teardown
and a Seeed `dtoverlay=gpio-led,gpio=22,label=lorawan` config snippet both
name it). GPIO 13 (button) and GPIO 14 (fan) are unverified -- no public
schematic exists for this board -- so this script is deliberately cautious:
the button test only ever reads, and the fan test requires an explicit
Enter keypress before it drives anything. If a guess is wrong, override it
with the matching --*-pin flag and retry rather than editing this file.

Usage:
    python3 test_gpio_hardware.py led
    python3 test_gpio_hardware.py button
    python3 test_gpio_hardware.py fan
    python3 test_gpio_hardware.py all
    python3 test_gpio_hardware.py button --button-pin 6   # try another guess
"""

from __future__ import annotations

import argparse
import sys
import time

LED_PIN_DEFAULT = 22
BUTTON_PIN_DEFAULT = 13
FAN_PIN_DEFAULT = 14


def test_led(pin: int) -> None:
    from gpiozero import LED

    print(f"LED on GPIO{pin}: blinking 5x (watch the expansion board)...")
    led = LED(pin)
    try:
        for _ in range(5):
            led.on()
            time.sleep(0.3)
            led.off()
            time.sleep(0.3)
        print("Done. Did it blink? If not, try a different --led-pin.")
    finally:
        led.close()


def test_button(pin: int, seconds: float) -> None:
    from gpiozero import Button

    print(
        f"Button on GPIO{pin}: reading for {seconds:.0f}s "
        f"(pull_up=True assumed -- press the button now)..."
    )
    button = Button(pin, pull_up=True, bounce_time=0.05)
    button.when_pressed = lambda: print("  -> pressed")
    button.when_released = lambda: print("  -> released")
    try:
        time.sleep(seconds)
        print(
            "Done. If nothing printed while pressing, this isn't the right "
            "pin (or it's wired active-high -- try pull_up=False by editing "
            "the script), try a different --button-pin."
        )
    finally:
        button.close()


def test_fan(pin: int, seconds: float) -> None:
    from gpiozero import OutputDevice

    print(f"About to drive GPIO{pin} HIGH for {seconds:.0f}s to spin the fan.")
    print(
        "This pin is an unverified guess. Watch/listen for the fan and be "
        "ready to Ctrl+C immediately if anything else on the board reacts "
        "unexpectedly (e.g. the concentrator resets, other LEDs flicker)."
    )
    input("Press Enter to arm and run the test, or Ctrl+C to abort... ")

    fan = OutputDevice(pin, active_high=True, initial_value=False)
    try:
        print("Fan ON")
        fan.on()
        time.sleep(seconds)
        print("Fan OFF")
        fan.off()
        print("Done. Did it spin up and stop? If not, try a different --fan-pin.")
    finally:
        fan.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "target", choices=["led", "button", "fan", "all"],
        help="which peripheral to test",
    )
    parser.add_argument("--led-pin", type=int, default=LED_PIN_DEFAULT)
    parser.add_argument("--button-pin", type=int, default=BUTTON_PIN_DEFAULT)
    parser.add_argument("--fan-pin", type=int, default=FAN_PIN_DEFAULT)
    parser.add_argument(
        "--seconds", type=float, default=10.0,
        help="how long to run the button/fan tests (default 10s)",
    )
    args = parser.parse_args()

    try:
        import gpiozero  # noqa: F401
    except ImportError:
        print(
            "gpiozero not installed. On Raspberry Pi OS it's usually "
            "preinstalled; otherwise: sudo apt install -y python3-gpiozero",
            file=sys.stderr,
        )
        return 1

    if args.target in ("led", "all"):
        test_led(args.led_pin)
    if args.target in ("button", "all"):
        test_button(args.button_pin, args.seconds)
    if args.target in ("fan", "all"):
        test_fan(args.fan_pin, min(args.seconds, 5.0))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
