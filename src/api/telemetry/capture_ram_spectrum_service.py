"""Band Spectrum sweeps from the SX1302 capture RAM (no SX1261 needed).

Third and last fallback behind the Band Spectrum card, for boards like
the RAK2287 that have no SX1261: the real ``SpectralScanService`` wins,
then the ``RfEnvCompanionScanService``; this one is only built when both
are absent **and** ``radio.capture_ram_spectrum`` is true (default off).

Each sweep takes a handful of ~1 ms raw I/Q snapshots of radio A and
radio B (capture RAM sources 2/3) through
``SX1302Wrapper.capture_ram_snapshot`` -- which holds the wrapper's HAL
lock and skips while TX is busy -- and folds them into a
``CaptureSweepAccumulator``. Coverage is only +/-1.5 MHz around each RF
chain's centre (EU868: ~866.8-870 MHz), and levels are dB over the
noise floor, not dBm (the radios' AGC makes absolute levels
meaningless); the sweep says so via ``units``/``source`` so the card can
label it.

**Calibration.** The radios' own filter shape shows up in an
uncalibrated sweep (first live run 2026-10-02: a steady +8 dB hump at
867.9-868.0 MHz, -9 dB at radio A's lower edge). ``request_calibration()``
runs a longer sweep and stores its per-point median as a baseline (JSON
in the data dir, so it survives restarts); later sweeps subtract it, so
flat = quiet. The baseline is tied to the RF chain centres it was taken
with and ignored if they change.

Exposes the duck-typed surfaces both consumers already use:
``spectrum_routes.py`` (``sweep_supported``, ``latest_sweep``,
``request_sweep()``) and ``rf_routes._spectral_status()``
(``hardware_supported``, ``is_running``, ``scans_run``,
``scans_failed``, ``histogram_payload()``) -- the Channel histogram is
built from the tuned channel's readings in the latest sweep. It never
feeds the ``NoiseFloorTracker``: relative dB can't stand in for a dBm
floor.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from src.api.telemetry.capture_ram_spectrum import CaptureSweepAccumulator
from src.hal.sx1302_capture_ram import (
    RAW_SAMPLE_RATE_HZ,
    SOURCE_RADIO_A,
    SOURCE_RADIO_B,
    decode_iq_12bit,
)
from src.hal.sx1302_spectral_scan import SpectralScanResult, spectral_scan_result_payload

if TYPE_CHECKING:
    from src.hal.sx1302_wrapper import SX1302Wrapper

logger = logging.getLogger(__name__)

DEFAULT_SWEEP_INTERVAL_SECONDS: float = 300.0
# Snapshots per radio per sweep. Each is only ~1 ms of air, so several,
# spread out in time, make the median/p95 mean something.
DEFAULT_CAPTURES_PER_RADIO: int = 8
# A calibration sweep wants the median shape, so more snapshots.
DEFAULT_CALIBRATION_CAPTURES_PER_RADIO: int = 32
# Pause between snapshots: lets the receive loop (which skips polls
# while a capture holds the HAL lock) catch up, and spreads the
# snapshots over ~4 s so they don't all land in the same packet.
DEFAULT_CAPTURE_GAP_SECONDS: float = 0.25
# Let RX settle after lgw_start() before the first sweep.
_STARTUP_DELAY_SECONDS: float = 15.0
_BASELINE_VERSION = 1


class CaptureRamSpectrumService:
    """Periodic capture-RAM band sweep for the Band Spectrum card."""

    def __init__(
        self,
        wrapper: "SX1302Wrapper",
        sweep_frequencies_hz: list[int],
        sweep_interval_seconds: float = DEFAULT_SWEEP_INTERVAL_SECONDS,
        captures_per_radio: int = DEFAULT_CAPTURES_PER_RADIO,
        calibration_captures_per_radio: int = DEFAULT_CALIBRATION_CAPTURES_PER_RADIO,
        capture_gap_seconds: float = DEFAULT_CAPTURE_GAP_SECONDS,
        startup_delay_seconds: float = _STARTUP_DELAY_SECONDS,
        baseline_path: Optional[Path] = None,
        channel_hz: int = 0,
        channel_bw_hz: int = 0,
    ) -> None:
        self._wrapper = wrapper
        self._grid_hz = list(sweep_frequencies_hz)
        # 0 = no automatic sweeps; "Sweep now" still works.
        self._sweep_interval_seconds = max(0.0, sweep_interval_seconds)
        self._captures_per_radio = max(1, captures_per_radio)
        self._calibration_captures = max(1, calibration_captures_per_radio)
        self._capture_gap_seconds = max(0.0, capture_gap_seconds)
        self._startup_delay_seconds = max(0.0, startup_delay_seconds)
        self._baseline_path = baseline_path
        self._channel_hz = channel_hz
        self._channel_bw_hz = channel_bw_hz
        self._sweep_requested = asyncio.Event()
        self._calibration_requested = False
        self._calibrating = False
        self._task: Optional[asyncio.Task] = None
        self._latest_sweep: Optional[dict] = None
        self._last_histogram: Optional[SpectralScanResult] = None
        self._baseline: Optional[dict] = None
        self._sweeps_run = 0
        self._captures_failed = 0

    @property
    def name(self) -> str:
        return "capture_ram_spectrum"

    @property
    def is_capture_ram(self) -> bool:
        """Duck-typed marker, like the companion's ``is_companion``."""
        return True

    @property
    def sweep_supported(self) -> bool:
        return bool(self._grid_hz) and self._wrapper.capture_ram_supported

    @property
    def hardware_supported(self) -> bool:
        return self.sweep_supported

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def latest_sweep(self) -> Optional[dict]:
        return self._latest_sweep

    @property
    def sweeps_run(self) -> int:
        return self._sweeps_run

    @property
    def scans_run(self) -> int:
        return self._sweeps_run

    @property
    def captures_failed(self) -> int:
        return self._captures_failed

    @property
    def scans_failed(self) -> int:
        return self._captures_failed

    def histogram_payload(self) -> Optional[dict]:
        payload = spectral_scan_result_payload(self._last_histogram)
        if payload is not None:
            payload["units"] = "db_rel"
            payload["source"] = "capture_ram"
        return payload

    # ── calibration ─────────────────────────────────────────────────

    def calibration_status(self) -> dict:
        baseline = self._active_baseline()
        return {
            "supported": True,
            "calibrated": baseline is not None,
            "calibrating": self._calibrating or self._calibration_requested,
            "created_at": baseline.get("created_at") if baseline else None,
        }

    def request_calibration(self) -> bool:
        if not self.sweep_supported or not self.is_running:
            return False
        self._calibration_requested = True
        self._sweep_requested.set()
        return True

    def clear_calibration(self) -> None:
        self._baseline = None
        if self._baseline_path is not None:
            try:
                self._baseline_path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                logger.exception("%s: could not delete %s", self.name, self._baseline_path)
        logger.info("%s: calibration cleared", self.name)

    def _active_baseline(self) -> Optional[dict]:
        """The stored baseline, if it matches the current RF centres."""
        b = self._baseline
        if b is None:
            return None
        if list(b.get("centers_hz", [])) != [c for _, c in self._radios()]:
            return None
        return b

    def _load_baseline(self) -> None:
        if self._baseline_path is None or not self._baseline_path.exists():
            return
        try:
            data = json.loads(self._baseline_path.read_text())
            if data.get("version") != _BASELINE_VERSION:
                return
            data["offsets_db"] = {int(k): float(v) for k, v in data["offsets_db"].items()}
            self._baseline = data
            logger.info(
                "%s: loaded calibration from %s (%s)",
                self.name, self._baseline_path, data.get("created_at"),
            )
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            logger.warning("%s: ignoring unreadable baseline %s", self.name, self._baseline_path)

    def _save_baseline(self, points: list[dict], captures: int) -> None:
        self._baseline = {
            "version": _BASELINE_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "centers_hz": [c for _, c in self._radios()],
            "captures": captures,
            "offsets_db": {
                round(p["frequency_mhz"] * 1e6): p["median_dbm"] for p in points
            },
        }
        if self._baseline_path is None:
            return
        try:
            self._baseline_path.parent.mkdir(parents=True, exist_ok=True)
            on_disk = dict(self._baseline)
            on_disk["offsets_db"] = {str(k): v for k, v in self._baseline["offsets_db"].items()}
            self._baseline_path.write_text(json.dumps(on_disk, indent=1))
        except OSError:
            logger.exception("%s: could not save baseline to %s", self.name, self._baseline_path)

    # ── lifecycle ───────────────────────────────────────────────────

    def request_sweep(self) -> bool:
        if not self.sweep_supported or not self.is_running:
            return False
        self._sweep_requested.set()
        return True

    async def start(self) -> None:
        if not self.sweep_supported:
            logger.warning(
                "%s: not started (capture RAM unsupported by this HAL or no "
                "sweep frequencies for the region)", self.name,
            )
            return
        self._load_baseline()
        self._task = asyncio.create_task(self._loop(), name=self.name)
        logger.info(
            "%s: started (every %.0fs, %d captures per radio)",
            self.name, self._sweep_interval_seconds, self._captures_per_radio,
        )

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        try:
            if self._sweep_interval_seconds > 0:
                await self._wait(self._startup_delay_seconds)
                await self._next_sweep()
            while True:
                timeout = self._sweep_interval_seconds or None
                await self._wait(timeout)
                await self._next_sweep()
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("%s: sweep loop crashed", self.name)

    async def _wait(self, timeout: Optional[float]) -> None:
        """Sleep ``timeout`` (None = forever), waking early on request."""
        try:
            await asyncio.wait_for(self._sweep_requested.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            pass

    async def _next_sweep(self) -> None:
        if self._calibration_requested:
            self._calibration_requested = False
            await self._run_sweep(calibrate=True)
            # The calibration sweep minus its own baseline is flat by
            # definition, so it's never shown; a normal sweep right after
            # is what the card displays.
        await self._run_sweep()

    def _radios(self) -> list[tuple[int, int]]:
        """(capture source, RF centre) per distinct radio centre."""
        center_a, center_b = self._wrapper.rf_center_hz
        radios = []
        if center_a:
            radios.append((SOURCE_RADIO_A, center_a))
        if center_b and center_b != center_a:
            radios.append((SOURCE_RADIO_B, center_b))
        return radios

    # ── sweeping ────────────────────────────────────────────────────

    async def _run_sweep(self, calibrate: bool = False) -> None:
        self._sweep_requested.clear()
        radios = self._radios()
        if not radios:
            logger.warning("%s: no RF chain centres known yet, skipping", self.name)
            return
        self._calibrating = calibrate
        try:
            await self._sweep(radios, calibrate)
        finally:
            self._calibrating = False

    async def _sweep(self, radios: list[tuple[int, int]], calibrate: bool) -> None:
        started = time.monotonic()
        acc = CaptureSweepAccumulator(
            self._grid_hz, [c for _, c in radios], RAW_SAMPLE_RATE_HZ,
            channel_hz=self._channel_hz, channel_bw_hz=self._channel_bw_hz,
        )
        rounds = self._calibration_captures if calibrate else self._captures_per_radio
        for _ in range(rounds):
            for radio_idx, (source, _center) in enumerate(radios):
                ok = await asyncio.to_thread(self._capture_into, acc, radio_idx, source)
                if not ok:
                    self._captures_failed += 1
                await asyncio.sleep(self._capture_gap_seconds)

        points = acc.points()
        if not points:
            logger.warning(
                "%s: %s produced no points (%d of %d captures usable)",
                self.name, "calibration" if calibrate else "sweep",
                acc.captures_added, rounds * len(radios),
            )
            return
        if calibrate:
            self._save_baseline(points, acc.captures_added)
            logger.info(
                "%s: calibrated from %d captures (%d points)",
                self.name, acc.captures_added, len(points),
            )
            return

        baseline = self._active_baseline()
        offsets = baseline["offsets_db"] if baseline else {}
        points = [_apply_offset(p, offsets) for p in points]
        self._last_histogram = self._histogram(acc.channel_values, offsets)

        self._sweeps_run += 1
        self._latest_sweep = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "duration_seconds": round(time.monotonic() - started, 2),
            "point_count": len(points),
            "points": points,
            "units": "db_rel",
            "source": "capture_ram",
            "captures": acc.captures_added,
            "calibrated": baseline is not None,
        }
        logger.info(
            "%s: band sweep #%d: %d points from %d captures in %.1fs%s",
            self.name, self._sweeps_run, len(points), acc.captures_added,
            self._latest_sweep["duration_seconds"],
            " (calibrated)" if baseline else "",
        )

    def _histogram(
        self, values: list[float], offsets: dict[int, float],
    ) -> Optional[SpectralScanResult]:
        """1 dB-bin level histogram of the tuned channel's readings."""
        if not values:
            return None
        offset = 0.0
        if offsets:
            nearest = min(offsets, key=lambda f: abs(f - self._channel_hz))
            offset = offsets[nearest]
        levels = [round(v - offset) for v in values]
        lo, hi = min(levels), max(levels)
        counts = [0] * (hi - lo + 1)
        for lvl in levels:
            counts[lvl - lo] += 1
        return SpectralScanResult(
            levels_dbm=tuple(range(lo, hi + 1)),
            counts=tuple(counts),
            frequency_hz=self._channel_hz,
            nb_scan=len(values),
            timestamp=time.time(),
        )

    def _capture_into(
        self, acc: CaptureSweepAccumulator, radio_idx: int, source: int,
    ) -> bool:
        """Worker-thread body: one snapshot + FFT, folded into ``acc``."""
        raw = self._wrapper.capture_ram_snapshot(source)
        if raw is None:
            return False
        return acc.add_capture(radio_idx, decode_iq_12bit(raw))


def _apply_offset(point: dict, offsets: dict[int, float]) -> dict:
    off = offsets.get(round(point["frequency_mhz"] * 1e6))
    if off is None:
        return point
    return {
        "frequency_mhz": point["frequency_mhz"],
        "floor_dbm": round(point["floor_dbm"] - off, 1),
        "median_dbm": round(point["median_dbm"] - off, 1),
        "p95_dbm": round(point["p95_dbm"] - off, 1),
    }
