"""Noise floor tracker.

Derives an estimated RF noise floor (in dBm) from per-packet RSSI and
SNR measurements, takes the rolling minimum across a window of
recent samples, and keeps the buffer for sparkline rendering.

Math:
    noise_dBm = rssi_dBm - snr_dB

That falls out of the SNR definition: SNR is "signal above noise"
in dB, so noise = signal - SNR.

Estimator choice — rolling min:
    For *any* successfully decoded packet, ``rssi - snr`` is an
    upper bound on the actual in-band noise floor: if the noise
    were higher, the demod could not have decoded. Strong nearby
    packets give loose bounds (AGC and demod nonlinearity inflate
    the apparent noise); weaker packets give tighter ones. Taking
    the minimum across a window of recent packets converges toward
    the true floor without filtering out the strong packets that
    rural setups depend on for *any* signal at all.

    An earlier version filtered to RSSI < -85 dBm + SNR < 12 dB
    before feeding an EMA. Rural users hearing only one strong
    neighbour got zero accepted samples and "calibrating" stuck
    forever. The min-based estimator handles both regimes from
    the same code path.

Sanity clamp:
    Theoretical thermal floor ``N0 = -174 + 10*log10(BW_Hz) + NF``
    sits around -117/-114/-111 dBm at 125/250/500 kHz with a 6 dB
    receiver NF. Samples *below* the floor (minus 3 dB slack for
    measurement noise) are physically impossible and dropped.

Saturation guard:
    The SX126x demod's SNR register clips around +22 dB. Packets
    with SNR >= 18 dB are likely clipped and would underestimate
    the noise floor; we drop those. SNR < 18 dB is honest data
    even on a strong packet.

This class is sync and lock-free; the FastAPI app holds a single
instance and feeds it from ``_on_packet_received``. ``snapshot()``
serialises the current state for the websocket frame.
"""
from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass

DEFAULT_BUFFER_SIZE: int = 120
STALE_AFTER_SECONDS: float = 30.0
NOISE_FIGURE_DB: float = 6.0

# Drop samples whose SNR is at/above the SX126x demod's register
# ceiling (it clips around +22 dB). A clipped SNR underestimates the
# noise floor; <18 dB readings are honest even on a strong packet.
MAX_SNR_FOR_FLOOR_DB: float = 18.0
# Number of accepted samples before the rolling-min estimate is
# considered settled. Below this threshold the UI shows
# "calibrating" rather than a number.
CALIBRATING_BELOW: int = 3


@dataclass(slots=True)
class NoiseSample:
    """One per-packet noise estimate."""

    timestamp: float
    noise_dbm: float
    bandwidth_khz: float


class NoiseFloorTracker:
    """Per-process noise floor estimator using rolling min over a buffer."""

    def __init__(
        self,
        buffer_size: int = DEFAULT_BUFFER_SIZE,
    ) -> None:
        self._buffer: deque[NoiseSample] = deque(maxlen=buffer_size)
        self._last_bandwidth_khz: float | None = None
        self._last_sample_at: float | None = None

    def update(
        self,
        rssi_dbm: float | None,
        snr_db: float | None,
        bandwidth_khz: float | None = None,
        timestamp: float | None = None,
    ) -> NoiseSample | None:
        """Push a new RSSI/SNR sample. Returns the sample if accepted."""
        if rssi_dbm is None or snr_db is None:
            return None
        if not math.isfinite(rssi_dbm) or not math.isfinite(snr_db):
            return None
        # Some encrypted/relayed Meshtastic packets ship snr=0.0 as a
        # placeholder; treat that as "unknown" rather than reporting
        # noise = rssi which would be wildly optimistic.
        if snr_db == 0.0 and rssi_dbm < -50:
            return None

        # SX126x demod clips SNR around +22 dB. >=18 dB is treated as
        # likely-clipped and would bias the estimate low.
        if snr_db >= MAX_SNR_FOR_FLOOR_DB:
            return None

        sample_dbm = rssi_dbm - snr_db
        if not _is_physically_plausible(sample_dbm, bandwidth_khz):
            return None

        ts = timestamp if timestamp is not None else time.time()
        sample = NoiseSample(
            timestamp=ts,
            noise_dbm=sample_dbm,
            bandwidth_khz=bandwidth_khz or 0.0,
        )
        self._buffer.append(sample)
        if bandwidth_khz:
            self._last_bandwidth_khz = bandwidth_khz
        self._last_sample_at = ts
        return sample

    def reset(self) -> None:
        """Drop all state. Called on bandwidth changes or test setup."""
        self._buffer.clear()
        self._last_bandwidth_khz = None
        self._last_sample_at = None

    @property
    def rolling_min(self) -> float | None:
        """Lowest sample in the current buffer (the noise-floor estimate).

        ``rssi - snr`` is an upper bound on the true noise floor for
        each individual packet, so the running minimum across the
        buffer converges toward the actual floor as more packets
        arrive. Returns None when the buffer is empty.
        """
        if not self._buffer:
            return None
        return min(s.noise_dbm for s in self._buffer)

    @property
    def rolling_mean(self) -> float | None:
        """Average sample over the buffer.

        Indicative of channel busyness rather than the noise floor:
        rises during heavy nearby traffic, falls when the band is
        quiet. Exposed for the future channel-utilisation widget.
        """
        if not self._buffer:
            return None
        total = sum(s.noise_dbm for s in self._buffer)
        return total / len(self._buffer)

    def snapshot(self) -> dict:
        """Serialise current state for the websocket frame."""
        now = time.time()
        stale = (
            self._last_sample_at is None
            or (now - self._last_sample_at) > STALE_AFTER_SECONDS
        )
        floor = self.rolling_min
        mean = self.rolling_mean
        return {
            "value_dbm": (
                round(floor, 1) if floor is not None else None
            ),
            "mean_dbm": (
                round(mean, 1) if mean is not None else None
            ),
            "bandwidth_khz": self._last_bandwidth_khz,
            "samples_dbm": [
                round(s.noise_dbm, 1) for s in self._buffer
            ],
            "samples_count": len(self._buffer),
            "calibrating": len(self._buffer) < CALIBRATING_BELOW,
            "last_seen_at": (
                self._last_sample_at if self._last_sample_at else None
            ),
            "stale": stale,
            "theoretical_floor_dbm": _theoretical_floor(
                self._last_bandwidth_khz
            ),
        }


def _theoretical_floor(bandwidth_khz: float | None) -> float | None:
    """Return the kTB+NF noise floor for a bandwidth, or None."""
    if not bandwidth_khz or bandwidth_khz <= 0:
        return None
    bandwidth_hz = bandwidth_khz * 1000.0
    floor = -174.0 + 10.0 * math.log10(bandwidth_hz) + NOISE_FIGURE_DB
    return round(floor, 1)


def _is_physically_plausible(
    sample_dbm: float, bandwidth_khz: float | None
) -> bool:
    """Reject samples that violate physics (below thermal floor)."""
    floor = _theoretical_floor(bandwidth_khz)
    if floor is None:
        # Unknown bandwidth; fall back to a generous global floor.
        return -150.0 <= sample_dbm <= 0.0
    # Allow ~3 dB slack for measurement noise.
    return (floor - 3.0) <= sample_dbm <= 0.0
