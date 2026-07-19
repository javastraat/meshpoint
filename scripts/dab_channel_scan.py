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

Results merge into --output by default: rerunning against a single channel
(or any subset) only updates those channels' entries in the existing JSON
file, leaving every other previously-scanned channel untouched -- so a
full station list can be built up across several smaller runs instead of
one long one. Pass --new to discard whatever's already in --output and
start from a clean file instead.

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
import os
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

# Some ensembles broadcast no real name at all -- just their own channel
# code (e.g. 9C's ensemble label decodes as literally "9C", nothing else).
# Surface a neutral placeholder rather than the redundant channel code as
# if it were a real name -- deliberately short and non-instructional (not
# "...set label in config"): it shows up as-is in the dashboard's DAB+
# Config tab and, when no custom_name override is set, as a DAB+ tab
# button label too, where a long "go do X" sentence reads as confusing
# instructions rather than a plain "this one has no name yet".
NO_LABEL_PLACEHOLDER = "{channel} (unnamed)"


def channel_sort_key(channel: str) -> int:
    """Sort by raster position (5A, 5B, ... 13F) instead of plain string order,
    where e.g. "10A" would otherwise sort before "5A". Unknown codes sort last."""
    try:
        return ALL_CHANNELS.index(channel)
    except ValueError:
        return len(ALL_CHANNELS)


def merge_channel_result(existing: Optional[dict], new: dict) -> dict:
    """Combine a freshly scanned channel result with whatever's already on
    file for it, additively -- a rescan should only ever add information
    (new stations decoded, a channel that previously failed now locking),
    never silently drop something already confirmed. A "nothing" rescan
    (transient dongle hiccup, or the scan exiting early once it has *a*
    station rather than waiting for all of them) leaves the existing entry
    untouched instead of overwriting known-good data with a thinner result.
    """
    if existing is None:
        return new
    if not new["ensemble"] and not new["stations"]:
        return existing
    merged_stations = list(existing.get("stations", []))
    for s in new["stations"]:
        if s not in merged_stations:
            merged_stations.append(s)
    # Start from a copy of the existing entry so any extra field the
    # dashboard's DAB+ Config tab may have added (e.g. a user-set
    # "custom_name" override) survives a rescan instead of being dropped
    # by rebuilding the dict from only the fields this script knows about.
    merged = dict(existing)
    merged.update({
        "channel": new["channel"],
        "ensemble": new["ensemble"] or existing.get("ensemble", ""),
        "snr": new["snr"],
        "stations": merged_stations,
        "scanned_at": new["scanned_at"],
    })
    return merged


def strip_channel_code(label: str, channel: str) -> str:
    """Remove a redundant channel-code token from a decoded ensemble label.

    Some ensembles bake their own channel code into the label (e.g. "8B
    N-H / Flevo" on channel 8B) -- redundant since the channel is already
    known, so strip it plus whatever separator punctuation is left dangling.
    If nothing is left over (the label WAS just the channel code), fall
    back to NO_LABEL_PLACEHOLDER instead of the now-empty/redundant string.
    """
    cleaned = re.sub(rf"\b{re.escape(channel)}\b", "", label, flags=re.IGNORECASE)
    cleaned = re.sub(r"^[\s/\-·,]+|[\s/\-·,]+$", "", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned or NO_LABEL_PLACEHOLDER.format(channel=channel)


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
        "--output", "-o", default="/opt/meshpoint/config/dab_channel_scan.json",
        help="write scan results to this JSON file, merging into it by default (default: "
             "/opt/meshpoint/config/dab_channel_scan.json)",
    )
    parser.add_argument(
        "--new", action="store_true",
        help="discard whatever's already in --output instead of merging into it",
    )
    args = parser.parse_args()

    if shutil.which("welle-cli") is None:
        print("welle-cli not found on PATH -- install welle.io first (apt install welle.io)", file=sys.stderr)
        return 1

    total = len(args.channels)
    print(f"Scanning {total} channel(s), up to {args.timeout:.0f}s each "
          f"(~{total * args.timeout / 60:.0f} min worst case)...\n")

    scan_time = datetime.now(timezone.utc).isoformat()
    all_results = []
    hits = []
    for i, channel in enumerate(args.channels, 1):
        print(f"[{i}/{total}] {channel} ...", end=" ", flush=True)
        result = scan_channel(channel, args.port, args.timeout)
        result["scanned_at"] = scan_time
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

    merged_by_channel = {}
    if not args.new and os.path.exists(args.output):
        try:
            with open(args.output) as f:
                existing = json.load(f)
            for c in existing.get("channels", []):
                merged_by_channel[c["channel"]] = c
        except (OSError, ValueError, KeyError) as e:
            print(f"Warning: couldn't read existing {args.output} ({e}) -- starting fresh", file=sys.stderr)
    for r in all_results:
        merged_by_channel[r["channel"]] = merge_channel_result(merged_by_channel.get(r["channel"]), r)
    merged_channels = sorted(merged_by_channel.values(), key=lambda r: channel_sort_key(r["channel"]))

    payload = {
        "last_run_at": scan_time,
        "timeout_seconds": args.timeout,
        "channels": merged_channels,
    }
    output_dir = os.path.dirname(args.output)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(payload, f, indent=2)
    if len(merged_channels) > len(all_results):
        print(f"\nResults merged into {args.output} ({len(merged_channels)} channels total, "
              f"{len(all_results)} scanned this run)")
    else:
        print(f"\nResults written to {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
