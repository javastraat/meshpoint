"""Capture source for the POCSAG/DAPNET companion (pocsag_companion).

Reads newline-delimited JSON off a USB serial connection to an ESP32
board running that sketch. Unlike the Meshtastic/MeshCore companions,
there is no request/response library here -- the board just prints one
JSON object per decoded page whenever it happens to receive one, plus
assorted plain-text boot/log lines this source simply ignores. Two
request/response commands ride the same line: a ``{"cmd":"status"}``
query, sent once at connect and then again every ``poll_interval_s``
seconds (default 60, see plugin config's ``status_poll_interval_s`` --
still request/response, never an unsolicited device broadcast, so this
shared serial line stays free of chatter that could be mistaken for a
decoded page) -- answered with ``{"type":"status","board":...,
"callsign":...,"freq":...,"hostname":...,"wifi_ssid":...,"wifi_ip":...,
"tx_count":...,"last_tx_ok":...,"uptime_ms":...}`` -- and an on-demand
``{"cmd":"set_callsign",...}`` a dashboard save can trigger (answered
with ``{"type":"set_callsign_result","ok":...}``), both via
``send_command()``.

pyserial's ``readline()`` is blocking, so the actual read loop runs in
a background thread (mirrors ``src/hal/gps_reader.py``'s fallback
path) and hands lines back to the asyncio side via
``loop.call_soon_threadsafe``, matching every other capture source's
``asyncio.Queue``-backed ``packets()`` shape. Outgoing commands are
handed to that same thread through a stdlib ``queue.Queue`` (not
``asyncio.Queue`` -- this queue is drained from the reader thread, not
the event loop) so every serial read/write stays on the one thread
that owns the ``serial.Serial`` object. ``send_command()`` is guarded
by an ``asyncio.Lock`` since only one request/response can be in
flight at a time (the wire protocol has no request-id) -- without it,
the periodic status poll and a manual "Set Callsign" click could race
and silently strand one of the two callers until its own timeout.
"""

from __future__ import annotations

import asyncio
import json
import logging
import queue
import threading
from typing import Any, AsyncIterator, Optional

from src.capture.base import CaptureSource
from src.models.packet import RawCapture
from src.models.signal import SignalMetrics

logger = logging.getLogger(__name__)

# The companion has no RF signal metrics on its JSON serial protocol at
# all -- this is a fixed placeholder for RawCapture's required (non-
# Optional) `signal` field only. The adapted Packet's own `signal`
# stays None; nothing downstream reads these placeholder numbers.
_NO_SIGNAL = SignalMetrics(
    rssi=0.0, snr=0.0, frequency_mhz=439.9875, spreading_factor=0, bandwidth_khz=0.0,
)


class DapnetSerialSource(CaptureSource):
    """Receives decoded POCSAG/DAPNET pages from a companion board over USB serial."""

    def __init__(
        self,
        serial_port: Optional[str] = None,
        serial_baud: int = 115200,
        label: str = "",
        status_poll_interval_s: int = 60,
    ):
        self._port = serial_port
        self._baud = serial_baud
        self._label = label
        self._poll_interval_s = status_poll_interval_s
        self._serial = None
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._running = False
        self._connected = False
        self._status: dict[str, Any] = {}
        self._reader_thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._poll_task: Optional[asyncio.Task] = None
        self._command_queue: "queue.Queue[bytes]" = queue.Queue()
        # Only one request/response command can be in flight at a time --
        # the wire protocol has no request-id, just "write a command,
        # the next matching-type reply is the answer" (same assumption
        # the one-shot status query already relied on). The lock (not
        # just the single-slot fields below) is what actually enforces
        # this against concurrent callers -- see send_command().
        self._command_lock = asyncio.Lock()
        self._pending_expect_type: Optional[str] = None
        self._pending_future: Optional[asyncio.Future] = None

    @property
    def name(self) -> str:
        return f"dapnet_{self._label}" if self._label else "dapnet"

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def status(self) -> dict[str, Any]:
        """Cached reply from the one-shot {"cmd":"status"} query -- board/
        callsign/freq, or {} if the companion hasn't answered yet (query
        lost, or a firmware too old to understand "cmd")."""
        return self._status

    def note_new_callsign(self, callsign: str) -> None:
        """Update the cached status right after a successful set_callsign
        command, so the topbar chip / config-page readout reflect the
        change immediately rather than waiting for another status query
        (which only ever happens once, at connect)."""
        self._status = {**self._status, "callsign": callsign}

    async def send_command(
        self, command: dict, expect_type: str, timeout: float = 5.0,
    ) -> Optional[dict]:
        """Write a JSON command line and wait for the companion's matching
        reply (matched by its "type" field), or None on timeout or if this
        source isn't connected. The actual write happens on the reader
        thread (see _read_loop) so it never races with a readline() call
        already in flight on the same serial.Serial object.

        Serialized by _command_lock -- e.g. the periodic status poll and
        a manual "Set Callsign" click could otherwise both call this at
        once, each overwriting the other's single-slot pending-reply
        state and stranding whichever one loses the race until its own
        timeout, even though the companion would have answered both
        correctly in order.
        """
        async with self._command_lock:
            if not self._connected or self._loop is None:
                return None
            future: asyncio.Future = self._loop.create_future()
            self._pending_expect_type = expect_type
            self._pending_future = future
            self._command_queue.put_nowait(json.dumps(command).encode() + b"\n")
            try:
                return await asyncio.wait_for(future, timeout=timeout)
            except asyncio.TimeoutError:
                return None
            finally:
                self._pending_expect_type = None
                self._pending_future = None

    async def start(self) -> None:
        if not self._port:
            logger.warning(
                "%s: no serial_port configured, source will not run", self.name
            )
            return
        try:
            import serial
            self._serial = serial.Serial(self._port, self._baud, timeout=1.0)
        except Exception:
            logger.exception("%s: failed to open serial port %s", self.name, self._port)
            return

        self._running = True
        self._connected = True
        self._loop = asyncio.get_running_loop()
        self._reader_thread = threading.Thread(
            target=self._read_loop, name=f"{self.name}-reader", daemon=True
        )
        self._reader_thread.start()
        if self._poll_interval_s > 0:
            self._poll_task = asyncio.create_task(
                self._status_poll_loop(), name=f"{self.name}-status-poll"
            )
        logger.info("%s: started on %s @ %d baud", self.name, self._port, self._baud)

    async def stop(self) -> None:
        self._running = False
        self._connected = False
        if self._poll_task is not None:
            self._poll_task.cancel()
            self._poll_task = None
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:
                pass
        self._serial = None

    async def _status_poll_loop(self) -> None:
        """Re-sends {"cmd":"status"} every poll_interval_s seconds so
        tx_count/last_tx_ok/uptime_ms stay current -- the initial query
        at connect only ever fires once. Still request/response (via
        send_command()), just repeated on a timer; the companion never
        pushes this unsolicited."""
        try:
            while self._running:
                await asyncio.sleep(self._poll_interval_s)
                if not self._running:
                    return
                await self.send_command(
                    {"cmd": "status"}, expect_type="status", timeout=5.0
                )
        except asyncio.CancelledError:
            pass

    async def packets(self) -> AsyncIterator[RawCapture]:
        while self._running:
            try:
                raw = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                yield raw
            except asyncio.TimeoutError:
                continue

    def _read_loop(self) -> None:
        """Runs in a background thread -- pyserial's readline() blocks."""
        try:
            self._serial.write(b'{"cmd":"status"}\n')
        except Exception:
            logger.debug("%s: failed to send status query", self.name)

        while self._running and self._serial is not None:
            self._flush_command_queue()
            try:
                line = self._serial.readline()
            except Exception:
                logger.exception("%s: serial read failed on %s", self.name, self._port)
                self._connected = False
                break
            if not line or not line.strip():
                continue
            data = _parse_json_line(line)
            if data is None:
                # Boot banners, WiFi/OTA logs, "SEND BLOCKED"/"SEND FAILED"
                # lines, etc. -- expected and harmless, just not for us.
                continue
            if isinstance(data, dict) and data.get("type") == "status":
                self._status = {
                    "board": data.get("board"),
                    "callsign": data.get("callsign"),
                    "freq": data.get("freq"),
                    "hostname": data.get("hostname"),
                    "wifi_ssid": data.get("wifi_ssid"),
                    "wifi_ip": data.get("wifi_ip"),
                    "tx_count": data.get("tx_count"),
                    "last_tx_ok": data.get("last_tx_ok"),
                    "uptime_ms": data.get("uptime_ms"),
                }
                # The periodic poll (unlike the fire-and-forget initial
                # query at connect) goes through send_command() and is
                # actually awaiting this reply -- resolve it too, not
                # just cache the values, or every poll would silently
                # time out despite the companion replying correctly.
                if self._pending_expect_type == "status":
                    self._resolve_pending(data)
                continue
            if (
                isinstance(data, dict)
                and self._pending_expect_type is not None
                and data.get("type") == self._pending_expect_type
            ):
                self._resolve_pending(data)
                continue
            if self._loop is not None:
                self._loop.call_soon_threadsafe(self._enqueue, line)

    def _flush_command_queue(self) -> None:
        """Write any queued outgoing commands -- called once per read-loop
        pass, so a command queued while readline() is blocked waits at
        most one read timeout (1s) before actually going out."""
        while True:
            try:
                cmd_line = self._command_queue.get_nowait()
            except queue.Empty:
                return
            try:
                self._serial.write(cmd_line)
            except Exception:
                logger.exception("%s: failed to write command", self.name)

    def _resolve_pending(self, data: dict) -> None:
        future = self._pending_future
        if future is None or self._loop is None:
            return

        def _set_result() -> None:
            if not future.done():
                future.set_result(data)

        self._loop.call_soon_threadsafe(_set_result)

    def _enqueue(self, line: bytes) -> None:
        try:
            self._queue.put_nowait(
                RawCapture(payload=line, signal=_NO_SIGNAL, capture_source=self.name)
            )
        except asyncio.QueueFull:
            logger.warning("%s: queue full, dropping line", self.name)


def _parse_json_line(line: bytes) -> Optional[dict]:
    """Parse a serial line as a JSON object, or None if it isn't one.

    Cheap pre-check on the first byte before ever calling json.loads --
    the sketch prints far more plain-text log lines than JSON lines."""
    stripped = line.strip()
    if not stripped or stripped[:1] != b"{":
        return None
    try:
        data = json.loads(stripped)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None
