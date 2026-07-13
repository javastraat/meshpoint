"""RTL-SDR pager decoders (P2000 / Pagers): rtl_fm -> multimon-ng -> decoded
message log.

Unlike the FM listener (src/audio/rtl_listener.py), there's nothing here
meant to be listened to -- multimon-ng's own stdout IS the decoded
output. Read line by line and kept as an in-memory ring buffer, polled
by the frontend on the same status-polling convention the FM listener
already uses (no new WebSocket infrastructure).

Pipeline:  rtl_fm (demod to s16le PCM) | multimon-ng (decode to text)
No ffmpeg stage -- nothing here produces audio.

Fixed per-kind frequency/decoders, not user-tunable (unlike the FM
listener's frequency picker): P2000 (Netherlands emergency dispatch)
runs FLEX on 169.65 MHz; the Pagers kind covers the POCSAG512/1200/2400
variants commonly used around 152-172 MHz depending on operator.

Only one of RtlListener/PagerListener("p2000")/PagerListener("pagers")
may hold the RTL-SDR dongle at a time -- see src/audio/sdr_registry.py.
Manual-stop-required: starting one while another is active raises
RuntimeError rather than silently stopping the other.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shlex
import shutil
import signal
import time
from collections import deque
from typing import Optional

from src.audio import sdr_registry

logger = logging.getLogger(__name__)

_MAX_MESSAGES = 200
_IDLE_STOP_SECS = 600  # mirrors rtl_listener.py's convention
_DEVICE_SETTLE_SECS = 0.4
_START_CHECK_SECS = 0.4
_START_RETRIES = 3

_ERROR_RE = re.compile(
    r"failed|error|cannot|could not|invalid|no supported|usb_",
    re.IGNORECASE,
)

# multimon-ng prints one line per decoded page, prefixed by the decoder
# that caught it (FLEX / POCSAG512 / POCSAG1200 / POCSAG2400). Exact
# field layout can vary a little by multimon-ng version, so parsing is
# best-effort: unmatched-but-recognized lines are still surfaced with
# the raw text rather than silently dropped.
#
# FLEX format confirmed against a real captured P2000 page (2026-07-13,
# `rtl_fm -f 169.65M -M fm -s 22050 -l 250 | multimon-ng -a FLEX -t raw
# /dev/stdin` run manually in a shell) -- it's pipe-delimited, NOT the
# colon/space format originally guessed from documentation alone (no
# RTL-SDR/multimon-ng on the Mac dev machine to test against at the time):
#   FLEX|2026-07-13 18:51:53|1600/2/K/A|13.006|002029582 000120161 000120999|ALN|A1 13161 Heesterveld 1102 Amsterdam 67412
# Field 5 (capcode) can list several space-separated addresses for the same
# page (simulcast/alternate addressing) -- only the first is kept for the
# compact capcode column; the full line is always preserved in `raw`.
_FLEX_RE = re.compile(
    r"^FLEX\|(?P<ts>[^|]+)\|(?P<baud>[^/|]+)/(?P<level>\d)/(?P<phase>[^/|])/(?P<cycle>[^/|])\|"
    r"(?P<frame>[^|]+)\|(?P<capcode>[^|]+)\|(?P<kind>[^|]+)\|(?P<message>.*)$"
)
_POCSAG_RE = re.compile(
    r"^(?P<proto>POCSAG\d+):\s*Address:\s*(?P<address>\d+)\s+Function:\s*(?P<function>\d+)"
    r"(?:\s+Alpha:\s*(?P<message>.*))?$"
)
# multimon-ng pads POCSAG alpha messages with literal "<NUL>" tokens
# (confirmed on real captured output, 2026-07-12) -- strip trailing ones
# for a clean display; they carry no message content.
_TRAILING_NUL_RE = re.compile(r"(?:<NUL>)+\s*$")

_KINDS = {
    "p2000": {
        "frequency_hz": 169_650_000,
        "multimon_args": ["-a", "FLEX"],
    },
    "pagers": {
        "frequency_hz": 172_450_000,
        "multimon_args": ["-a", "POCSAG512", "-a", "POCSAG1200", "-a", "POCSAG2400"],
    },
    "pocsag": {
        "frequency_hz": 439_987_500,
        "multimon_args": ["-a", "POCSAG512", "-a", "POCSAG1200", "-a", "POCSAG2400"],
    },
}


def _parse_line(text: str) -> Optional[dict]:
    """Best-effort structured extraction; always keeps the raw line too
    so nothing is lost if the format doesn't match what's expected."""
    now = time.time()
    m = _FLEX_RE.match(text)
    if m:
        return {
            "protocol": "FLEX",
            "capcode": m.group("capcode").split()[0],
            "message": m.group("message").strip(),
            "raw": text,
            "received_at": now,
        }
    m = _POCSAG_RE.match(text)
    if m:
        message = _TRAILING_NUL_RE.sub("", (m.group("message") or "")).strip()
        return {
            "protocol": m.group("proto"),
            "capcode": m.group("address"),
            "message": message,
            "raw": text,
            "received_at": now,
        }
    if text.startswith(("FLEX|", "FLEX:", "POCSAG")):
        # Recognized protocol prefix but didn't match the expected field
        # layout (version/format drift) -- still surface it raw rather
        # than silently dropping a real decoded page.
        return {
            "protocol": "unknown", "capcode": "", "message": text,
            "raw": text, "received_at": now,
        }
    return None  # startup banner, blank lines, etc -- not a decoded page


class PagerListener:
    """Owns one rtl_fm|multimon-ng pipeline for a fixed pager protocol set."""

    def __init__(self, kind: str) -> None:
        if kind not in _KINDS:
            raise ValueError(f"unknown pager kind {kind!r}; one of {sorted(_KINDS)}")
        self.kind = kind
        self._spec = _KINDS[kind]
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._reader_task: Optional[asyncio.Task] = None
        self._stderr_task: Optional[asyncio.Task] = None
        self._idle_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        self._last_error: str = ""
        self._last_poll_at: float = 0.0
        self.messages: "deque[dict]" = deque(maxlen=_MAX_MESSAGES)

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    async def start(self) -> None:
        """Raises RuntimeError if binaries are missing or the dongle is
        currently claimed by the FM listener or the other pager kind."""
        if shutil.which("rtl_fm") is None:
            raise RuntimeError("rtl_fm not found on PATH")
        if shutil.which("multimon-ng") is None:
            raise RuntimeError("multimon-ng not found on PATH")

        async with self._lock:
            if self.running:
                return  # already running, idempotent
            sdr_registry.claim(self.kind)
            try:
                await self._start_locked_retrying()
            except Exception:
                sdr_registry.release(self.kind)
                raise

    async def stop(self) -> None:
        async with self._lock:
            await self._stop_locked()

    def poll(self) -> dict:
        """Called by the status endpoint; marks activity for the idle watchdog."""
        self._last_poll_at = time.monotonic()
        return self.status()

    def status(self) -> dict:
        return {
            "kind": self.kind,
            "running": self.running,
            "frequency_hz": self._spec["frequency_hz"],
            "frequency_mhz": round(self._spec["frequency_hz"] / 1e6, 6),
            "message_count": len(self.messages),
            "messages": list(self.messages),
            "last_error": self._last_error,
            # Who currently holds the shared RTL-SDR dongle (None = free,
            # this kind, or the other listener) -- lets the frontend show
            # "busy" instead of a bare "idle" when someone else has it.
            "dongle_owner": sdr_registry.current_owner(),
        }

    # ── pipeline management (call with self._lock held) ──────────

    async def _start_locked(self) -> None:
        rtl_cmd = [
            "rtl_fm", "-d", "0", "-f", str(self._spec["frequency_hz"]),
            "-M", "fm", "-s", "22050", "-l", "250",
        ]
        multimon_cmd = [
            "multimon-ng", *self._spec["multimon_args"], "-t", "raw", "/dev/stdin",
        ]
        rtl_str = " ".join(shlex.quote(x) for x in rtl_cmd)
        mm_str = " ".join(shlex.quote(x) for x in multimon_cmd)
        cmd = f"{rtl_str} | {mm_str}"

        logger.info("Pager listener (%s) starting: %s", self.kind, cmd)
        self._last_error = ""
        self._proc = await asyncio.create_subprocess_exec(
            "/bin/bash", "-c", cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,  # own process group -> killpg gets all
        )
        loop = asyncio.get_running_loop()
        self._reader_task = loop.create_task(self._read_loop(self._proc))
        self._stderr_task = loop.create_task(self._stderr_loop(self._proc))
        self._idle_task = loop.create_task(self._idle_watchdog())
        self._last_poll_at = time.monotonic()

    async def _start_locked_retrying(self) -> None:
        """Start the pipeline, retrying if rtl_fm can't open the dongle yet.

        Mirrors RtlListener's retry loop: on a fast start-right-after-stop
        the previous rtl_fm may still hold the USB device.
        """
        for attempt in range(1, _START_RETRIES + 1):
            await self._start_locked()
            await asyncio.sleep(_START_CHECK_SECS)
            if self._proc is not None and self._proc.returncode is None:
                return  # still alive -> device opened
            logger.warning(
                "Pager listener (%s) start attempt %d/%d failed (%s); retrying",
                self.kind, attempt, _START_RETRIES,
                self._last_error or "process exited",
            )
            await self._stop_locked_no_release()
            if attempt < _START_RETRIES:
                await asyncio.sleep(_DEVICE_SETTLE_SECS)
        # Final attempt; leave it running (or with _last_error set) for status.
        await self._start_locked()

    async def _stop_locked(self) -> None:
        await self._stop_locked_no_release()
        sdr_registry.release(self.kind)

    async def _stop_locked_no_release(self) -> None:
        """Tear down the process without releasing the registry claim --
        used mid-retry, where we're about to start again and must not let
        another listener steal the dongle in between attempts."""
        proc, self._proc = self._proc, None
        for attr in ("_reader_task", "_stderr_task", "_idle_task"):
            task = getattr(self, attr)
            setattr(self, attr, None)
            if task is not None:
                task.cancel()
        if proc is not None and proc.returncode is None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
            try:
                await asyncio.wait_for(proc.wait(), timeout=3.0)
            except asyncio.TimeoutError:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
                await proc.wait()
            logger.info("Pager listener (%s) stopped", self.kind)

    # ── background tasks ──────────────────────────────────────────

    async def _read_loop(self, proc: asyncio.subprocess.Process) -> None:
        """Parse decoded pages from multimon-ng's stdout into the ring buffer."""
        try:
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                text = line.decode(errors="replace").rstrip()
                if not text:
                    continue
                parsed = _parse_line(text)
                if parsed is not None:
                    self.messages.append(parsed)
        except asyncio.CancelledError:
            return
        # EOF: pipeline died on its own (dongle missing, rtl_fm crash, ...)
        if self._proc is proc:
            rc = proc.returncode
            self._last_error = self._last_error or f"pipeline exited (code {rc})"
            logger.warning(
                "Pager listener (%s) pipeline ended: %s", self.kind, self._last_error,
            )
            self._proc = None
            sdr_registry.release(self.kind)

    async def _stderr_loop(self, proc: asyncio.subprocess.Process) -> None:
        try:
            while True:
                line = await proc.stderr.readline()
                if not line:
                    return
                text = line.decode(errors="replace").rstrip()
                if not text:
                    continue
                logger.debug("pager pipeline (%s): %s", self.kind, text)
                if _ERROR_RE.search(text):
                    self._last_error = text
        except asyncio.CancelledError:
            return

    async def _idle_watchdog(self) -> None:
        """Stop the pipeline when nobody has polled status for a while."""
        try:
            while True:
                await asyncio.sleep(30)
                idle = time.monotonic() - self._last_poll_at
                if idle >= _IDLE_STOP_SECS:
                    logger.info(
                        "Pager listener (%s) idle for %.0f s -- stopping",
                        self.kind, idle,
                    )
                    async with self._lock:
                        await self._stop_locked()
                    return
        except asyncio.CancelledError:
            return
