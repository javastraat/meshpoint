"""Noise floor tracker.

Derives an estimated RF noise floor (in dBm) from per-packet RSSI and
SNR measurements, smooths the result with an exponential moving
average, and keeps a rolling buffer of recent samples for sparkline
rendering on the dashboard.

Math:
    noise_dBm = rssi_dBm - snr_dB

That falls out of the SNR definition: SNR is "signal above noise"
in dB, so noise = signal - SNR. Per-packet samples are noisy on
their own; ``alpha=0.15`` EMA settles in ~10 packets while staying
responsive to real channel changes.

Sanity clamp:
    The theoretical thermal floor is roughly
        N0 = -174 + 10*log10(BW_Hz) + NF
    For typical SX126x noise figure (~6 dB) the floor sits around
    -117/-114/-111 dBm at 125/250/500 kHz. Samples that compute to
    a noise level *below* the theoretical floor are physically
    impossible and are dropped as bad data.

This class is sync and lock-free; the FastAPI app holds a single
instance and feeds it from ``_on_packet_received``. ``snapshot()``
serialises the current state for the websocket frame.
"""
from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass

DEFAULT_ALPHA: float = 0.15
DEFAULT_BUFFER_SIZE: int = 120
STALE_AFTER_SECONDS: float = 30.0
NOISE_FIGURE_DB: float = 6.0

# Only weak packets give a useful noise floor reading. Strong packets
# saturate the SX126x demodulator's SNR register (it caps around
# +22 dB), so ``noise = rssi - snr`` for a strong nearby packet
# *underestimates* the noise floor by however far the SNR was
# clipped. We restrict samples to packets that are far enough away
# that the demod is operating near sensitivity.
MAX_RSSI_FOR_FLOOR_DBM: float = -85.0
MAX_SNR_FOR_FLOOR_DB: float = 12.0
# Number of accepted samples before we consider the EMA settled.
CALIBRATING_BELOW: int = 5


@dataclass(slots=True)
class NoiseSample:
    """One per-packet noise estimate."""

    timestamp: float
    noise_dbm: float
    bandwidth_khz: float


class NoiseFloorTracker:
    """Per-process noise floor estimator and rolling buffer."""

    def __init__(
        self,
        alpha: float = DEFAULT_ALPHA,
        buffer_size: int = DEFAULT_BUFFER_SIZE,
    ) -> None:
        self._alpha = alpha
        self._buffer: deque[NoiseSample] = deque(maxlen=buffer_size)
        self._ema: float | None = None
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

        # Strong nearby packets have a clipped SNR reading from the
        # demodulator and underestimate the floor. Skip them; the
        # estimator is biased low without this filter and rural users
        # see "noisy red" when they should see "clean green".
        if rssi_dbm > MAX_RSSI_FOR_FLOOR_DBM:
            return None
        if snr_db > MAX_SNR_FOR_FLOOR_DB:
            return None

        sample_dbm = rssi_dbm - snr_db
        if not _is_physically_plausible(sample_dbm, bandwidth_khz):
            return None

        ts = timestamp if timestamp is not None else time.time()
        if self._ema is None:
            self._ema = sample_dbm
        else:
            self._ema = self._alpha * sample_dbm + (1 - self._alpha) * self._ema

        sample = NoiseSample(
            timestamp=ts,
            noise_dbm=self._ema,
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
        self._ema = None
        self._last_bandwidth_khz = None
        self._last_sample_at = None

    def snapshot(self) -> dict:
        """Serialise current state for the websocket frame."""
        now = time.time()
        stale = (
            self._last_sample_at is None
            or (now - self._last_sample_at) > STALE_AFTER_SECONDS
        )
        return {
            "value_dbm": (
                round(self._ema, 1) if self._ema is not None else None
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
