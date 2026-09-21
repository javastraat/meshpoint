#!/usr/bin/env python3
"""Diagnostic probe for a carrier board's onboard LED/button/fan.

Run directly on the Pi (needs `gpiozero` -- preinstalled system-wide on
Raspberry Pi OS, and also a declared Meshpoint dependency as of the PWM
fan controller in src/hardware/fan_control.py, but this script itself
can run standalone even without a Meshpoint venv set up).

Pin numbers below are BCM GPIO numbers, NOT physical header pin numbers.
Defaults are the SenseCap M1's confirmed pins (via `button-scan`/`fan-scan`,
see below): LED = GPIO 22, button = GPIO 27, fan = GPIO 13. (Initial
guesses of button=13/fan=14 were wrong -- 13 is actually the fan.)

Other carriers do NOT necessarily share these -- confirmed different on
a Cortex X3: front button = GPIO 23 (not the M1's 27), front LED = GPIO 27
(the M1's button pin, not its LED) -- fan pin still unconfirmed there.
Re-derive per board with the *-scan modes below rather than assuming the
defaults; RESERVED_PINS/SCAN_CANDIDATES are the M1's picture of "what's
already spoken for", not a universal one.

`button-scan`/`fan-scan`/`led-scan` sweep a whole batch of candidate pins
at once, useful whenever this needs re-deriving on different hardware:

    python3 test_gpio_hardware.py button-scan   # press the button a few
                                                  # times during the 20s scan
    python3 test_gpio_hardware.py fan-scan       # one Enter to arm, then
                                                  # watches/announces each
                                                  # candidate pin in turn
    python3 test_gpio_hardware.py led-scan       # same, but blinks each
                                                  # candidate pin instead --
                                                  # watch the case for a
                                                  # flicker, not the fan

Candidates default to excluding pins already known to be spoken for on
the SenseCap M1: SPI0 (7-11, the concentrator's bus -- confirmed by
/dev/spidev0.x elsewhere in this repo), I2C1 (2-3, the ATECC608 crypto
chip + temp sensor), the HAT ID EEPROM pins (0-1), the concentrator
reset lines (17, 25, from reset_concentrator.sh), GPIO 22 (the M1's LED)
and GPIO 27 (the M1's button). On a board where those last two aren't
actually the LED/button (e.g. the Cortex X3, where it's the other way
around -- button=23, LED=27), pass --exclude to override which pins get
skipped -- e.g. re-scanning the X3 for its still-unconfirmed fan pin
needs its own known pins (23, 27) excluded instead of the M1's (22, 27):

    python3 test_gpio_hardware.py fan-scan --exclude 0,1,2,3,7,8,9,10,11,17,23,25,27

Usage:
    python3 test_gpio_hardware.py led
    python3 test_gpio_hardware.py button
    python3 test_gpio_hardware.py fan
    python3 test_gpio_hardware.py all
    python3 test_gpio_hardware.py button-scan
    python3 test_gpio_hardware.py fan-scan
    python3 test_gpio_hardware.py led-scan
"""

from __future__ import annotations

import argparse
import sys
import time

LED_PIN_DEFAULT = 22
BUTTON_PIN_DEFAULT = 27
FAN_PIN_DEFAULT = 13

# SenseCap M1's picture of "already spoken for" -- the default candidate
# exclusion set for every *-scan mode, overridable per board with
# --exclude (see module docstring: this doesn't hold on every carrier).
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


def led_scan(pins: list[int], blink_seconds: float, blinks: int) -> None:
    """Blink each candidate pin a few times in turn -- same one-at-a-time
    sweep as `fan_scan`, but multiple short blinks rather than one long
    HIGH pulse: a single pulse is plenty to feel/hear a fan spin up, but
    an LED flickering once amid whatever else is lit on the board is
    easy to miss, so this repeats it and leaves a visible gap between
    pins to make the correlation with the printed GPIO number obvious."""
    from gpiozero import LED

    print(f"About to blink {len(pins)} candidate pins one at a time: {pins}")
    print(
        "Each pin blinks a few times. Watch the front of the board and note "
        "which announced GPIO number lines up with the LED flickering. Be "
        "ready to Ctrl+C if anything else on the board reacts unexpectedly."
    )
    input("Press Enter to arm and start the sweep, or Ctrl+C to abort... ")

    for pin in pins:
        print(f"Testing GPIO{pin}...")
        try:
            led = LED(pin)
        except Exception as exc:
            print(f"  GPIO{pin}: skipped ({exc})")
            continue
        try:
            for _ in range(blinks):
                led.on()
                time.sleep(blink_seconds)
                led.off()
                time.sleep(blink_seconds)
        finally:
            led.close()
        time.sleep(0.8)

    print("\nSweep done. Which GPIO number was announced when the LED flickered?")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "target",
        choices=["led", "button", "fan", "all", "button-scan", "fan-scan", "led-scan"],
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
        "--blink-seconds", type=float, default=0.2,
        help="on/off duration per blink in led-scan (default 0.2s)",
    )
    parser.add_argument(
        "--blinks", type=int, default=3,
        help="how many times led-scan blinks each candidate pin (default 3)",
    )
    parser.add_argument(
        "--pull-up-mode", choices=["up", "down"], default="up",
        help="button-scan pull resistor direction to try (default up)",
    )
    parser.add_argument(
        "--exclude", type=str, default=None,
        help=(
            "comma-separated GPIO numbers to skip in any *-scan mode, "
            "overriding RESERVED_PINS -- needed on a carrier whose "
            "known-pins don't match the SenseCap M1's (e.g. the Cortex "
            "X3, whose button turned out to be GPIO 23, not 27)"
        ),
    )
    args = parser.parse_args()

    if args.exclude is not None:
        excluded = {int(p) for p in args.exclude.split(",") if p.strip()}
        scan_candidates = [p for p in range(2, 28) if p not in excluded]
    else:
        scan_candidates = SCAN_CANDIDATES

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
        button_scan(scan_candidates, args.scan_seconds, args.pull_up_mode == "up")
    if args.target == "fan-scan":
        fan_scan(scan_candidates, args.pulse_seconds)
    if args.target == "led-scan":
        led_scan(scan_candidates, args.blink_seconds, args.blinks)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
