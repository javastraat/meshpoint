#!/usr/bin/env python3
"""Test whether this concentrator's SX1261 companion chip is reachable at
a given SPI path, without permanently setting radio.sx1261_spi_path.

⚠️  REAL RISK, READ BEFORE RUNNING. This calls the exact same lgw_start()
the real service calls -- on a carrier where the SX1261 isn't reachable at
the given path, that call can abort ENTIRELY (RX/TX/relay, not just the
SX1261 step), the same failure mode documented in docs/CONFIGURATION.md's
"Opting in to true spectral scan" section. This script does not make that
safer -- it only avoids two things the normal test-via-config-file method
carries: it never touches config/local.yaml (nothing to remember to revert
if it fails), and it runs as an isolated one-shot process instead of the
live service, so there's no live capture to interrupt for the seconds this
takes.

**The Meshpoint service must already be stopped before running this** --
`sudo systemctl stop meshpoint`. This script refuses to run otherwise
(both processes touching the same SPI device at once is a real conflict on
its own, independent of the SX1261 question). Recovery from a failure is
just restarting the service normally afterward (`sudo systemctl start
meshpoint`) -- lgw_start() re-initializes fresh every time, nothing here
persists to disk or to the chip.

Reuses the exact same config, channel-plan, and HAL wrapper the real
service uses (src.config.load_config, ConcentratorChannelPlan.from_radio_
config, SX1302Wrapper) rather than a hand-rolled test, so a pass/fail here
reflects the real thing the service would do.

Run as root, from the Meshpoint venv, from the repo root (needs
src.hal.* / src.config importable, same convention as
scripts/test_concentrator_reset.py):

    sudo systemctl stop meshpoint
    sudo /opt/meshpoint/venv/bin/python3 scripts/probe_sx1261.py
    sudo /opt/meshpoint/venv/bin/python3 scripts/probe_sx1261.py /dev/spidev0.2
    sudo /opt/meshpoint/venv/bin/python3 scripts/probe_sx1261.py --force
    sudo systemctl start meshpoint   # when done, either way
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


def _service_is_active() -> bool | None:
    """True/False if systemctl gave a clear answer, None if it couldn't
    tell (missing systemctl, unknown unit name, etc.) -- treated as "can't
    confirm it's stopped" by the caller, same as True."""
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "meshpoint"],
            capture_output=True, text=True, timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    state = result.stdout.strip()
    if state == "active":
        return True
    if state in ("inactive", "failed", "unknown"):
        return False
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "sx1261_path", nargs="?", default="/dev/spidev0.1",
        help="candidate SX1261 SPI device path (default: /dev/spidev0.1)",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="skip the meshpoint-service-is-stopped check",
    )
    args = parser.parse_args()

    active = _service_is_active()
    if active is not False and not args.force:
        if active is True:
            print(
                "The meshpoint service looks ACTIVE. Stop it first:\n"
                "  sudo systemctl stop meshpoint\n"
                "then re-run this script.",
                file=sys.stderr,
            )
        else:
            print(
                "Could not confirm the meshpoint service is stopped "
                "(systemctl gave no clear answer). Stop it yourself first "
                "(`sudo systemctl stop meshpoint`), confirm with "
                "`systemctl status meshpoint`, then either re-run this "
                "script or pass --force if you're certain it's down.",
                file=sys.stderr,
            )
        return 1

    from src.config import load_config
    from src.hal.concentrator_config import ConcentratorChannelPlan
    from src.hal.sx1302_wrapper import SX1302Wrapper

    cfg = load_config()
    plan = ConcentratorChannelPlan.from_radio_config(
        region=cfg.radio.region,
        frequency_mhz=cfg.radio.frequency_mhz,
        spreading_factor=cfg.radio.spreading_factor,
        bandwidth_khz=cfg.radio.bandwidth_khz,
    )

    print(f"Testing SX1261 reachability at {args.sx1261_path!r} ...")
    print(f"(main SPI: {cfg.capture.concentrator_spi_device}, "
          f"region: {cfg.radio.region}, this WILL bring up the whole "
          f"concentrator briefly)")

    wrapper = SX1302Wrapper(
        spi_path=cfg.capture.concentrator_spi_device,
        sx1261_spi_path=args.sx1261_path,
    )

    try:
        wrapper.load()
    except FileNotFoundError as exc:
        # A setup problem (libloragw.so missing), not an SX1261 verdict --
        # this is the same thing that would stop the real service from
        # starting at all, regardless of sx1261_spi_path.
        print(f"\n✗ Can't test -- {exc}\n")
        print("  This isn't about SX1261 -- fix the underlying install "
              "first (see docs/ONBOARDING.md), then re-run this.")
        return 1

    try:
        wrapper.reset()
        wrapper.configure(plan)
        wrapper.start()
    except Exception as exc:  # noqa: BLE001 -- report anything, don't hide it
        print(f"\n✗ FAILED -- SX1261 is NOT reachable at {args.sx1261_path!r} "
              f"on this board.\n")
        print(f"  {exc}\n")
        print("  Do not set radio.sx1261_spi_path in config/local.yaml on "
              "this unit -- leave it empty and use the packet-derived "
              "noise floor instead.")
        return 1
    else:
        print(f"\n✓ PASSED -- SX1261 is reachable at {args.sx1261_path!r}.\n")
        print("  Safe to set this in config/local.yaml:")
        print("    radio:")
        print(f'      sx1261_spi_path: "{args.sx1261_path}"')
        print("  then restart the service.")
        return 0
    finally:
        wrapper.stop()


if __name__ == "__main__":
    raise SystemExit(main())
