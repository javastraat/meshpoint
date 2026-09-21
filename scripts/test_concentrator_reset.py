#!/usr/bin/env python3
"""Diagnostic: find a GPIO reset/enable pin that lets the concentrator
survive a warm restart, not just a cold power-up.

Background (see docs/TROUBLESHOOTING.md's concentrator-reset section):
on some boards, `lgw_start()` succeeds right after a real power cycle
but fails every time on a plain `systemctl restart meshpoint` -- same
config, same code, only difference is whether power was ever actually
removed. That's NOT something a naive one-shot pin test can catch:
almost any pin "works" immediately after a real power-up, because the
chip is already in a clean state regardless of which pin gets toggled.
The bug only shows up on a SECOND attempt with no power cycle in
between -- so every candidate here is tested TWICE IN A ROW, back to
back, in two independent fresh processes (matching what actually
happens across a `systemctl restart`), and only a candidate that
passes BOTH counts as a real fix.

Each attempt runs the exact same bring-up sequence Meshpoint itself
uses (src.hal.sx1302_wrapper.SX1302Wrapper: load -> configure ->
set_syncword -> start), not a reimplementation -- so a PASS here means
Meshpoint itself would actually start cleanly with that pin, not just
that libloragw responded to something.

Run as root, from the Meshpoint venv, from the repo root (needs
`src.hal.*` importable):

    sudo /opt/meshpoint/venv/bin/python3 scripts/test_concentrator_reset.py \\
        --sweep-reset 4,5,6,13,19,21,23,24,26,27

    sudo /opt/meshpoint/venv/bin/python3 scripts/test_concentrator_reset.py \\
        --sweep-enable 4,5,6,13,19,21,23,24,26,27

    sudo /opt/meshpoint/venv/bin/python3 scripts/test_concentrator_reset.py \\
        --pins 22 --mode enable   # test one specific candidate

--sweep-reset tests each pin ALONE as the reset line, replacing the
default [17, 25] entirely (same semantics as Meshpoint's own
RESET_GPIO env var -- this script sets it internally per attempt).
--sweep-enable tests each pin held HIGH (never pulsed low) ALONGSIDE
the normal default [17, 25] reset -- for a candidate "power enable"
line that needs to be on *before* the normal reset happens, not a
replacement for it. Candidates already ruled out this session (17,
18, 20, 22, 25, plus 12/16 from the real Pisces vendor firmware) are
left OUT of the example candidate lists above on purpose -- pass
--include-tested to add them back if you want a from-scratch run.

Reserved pins (SPI0 MOSI/MISO/SCLK/CE0 on 8-11, I2C1 on 2-3, HAT ID
EEPROM on 0-1, UART/GPS on 14-15) are excluded from --sweep-* by
default since toggling them fights a different peripheral entirely --
pass --include-reserved to test them anyway (this script doesn't stop
you, since this exact board turned out to route something real onto
GPIO 7, one of the "reserved" SPI0 pins, on a board using a
single-chip-select overlay).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

RESERVED_PINS = {0, 1, 2, 3, 8, 9, 10, 11, 14, 15}
ALREADY_TESTED = {7, 12, 16, 17, 18, 20, 22, 25}


def _pinctrl(*args: str) -> None:
    subprocess.run(["pinctrl", *args], check=True, capture_output=True)


def _hold_high(pins: list[int]) -> None:
    for pin in pins:
        _pinctrl("set", str(pin), "op", "dh")


def _release_to_input(pins: list[int]) -> None:
    """Best-effort cleanup between attempts -- release a held-high
    enable-role pin back to input so it doesn't bleed into whatever's
    tested next. Failures here are not fatal to the test itself."""
    for pin in pins:
        try:
            _pinctrl("set", str(pin), "ip")
        except Exception:  # noqa: BLE001
            pass


def _run_attempt(pins: list[int], mode: str, spi_path: str) -> tuple[bool, str]:
    """One fresh-process attempt: subprocess re-invokes this same
    script in worker mode, so every attempt gets a genuinely fresh
    ctypes/libloragw load -- exactly like a real Meshpoint process,
    never two lgw_start() calls sharing one process's library state."""
    cmd = [
        sys.executable, __file__, "--_worker",
        "--pins", ",".join(str(p) for p in pins),
        "--mode", mode,
        "--spi-path", spi_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    ok = result.returncode == 0
    # Look specifically for this script's own "RESULT: ..." sentinel line,
    # not just whatever happens to print last -- the underlying C library
    # (libloragw) writes its own diagnostic lines straight to stdout/stderr
    # via printf(), on a different buffering path than Python's print(),
    # so a naive "last line of combined output" can pick up one of ITS
    # lines instead of this script's actual verdict.
    lines = (result.stdout + result.stderr).strip().splitlines()
    result_lines = [ln for ln in lines if ln.startswith("RESULT:")]
    detail = result_lines[-1] if result_lines else (lines[-1] if lines else "(no output)")
    return ok, detail


def _worker(pins: list[int], mode: str, spi_path: str) -> int:
    """Runs inside the fresh subprocess. Mirrors exactly what
    Meshpoint's own ConcentratorCaptureSource.start() does, just with
    the candidate pin(s) substituted in for this one attempt."""
    import os

    from src.hal.concentrator_config import ConcentratorChannelPlan
    from src.hal.sx1302_wrapper import SX1302Wrapper

    wrapper = SX1302Wrapper(spi_path=spi_path)
    try:
        wrapper.load()
        if mode == "enable":
            _hold_high(pins)
            wrapper.reset()  # default [17, 25] pulse, same as always
        else:
            os.environ["RESET_GPIO"] = " ".join(str(p) for p in pins)
            wrapper.reset()

        # Exact production order (server.py's _inject_tx_gain_into_source /
        # _start_with_tx_gain): configure BEFORE start, set_syncword AFTER --
        # set_syncword does raw lgw_reg_w() register writes that are
        # meaningless (and only ever logged as a swallowed warning, never
        # raised) before lgw_start() has actually run. Getting this order
        # wrong doesn't crash anything, it just makes every attempt look
        # identical in the log regardless of whether start() truly worked.
        wrapper.configure(ConcentratorChannelPlan.eu868_lorawan())
        wrapper.start()
        wrapper.set_syncword(0x2B)
    except Exception as exc:  # noqa: BLE001
        print(f"RESULT: FAIL: {type(exc).__name__}: {exc}")
        return 1
    else:
        print("RESULT: OK")
        try:
            wrapper.stop()
        except Exception:  # noqa: BLE001
            pass
        return 0
    finally:
        if mode == "enable":
            _release_to_input(pins)


def test_candidate(pins: list[int], mode: str, spi_path: str, warm_delay: float) -> str:
    label = f"{'+'.join(str(p) for p in pins)} ({mode})"
    print(f"Testing {label} ...", flush=True)

    ok1, detail1 = _run_attempt(pins, mode, spi_path)
    print(f"  attempt 1 (cold-ish): {'OK' if ok1 else 'FAIL'} -- {detail1}")
    if not ok1:
        return f"{label}: FAIL on attempt 1 -- doesn't even work once"

    if warm_delay:
        time.sleep(warm_delay)

    ok2, detail2 = _run_attempt(pins, mode, spi_path)
    print(f"  attempt 2 (warm, no power cycle): {'OK' if ok2 else 'FAIL'} -- {detail2}")

    if ok2:
        return f"{label}: PASS -- survived a warm restart, this may be the fix"
    return f"{label}: PARTIAL -- works once, fails on a warm restart (matches the known bug)"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pins", type=str, help="comma-separated GPIO numbers to test as ONE combination")
    parser.add_argument("--mode", choices=["reset", "enable"], default="reset")
    parser.add_argument("--sweep-reset", type=str, help="comma-separated GPIOs, each tested alone as the reset line")
    parser.add_argument("--sweep-enable", type=str, help="comma-separated GPIOs, each tested held-high alongside the default reset")
    parser.add_argument("--spi-path", type=str, default="/dev/spidev0.0")
    parser.add_argument("--warm-delay", type=float, default=0.0, help="seconds to wait between attempt 1 and 2 (default: 0, back to back)")
    parser.add_argument("--include-reserved", action="store_true")
    parser.add_argument("--include-tested", action="store_true")
    parser.add_argument("--_worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args._worker:
        pins = [int(p) for p in args.pins.split(",")]
        return _worker(pins, args.mode, args.spi_path)

    def _filter(candidates: list[int]) -> list[int]:
        out = candidates
        if not args.include_reserved:
            out = [p for p in out if p not in RESERVED_PINS]
        if not args.include_tested:
            out = [p for p in out if p not in ALREADY_TESTED]
        return out

    results: list[str] = []

    if args.pins:
        pins = [int(p) for p in args.pins.split(",")]
        results.append(test_candidate(pins, args.mode, args.spi_path, args.warm_delay))

    if args.sweep_reset:
        for pin in _filter([int(p) for p in args.sweep_reset.split(",")]):
            results.append(test_candidate([pin], "reset", args.spi_path, args.warm_delay))

    if args.sweep_enable:
        for pin in _filter([int(p) for p in args.sweep_enable.split(",")]):
            results.append(test_candidate([pin], "enable", args.spi_path, args.warm_delay))

    if not results:
        parser.print_help()
        return 1

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for line in results:
        print(line)
    passes = [r for r in results if ": PASS" in r]
    if passes:
        print(f"\n{len(passes)} candidate(s) survived a warm restart -- try that one for real.")
    else:
        print("\nNo candidate survived a warm restart. See TROUBLESHOOTING.md for what that likely means.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
