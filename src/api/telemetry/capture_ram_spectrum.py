"""Spectrum maths for SX1302 capture RAM snapshots (pure Python, no numpy).

Turns raw radio A/B I/Q snapshots (``src/hal/sx1302_capture_ram.py``)
into Band Spectrum sweep points shaped exactly like
``SpectralScanService``'s (``frequency_mhz``/``floor_dbm``/``median_dbm``/
``p95_dbm``), but in **dB over the noise floor**, not dBm:

- The radios' AGC is live (the floor dropped ~30 dB when a strong packet
  was present in the 2026-09-30 probe), so raw levels aren't comparable
  between captures. Each capture is therefore normalised to its own
  median bin, which cancels the gain: what's left is "how far above the
  floor", which is what the card is for.
- A single 4096-point FFT scatters about +/-10 dB, so each capture is
  split into 16 Hann-windowed 256-point segments (15.6 kHz bins). Per
  segment, each 100 kHz sweep point gets the mean power of its ~6 bins
  (the power in that slot, like an RSSI reading -- a narrow carrier
  still lifts it), and floor/median/p95 are taken over those readings
  across all segments and captures.
- Optionally, readings over the tuned channel (``channel_hz`` +/- half
  its bandwidth, e.g. Meshtastic's 869.525 MHz / 250 kHz) are kept as a
  flat list for the RF Environment page's Channel histogram.
- Only +/-``usable_hz`` around each RF centre is used: the radio's
  filter rolls off ~5-8 dB towards +/-2 MHz. Where the two radios
  overlap, a point is taken from the radio whose centre is nearer.
"""
from __future__ import annotations

import cmath
import math
from typing import Optional

SEGMENT_SIZE = 256
DEFAULT_USABLE_HZ = 1_500_000
# Bins this close to the centre carry the DC / LO-leakage spike even
# after mean removal -- never real RF.
_DC_GUARD_BINS = 1

_tables: dict[int, tuple[list[int], list[complex], list[float]]] = {}


def _fft_tables(n: int) -> tuple[list[int], list[complex], list[float]]:
    """Bit-reversal order, twiddles and a Hann window for size ``n``."""
    cached = _tables.get(n)
    if cached is not None:
        return cached
    bits = n.bit_length() - 1
    if 1 << bits != n:
        raise ValueError(f"FFT size must be a power of two, got {n}")
    rev = [int(format(i, f"0{bits}b")[::-1], 2) for i in range(n)]
    twiddles = [cmath.exp(-2j * math.pi * k / n) for k in range(n // 2)]
    window = [0.5 - 0.5 * math.cos(2 * math.pi * k / (n - 1)) for k in range(n)]
    _tables[n] = (rev, twiddles, window)
    return _tables[n]


def fft(samples: list[complex]) -> list[complex]:
    """Iterative radix-2 FFT (length must be a power of two)."""
    n = len(samples)
    rev, twiddles, _ = _fft_tables(n)
    a = [samples[i] for i in rev]
    size = 2
    while size <= n:
        half = size // 2
        step = n // size
        for start in range(0, n, size):
            for k in range(half):
                t = twiddles[k * step] * a[start + k + half]
                u = a[start + k]
                a[start + k] = u + t
                a[start + k + half] = u - t
        size *= 2
    return a


def segment_power_db(iq: list[complex], n: int = SEGMENT_SIZE) -> list[list[float]]:
    """Per-segment power spectra in dB, centre-ordered (bin n/2 = DC)."""
    _, _, window = _fft_tables(n)
    if not iq:
        return []
    mean = sum(iq) / len(iq)
    half = n // 2
    spectra = []
    for start in range(0, len(iq) - n + 1, n):
        seg = [(iq[start + k] - mean) * window[k] for k in range(n)]
        spec = fft(seg)
        shifted = spec[half:] + spec[:half]
        spectra.append([10.0 * math.log10(abs(v) ** 2 + 1e-12) for v in shifted])
    return spectra


def _mean_db(levels_db: list[float]) -> float:
    """Mean power of several dB levels, back in dB."""
    mean = sum(10.0 ** (v / 10.0) for v in levels_db) / len(levels_db)
    return 10.0 * math.log10(mean)


def _percentile(sorted_vals: list[float], pct: float) -> float:
    idx = min(len(sorted_vals) - 1, max(0, round(pct / 100.0 * (len(sorted_vals) - 1))))
    return sorted_vals[idx]


class CaptureSweepAccumulator:
    """Collects dB-over-floor bins per sweep point across many captures."""

    def __init__(
        self,
        grid_hz: list[int],
        centers_hz: list[int],
        sample_rate_hz: int,
        step_hz: int = 100_000,
        usable_hz: int = DEFAULT_USABLE_HZ,
        n: int = SEGMENT_SIZE,
        channel_hz: int = 0,
        channel_bw_hz: int = 0,
    ) -> None:
        self._n = n
        self._usable_hz = usable_hz
        self._bin_hz = sample_rate_hz / n
        self._centers = list(centers_hz)
        # point frequency -> (radio index, [bin indices])
        self._point_bins: dict[int, tuple[int, list[int]]] = {}
        for f in grid_hz:
            radio = self._nearest_radio(f)
            if radio is None:
                continue
            bins = self._bins_for(f, self._centers[radio], step_hz)
            if bins:
                self._point_bins[f] = (radio, bins)
        self._values: dict[int, list[float]] = {f: [] for f in self._point_bins}
        self._channel: Optional[tuple[int, list[int]]] = None
        if channel_hz > 0 and channel_bw_hz > 0:
            radio = self._nearest_radio(channel_hz)
            if radio is not None:
                bins = self._bins_for(channel_hz, self._centers[radio], channel_bw_hz)
                if bins:
                    self._channel = (radio, bins)
        self.channel_values: list[float] = []
        self.captures_added = 0

    @property
    def covered_hz(self) -> list[int]:
        return sorted(self._point_bins)

    def _nearest_radio(self, f: int) -> Optional[int]:
        best, best_dist = None, None
        for i, c in enumerate(self._centers):
            dist = abs(f - c)
            if dist <= self._usable_hz and (best_dist is None or dist < best_dist):
                best, best_dist = i, dist
        return best

    def _bins_for(self, f: int, center: int, step_hz: int) -> list[int]:
        half = self._n // 2
        lo, hi = f - step_hz / 2, f + step_hz / 2
        bins = []
        for k in range(self._n):
            offset = (k - half) * self._bin_hz
            if abs(k - half) <= _DC_GUARD_BINS or abs(offset) > self._usable_hz:
                continue
            if lo <= center + offset < hi:
                bins.append(k)
        return bins

    def add_capture(self, radio: int, iq: list[complex]) -> bool:
        """Fold one capture of radio ``radio`` in; False if unusable."""
        spectra = segment_power_db(iq, self._n)
        mine = [(f, bins) for f, (r, bins) in self._point_bins.items() if r == radio]
        if not spectra or not mine:
            return False
        readings = {
            f: [_mean_db([spec[k] for k in bins]) for spec in spectra]
            for f, bins in mine
        }
        # The capture's own floor: median slot reading across this radio's
        # span. Subtracting it cancels the AGC gain of this capture.
        everything = sorted(v for vals in readings.values() for v in vals)
        floor = everything[len(everything) // 2]
        for f, vals in readings.items():
            self._values[f].extend(v - floor for v in vals)
        if self._channel is not None and self._channel[0] == radio:
            bins = self._channel[1]
            self.channel_values.extend(
                _mean_db([spec[k] for k in bins]) - floor for spec in spectra
            )
        self.captures_added += 1
        return True

    def points(self) -> list[dict]:
        out = []
        for f in sorted(self._values):
            vals = sorted(self._values[f])
            if not vals:
                continue
            out.append({
                "frequency_mhz": round(f / 1e6, 4),
                "floor_dbm": round(_percentile(vals, 5), 1),
                "median_dbm": round(_percentile(vals, 50), 1),
                "p95_dbm": round(_percentile(vals, 95), 1),
            })
        return out
