#!/usr/bin/env python3
"""
DAB+ channel scanner for Meshpoint's RTL-SDR dongle.

Standalone diagnostic (no meshpoint imports, stdlib only): drives
welle-cli directly across the full Band III DAB raster (5A-13F, 38
channels) and reports which ones actually decode an ensemble + stations
at this antenna, so the dashboard's DAB+ channel presets can be picked
from real data instead of another location's scanner listing.

IMPORTANT: stop any active Radio/DAB+/P2000/Pagers/POCSAG/RTL433 tab in
the dashboard first. This script talks to welle-cli directly and knows
nothing about Meshpoint's own dongle-exclusivity registry (src/audio/
sdr_registry.py) -- if another listener is running, welle-cli will just
fail to open the device for every channel.

Usage:
    python3 scripts/dab_channel_scan.py                  # all 38 channels
    python3 scripts/dab_channel_scan.py --channels 12C 11C 9C
    python3 scripts/dab_channel_scan.py --timeout 30     # slower/weaker antenna
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
import urllib.request
from typing import Optional

ALL_CHANNELS = [f"{n}{letter}" for n in range(5, 13) for letter in "ABCD"] + [
    f"13{letter}" for letter in "ABCDEF"
]

POLL_INTERVAL_SECONDS = 2.0
DEVICE_SETTLE_SECONDS = 0.5


def fetch_mux_json(port: int) -> Optional[dict]:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/mux.json", timeout=2) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return None


def scan_channel(channel: str, port: int, timeout: float) -> dict:
    result: dict = {"channel": channel, "ensemble": "", "snr": 0.0, "stations": []}
    proc = subprocess.Popen(
        ["welle-cli", "-c", channel, "-w", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            time.sleep(POLL_INTERVAL_SECONDS)
            data = fetch_mux_json(port)
            if not data:
                continue
            label = (data.get("ensemble", {}).get("label", {}) or {}).get("label", "").strip()
            if label:
                result["ensemble"] = label
            snr = data.get("demodulator", {}).get("snr")
            if isinstance(snr, (int, float)):
                result["snr"] = float(snr)
            stations = [
                (s.get("label") or {}).get("label", "").strip()
                for s in data.get("services", [])
                if s.get("url_mp3")
            ]
            if stations:
                result["stations"] = stations
            # Ensemble locked and at least one station decoded -- no need
            # to burn the rest of the timeout on this channel.
            if result["ensemble"] and result["stations"]:
                break
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        time.sleep(DEVICE_SETTLE_SECONDS)  # let the dongle release before the next channel
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--channels", nargs="+", default=ALL_CHANNELS,
        help="specific channels to scan, e.g. --channels 12C 11C 9C (default: all 38 Band III channels)",
    )
    parser.add_argument(
        "--timeout", type=float, default=20.0,
        help="max seconds to wait per channel for sync + station decode (default: 20)",
    )
    parser.add_argument("--port", type=int, default=7979, help="welle-cli webserver port (default: 7979)")
    args = parser.parse_args()

    if shutil.which("welle-cli") is None:
        print("welle-cli not found on PATH -- install welle.io first (apt install welle.io)", file=sys.stderr)
        return 1

    total = len(args.channels)
    print(f"Scanning {total} channel(s), up to {args.timeout:.0f}s each "
          f"(~{total * args.timeout / 60:.0f} min worst case)...\n")

    hits = []
    for i, channel in enumerate(args.channels, 1):
        print(f"[{i}/{total}] {channel} ...", end=" ", flush=True)
        result = scan_channel(channel, args.port, args.timeout)
        if result["ensemble"] or result["stations"]:
            print(f"FOUND: {result['ensemble']!r} (SNR {result['snr']:.1f} dB) -- {len(result['stations'])} station(s)")
            hits.append(result)
        else:
            print("nothing")

    print("\n" + "=" * 60)
    print("Channels with content:")
    print("=" * 60)
    if not hits:
        print("None -- no channel decoded an ensemble at this antenna.")
    for r in hits:
        print(f"\n{r['channel']} -- {r['ensemble']} (SNR {r['snr']:.1f} dB)")
        for s in r["stations"]:
            print(f"    - {s}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
