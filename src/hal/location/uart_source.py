"""UART location source: direct on-board NMEA GPS reading.

Parses GGA (position, altitude, fix quality) and GSA (2D/3D fix mode,
DOP) sentences from a plain NMEA serial stream -- the two sentence
types practically every GPS module emits at minimum, including the
RAK Pi HAT's onboard ZOE-M8Q this source was originally reserved for.

GSV (per-satellite azimuth/elevation/SNR, needed for the GPS card's
skyplot) is deliberately NOT parsed: it arrives as several sentences
per report cycle that have to be accumulated and merged, a genuinely
separate parsing job from GGA/GSA's "one sentence, one update" shape.
GGA+GSA alone already gives a complete, real fix -- position, altitude,
2D/3D mode, and DOP -- so this source works fully for placement and
mesh POSITION broadcasts; the skyplot just stays empty here, same as
it does for ``StaticSource``. Worth adding later if someone wants the
skyplot on UART specifically, not required for the source to be real.

Runs pyserial's blocking API in a background thread via
``asyncio.to_thread`` rather than adding ``pyserial-asyncio`` as a
second serial dependency -- a 1 Hz NMEA stream has no need for a true
async serial API, and ``SerialCaptureSource`` already establishes this
exact blocking-I/O-off-the-event-loop pattern elsewhere in this
codebase for the same reason.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from src.hal.location.base import LocationSource
from src.hal.location.models import GpsDeviceInfo, GpsStatus, LocationFix

logger = logging.getLogger(__name__)

_RECONNECT_DELAY_SECONDS = 5.0
_READ_TIMEOUT_SECONDS = 2.0


class UartSource(LocationSource):
    """Direct on-board UART GPS (RAK Pi HAT ZOE-M8Q and similar)."""

    def __init__(self, device: str = "/dev/ttyAMA0", baud: int = 9600) -> None:
        self._device = device
        self._baud = baud
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()

        self._latest_fix: Optional[LocationFix] = None
        self._last_update: Optional[datetime] = None
        self._connected = False
        self._last_error: Optional[str] = None
        # From GSA -- the authoritative 2D/3D/no-fix mode. GGA's own
        # "fix quality" field is a different axis entirely (invalid /
        # GPS / DGPS / RTK / ...), not dimensionality, so it can't
        # answer "2D or 3D" on its own.
        self._mode = 1
        self._dop: dict[str, float] = {}

    @property
    def source_name(self) -> str:
        return "uart"

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_reader_loop(), name="uart-gps-reader")
        logger.info("UART GPS location source: reading %s @ %d baud", self._device, self._baud)

    async def stop(self) -> None:
        self._stop_event.set()
        task = self._task
        if task is None:
            return
        self._task = None
        if task.done():
            return
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass

    def get_status(self) -> GpsStatus:
        device = GpsDeviceInfo(driver="nmea", path=self._device) if self._connected else None
        if self._connected and self._latest_fix is not None:
            return GpsStatus(
                source="uart",
                available=True,
                fix=self._latest_fix,
                satellites=None,  # GSV not parsed -- see module docstring
                device=device,
                last_update=self._last_update,
            )
        if self._connected:
            # Connected but no fix decoded yet -- still "available" so
            # the GPS card can show "WAITING FOR FIX" rather than
            # treating a cold-starting receiver as an error.
            return GpsStatus(
                source="uart",
                available=True,
                fix=None,
                satellites=None,
                device=device,
                last_update=self._last_update,
            )
        return GpsStatus(
            source="uart",
            available=False,
            fix=None,
            satellites=None,
            device=None,
            last_update=self._last_update,
            error=self._last_error or f"Not connected to {self._device}",
        )

    async def _run_reader_loop(self) -> None:
        """Outer loop: connect, read, reconnect with a fixed delay --
        same self-healing shape as GpsdSource's reconnect loop, just a
        flat delay instead of exponential backoff (a local UART device
        either exists or doesn't; there's no remote peer whose load a
        backoff would be protecting)."""
        while not self._stop_event.is_set():
            try:
                await asyncio.to_thread(self._blocking_read_session)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 -- defensive top-level
                self._last_error = f"{type(exc).__name__}: {exc}"
                logger.debug(
                    "UART GPS session ended: %s -- reconnecting in %.0fs",
                    self._last_error, _RECONNECT_DELAY_SECONDS,
                )
            self._connected = False
            if self._stop_event.is_set():
                break
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=_RECONNECT_DELAY_SECONDS,
                )
                break
            except asyncio.TimeoutError:
                pass

    def _blocking_read_session(self) -> None:
        """Runs entirely off the event loop via asyncio.to_thread. The
        2s read timeout below both recovers from a receiver that's
        gone quiet and gives this loop a chance to notice
        ``_stop_event`` within a bounded time even while blocked in
        readline()."""
        import serial

        ser = serial.Serial(self._device, self._baud, timeout=_READ_TIMEOUT_SECONDS)
        self._connected = True
        self._last_error = None
        logger.info("UART GPS connected at %s", self._device)
        try:
            while not self._stop_event.is_set():
                raw = ser.readline()
                if not raw:
                    continue  # read timeout, not a disconnect -- keep listening
                sentence = raw.decode("ascii", errors="ignore").strip()
                self._handle_sentence(sentence)
        finally:
            ser.close()

    def _handle_sentence(self, sentence: str) -> None:
        if sentence.startswith(("$GPGGA", "$GNGGA")):
            self._handle_gga(sentence)
        elif sentence.startswith(("$GPGSA", "$GNGSA")):
            self._handle_gsa(sentence)
        # Every other sentence (RMC, VTG, GSV, ...) is intentionally
        # ignored -- see module docstring on why GGA+GSA is enough.

    def _handle_gga(self, sentence: str) -> None:
        parts = sentence.split(",")
        if len(parts) < 10:
            return
        try:
            fix_quality = int(parts[6]) if parts[6] else 0
        except ValueError:
            fix_quality = 0
        self._last_update = datetime.now(timezone.utc)
        if fix_quality == 0:
            # No fix on this sentence -- keep whatever fix we already
            # have rather than collapsing the dashboard to zero
            # coordinates over one bad reading (same reasoning as
            # GpsdSource's own low-mode TPV handling).
            return

        lat = _nmea_to_decimal(parts[2], parts[3])
        lon = _nmea_to_decimal(parts[4], parts[5])
        if lat is None or lon is None:
            return
        try:
            altitude = float(parts[9]) if parts[9] else None
        except ValueError:
            altitude = None

        self._latest_fix = LocationFix(
            # GGA alone can't distinguish 2D from 3D; a valid fix here
            # implies at least 2D until a GSA sentence says otherwise.
            mode=self._mode if self._mode >= 2 else 2,
            latitude=lat,
            longitude=lon,
            altitude_m=altitude,
            hdop=self._dop.get("hdop"),
            pdop=self._dop.get("pdop"),
            vdop=self._dop.get("vdop"),
        )

    def _handle_gsa(self, sentence: str) -> None:
        parts = sentence.split(",")
        if len(parts) < 18:
            return
        try:
            if parts[2]:
                self._mode = int(parts[2])
        except ValueError:
            pass

        def _dop_field(index: int) -> Optional[float]:
            if index >= len(parts):
                return None
            raw = parts[index].split("*")[0]  # last field carries the checksum
            try:
                return float(raw) if raw else None
            except ValueError:
                return None

        pdop, hdop, vdop = _dop_field(15), _dop_field(16), _dop_field(17)
        if pdop is not None:
            self._dop["pdop"] = pdop
        if hdop is not None:
            self._dop["hdop"] = hdop
        if vdop is not None:
            self._dop["vdop"] = vdop

        # Merge the freshly-updated mode/DOP into the current fix
        # immediately, rather than waiting for the next GGA to carry
        # them -- GSA and GGA are usually both part of the same report
        # cycle, but there's no guarantee they arrive in a fixed order.
        if self._latest_fix is not None:
            self._latest_fix = LocationFix(
                mode=self._mode,
                latitude=self._latest_fix.latitude,
                longitude=self._latest_fix.longitude,
                altitude_m=self._latest_fix.altitude_m,
                hdop=self._dop.get("hdop"),
                pdop=self._dop.get("pdop"),
                vdop=self._dop.get("vdop"),
            )


def _nmea_to_decimal(coord: str, direction: str) -> Optional[float]:
    """NMEA ``ddmm.mmmm`` / ``dddmm.mmmm`` -> signed decimal degrees."""
    if not coord or not direction:
        return None
    try:
        dot = coord.index(".")
        degrees = int(coord[: dot - 2])
        minutes = float(coord[dot - 2:])
    except (ValueError, IndexError):
        return None
    decimal = degrees + minutes / 60.0
    if direction in ("S", "W"):
        decimal = -decimal
    return round(decimal, 7)
