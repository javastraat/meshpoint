"""Tests for the SX1302 capture-RAM Band Spectrum fallback.

Covers the three layers separately, all runnable without hardware:
  - ``sx1302_capture_ram``: 12-bit I/Q word decoding (same layout as
    extra/sniffer.c's capture_decode) and the register sequence.
  - ``capture_ram_spectrum``: the pure-Python FFT and the per-point
    dB-over-floor accumulator (tone detection, AGC independence, radio
    coverage/overlap).
  - ``CaptureRamSpectrumService`` + ``SX1302Wrapper.capture_ram_snapshot``:
    sweep envelope shape, failure handling, the TX-busy skip and the HAL
    lock that keeps receive() off the bus during a capture.
"""
from __future__ import annotations

import asyncio
import cmath
import ctypes
import math
import random
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from src.api.telemetry.capture_ram_spectrum import (
    CaptureSweepAccumulator,
    fft,
    segment_power_db,
)
from src.api.telemetry.capture_ram_spectrum_service import CaptureRamSpectrumService
from src.hal.sx1302_capture_ram import (
    CAPTURE_RAM_SIZE,
    RAW_SAMPLE_RATE_HZ,
    SOURCE_RADIO_A,
    SOURCE_RADIO_B,
    decode_iq_12bit,
    read_capture_ram,
)
from src.hal.sx1302_wrapper import TX_STATUS_EMITTING, TX_STATUS_FREE, SX1302Wrapper

_N_SAMPLES = CAPTURE_RAM_SIZE // 4
_EU_GRID = list(range(863_000_000, 870_000_001, 100_000))


def _encode_iq(samples: list[complex]) -> bytes:
    """Inverse of decode_iq_12bit: 12-bit I/Q packed into 32-bit words."""
    out = bytearray()
    for s in samples:
        i = max(-2048, min(2047, int(round(s.real))))
        q = max(-2048, min(2047, int(round(s.imag))))
        out += (q << 4).to_bytes(2, "little", signed=True)
        out += (i << 4).to_bytes(2, "little", signed=True)
    return bytes(out)


def _noise_with_tone(
    rng: random.Random,
    noise_amp: float = 20.0,
    tone_hz: float | None = None,
    tone_amp: float = 0.0,
) -> list[complex]:
    out = []
    for k in range(_N_SAMPLES):
        v = complex(rng.gauss(0, noise_amp), rng.gauss(0, noise_amp))
        if tone_hz is not None:
            v += tone_amp * cmath.exp(2j * math.pi * tone_hz * k / RAW_SAMPLE_RATE_HZ)
        out.append(v)
    return out


class TestDecode(unittest.TestCase):
    def test_round_trip_signed_values(self) -> None:
        samples = [complex(0, 0), complex(2047, -2048), complex(-1, 1), complex(-300, 512)]
        self.assertEqual(decode_iq_12bit(_encode_iq(samples)), samples)

    def test_word_layout_matches_sniffer(self) -> None:
        # w3:w2 = 0x7FF0 -> I = 2047, w1:w0 = 0x8000 -> Q = -2048
        self.assertEqual(decode_iq_12bit(bytes([0x00, 0x80, 0xF0, 0x7F])), [complex(2047, -2048)])


class TestFft(unittest.TestCase):
    def test_matches_naive_dft(self) -> None:
        rng = random.Random(1)
        x = [complex(rng.uniform(-1, 1), rng.uniform(-1, 1)) for _ in range(16)]
        naive = [
            sum(x[t] * cmath.exp(-2j * math.pi * k * t / 16) for t in range(16))
            for k in range(16)
        ]
        for a, b in zip(fft(x), naive):
            self.assertAlmostEqual(a, b, places=9)

    def test_rejects_non_power_of_two(self) -> None:
        with self.assertRaises(ValueError):
            fft([0j] * 12)

    def test_segment_count_and_centre_ordering(self) -> None:
        rng = random.Random(2)
        iq = _noise_with_tone(rng, tone_hz=500_000, tone_amp=400)
        spectra = segment_power_db(iq)
        self.assertEqual(len(spectra), _N_SAMPLES // 256)
        # +500 kHz at 15.625 kHz/bin = 32 bins above centre (bin 128).
        peak_bin = max(range(256), key=lambda k: spectra[0][k])
        self.assertEqual(peak_bin, 128 + 32)


class TestAccumulator(unittest.TestCase):
    def _acc(self, centers=(868_300_000, 869_525_000)) -> CaptureSweepAccumulator:
        return CaptureSweepAccumulator(_EU_GRID, list(centers), RAW_SAMPLE_RATE_HZ)

    def test_coverage_is_usable_span_around_each_radio(self) -> None:
        covered = self._acc().covered_hz
        self.assertEqual(covered[0], 866_800_000)
        self.assertEqual(covered[-1], 870_000_000)   # band limit, not radio B's edge
        self.assertNotIn(866_700_000, covered)

    def test_tone_shows_up_at_its_frequency_only(self) -> None:
        rng = random.Random(3)
        acc = self._acc()
        for _ in range(4):
            acc.add_capture(0, _noise_with_tone(rng, tone_hz=300_000, tone_amp=300))
            acc.add_capture(1, _noise_with_tone(rng))
        points = {p["frequency_mhz"]: p for p in acc.points()}
        tone = points[868.6]
        self.assertGreater(tone["median_dbm"], 20.0)
        quiet = [p for f, p in points.items() if abs(f - 868.6) > 0.2]
        for p in quiet:
            self.assertLess(abs(p["median_dbm"]), 3.0, p)

    def test_levels_are_independent_of_capture_gain(self) -> None:
        """AGC scales noise and signal together; dB over floor must not move."""
        low, high = self._acc(), self._acc()
        rng_a, rng_b = random.Random(4), random.Random(4)
        for _ in range(2):
            low.add_capture(0, _noise_with_tone(rng_a, 10, 300_000, 150))
            high.add_capture(0, _noise_with_tone(rng_b, 100, 300_000, 1500))
        a = {p["frequency_mhz"]: p["median_dbm"] for p in low.points()}
        b = {p["frequency_mhz"]: p["median_dbm"] for p in high.points()}
        self.assertAlmostEqual(a[868.6], b[868.6], delta=1.0)

    def test_overlap_takes_nearest_radio(self) -> None:
        acc = self._acc()
        rng = random.Random(5)
        # Only radio B gets captures: points nearer radio A stay empty.
        acc.add_capture(1, _noise_with_tone(rng))
        freqs = [p["frequency_mhz"] for p in acc.points()]
        self.assertNotIn(868.8, freqs)    # nearer 868.3 (A)
        self.assertIn(869.0, freqs)       # nearer 869.525 (B)

    def test_no_captures_no_points(self) -> None:
        self.assertEqual(self._acc().points(), [])


class _FakeWrapper:
    capture_ram_supported = True

    def __init__(self, centers=(868_300_000, 869_525_000), fail=False, tone_hz=None) -> None:
        self.rf_center_hz = centers
        self._fail = fail
        self._tone_hz = tone_hz   # steady tone on radio A, e.g. a fake filter bump
        self._rng = random.Random(6)
        self.sources: list[int] = []

    def capture_ram_snapshot(self, source: int):
        self.sources.append(source)
        if self._fail:
            return None
        if source == SOURCE_RADIO_A and self._tone_hz is not None:
            return _encode_iq(_noise_with_tone(self._rng, 20, self._tone_hz, 200))
        return _encode_iq(_noise_with_tone(self._rng))


class TestService(unittest.TestCase):
    def _service(self, wrapper, **kw) -> CaptureRamSpectrumService:
        return CaptureRamSpectrumService(
            wrapper, _EU_GRID, captures_per_radio=2, capture_gap_seconds=0, **kw,
        )

    def test_sweep_envelope_shape(self) -> None:
        wrapper = _FakeWrapper()
        svc = self._service(wrapper)
        asyncio.run(svc._run_sweep())
        sweep = svc.latest_sweep
        self.assertEqual(sweep["units"], "db_rel")
        self.assertEqual(sweep["source"], "capture_ram")
        self.assertEqual(sweep["captures"], 4)
        self.assertEqual(sweep["point_count"], len(sweep["points"]))
        self.assertEqual(
            set(sweep["points"][0]),
            {"frequency_mhz", "floor_dbm", "median_dbm", "p95_dbm"},
        )
        self.assertEqual(wrapper.sources, [SOURCE_RADIO_A, SOURCE_RADIO_B] * 2)

    def test_identical_centres_capture_one_radio(self) -> None:
        wrapper = _FakeWrapper(centers=(869_525_000, 869_525_000))
        asyncio.run(self._service(wrapper)._run_sweep())
        self.assertEqual(wrapper.sources, [SOURCE_RADIO_A] * 2)

    def test_all_captures_failing_keeps_no_sweep(self) -> None:
        svc = self._service(_FakeWrapper(fail=True))
        asyncio.run(svc._run_sweep())
        self.assertIsNone(svc.latest_sweep)
        self.assertEqual(svc.captures_failed, 4)

    def test_unsupported_hal_means_no_sweep_support(self) -> None:
        wrapper = _FakeWrapper()
        wrapper.capture_ram_supported = False
        svc = self._service(wrapper)
        self.assertFalse(svc.sweep_supported)
        self.assertFalse(svc.request_sweep())

    def test_request_sweep_runs_on_demand_with_interval_zero(self) -> None:
        async def run() -> CaptureRamSpectrumService:
            svc = self._service(_FakeWrapper(), sweep_interval_seconds=0)
            await svc.start()
            self.assertTrue(svc.request_sweep())
            for _ in range(200):
                if svc.latest_sweep is not None:
                    break
                await asyncio.sleep(0.01)
            await svc.stop()
            return svc

        self.assertIsNotNone(asyncio.run(run()).latest_sweep)


class TestCalibrationAndHistogram(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "capture_ram_baseline.json"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _service(self, wrapper) -> CaptureRamSpectrumService:
        return CaptureRamSpectrumService(
            wrapper, _EU_GRID, captures_per_radio=2, calibration_captures_per_radio=4,
            capture_gap_seconds=0, baseline_path=self.path,
            channel_hz=869_525_000, channel_bw_hz=250_000,
        )

    @staticmethod
    def _median_at(svc, mhz) -> float:
        return {p["frequency_mhz"]: p["median_dbm"] for p in svc.latest_sweep["points"]}[mhz]

    def test_calibration_flattens_a_steady_shape_and_persists(self) -> None:
        wrapper = _FakeWrapper(tone_hz=-300_000)          # steady bump at 868.0
        svc = self._service(wrapper)
        asyncio.run(svc._run_sweep())
        self.assertGreater(self._median_at(svc, 868.0), 15)
        self.assertFalse(svc.latest_sweep["calibrated"])

        before = svc.latest_sweep["generated_at"]
        asyncio.run(svc._run_sweep(calibrate=True))
        # The calibration sweep itself is never shown (flat by definition).
        self.assertEqual(svc.latest_sweep["generated_at"], before)
        self.assertTrue(self.path.exists())
        asyncio.run(svc._run_sweep())
        self.assertTrue(svc.latest_sweep["calibrated"])
        self.assertLess(abs(self._median_at(svc, 868.0)), 3)

        # A fresh service (restart) picks the baseline up from disk.
        fresh = self._service(wrapper)
        fresh._load_baseline()
        self.assertTrue(fresh.calibration_status()["calibrated"])

    def test_calibration_request_publishes_a_normal_sweep_after(self) -> None:
        svc = self._service(_FakeWrapper())
        svc._calibration_requested = True
        asyncio.run(svc._next_sweep())
        self.assertTrue(svc.latest_sweep["calibrated"])
        self.assertEqual(svc.latest_sweep["captures"], 4)   # normal sweep, not the 8-capture calibration
        self.assertFalse(svc._calibration_requested)

    def test_baseline_ignored_when_rf_centres_change(self) -> None:
        svc = self._service(_FakeWrapper())
        asyncio.run(svc._run_sweep(calibrate=True))
        svc._wrapper.rf_center_hz = (868_100_000, 869_525_000)
        self.assertFalse(svc.calibration_status()["calibrated"])

    def test_clear_calibration_removes_file(self) -> None:
        svc = self._service(_FakeWrapper())
        asyncio.run(svc._run_sweep(calibrate=True))
        svc.clear_calibration()
        self.assertFalse(self.path.exists())
        self.assertFalse(svc.calibration_status()["calibrated"])

    def test_unreadable_baseline_is_ignored(self) -> None:
        self.path.write_text("{not json")
        svc = self._service(_FakeWrapper())
        svc._load_baseline()
        self.assertFalse(svc.calibration_status()["calibrated"])

    def test_histogram_from_tuned_channel(self) -> None:
        svc = self._service(_FakeWrapper())
        self.assertIsNone(svc.histogram_payload())
        asyncio.run(svc._run_sweep())
        hist = svc.histogram_payload()
        self.assertEqual(hist["units"], "db_rel")
        self.assertEqual(hist["frequency_hz"], 869_525_000)
        # 2 radio-B captures x 16 segments
        self.assertEqual(hist["total_samples"], 32)
        self.assertEqual(len(hist["levels_dbm"]), len(hist["counts"]))
        self.assertLess(abs(hist["median_dbm"]), 4)


class TestRoutes(unittest.TestCase):
    def test_rf_status_message_for_capture_ram(self) -> None:
        from src.api.routes import rf_routes
        svc = CaptureRamSpectrumService(_FakeWrapper(), _EU_GRID)
        self.assertIn("capture RAM", rf_routes._fallback_message(svc))
        self.assertIsNone(rf_routes._fallback_message(object()))

    def test_rf_status_reports_sweep_interval_for_capture_ram(self) -> None:
        from src.api.routes import rf_routes
        from src.config import RadioConfig

        class _Cfg:
            radio = RadioConfig(spectral_scan_interval_seconds=0,
                                spectrum_sweep_interval_seconds=300)

        svc = CaptureRamSpectrumService(_FakeWrapper(), _EU_GRID)
        saved = (rf_routes._scan_service, rf_routes._config)
        rf_routes._scan_service, rf_routes._config = svc, _Cfg()
        try:
            status = rf_routes._spectral_status()
        finally:
            rf_routes._scan_service, rf_routes._config = saved
        self.assertTrue(status["enabled"])
        self.assertEqual(status["interval_seconds"], 300.0)


def _mock_lib(tx_status: int = TX_STATUS_FREE, complete: int = 1) -> MagicMock:
    lib = MagicMock()

    def _status(_chain, _what, ptr):
        ptr._obj.value = tx_status
        return 0

    def _reg_r(_reg, ptr):
        ptr._obj.value = complete
        return 0

    lib.lgw_status.side_effect = _status
    lib.lgw_reg_r.side_effect = _reg_r
    lib.lgw_mem_rb.return_value = 0
    lib.lgw_receive.return_value = 0
    return lib


def _wrapper(lib: MagicMock) -> SX1302Wrapper:
    w = SX1302Wrapper()
    w._lib = lib
    w._started = True
    w._capture_ram_supported = True
    return w


class TestWrapperCapture(unittest.TestCase):
    def test_snapshot_returns_ram_and_restores_page(self) -> None:
        lib = _mock_lib()
        raw = _wrapper(lib).capture_ram_snapshot(SOURCE_RADIO_B)
        self.assertEqual(len(raw), CAPTURE_RAM_SIZE)
        writes = [c.args for c in lib.lgw_reg_w.call_args_list]
        self.assertIn((1035, SOURCE_RADIO_B), writes)       # source mux
        self.assertEqual(writes[-2:], [(0, 1), (0, 0)])      # page 1, then back to 0

    def test_skipped_while_tx_busy(self) -> None:
        lib = _mock_lib(tx_status=TX_STATUS_EMITTING)
        self.assertIsNone(_wrapper(lib).capture_ram_snapshot(SOURCE_RADIO_A))
        lib.lgw_reg_w.assert_not_called()

    def test_skipped_when_not_started(self) -> None:
        lib = _mock_lib()
        w = _wrapper(lib)
        w._started = False
        self.assertIsNone(w.capture_ram_snapshot(SOURCE_RADIO_A))
        lib.lgw_reg_w.assert_not_called()

    def test_incomplete_capture_returns_none(self) -> None:
        lib = _mock_lib(complete=0)
        self.assertIsNone(read_capture_ram(lib, SOURCE_RADIO_A, sleep=lambda _s: None))
        lib.lgw_mem_rb.assert_not_called()

    def test_receive_skips_poll_while_hal_lock_held(self) -> None:
        lib = _mock_lib()
        w = _wrapper(lib)
        held, release = threading.Event(), threading.Event()

        def holder() -> None:
            with w._hal_lock:
                held.set()
                release.wait(2)

        t = threading.Thread(target=holder)
        t.start()
        held.wait(2)
        try:
            self.assertEqual(w.receive(), [])
            lib.lgw_receive.assert_not_called()
        finally:
            release.set()
            t.join()
        w.receive()
        lib.lgw_receive.assert_called_once()


if __name__ == "__main__":
    unittest.main()
