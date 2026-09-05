"""Compile and flash the plugin's pocsag_companion firmware from the dashboard.

Wraps ``arduino-cli`` (installed by ``scripts/install.sh``'s "Install
arduino-cli + ESP32 toolchain" section into a self-contained
``/opt/arduino-cli``, owned by the ``meshpoint`` service user -- a SHARED
toolchain the Meshtastic/MeshCore companion flashing also depends on, not
something this plugin's own ``setup.sh`` installs) to build and upload
``pocsag_companion/pocsag_companion.ino`` without an Arduino IDE or a
separate machine. Two actions, each streamed to the browser as NDJSON --
same wire shape as core's ``src/api/update/streaming.py``'s
``stream_update()``, just driven by an arbitrary subprocess's stdout/stderr
instead of a named git/pip step chain: compile produces a cached build for
a chosen board target, flash writes that cached build to a chosen USB-
serial port -- any currently-connected device, not just an already-
configured companion (see ``flash_firmware_stream``'s own docstring).

The board target ("Heltec V3" vs "TTGO LoRa32") is a source-level
``#define`` in the sketch, not an ``arduino-cli`` flag -- see
``_select_board_define()`` -- so compiling for board X rewrites the
sketch's own ``BOARD_*`` toggle lines on disk first, the same edit made by
hand earlier while compile-verifying both boards. The set of available
boards is auto-discovered from whatever ``BOARD_*`` defines actually exist
in the file (``_discover_board_targets``), matched against a small
macro->label/fqbn lookup here (``_KNOWN_BOARDS``) that can't be derived
from the macro name alone -- so a third board added to the sketch later
shows up in the dropdown automatically, but still needs one line added to
``_KNOWN_BOARDS`` before it's actually buildable from here.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
from pathlib import Path
from typing import AsyncIterator, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.api.audit import AuditLogWriter
from src.api.audit.dependencies import get_audit_writer
from src.api.auth.dependencies import require_admin
from src.api.auth.jwt_session import SessionClaims

from . import state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/pocsag/firmware", tags=["config", "dapnet"])

_dapnet_sources: list = []

# The sketch ships INSIDE this plugin (plugins/apps/dapnet/pocsag_companion/)
# rather than in the repo-wide extra/ folder -- it's DAPNET-specific
# hardware firmware, nothing else in the codebase depends on it, so it
# belongs with the plugin that owns it. 1 parent up from backend/ to the
# plugin root.
_SKETCH_DIR = Path(__file__).resolve().parents[1] / "pocsag_companion"
_ARDUINO_CLI_BIN = "arduino-cli"
_ARDUINO_CLI_CONFIG = "/opt/arduino-cli/arduino-cli.yaml"

# macro -> label/fqbn. Every OTHER piece of board-target info (which
# macros exist at all, which one is currently active) is auto-discovered
# from the .ino itself -- this mapping is the one thing that genuinely
# can't be, since a board's FQBN isn't spelled out anywhere in the source.
_KNOWN_BOARDS: dict[str, dict[str, str]] = {
    "BOARD_HELTEC_WIFI_LORA32_V3": {
        "label": "Heltec V3", "fqbn": "esp32:esp32:heltec_wifi_lora_32_V3",
    },
    "BOARD_TTGO_LORA32": {
        "label": "TTGO LoRa32", "fqbn": "esp32:esp32:ttgo-lora32",
    },
}

# Matches a whole-line `#define BOARD_xxx` or `//#define BOARD_xxx` --
# deliberately scoped to the BOARD_ prefix so it never touches the
# sketch's many other unrelated #define lines (pins, timeouts, etc).
_BOARD_DEFINE_RE = re.compile(r"^(//)?(#define[ \t]+(BOARD_\w+))[ \t]*$", re.MULTILINE)


def init_routes(dapnet_sources=None) -> None:
    global _dapnet_sources
    _dapnet_sources = list(dapnet_sources) if dapnet_sources else []


def _resolve_dapnet_source(label: str):
    """Mirrors config_routes.py's own helper -- same
    ``dapnet_<label>``/bare ``dapnet`` naming convention."""
    name = f"dapnet_{label}" if label else "dapnet"
    for src in _dapnet_sources:
        if src.name == name:
            return src
    return None


def _sketch_ino_path() -> Path:
    return _SKETCH_DIR / "pocsag_companion.ino"


def _discover_board_targets() -> list[dict]:
    """Board choices for the Compile/Flash pulldown: every ``BOARD_*``
    toggle found in the sketch, matched against ``_KNOWN_BOARDS``. Macros
    found in the file but missing from that lookup are silently skipped
    (buildable only once a label/fqbn is added here by hand)."""
    text = _sketch_ino_path().read_text()
    found: list[dict] = []
    seen: set[str] = set()
    for m in _BOARD_DEFINE_RE.finditer(text):
        macro = m.group(3)
        if macro in seen or macro not in _KNOWN_BOARDS:
            continue
        seen.add(macro)
        found.append({"macro": macro, **_KNOWN_BOARDS[macro]})
    return found


def _select_board_define(macro: str) -> None:
    """Rewrite the sketch's ``BOARD_*`` toggle lines so exactly ``macro``
    is active (uncommented) and every other known board macro is
    commented out. Mutates ``pocsag_companion.ino`` on disk -- the sketch
    has no build-time board flag, only this source-level ``#define``, so
    compiling for a specific board leaves the checked-out file itself in
    that board's state afterward, same as flipping it by hand.
    """
    if macro not in _KNOWN_BOARDS:
        raise ValueError(f"unknown board macro: {macro}")
    ino_path = _sketch_ino_path()
    text = ino_path.read_text()

    def repl(m: re.Match) -> str:
        directive, line_macro = m.group(2), m.group(3)
        if line_macro not in _KNOWN_BOARDS:
            return m.group(0)
        return directive if line_macro == macro else f"//{directive}"

    ino_path.write_text(_BOARD_DEFINE_RE.sub(repl, text))


def _ndjson(payload: dict) -> bytes:
    return (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")


async def _stream_subprocess(cmd: list[str]) -> AsyncIterator[bytes]:
    """Run ``cmd``, yielding one NDJSON line per stdout/stderr line as it
    arrives, then a final ``{"type":"result",...}``. Same wire shape as
    core's ``src/api/update/streaming.py``'s ``stream_update()``, adapted
    for an arbitrary subprocess instead of the git/pip apply chain."""
    yield _ndjson({"type": "started", "cmd": cmd})
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except (FileNotFoundError, OSError) as exc:
        yield _ndjson({
            "type": "result",
            "result": {"returncode": -1, "success": False, "error": str(exc)},
        })
        return

    queue: asyncio.Queue = asyncio.Queue()

    async def pump(stream: Optional[asyncio.StreamReader], name: str) -> None:
        if stream is not None:
            while True:
                line = await stream.readline()
                if not line:
                    break
                await queue.put({
                    "type": "line", "stream": name,
                    "text": line.decode("utf-8", errors="replace").rstrip("\n"),
                })
        await queue.put(None)

    stdout_task = asyncio.create_task(pump(process.stdout, "stdout"))
    stderr_task = asyncio.create_task(pump(process.stderr, "stderr"))

    pending = 2
    while pending:
        item = await queue.get()
        if item is None:
            pending -= 1
            continue
        yield _ndjson(item)

    await stdout_task
    await stderr_task
    returncode = await process.wait()
    yield _ndjson({
        "type": "result",
        "result": {"returncode": returncode, "success": returncode == 0},
    })


def _arduino_cli_available() -> bool:
    """Whether `arduino-cli` is actually on PATH -- scripts/install.sh's
    "Install arduino-cli + ESP32 toolchain" section is opt-in (asked
    interactively, or skippable with --skip-arduino), so a fresh install
    may legitimately not have it. Compile/Flash would otherwise just
    fail with an opaque "command not found" deep in the stream output."""
    return shutil.which(_ARDUINO_CLI_BIN) is not None


@router.get("/targets")
async def firmware_targets(_claims: SessionClaims = Depends(require_admin)) -> dict:
    """Board choices for the Compile/Flash pulldown, auto-discovered from
    the sketch's own BOARD_* defines (see _discover_board_targets)."""
    return {
        "boards": _discover_board_targets(),
        "arduino_cli_available": _arduino_cli_available(),
    }


class CompileRequest(BaseModel):
    board_macro: str


@router.post("/compile/stream")
async def compile_firmware_stream(
    req: CompileRequest,
    claims: SessionClaims = Depends(require_admin),
    audit: AuditLogWriter = Depends(get_audit_writer),
) -> StreamingResponse:
    """Compile pocsag_companion.ino for the chosen board, streaming
    arduino-cli's own stdout/stderr live. Board selection is done by
    rewriting the sketch's #define first (see _select_board_define);
    the compiled artifact lands in arduino-cli's own build cache
    (/opt/arduino-cli/cache), keyed by sketch path + fqbn -- the
    matching flash/stream call below finds it there.
    """
    board = _KNOWN_BOARDS.get(req.board_macro)
    if board is None:
        raise HTTPException(400, "Unknown board_macro")

    async def body() -> AsyncIterator[bytes]:
        with audit.timed_action(
            user=claims.subject, action="pocsag_firmware.compile",
            params={"board_macro": req.board_macro},
        ) as ctx:
            _select_board_define(req.board_macro)
            cmd = [
                _ARDUINO_CLI_BIN, "--config-file", _ARDUINO_CLI_CONFIG,
                "compile", "-v", "--fqbn", board["fqbn"], str(_SKETCH_DIR),
            ]
            success = False
            async for chunk in _stream_subprocess(cmd):
                yield chunk
                event = json.loads(chunk)
                if event.get("type") == "result":
                    success = bool((event.get("result") or {}).get("success"))
            ctx.set_result("success" if success else "error")

    return StreamingResponse(
        body(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


class FlashRequest(BaseModel):
    board_macro: str
    port: str


@router.post("/flash/stream")
async def flash_firmware_stream(
    req: FlashRequest,
    claims: SessionClaims = Depends(require_admin),
    audit: AuditLogWriter = Depends(get_audit_writer),
) -> StreamingResponse:
    """Upload the board's already-compiled artifact (see compile/stream
    above -- flash does not recompile) to ``port``.

    ``port`` can be ANY currently-connected USB-serial device, not just
    one already added as a configured POCSAG companion -- flashing a
    spare board (or a friend's, just passing through) shouldn't require
    adding-then-removing a permanent device entry first, same reasoning
    as the Meshtastic/MeshCore flash routes. It's validated against the
    live enumeration below (same one GET /api/config/serial-ports uses),
    never trusted as a raw path from the browser.

    If ``port`` happens to match a configured companion's serial_port
    (looked up in this plugin's own state.devices(), not core config --
    that's the one thing that changed when this moved out of core), that
    companion's DapnetSerialSource is released before flashing (esptool
    needs exclusive access to reset+write the board) and re-opened
    afterward -- without this, a flash triggered here would leave
    capture silently dead until a manual service restart, the exact gap
    confirmed live while testing the underlying toolchain by hand. If it
    doesn't match anything configured, there's nothing to release/
    restart, which is exactly right for a board that isn't part of this
    box's own config at all.
    """
    board = _KNOWN_BOARDS.get(req.board_macro)
    if board is None:
        raise HTTPException(400, "Unknown board_macro")

    from src.hal.usb_classifier import list_serial_ports_with_stable_paths
    real_ports = {
        value
        for dev in list_serial_ports_with_stable_paths()
        if dev.vid is not None
        for value in (dev.device, dev.stable_path, dev.by_id, dev.by_path)
        if value
    }
    if req.port not in real_ports:
        raise HTTPException(400, "Selected port is not a currently connected USB-serial device")
    port = req.port

    label = ""
    source = None
    for d in state.devices():
        if d.get("serial_port") == port:
            label = d.get("label") or ""
            source = _resolve_dapnet_source(label)
            break

    async def body() -> AsyncIterator[bytes]:
        with audit.timed_action(
            user=claims.subject, action="pocsag_firmware.flash",
            params={"board_macro": req.board_macro, "label": label, "port": port},
        ) as ctx:
            released = source is not None and source.connected
            if released:
                yield _ndjson({
                    "type": "line", "stream": "stdout",
                    "text": f"Releasing {port} ({source.name} was connected)…",
                })
                await source.stop()

            cmd = [
                _ARDUINO_CLI_BIN, "--config-file", _ARDUINO_CLI_CONFIG,
                "upload", "-p", port, "--fqbn", board["fqbn"], str(_SKETCH_DIR),
            ]
            success = False
            async for chunk in _stream_subprocess(cmd):
                yield chunk
                event = json.loads(chunk)
                if event.get("type") == "result":
                    success = bool((event.get("result") or {}).get("success"))

            if released:
                yield _ndjson({
                    "type": "line", "stream": "stdout",
                    "text": "Waiting for the board to finish rebooting…",
                })
                await asyncio.sleep(3.0)
                await source.start()
                yield _ndjson({
                    "type": "line", "stream": "stdout",
                    "text": (
                        f"{source.name} reconnected on {port}."
                        if source.connected
                        else f"{source.name} did NOT reconnect -- "
                             "a service restart may be needed."
                    ),
                })

            ctx.set_result("success" if success else "error")

    return StreamingResponse(
        body(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )
