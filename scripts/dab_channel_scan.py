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
    python3 scripts/dab_channel_scan.py                  # all 38 channels, 30s each
    python3 scripts/dab_channel_scan.py --channels 12C 11C 9C
    python3 scripts/dab_channel_scan.py --timeout 45     # slower/weaker antenna

A "nothing" result on a full scan isn't always definitive: back-to-back
channel switches can occasionally leave welle-cli unable to reopen the
dongle in time even with the gap between channels, producing a false
negative on an otherwise-good channel (seen live: 9C read "nothing" on
a full run, then decoded 15 stations at SNR 7 dB when retested alone).
Worth an isolated retest (--channels <X>) before writing a channel off.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from typing import Optional

ALL_CHANNELS = [f"{n}{letter}" for n in range(5, 13) for letter in "ABCD"] + [
    f"13{letter}" for letter in "ABCDEF"
]

POLL_INTERVAL_SECONDS = 2.0
DEVICE_SETTLE_SECONDS = 1.5

# Some ensembles broadcast a generic label instead of a real name (seen on
# 11C, the Dutch commercial-radio multiplex, which identifies itself as
# literally "DAB+") -- override with something actually useful for picking
# a channel from the results.
ENSEMBLE_LABEL_OVERRIDES = {"DAB+": "Commercial"}


def strip_channel_code(label: str, channel: str) -> str:
    """Remove a redundant channel-code token from a decoded ensemble label.

    Some ensembles bake their own channel code into the label (e.g. "8B
    N-H / Flevo" on channel 8B) -- redundant since the channel is already
    known, so strip it plus whatever separator punctuation is left dangling.
    """
    cleaned = re.sub(rf"\b{re.escape(channel)}\b", "", label, flags=re.IGNORECASE)
    cleaned = re.sub(r"^[\s/\-·,]+|[\s/\-·,]+$", "", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned or label


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
                if s.get("url_mp3") and (s.get("label") or {}).get("label", "").strip()
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
    if result["ensemble"]:
        result["ensemble"] = strip_channel_code(result["ensemble"], channel)
    if result["ensemble"] in ENSEMBLE_LABEL_OVERRIDES:
        result["ensemble"] = ENSEMBLE_LABEL_OVERRIDES[result["ensemble"]]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--channels", nargs="+", default=ALL_CHANNELS,
        help="specific channels to scan, e.g. --channels 12C 11C 9C (default: all 38 Band III channels)",
    )
    parser.add_argument(
        "--timeout", type=float, default=30.0,
        help="max seconds to wait per channel for sync + station decode (default: 30)",
    )
    parser.add_argument("--port", type=int, default=7979, help="welle-cli webserver port (default: 7979)")
    parser.add_argument(
        "--output", "-o", default="dab_channel_scan.json",
        help="write scan results to this JSON file (default: dab_channel_scan.json)",
    )
    args = parser.parse_args()

    if shutil.which("welle-cli") is None:
        print("welle-cli not found on PATH -- install welle.io first (apt install welle.io)", file=sys.stderr)
        return 1

    total = len(args.channels)
    print(f"Scanning {total} channel(s), up to {args.timeout:.0f}s each "
          f"(~{total * args.timeout / 60:.0f} min worst case)...\n")

    all_results = []
    hits = []
    for i, channel in enumerate(args.channels, 1):
        print(f"[{i}/{total}] {channel} ...", end=" ", flush=True)
        result = scan_channel(channel, args.port, args.timeout)
        all_results.append(result)
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

    payload = {
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "timeout_seconds": args.timeout,
        "channels": all_results,
    }
    with open(args.output, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"\nResults written to {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
