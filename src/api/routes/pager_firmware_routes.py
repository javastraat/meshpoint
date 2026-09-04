"""Compile and flash extra/pager_client firmware from the dashboard.

Same mechanism as pocsag_firmware_routes.py (wraps ``arduino-cli``, streamed
to the browser as NDJSON), simplified in two ways since pager_client is a
much simpler sketch:

- **Single board only.** pager_client.ino has no ``BOARD_*`` toggle at all
  (Heltec V3 exclusively, per the sketch's own header comment) -- no board
  pulldown, no ``_select_board_define()``/``_discover_board_targets()``
  machinery to mirror from pocsag_firmware_routes.py.
- **No companion device to release/reconnect.** pager_client talks directly
  over the air to the concentrator's ch9 -- it has no USB-serial link to
  Meshpoint at all, unlike a configured POCSAG/MeshCore/Meshtastic companion,
  so flashing here never needs to pause/resume a live capture source first.

Also handles per-unit capcode injection: pager_client.ino's MY_CAPCODES[]
(one or more capcodes this specific physical pager should answer to --
its personal number, optionally plus one or more group/team addresses)
and SEND_TO_CAPCODE (the base station it replies to) are placeholders in
the checked-out sketch, rewritten on disk right before each compile --
MY_CAPCODES from this request's ``my_capcodes`` list, SEND_TO_CAPCODE
from this box's own already-configured ``radio.pager_capcode``. Same
"rewrite a source-level placeholder before compiling" idea as
pocsag_firmware_routes.py's board-select handling, just a numeric
literal instead of a comment-toggle.

``_ndjson``/``_stream_subprocess`` are duplicated from pocsag_firmware_routes.py
rather than shared -- matches the existing convention (the DAB+ plugin's
routes.py, meshcore_firmware_routes.py, and meshtastic_firmware_routes.py
each keep their own copy too), not a new pattern introduced here.
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
from pydantic import BaseModel, Field

from src.api.audit import AuditLogWriter
from src.api.audit.dependencies import get_audit_writer
from src.api.auth.dependencies import require_admin
from src.api.auth.jwt_session import SessionClaims
from src.config import AppConfig

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/pager/firmware", tags=["config", "pager"])

_SKETCH_DIR = Path(__file__).resolve().parents[3] / "extra" / "pager_client"
_ARDUINO_CLI_BIN = "arduino-cli"
_ARDUINO_CLI_CONFIG = "/opt/arduino-cli/arduino-cli.yaml"
_FQBN = "esp32:esp32:heltec_wifi_lora_32_V3"
_BOARD_LABEL = "Heltec V3"

_config: AppConfig | None = None

_UINT32_MAX = 0xFFFFFFFF

# Matches the whole `const uint32_t MY_CAPCODES[] = { ... };` initializer
# line -- deliberately scoped to this one declaration so it can never
# touch EMERGENCY_CAPCODES[] (a different, deliberately NOT-injected
# array, see pager_client.ino's own comment) or anything else in the file.
_MY_CAPCODES_RE = re.compile(
    r"(const uint32_t MY_CAPCODES\[\] = )\{[^}]*\}(;)"
)
_SEND_TO_CAPCODE_RE = re.compile(
    r"(const uint32_t SEND_TO_CAPCODE = )\d+(UL;)"
)


def init_routes(config: AppConfig) -> None:
    global _config
    _config = config


def _sketch_ino_path() -> Path:
    return _SKETCH_DIR / "pager_client.ino"


def _rewrite_my_capcodes(text: str, capcodes: list[int]) -> str:
    literal = "{ " + ", ".join(f"{c}UL" for c in capcodes) + " }"
    new_text, count = _MY_CAPCODES_RE.subn(rf"\g<1>{literal}\g<2>", text)
    if count != 1:
        raise RuntimeError(
            f"expected exactly one MY_CAPCODES[] definition in "
            f"pager_client.ino, found {count}"
        )
    return new_text


def _rewrite_send_to_capcode(text: str, value: int) -> str:
    new_text, count = _SEND_TO_CAPCODE_RE.subn(rf"\g<1>{value}\g<2>", text)
    if count != 1:
        raise RuntimeError(
            f"expected exactly one SEND_TO_CAPCODE definition in "
            f"pager_client.ino, found {count}"
        )
    return new_text


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
    """Single fixed board -- kept as a list for shape-compatibility with
    the other firmware cards' frontend code, even though there's only
    ever one entry."""
    return {
        "boards": [{"macro": "HELTEC_V3", "label": _BOARD_LABEL, "fqbn": _FQBN}],
        "arduino_cli_available": _arduino_cli_available(),
    }


class CompileRequest(BaseModel):
    my_capcodes: list[int] = Field(..., min_length=1)


@router.post("/compile/stream")
async def compile_firmware_stream(
    req: CompileRequest,
    claims: SessionClaims = Depends(require_admin),
    audit: AuditLogWriter = Depends(get_audit_writer),
) -> StreamingResponse:
    """Compile pager_client.ino for the capcode(s) this specific physical
    unit should answer to, streaming arduino-cli's own stdout/stderr
    live. The compiled artifact lands in arduino-cli's own build cache
    (/opt/arduino-cli/cache), keyed by sketch path + fqbn -- the matching
    flash/stream call below finds it there.

    ``my_capcodes`` (this device's personal number, optionally plus one
    or more group/team addresses) and this box's own configured
    ``radio.pager_capcode`` (SEND_TO_CAPCODE -- the base station a reply
    goes to) are rewritten into the sketch on disk first, mirroring
    pocsag_firmware_routes.py's board-select rewrite. Leaves the
    checked-out file in that state afterward, same as that precedent.
    """
    if _config is None:
        raise HTTPException(503, "Config not loaded")
    for code in req.my_capcodes:
        if not (0 <= code <= _UINT32_MAX):
            raise HTTPException(400, f"capcode {code} out of range (0-{_UINT32_MAX})")
    send_to = _config.radio.pager_capcode
    if not send_to:
        raise HTTPException(
            400,
            "Set this box's own pager capcode (Configuration → Radio → Pager) "
            "before compiling pager firmware -- otherwise the flashed unit would "
            "report to capcode 0, which nothing listens on.",
        )

    async def body() -> AsyncIterator[bytes]:
        with audit.timed_action(
            user=claims.subject, action="pager_firmware.compile",
            params={"my_capcodes": req.my_capcodes, "send_to_capcode": send_to},
        ) as ctx:
            ino_path = _sketch_ino_path()
            text = ino_path.read_text()
            text = _rewrite_my_capcodes(text, req.my_capcodes)
            text = _rewrite_send_to_capcode(text, send_to)
            ino_path.write_text(text)
            yield _ndjson({
                "type": "line", "stream": "stdout",
                "text": f"Programming capcodes {req.my_capcodes}, "
                        f"reporting to {send_to}…",
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

    ``port`` can be ANY currently-connected USB-serial device -- validated
    against the live enumeration below (same one GET /api/config/serial-ports
    uses), never trusted as a raw path from the browser. Unlike the POCSAG/
    MeshCore/Meshtastic flash routes, there's no configured companion source
    to release/reconnect here: pager_client has no USB-serial link to
    Meshpoint at all, so flashing it never touches a live capture source.
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

    async def body() -> AsyncIterator[bytes]:
        with audit.timed_action(
            user=claims.subject, action="pager_firmware.flash", params={"port": port},
        ) as ctx:
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
            ctx.set_result("success" if success else "error")

    return StreamingResponse(
        body(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )
