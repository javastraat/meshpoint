#!/usr/bin/env python3
"""Diagnostic probe for the SenseCap M1's onboard LED/button/fan.

Run directly on the Pi (needs `gpiozero`, preinstalled on Raspberry Pi OS —
this is NOT a Meshpoint runtime dependency, just a one-off hardware check).

Pin numbers below are BCM GPIO numbers, NOT physical header pin numbers.
All three are now confirmed live on the actual board (via `button-scan`/
`fan-scan`, see below): LED = GPIO 22, button = GPIO 27, fan = GPIO 13.
(Initial guesses of button=13/fan=14 were wrong -- 13 is actually the fan.)

`button-scan` and `fan-scan` sweep a whole batch of candidate pins at once,
useful if this ever needs re-deriving on different hardware:

    python3 test_gpio_hardware.py button-scan   # press the button a few
                                                  # times during the 20s scan
    python3 test_gpio_hardware.py fan-scan       # one Enter to arm, then
                                                  # watches/announces each
                                                  # candidate pin in turn

Candidates exclude pins already known to be spoken for on this board:
SPI0 (7-11, the concentrator's bus -- confirmed by /dev/spidev0.x elsewhere
in this repo), I2C1 (2-3, the ATECC608 crypto chip + temp sensor), the HAT ID
EEPROM pins (0-1), the concentrator reset lines (17, 25, from
reset_concentrator.sh), and GPIO 22 (the LED).

Usage:
    python3 test_gpio_hardware.py led
    python3 test_gpio_hardware.py button
    python3 test_gpio_hardware.py fan
    python3 test_gpio_hardware.py all
    python3 test_gpio_hardware.py button-scan
    python3 test_gpio_hardware.py fan-scan
"""

from __future__ import annotations

import argparse
import sys
import time

LED_PIN_DEFAULT = 22
BUTTON_PIN_DEFAULT = 27
FAN_PIN_DEFAULT = 13

# Pins already spoken for on this board -- never included in a scan.
RESERVED_PINS = {0, 1, 2, 3, 7, 8, 9, 10, 11, 13, 17, 22, 25, 27}
SCAN_CANDIDATES = [p for p in range(2, 28) if p not in RESERVED_PINS]


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


def button_scan(pins: list[int], seconds: float, pull_up: bool) -> None:
    from gpiozero import Button

    mode = "pull_up (idle HIGH, press pulls LOW)" if pull_up else "pull_down (idle LOW, press pulls HIGH)"
    print(f"Scanning {len(pins)} candidate pins for {seconds:.0f}s, {mode}: {pins}")
    print("Press the button repeatedly throughout the whole scan now...")

    changed: set[int] = set()
    buttons = []
    for pin in pins:
        try:
            b = Button(pin, pull_up=pull_up, bounce_time=0.05)
        except Exception as exc:
            print(f"  GPIO{pin}: skipped ({exc})")
            continue
        def on_press(p=pin):
            changed.add(p)
            print(f"  GPIO{p} -> pressed")

        b.when_pressed = on_press
        b.when_released = lambda p=pin: print(f"  GPIO{p} -> released")
        buttons.append(b)

    try:
        time.sleep(seconds)
    finally:
        for b in buttons:
            b.close()

    if changed:
        print(f"\nCandidate button pin(s), changed state during the scan: {sorted(changed)}")
    else:
        print(
            "\nNo pin changed state. If you were pressing the button, retry with "
            "--pull-up-mode down (some buttons are wired the other way), or the "
            "button may be on one of the excluded/reserved pins."
        )


def fan_scan(pins: list[int], pulse_seconds: float) -> None:
    from gpiozero import OutputDevice

    print(f"About to pulse {len(pins)} candidate pins one at a time: {pins}")
    print(
        "Each pin is driven HIGH briefly, then released. Watch/listen for the "
        "fan and note which announced GPIO number lines up with it spinning. "
        "Be ready to Ctrl+C if anything else on the board reacts unexpectedly."
    )
    input("Press Enter to arm and start the sweep, or Ctrl+C to abort... ")

    for pin in pins:
        print(f"Testing GPIO{pin}...")
        try:
            dev = OutputDevice(pin, active_high=True, initial_value=False)
        except Exception as exc:
            print(f"  GPIO{pin}: skipped ({exc})")
            continue
        try:
            dev.on()
            time.sleep(pulse_seconds)
            dev.off()
        finally:
            dev.close()
        time.sleep(0.8)

    print("\nSweep done. Which GPIO number was announced when the fan moved?")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "target",
        choices=["led", "button", "fan", "all", "button-scan", "fan-scan"],
        help="which peripheral to test",
    )
    parser.add_argument("--led-pin", type=int, default=LED_PIN_DEFAULT)
    parser.add_argument("--button-pin", type=int, default=BUTTON_PIN_DEFAULT)
    parser.add_argument("--fan-pin", type=int, default=FAN_PIN_DEFAULT)
    parser.add_argument(
        "--seconds", type=float, default=10.0,
        help="how long to run the button/fan tests (default 10s)",
    )
    parser.add_argument(
        "--scan-seconds", type=float, default=20.0,
        help="how long button-scan listens for (default 20s)",
    )
    parser.add_argument(
        "--pulse-seconds", type=float, default=0.4,
        help="how long fan-scan drives each candidate pin (default 0.4s)",
    )
    parser.add_argument(
        "--pull-up-mode", choices=["up", "down"], default="up",
        help="button-scan pull resistor direction to try (default up)",
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
    if args.target == "button-scan":
        button_scan(SCAN_CANDIDATES, args.scan_seconds, args.pull_up_mode == "up")
    if args.target == "fan-scan":
        fan_scan(SCAN_CANDIDATES, args.pulse_seconds)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
