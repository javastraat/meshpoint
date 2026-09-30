#!/usr/bin/env python3
"""FFT of a capture file written by ``sniffer --capture``.

Prints the strongest spectral peaks (offset from the RF chain centre and,
for the 4 MHz raw sources, the absolute frequency) and, if matplotlib is
installed, saves a spectrum PNG next to the CSV.

Which RF chain a source belongs to is exactly what the probe is meant to
find out, so ``--center`` lets you override the guess (source 2 -> rf0,
source 3 -> rf1, everything else unknown).

Usage:
    python3 capture_fft.py capture_src03_1759250000.csv
    python3 capture_fft.py capture_src02_*.csv --center 868.3
"""

import argparse
import re
import sys

import numpy as np


def load(path):
    with open(path) as f:
        header = f.readline()
    meta = dict(re.findall(r"(\w+)=(\d+)", header))
    data = np.loadtxt(path, delimiter=",", comments="#", skiprows=2)
    iq = data[:, 0] + 1j * data[:, 1]
    return {k: int(v) for k, v in meta.items()}, iq


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", nargs="+")
    ap.add_argument("--center", type=float, help="RF centre in MHz (overrides the guess)")
    ap.add_argument("--peaks", type=int, default=5)
    args = ap.parse_args()

    for path in args.csv:
        meta, iq = load(path)
        src, rate = meta["source"], meta["rate_hz"]
        if args.center is not None:
            center_hz = args.center * 1e6
        else:
            center_hz = {2: meta.get("rf0_hz"), 3: meta.get("rf1_hz")}.get(src)

        iq = iq - iq.mean()  # drop the DC spike so it doesn't win every time
        spec = np.fft.fftshift(np.fft.fft(iq * np.hanning(len(iq))))
        db = 20 * np.log10(np.abs(spec) + 1e-9)
        freqs = np.fft.fftshift(np.fft.fftfreq(len(iq), d=1.0 / rate))

        print(f"\n{path}: source {src}, {len(iq)} samples @ {rate} Hz "
              f"(span ±{rate / 2e3:.1f} kHz), noise floor (median) {np.median(db):.1f} dB")
        for idx in np.argsort(db)[::-1][: args.peaks]:
            line = f"  {freqs[idx] / 1e3:+9.1f} kHz  {db[idx]:6.1f} dB  ({db[idx] - np.median(db):+.1f} over floor)"
            if center_hz:
                line += f"  = {(center_hz + freqs[idx]) / 1e6:.4f} MHz"
            print(line)

        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
        except ImportError:
            continue
        x = (center_hz + freqs) / 1e6 if center_hz else freqs / 1e3
        plt.figure(figsize=(10, 4))
        plt.plot(x, db, lw=0.6)
        plt.xlabel("MHz" if center_hz else "offset (kHz)")
        plt.ylabel("dB (raw)")
        plt.title(f"capture source {src} @ {rate} Hz")
        plt.grid(alpha=0.3)
        png = path.rsplit(".", 1)[0] + ".png"
        plt.savefig(png, dpi=120, bbox_inches="tight")
        plt.close()
        print(f"  plot: {png}")


if __name__ == "__main__":
    sys.exit(main())
