"""Unit tests for src/api/telemetry/noise_floor.py."""
from __future__ import annotations

import math
import time
import unittest

from src.api.telemetry.noise_floor import (
    CALIBRATING_BELOW,
    MAX_RSSI_FOR_FLOOR_DBM,
    MAX_SNR_FOR_FLOOR_DB,
    NOISE_FIGURE_DB,
    STALE_AFTER_SECONDS,
    NoiseFloorTracker,
    _theoretical_floor,
)


class TestTheoreticalFloor(unittest.TestCase):

    def test_125khz_floor_is_around_minus_117(self) -> None:
        floor = _theoretical_floor(125.0)
        # -174 + 10*log10(125e3) + 6 ~= -117 dBm
        self.assertIsNotNone(floor)
        self.assertAlmostEqual(floor, -117.0, delta=0.5)

    def test_250khz_floor_is_around_minus_114(self) -> None:
        floor = _theoretical_floor(250.0)
        self.assertAlmostEqual(floor, -114.0, delta=0.5)

    def test_500khz_floor_is_around_minus_111(self) -> None:
        floor = _theoretical_floor(500.0)
        self.assertAlmostEqual(floor, -111.0, delta=0.5)

    def test_zero_or_none_returns_none(self) -> None:
        self.assertIsNone(_theoretical_floor(0))
        self.assertIsNone(_theoretical_floor(None))


class TestNoiseFloorTracker(unittest.TestCase):

    def test_first_sample_seeds_ema_with_value(self) -> None:
        tracker = NoiseFloorTracker()
        sample = tracker.update(rssi_dbm=-90, snr_db=5, bandwidth_khz=250)
        self.assertIsNotNone(sample)
        self.assertEqual(sample.noise_dbm, -95.0)

    def test_ema_smooths_subsequent_samples(self) -> None:
        tracker = NoiseFloorTracker(alpha=0.5)
        tracker.update(rssi_dbm=-90, snr_db=5, bandwidth_khz=250)
        # Second sample at -100 (rssi=-95, snr=-5) should land halfway.
        sample = tracker.update(rssi_dbm=-95, snr_db=-5, bandwidth_khz=250)
        self.assertAlmostEqual(sample.noise_dbm, -92.5, places=1)

    def test_none_inputs_return_none(self) -> None:
        tracker = NoiseFloorTracker()
        self.assertIsNone(tracker.update(rssi_dbm=None, snr_db=5))
        self.assertIsNone(tracker.update(rssi_dbm=-90, snr_db=None))

    def test_nan_inputs_are_dropped(self) -> None:
        tracker = NoiseFloorTracker()
        self.assertIsNone(
            tracker.update(rssi_dbm=float("nan"), snr_db=5, bandwidth_khz=250)
        )

    def test_zero_snr_with_real_rssi_is_treated_as_unknown(self) -> None:
        # Encrypted Meshtastic packets sometimes set snr=0.0 as a placeholder;
        # we should drop those rather than report noise = rssi.
        tracker = NoiseFloorTracker()
        self.assertIsNone(
            tracker.update(rssi_dbm=-95, snr_db=0.0, bandwidth_khz=250)
        )

    def test_below_theoretical_floor_is_clamped(self) -> None:
        # 250 kHz floor is ~-114 dBm; -130 is below it and should be rejected.
        tracker = NoiseFloorTracker()
        self.assertIsNone(
            tracker.update(rssi_dbm=-128, snr_db=2, bandwidth_khz=250)
        )

    def test_buffer_bounded_to_capacity(self) -> None:
        tracker = NoiseFloorTracker(buffer_size=5)
        for i in range(20):
            tracker.update(rssi_dbm=-90 - i * 0.1, snr_db=5, bandwidth_khz=250)
        snap = tracker.snapshot()
        self.assertEqual(len(snap["samples_dbm"]), 5)

    def test_snapshot_includes_bandwidth_and_floor(self) -> None:
        tracker = NoiseFloorTracker()
        tracker.update(rssi_dbm=-95, snr_db=8, bandwidth_khz=250)
        snap = tracker.snapshot()
        self.assertEqual(snap["bandwidth_khz"], 250)
        self.assertAlmostEqual(snap["theoretical_floor_dbm"], -114.0, delta=0.5)
        self.assertEqual(snap["value_dbm"], -103.0)
        self.assertFalse(snap["stale"])

    def test_snapshot_marks_stale_when_no_recent_sample(self) -> None:
        tracker = NoiseFloorTracker()
        # Inject a synthetic old sample and verify staleness.
        old_ts = time.time() - (STALE_AFTER_SECONDS + 5)
        tracker.update(
            rssi_dbm=-90, snr_db=5, bandwidth_khz=250, timestamp=old_ts,
        )
        snap = tracker.snapshot()
        self.assertTrue(snap["stale"])

    def test_reset_clears_state(self) -> None:
        tracker = NoiseFloorTracker()
        tracker.update(rssi_dbm=-90, snr_db=5, bandwidth_khz=250)
        tracker.reset()
        snap = tracker.snapshot()
        self.assertIsNone(snap["value_dbm"])
        self.assertEqual(len(snap["samples_dbm"]), 0)
        self.assertTrue(snap["stale"])

    def test_unknown_bandwidth_uses_global_clamp(self) -> None:
        tracker = NoiseFloorTracker()
        # Without a bandwidth we accept any value in [-150, 0].
        self.assertIsNotNone(tracker.update(rssi_dbm=-90, snr_db=5))
        self.assertIsNone(tracker.update(rssi_dbm=-200, snr_db=5))


class TestStrongPacketRejection(unittest.TestCase):
    """Strong nearby packets bias the floor low (clipped SNR register).

    The tracker should drop them so the EMA only sees weak packets
    where ``noise = rssi - snr`` is a faithful estimate.
    """

    def test_strong_rssi_is_rejected(self) -> None:
        tracker = NoiseFloorTracker()
        # A strong nearby packet at -50 dBm with the SNR register
        # clipped at +22 dB would compute noise = -72 dBm. That's
        # what users were seeing as "red" in rural-quiet locations.
        result = tracker.update(rssi_dbm=-50, snr_db=22, bandwidth_khz=250)
        self.assertIsNone(result)
        snap = tracker.snapshot()
        self.assertIsNone(snap["value_dbm"])

    def test_high_snr_is_rejected_even_when_rssi_is_low(self) -> None:
        # Even a weak-looking RSSI with extreme SNR is suspect: SNR
        # >12 dB is rare for a packet truly near the noise floor.
        tracker = NoiseFloorTracker()
        result = tracker.update(rssi_dbm=-95, snr_db=18, bandwidth_khz=250)
        self.assertIsNone(result)

    def test_weak_packet_below_threshold_is_accepted(self) -> None:
        tracker = NoiseFloorTracker()
        # -95 dBm RSSI with +5 dB SNR is exactly the kind of packet
        # we want — likely far away, demod working near sensitivity.
        sample = tracker.update(rssi_dbm=-95, snr_db=5, bandwidth_khz=250)
        self.assertIsNotNone(sample)
        self.assertEqual(sample.noise_dbm, -100.0)

    def test_filter_thresholds_match_docstring(self) -> None:
        self.assertEqual(MAX_RSSI_FOR_FLOOR_DBM, -85.0)
        self.assertEqual(MAX_SNR_FOR_FLOOR_DB, 12.0)


class TestCalibratingFlag(unittest.TestCase):

    def test_calibrating_until_threshold_samples_collected(self) -> None:
        tracker = NoiseFloorTracker()
        for _ in range(CALIBRATING_BELOW - 1):
            tracker.update(rssi_dbm=-95, snr_db=5, bandwidth_khz=250)
        snap = tracker.snapshot()
        self.assertTrue(snap["calibrating"])
        self.assertEqual(snap["samples_count"], CALIBRATING_BELOW - 1)

    def test_not_calibrating_once_enough_samples_collected(self) -> None:
        tracker = NoiseFloorTracker()
        for _ in range(CALIBRATING_BELOW):
            tracker.update(rssi_dbm=-95, snr_db=5, bandwidth_khz=250)
        snap = tracker.snapshot()
        self.assertFalse(snap["calibrating"])
        self.assertEqual(snap["samples_count"], CALIBRATING_BELOW)

    def test_calibrating_when_no_samples_yet(self) -> None:
        tracker = NoiseFloorTracker()
        snap = tracker.snapshot()
        self.assertTrue(snap["calibrating"])
        self.assertEqual(snap["samples_count"], 0)
        self.assertIsNone(snap["value_dbm"])


class TestNoiseFigureSanity(unittest.TestCase):
    """Defensive: the constants used in the formula match what's documented."""

    def test_noise_figure_constant_matches_doc(self) -> None:
        self.assertEqual(NOISE_FIGURE_DB, 6.0)


if __name__ == "__main__":
    unittest.main()
