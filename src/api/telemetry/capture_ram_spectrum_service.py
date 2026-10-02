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
chain's centre (EU868: ~866.8-871.0 MHz), and levels are dB over the
noise floor, not dBm (the radios' AGC makes absolute levels
meaningless); the sweep says so via ``units``/``source`` so the card can
label it.

Exposes the same duck-typed surface ``spectrum_routes.py`` uses for the
other two services (``sweep_supported``, ``latest_sweep``,
``request_sweep()``). It deliberately does not feed the noise-floor
histogram/``rf_routes``: relative dB can't stand in for a dBm floor.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from src.api.telemetry.capture_ram_spectrum import CaptureSweepAccumulator
from src.hal.sx1302_capture_ram import (
    RAW_SAMPLE_RATE_HZ,
    SOURCE_RADIO_A,
    SOURCE_RADIO_B,
    decode_iq_12bit,
)

if TYPE_CHECKING:
    from src.hal.sx1302_wrapper import SX1302Wrapper

logger = logging.getLogger(__name__)

DEFAULT_SWEEP_INTERVAL_SECONDS: float = 300.0
# Snapshots per radio per sweep. Each is only ~1 ms of air, so several,
# spread out in time, make the median/p95 mean something.
DEFAULT_CAPTURES_PER_RADIO: int = 8
# Pause between snapshots: lets the receive loop (which skips polls
# while a capture holds the HAL lock) catch up, and spreads the
# snapshots over ~4 s so they don't all land in the same packet.
DEFAULT_CAPTURE_GAP_SECONDS: float = 0.25
# Let RX settle after lgw_start() before the first sweep.
_STARTUP_DELAY_SECONDS: float = 15.0


class CaptureRamSpectrumService:
    """Periodic capture-RAM band sweep for the Band Spectrum card."""

    def __init__(
        self,
        wrapper: "SX1302Wrapper",
        sweep_frequencies_hz: list[int],
        sweep_interval_seconds: float = DEFAULT_SWEEP_INTERVAL_SECONDS,
        captures_per_radio: int = DEFAULT_CAPTURES_PER_RADIO,
        capture_gap_seconds: float = DEFAULT_CAPTURE_GAP_SECONDS,
        startup_delay_seconds: float = _STARTUP_DELAY_SECONDS,
    ) -> None:
        self._wrapper = wrapper
        self._grid_hz = list(sweep_frequencies_hz)
        # 0 = no automatic sweeps; "Sweep now" still works.
        self._sweep_interval_seconds = max(0.0, sweep_interval_seconds)
        self._captures_per_radio = max(1, captures_per_radio)
        self._capture_gap_seconds = max(0.0, capture_gap_seconds)
        self._startup_delay_seconds = max(0.0, startup_delay_seconds)
        self._sweep_requested = asyncio.Event()
        self._task: Optional[asyncio.Task] = None
        self._latest_sweep: Optional[dict] = None
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
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def latest_sweep(self) -> Optional[dict]:
        return self._latest_sweep

    @property
    def sweeps_run(self) -> int:
        return self._sweeps_run

    @property
    def captures_failed(self) -> int:
        return self._captures_failed

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
                await self._run_sweep()
            while True:
                timeout = self._sweep_interval_seconds or None
                await self._wait(timeout)
                await self._run_sweep()
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

    def _radios(self) -> list[tuple[int, int]]:
        """(capture source, RF centre) per distinct radio centre."""
        center_a, center_b = self._wrapper.rf_center_hz
        radios = []
        if center_a:
            radios.append((SOURCE_RADIO_A, center_a))
        if center_b and center_b != center_a:
            radios.append((SOURCE_RADIO_B, center_b))
        return radios

    async def _run_sweep(self) -> None:
        self._sweep_requested.clear()
        radios = self._radios()
        if not radios:
            logger.warning("%s: no RF chain centres known yet, skipping", self.name)
            return
        started = time.monotonic()
        acc = CaptureSweepAccumulator(
            self._grid_hz, [c for _, c in radios], RAW_SAMPLE_RATE_HZ,
        )
        for _ in range(self._captures_per_radio):
            for radio_idx, (source, _center) in enumerate(radios):
                ok = await asyncio.to_thread(self._capture_into, acc, radio_idx, source)
                if not ok:
                    self._captures_failed += 1
                await asyncio.sleep(self._capture_gap_seconds)

        points = acc.points()
        if not points:
            logger.warning(
                "%s: sweep produced no points (%d of %d captures usable)",
                self.name, acc.captures_added,
                self._captures_per_radio * len(radios),
            )
            return
        self._sweeps_run += 1
        self._latest_sweep = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "duration_seconds": round(time.monotonic() - started, 2),
            "point_count": len(points),
            "points": points,
            "units": "db_rel",
            "source": "capture_ram",
            "captures": acc.captures_added,
        }
        logger.info(
            "%s: band sweep #%d: %d points from %d captures in %.1fs",
            self.name, self._sweeps_run, len(points), acc.captures_added,
            self._latest_sweep["duration_seconds"],
        )

    def _capture_into(
        self, acc: CaptureSweepAccumulator, radio_idx: int, source: int,
    ) -> bool:
        """Worker-thread body: one snapshot + FFT, folded into ``acc``."""
        raw = self._wrapper.capture_ram_snapshot(source)
        if raw is None:
            return False
        return acc.add_capture(radio_idx, decode_iq_12bit(raw))
