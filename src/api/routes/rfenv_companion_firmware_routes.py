"""Compile and flash extra/rfenv_companion firmware from the dashboard.

Same ``arduino-cli`` streaming mechanism as pocsag_firmware_routes.py /
pager_firmware_routes.py. **Single board** (Heltec V3, no ``BOARD_*``
toggle, no board pulldown) -- but unlike pager_client, this sketch DOES
have one compile-time choice: which RF band it's built for
(``BAND_EU868`` vs ``BAND_70CM``, see the sketch's own "BAND SELECT"
block). A second, physically distinct Heltec V3 (different antenna/RF
matching network for that band) can be flashed as a standalone 430-440
MHz handheld scanner -- it can never usefully feed a 868/915-band
Meshpoint's own RF Environment page, this is purely a second tool.
Band selection uses the exact same source-level toggle + regex-rewrite
mechanism as pocsag_firmware_routes.py's own board picker
(``_select_board_define()``/``_discover_board_targets()``), just for a
``BAND_*`` prefix instead of ``BOARD_*``.

Unlike pager_client, this board DOES hold a live USB-serial connection
when configured+running (RfEnvCompanionScanService owns the port
exactly like DapnetSerialSource does) -- so the flash route mirrors
pocsag_firmware_routes.py's release/reconnect logic instead of pager's
"nothing to release" simplicity: if the selected port matches the
configured ``capture.rfenv_companion`` device, the live service is
stopped before flashing (arduino-cli needs exclusive access to reset+
write the board) and restarted afterward.
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
from src.config import AppConfig

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/rfenv-companion/firmware", tags=["config", "rfenv-companion"])

_SKETCH_DIR = Path(__file__).resolve().parents[3] / "extra" / "rfenv_companion"
_ARDUINO_CLI_BIN = "arduino-cli"
_ARDUINO_CLI_CONFIG = "/opt/arduino-cli/arduino-cli.yaml"
_FQBN = "esp32:esp32:heltec_wifi_lora_32_V3"
_BOARD_LABEL = "Heltec V3"

# macro -> label. Mirrors pocsag_firmware_routes.py's _KNOWN_BOARDS --
# which macros exist is auto-discovered from the sketch itself, but the
# human label can't be derived from the macro name alone.
_KNOWN_BANDS: dict[str, dict[str, str]] = {
    "BAND_EU868": {"label": "868 MHz (EU868)"},
    "BAND_70CM": {"label": "430-440 MHz (70cm)"},
}

# Matches a whole-line `#define BAND_xxx` or `//#define BAND_xxx` --
# scoped to the BAND_ prefix so it never touches the sketch's other
# #define lines. Same shape as pocsag_firmware_routes.py's _BOARD_DEFINE_RE.
_BAND_DEFINE_RE = re.compile(r"^(//)?(#define[ \t]+(BAND_\w+))[ \t]*$", re.MULTILINE)

_config: AppConfig | None = None
_service = None  # RfEnvCompanionScanService, or None if not configured/running


def init_routes(config: AppConfig, service=None) -> None:
    global _config, _service
    _config = config
    _service = service


def _sketch_ino_path() -> Path:
    return _SKETCH_DIR / "rfenv_companion.ino"


def _ensure_secrets_header() -> None:
    """``#include "secrets.h"`` is gitignored (real WiFi/OTA/web-password
    values never land in a tracked .ino), so a fresh checkout -- e.g. the
    Pi -- lacks it and arduino-cli fails with ``secrets.h: No such file``.
    Seed it from the committed ``secrets.h.example`` (all-placeholder: the
    sketch treats placeholder / empty creds as "no WiFi", real values set
    later over serial or the unit's web UI). Never overwrites an existing
    ``secrets.h``."""
    secrets = _SKETCH_DIR / "secrets.h"
    if secrets.exists():
        return
    example = _SKETCH_DIR / "secrets.h.example"
    if example.is_file():
        shutil.copyfile(example, secrets)
        logger.info("seeded %s from secrets.h.example (placeholder creds)", secrets)


def _discover_band_targets() -> list[dict]:
    """Band choices for the Compile pulldown: every ``BAND_*`` toggle
    found in the sketch, matched against ``_KNOWN_BANDS``. Mirrors
    pocsag_firmware_routes.py's ``_discover_board_targets()`` exactly."""
    text = _sketch_ino_path().read_text()
    found: list[dict] = []
    seen: set[str] = set()
    for m in _BAND_DEFINE_RE.finditer(text):
        macro = m.group(3)
        if macro in seen or macro not in _KNOWN_BANDS:
            continue
        seen.add(macro)
        found.append({"macro": macro, **_KNOWN_BANDS[macro]})
    return found


def _select_band_define(macro: str) -> None:
    """Rewrite the sketch's ``BAND_*`` toggle lines so exactly ``macro``
    is active (uncommented) and every other known band macro is
    commented out. Mutates ``rfenv_companion.ino`` on disk -- mirrors
    pocsag_firmware_routes.py's ``_select_board_define()`` exactly,
    just for the BAND SELECT block instead of BOARD SELECT.
    """
    if macro not in _KNOWN_BANDS:
        raise ValueError(f"unknown band macro: {macro}")
    ino_path = _sketch_ino_path()
    text = ino_path.read_text()

    def repl(m: re.Match) -> str:
        directive, line_macro = m.group(2), m.group(3)
        if line_macro not in _KNOWN_BANDS:
            return m.group(0)
        return directive if line_macro == macro else f"//{directive}"

    ino_path.write_text(_BAND_DEFINE_RE.sub(repl, text))


def _ndjson(payload: dict) -> bytes:
    return (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")


async def _stream_subprocess(cmd: list[str]) -> AsyncIterator[bytes]:
    """Run ``cmd``, yielding one NDJSON line per stdout/stderr line as it
    arrives, then a final ``{"type":"result",...}``. Identical shape to
    pocsag_firmware_routes.py's own copy."""
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
    """Single fixed board (kept as a list for shape-compatibility with
    the other firmware cards' frontend code) plus the discovered band
    choices (see _discover_band_targets)."""
    return {
        "boards": [{"macro": "HELTEC_V3", "label": _BOARD_LABEL, "fqbn": _FQBN}],
        "bands": _discover_band_targets(),
        "arduino_cli_available": _arduino_cli_available(),
    }


class CompileRequest(BaseModel):
    band_macro: str


@router.post("/compile/stream")
async def compile_firmware_stream(
    req: CompileRequest,
    claims: SessionClaims = Depends(require_admin),
    audit: AuditLogWriter = Depends(get_audit_writer),
) -> StreamingResponse:
    """Compile rfenv_companion.ino for the requested band, rewriting the
    sketch's BAND SELECT toggle first (see _select_band_define) --
    mirrors pocsag_firmware_routes.py's board-select rewrite. Leaves the
    checked-out file in that state afterward, same as that precedent.
    """
    if req.band_macro not in _KNOWN_BANDS:
        raise HTTPException(400, f"Unknown band_macro {req.band_macro!r}")

    async def body() -> AsyncIterator[bytes]:
        with audit.timed_action(
            user=claims.subject, action="rfenv_companion_firmware.compile",
            params={"band_macro": req.band_macro},
        ) as ctx:
            _select_band_define(req.band_macro)
            _ensure_secrets_header()
            yield _ndjson({
                "type": "line", "stream": "stdout",
                "text": f"Building for {_KNOWN_BANDS[req.band_macro]['label']}…",
            })

            cmd = [
                _ARDUINO_CLI_BIN, "--config-file", _ARDUINO_CLI_CONFIG,
                "compile", "-v", "--fqbn", _FQBN, str(_SKETCH_DIR),
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
    port: str


@router.post("/flash/stream")
async def flash_firmware_stream(
    req: FlashRequest,
    claims: SessionClaims = Depends(require_admin),
    audit: AuditLogWriter = Depends(get_audit_writer),
) -> StreamingResponse:
    """Upload the already-compiled artifact (see compile/stream above --
    flash does not recompile) to ``port``.

    ``port`` can be ANY currently-connected USB-serial device, same
    live-enumeration validation every other flash route uses. If it
    matches the configured ``capture.rfenv_companion`` device's own
    port, the live RfEnvCompanionScanService is stopped first (esptool
    needs exclusive access) and restarted afterward -- same
    release/reconnect reasoning as pocsag_firmware_routes.py's own flash
    route, adapted for this service instead of a CaptureSource.
    """
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

    configured_port = None
    if _config is not None and _config.capture.rfenv_companion:
        configured_port = _config.capture.rfenv_companion[0].serial_port
    service = _service if (configured_port and configured_port == port) else None

    async def body() -> AsyncIterator[bytes]:
        with audit.timed_action(
            user=claims.subject, action="rfenv_companion_firmware.flash", params={"port": port},
        ) as ctx:
            released = service is not None
            if released:
                yield _ndjson({
                    "type": "line", "stream": "stdout",
                    "text": f"Releasing {port} (RF Environment companion was connected)…",
                })
                await service.stop()

            cmd = [
                _ARDUINO_CLI_BIN, "--config-file", _ARDUINO_CLI_CONFIG,
                "upload", "-p", port, "--fqbn", _FQBN, str(_SKETCH_DIR),
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
                await service.start()
                yield _ndjson({
                    "type": "line", "stream": "stdout",
                    "text": (
                        "RF Environment companion reconnected."
                        if service.is_running
                        else "RF Environment companion did NOT reconnect -- "
                             "a service restart may be needed."
                    ),
                })

            ctx.set_result("success" if success else "error")

    return StreamingResponse(
        body(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )
