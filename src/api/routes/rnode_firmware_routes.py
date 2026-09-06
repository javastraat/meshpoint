"""Flash "dumb modem" RNode firmware onto a connected board from the
dashboard -- the same 3-step process (flash, provision EEPROM, set
firmware hash) the standalone https://liamcottle.github.io/rnode-flasher
web tool does via Web Serial in-browser, but driven server-side instead.

Deliberately NOT a Web Serial/browser-side port of rnode-flasher, even
though that's what reticulum-meshchat itself vendors verbatim
(src/frontend/public/rnode-flasher/ in that repo). Web Serial reaches
serial ports on whatever machine the *browser* is running on -- fine
for a local Electron app like meshchat, wrong for meshpoint, where the
dashboard is viewed remotely but the RNode is physically on the Pi.
Same server-side-subprocess pattern every other firmware card here
already uses (pocsag_firmware_routes.py, reticulum_companion_firmware_
routes.py, etc.) is the correct fit.

Wraps ``rnodeconf`` (RNS.Utilities.rnodeconf, a console-script bundled
with the ``rns`` pip package -- already a meshpoint dependency, so no
separate install step). ``rnodeconf --autoinstall`` is a purely
interactive wizard with no non-interactive CLI flags for board/band
selection -- confirmed by reading the real installed source
(RNS/Utilities/rnodeconf.py) rather than guessing, since a wrong
answer sequence could flash the wrong firmware for a board's radio
chip. ``_BOARDS`` below encodes the exact numbered-menu answer
sequence for each supported board, extracted directly from that
source. One confirmed simplification: ``-a`` alone (with a port
already supplied positionally) flashes firmware AND bootstraps the
EEPROM AND sets the firmware hash in the same run -- no separate
``-r``/``-H`` calls needed, confirmed from source (a successful flash
sets ``args.rom = True`` and ``wants_fw_provision = True`` internally,
falling through into the same process's own EEPROM-bootstrap step).

Two boards (LilyGO LoRa T3S3, LilyGO T-Beam) have a genuine radio-chip
ambiguity at the "868/915/923 MHz" band choice -- the menu offers it
twice, once for an SX1276 build and once for SX1262 -- so those two
expose both variants distinctly in ``_BOARDS`` rather than guessing
which chip a given physical unit has.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import sys
from pathlib import Path
from typing import AsyncIterator, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.api.audit import AuditLogWriter
from src.api.audit.dependencies import get_audit_writer
from src.api.auth.dependencies import require_admin
from src.api.auth.jwt_session import SessionClaims
# Re-exported under the old private name for this module's own uses and for
# src/api/routes/reticulum_config_routes.py, which imports it from here
# until that file goes away in the reticulum-to-plugin cutover.
from src.api.systemctl import run_systemctl as _run_systemctl
from src.config import AppConfig

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/rnode/firmware", tags=["config", "reticulum"])

_config: Optional[AppConfig] = None


def init_routes(config: AppConfig) -> None:
    global _config
    _config = config


def _resolve_rnodeconf_bin() -> str:
    """``rnodeconf`` is a console-script pip installs alongside ``rns``
    in whichever Python environment ran ``pip install`` -- for
    meshpoint that's its own venv (``requirements.txt``), not
    necessarily on this *process's* ``$PATH``. Unlike an interactively
    activated venv (which prepends its own ``bin/`` to ``$PATH``),
    ``meshpoint.service`` invokes ``/opt/meshpoint/venv/bin/python``
    directly and gets systemd's own minimal default `$PATH` otherwise
    -- confirmed live: ``shutil.which("rnodeconf")`` came back empty
    even though it's genuinely installed. ``sys.executable``'s own
    directory is where pip actually put it (a sibling console-script
    next to the interpreter itself), so resolve relative to that
    first; fall back to a bare PATH lookup for any other environment
    (e.g. a real activated-venv shell) where that's simply how it's
    found.
    """
    candidate = Path(sys.executable).parent / "rnodeconf"
    if candidate.exists():
        return str(candidate)
    return "rnodeconf"


_RNODECONF_BIN = _resolve_rnodeconf_bin()

# Each value is the ordered sequence of menu answers rnodeconf's
# --autoinstall wizard expects on stdin, one line per prompt:
#   [top-level device-type number, "" (bare Enter past the info
#    screen), band/model number, "y" (final confirmation)]
# Extracted directly from RNS/Utilities/rnodeconf.py's autoinstall()
# menu -- see this module's own docstring. "label" is what the
# dropdown shows; boards are grouped by device, with one entry per
# meaningful band/chip variant.
_BOARDS = {
    "heltec_v2_433":  {"label": "Heltec LoRa32 v2 (433 MHz)",  "seq": ["7", "", "1", "y"]},
    "heltec_v2_868":  {"label": "Heltec LoRa32 v2 (868 MHz)",  "seq": ["7", "", "2", "y"]},
    "heltec_v2_915":  {"label": "Heltec LoRa32 v2 (915 MHz)",  "seq": ["7", "", "3", "y"]},
    "heltec_v2_923":  {"label": "Heltec LoRa32 v2 (923 MHz)",  "seq": ["7", "", "4", "y"]},

    "heltec_v3_433":  {"label": "Heltec LoRa32 v3 (433 MHz)",  "seq": ["8", "", "1", "y"]},
    "heltec_v3_868":  {"label": "Heltec LoRa32 v3 (868 MHz)",  "seq": ["8", "", "2", "y"]},
    "heltec_v3_915":  {"label": "Heltec LoRa32 v3 (915 MHz)",  "seq": ["8", "", "3", "y"]},
    "heltec_v3_923":  {"label": "Heltec LoRa32 v3 (923 MHz)",  "seq": ["8", "", "4", "y"]},

    # No 433 MHz variant exists for v4 -- only 3 band options in rnodeconf's own menu.
    "heltec_v4_868":  {"label": "Heltec LoRa32 v4 (868 MHz)",  "seq": ["9", "", "1", "y"]},
    "heltec_v4_915":  {"label": "Heltec LoRa32 v4 (915 MHz)",  "seq": ["9", "", "2", "y"]},
    "heltec_v4_923":  {"label": "Heltec LoRa32 v4 (923 MHz)",  "seq": ["9", "", "3", "y"]},

    "heltec_t114_433": {"label": "Heltec T114 (433 MHz)", "seq": ["15", "", "1", "y"]},
    "heltec_t114_868": {"label": "Heltec T114 (868 MHz)", "seq": ["15", "", "2", "y"]},
    "heltec_t114_915": {"label": "Heltec T114 (915 MHz)", "seq": ["15", "", "3", "y"]},
    "heltec_t114_923": {"label": "Heltec T114 (923 MHz)", "seq": ["15", "", "4", "y"]},

    "lilygo_v1_0_433": {"label": "LilyGO LoRa32 v1.0 (433 MHz)", "seq": ["5", "", "1", "y"]},
    "lilygo_v1_0_868": {"label": "LilyGO LoRa32 v1.0 (868 MHz)", "seq": ["5", "", "2", "y"]},
    "lilygo_v1_0_915": {"label": "LilyGO LoRa32 v1.0 (915 MHz)", "seq": ["5", "", "3", "y"]},
    "lilygo_v1_0_923": {"label": "LilyGO LoRa32 v1.0 (923 MHz)", "seq": ["5", "", "4", "y"]},

    "lilygo_v2_0_433": {"label": "LilyGO LoRa32 v2.0 (433 MHz)", "seq": ["4", "", "1", "y"]},
    "lilygo_v2_0_868": {"label": "LilyGO LoRa32 v2.0 (868 MHz)", "seq": ["4", "", "2", "y"]},
    "lilygo_v2_0_915": {"label": "LilyGO LoRa32 v2.0 (915 MHz)", "seq": ["4", "", "3", "y"]},
    "lilygo_v2_0_923": {"label": "LilyGO LoRa32 v2.0 (923 MHz)", "seq": ["4", "", "4", "y"]},

    # v2.1's own menu offers one combined 868/915/923 choice, plus TCXO variants.
    "lilygo_v2_1_433":          {"label": "LilyGO LoRa32 v2.1 (433 MHz)", "seq": ["3", "", "1", "y"]},
    "lilygo_v2_1_868_915_923":  {"label": "LilyGO LoRa32 v2.1 (868/915/923 MHz)", "seq": ["3", "", "2", "y"]},
    "lilygo_v2_1_433_tcxo":     {"label": "LilyGO LoRa32 v2.1 (433 MHz, TCXO)", "seq": ["3", "", "3", "y"]},
    "lilygo_v2_1_868_915_923_tcxo": {"label": "LilyGO LoRa32 v2.1 (868/915/923 MHz, TCXO)", "seq": ["3", "", "4", "y"]},

    # Chip-ambiguous: rnodeconf offers 868/915/923 twice, once per radio chip.
    "lilygo_t3s3_433_sx1278":         {"label": "LilyGO LoRa T3S3 (433 MHz, SX1278)", "seq": ["10", "", "1", "y"]},
    "lilygo_t3s3_868_915_923_sx1276": {"label": "LilyGO LoRa T3S3 (868/915/923 MHz, SX1276)", "seq": ["10", "", "2", "y"]},
    "lilygo_t3s3_433_sx1268":         {"label": "LilyGO LoRa T3S3 (433 MHz, SX1268)", "seq": ["10", "", "3", "y"]},
    "lilygo_t3s3_868_915_923_sx1262": {"label": "LilyGO LoRa T3S3 (868/915/923 MHz, SX1262)", "seq": ["10", "", "4", "y"]},
    "lilygo_t3s3_2_4ghz":             {"label": "LilyGO LoRa T3S3 (2.4 GHz)", "seq": ["10", "", "5", "y"]},

    "lilygo_tbeam_433_sx1278":         {"label": "LilyGO T-Beam (433 MHz, SX1278)", "seq": ["6", "", "1", "y"]},
    "lilygo_tbeam_868_915_923_sx1276": {"label": "LilyGO T-Beam (868/915/923 MHz, SX1276)", "seq": ["6", "", "2", "y"]},
    "lilygo_tbeam_433_sx1268":         {"label": "LilyGO T-Beam (433 MHz, SX1268)", "seq": ["6", "", "3", "y"]},
    "lilygo_tbeam_868_915_923_sx1262": {"label": "LilyGO T-Beam (868/915/923 MHz, SX1262)", "seq": ["6", "", "4", "y"]},

    "lilygo_tbeam_supreme_433":         {"label": "LilyGO T-Beam Supreme (433 MHz)", "seq": ["13", "", "1", "y"]},
    "lilygo_tbeam_supreme_868_915_923": {"label": "LilyGO T-Beam Supreme (868/915/923 MHz)", "seq": ["13", "", "2", "y"]},

    "lilygo_tdeck_433":         {"label": "LilyGO T-Deck (433 MHz)", "seq": ["14", "", "1", "y"]},
    "lilygo_tdeck_868_915_923": {"label": "LilyGO T-Deck (868/915/923 MHz)", "seq": ["14", "", "2", "y"]},

    "lilygo_techo_433": {"label": "LilyGO T-Echo (433 MHz)", "seq": ["12", "", "1", "y"]},
    "lilygo_techo_868": {"label": "LilyGO T-Echo (868 MHz)", "seq": ["12", "", "2", "y"]},
    "lilygo_techo_915": {"label": "LilyGO T-Echo (915 MHz)", "seq": ["12", "", "3", "y"]},
    "lilygo_techo_923": {"label": "LilyGO T-Echo (923 MHz)", "seq": ["12", "", "4", "y"]},

    "rak4631_433": {"label": "RAK4631 (433 MHz)", "seq": ["11", "", "1", "y"]},
    "rak4631_868": {"label": "RAK4631 (868 MHz)", "seq": ["11", "", "2", "y"]},
    "rak4631_915": {"label": "RAK4631 (915 MHz)", "seq": ["11", "", "3", "y"]},
    "rak4631_923": {"label": "RAK4631 (923 MHz)", "seq": ["11", "", "4", "y"]},
}

# Printed only when args.autoinstall is set AND the post-write EEPROM
# read-back confirms rnode.provisioned -- i.e. flash + EEPROM bootstrap
# + firmware-hash-set all genuinely succeeded. A 0 returncode alone
# isn't a reliable success signal here.
_SUCCESS_MARKER = "RNode Firmware autoinstallation complete!"

# A board that's already correctly flashed and provisioned exits here
# instead -- confirmed live (a real device hit this exact path on a
# second run). This is a GOOD outcome (nothing needed doing), not a
# failure -- without treating it as success too, the dashboard would
# show "Failed" for a board that's actually already in the desired
# state, which is exactly backwards.
_ALREADY_PROVISIONED_MARKER = "This device is already installed and provisioned"


def _ndjson(payload: dict) -> bytes:
    return (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")


def _rnodeconf_available() -> bool:
    resolved = Path(_RNODECONF_BIN)
    if resolved.is_absolute():
        return resolved.exists()
    return shutil.which(_RNODECONF_BIN) is not None


# rnodeconf.py hardcodes its own config/firmware-cache directory as
# os.path.expanduser("~/.config/rnodeconf") -- no env var or CLI flag
# to redirect it (confirmed from source, not guessed). That resolves
# via $HOME, and the meshpoint systemd user is --no-create-home, so
# it tries to create /home/meshpoint and fails -- confirmed live
# (PermissionError, same class of bug RNS.Reticulum() and PlatformIO/
# arduino-cli already hit earlier this session for the same user).
# Overriding just $HOME for this one subprocess, same fix shape as
# meshpoint.service's own XDG_CACHE_HOME/PLATFORMIO_CORE_DIR
# Environment= lines solve for those other tools.
_RNODECONF_HOME_DIR = "data/rnodeconf_home"


def _rnodeconf_env() -> dict:
    home = Path(_RNODECONF_HOME_DIR).resolve()
    home.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["HOME"] = str(home)
    return env


async def _stream_autoinstall(port: str, sequence: list[str]) -> AsyncIterator[bytes]:
    """Runs ``rnodeconf -a <port>``, pre-feeding the entire canned answer
    sequence to stdin immediately after spawn. Safe to do up front
    rather than matching each prompt before answering it: rnodeconf's
    ``input()`` calls are strictly sequential synchronous reads, so
    queued lines satisfy each prompt in order regardless of whether
    its prompt text has been printed yet -- confirmed against the real
    source, not assumed.

    ``--baud-flash 115200`` overrides rnodeconf's own default
    (921600): live-caught a real esptool write failure
    (``StopIteration`` in its serial reader, i.e. a dropped/desynced
    byte stream) partway through flashing a real Heltec V3 at the
    default rate -- rnodeconf's own error output recommends this exact
    flag for boards with high-speed flashing trouble. Defaulted here
    rather than exposed as a UI option: a few extra seconds of flash
    time is a small price for not needing a retry, and 115200 is safe
    for every board this card supports.
    """
    cmd = [_RNODECONF_BIN, "-a", "--baud-flash", "115200", port]
    yield _ndjson({"type": "started", "cmd": cmd})
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_rnodeconf_env(),
        )
    except (FileNotFoundError, OSError) as exc:
        yield _ndjson({
            "type": "result",
            "result": {"returncode": -1, "success": False, "error": str(exc)},
        })
        return

    if process.stdin is not None:
        input_bytes = ("\n".join(sequence) + "\n").encode("utf-8")
        process.stdin.write(input_bytes)
        await process.stdin.drain()
        process.stdin.close()

    queue: asyncio.Queue = asyncio.Queue()
    saw_success_marker = False
    saw_already_provisioned = False

    async def pump(stream: Optional[asyncio.StreamReader], name: str) -> None:
        if stream is not None:
            while True:
                line = await stream.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").rstrip("\n")
                await queue.put({"type": "line", "stream": name, "text": text})
        await queue.put(None)

    stdout_task = asyncio.create_task(pump(process.stdout, "stdout"))
    stderr_task = asyncio.create_task(pump(process.stderr, "stderr"))

    pending = 2
    while pending:
        item = await queue.get()
        if item is None:
            pending -= 1
            continue
        text = item.get("text", "")
        if _SUCCESS_MARKER in text:
            saw_success_marker = True
        elif _ALREADY_PROVISIONED_MARKER in text:
            saw_already_provisioned = True
        yield _ndjson(item)

    await stdout_task
    await stderr_task
    returncode = await process.wait()
    yield _ndjson({
        "type": "result",
        "result": {
            "returncode": returncode,
            "success": saw_success_marker or saw_already_provisioned,
            "already_provisioned": saw_already_provisioned,
        },
    })


async def _stream_eeprom_wipe(port: str) -> AsyncIterator[bytes]:
    """Runs ``rnodeconf --eeprom-wipe <port>`` -- unlike autoinstall,
    this is fully non-interactive (no stdin sequence needed, confirmed
    from source: it just logs a warning, wipes, hard-resets, and
    exits) and prints no distinct success marker, so a 0 returncode is
    the only signal available here."""
    cmd = [_RNODECONF_BIN, "--eeprom-wipe", port]
    yield _ndjson({"type": "started", "cmd": cmd})
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_rnodeconf_env(),
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
                text = line.decode("utf-8", errors="replace").rstrip("\n")
                await queue.put({"type": "line", "stream": name, "text": text})
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




def _rnsd_configured_port() -> str:
    """The RNode serial port rnsd is configured to hold, from
    ``plugins.reticulum.rnode_serial_port`` (an opaque per-plugin dict --
    the reticulum plugin owns this key now that Reticulum moved out of
    core). Empty string if unset or the plugin isn't configured."""
    if _config is None:
        return ""
    plugin_cfg = _config.plugins.get("reticulum", {})
    return str(plugin_cfg.get("rnode_serial_port") or "") if isinstance(plugin_cfg, dict) else ""


def _rnsd_owns_port(port_aliases: set) -> bool:
    """``port_aliases`` should be every known alias (device/stable_path/
    by_id/by_path) of the *matched* device, not just the single string
    the client submitted -- ``plugins.reticulum.rnode_serial_port`` in
    local.yaml and whatever alias the dashboard's own port picker
    happened to submit are both valid identifiers for the same physical
    device, but rarely the same literal string (e.g. one's a by-id path,
    the other's by-path). Comparing only the submitted string against
    the configured one produced a real live bug: rnsd's port genuinely
    matched but this returned False, so rnsd never got released and the
    flash failed with "Could not find specified port" -- confirmed live."""
    configured = _rnsd_configured_port()
    return bool(configured and configured in port_aliases)


@router.get("/targets")
async def firmware_targets(_claims: SessionClaims = Depends(require_admin)) -> dict:
    return {
        "boards": [
            {"value": key, "label": board["label"]}
            for key, board in _BOARDS.items()
        ],
        "rnodeconf_available": _rnodeconf_available(),
    }


class FlashRequest(BaseModel):
    board: str
    port: str
    erase_first: bool = False


@router.post("/flash/stream")
async def flash_firmware_stream(
    req: FlashRequest,
    claims: SessionClaims = Depends(require_admin),
    audit: AuditLogWriter = Depends(get_audit_writer),
) -> StreamingResponse:
    """Flashes RNode firmware + bootstraps EEPROM + sets firmware hash
    in one ``rnodeconf -a`` run (see module docstring for why one
    command covers all three steps). ``port`` can be ANY currently-
    connected USB-serial device, same live-enumeration validation
    every other flash route uses -- this isn't tied to a pre-configured
    companion."""
    board = _BOARDS.get(req.board)
    if board is None:
        raise HTTPException(400, "Unknown board selection")

    from src.hal.usb_classifier import list_serial_ports_with_stable_paths
    matched_aliases: Optional[set] = None
    canonical_device: Optional[str] = None
    for dev in list_serial_ports_with_stable_paths():
        if dev.vid is None:
            continue
        aliases = {v for v in (dev.device, dev.stable_path, dev.by_id, dev.by_path) if v}
        if req.port in aliases:
            matched_aliases = aliases
            canonical_device = dev.device
            break
    if matched_aliases is None or canonical_device is None:
        raise HTTPException(400, "Selected port is not a currently connected USB-serial device")
    # rnodeconf matches its `port` argument against pyserial's own
    # list_ports.comports() by exact `port.device` equality (confirmed
    # from RNS/Utilities/rnodeconf.py source) -- comports() only ever
    # returns canonical /dev/ttyUSBx-style paths, never a by-id/by-path
    # symlink, even though those are equally valid for actually opening
    # the device. Passing a stable alias here (which every other flash
    # route in this codebase does, and which is the right choice for a
    # *persisted* config value like reticulum.rnode_serial_port) fails
    # with "Could not find specified port" every time -- confirmed
    # live, independent of whether rnsd holds the port or not. rnodeconf
    # itself is the one exception that needs the live canonical path.
    port = canonical_device
    release_rnsd = _rnsd_owns_port(matched_aliases)

    async def body() -> AsyncIterator[bytes]:
        with audit.timed_action(
            user=claims.subject, action="rnode_firmware.flash",
            params={
                "board": req.board, "port": port,
                "released_rnsd": release_rnsd, "erase_first": req.erase_first,
            },
        ) as ctx:
            if release_rnsd:
                yield _ndjson({
                    "type": "line", "stream": "stdout",
                    "text": f"Stopping rnsd (holds {port} open as its own RNode interface)…",
                })
                rc, out = await _run_systemctl("stop", "rnsd")
                if rc != 0:
                    yield _ndjson({
                        "type": "line", "stream": "stderr",
                        "text": f"Could not stop rnsd (exit {rc}): {out}",
                    })

            success = False
            try:
                if req.erase_first:
                    # A board that's already provisioned refuses to
                    # reflash (see _ALREADY_PROVISIONED_MARKER) --
                    # rnodeconf's own docs say wiping the EEPROM first
                    # is the way to force a real reinstall. Aborts
                    # before ever attempting the flash if the wipe
                    # itself fails, same as any other precondition.
                    yield _ndjson({
                        "type": "line", "stream": "stdout",
                        "text": "Erasing EEPROM first…",
                    })
                    wipe_ok = False
                    async for chunk in _stream_eeprom_wipe(port):
                        yield chunk
                        event = json.loads(chunk)
                        if event.get("type") == "result":
                            wipe_ok = bool((event.get("result") or {}).get("success"))
                    if not wipe_ok:
                        yield _ndjson({
                            "type": "line", "stream": "stderr",
                            "text": "EEPROM erase failed -- aborting before attempting to flash.",
                        })
                        return
                    yield _ndjson({
                        "type": "line", "stream": "stdout",
                        "text": "Waiting for the board to finish resetting…",
                    })
                    await asyncio.sleep(2.0)

                async for chunk in _stream_autoinstall(port, board["seq"]):
                    yield chunk
                    event = json.loads(chunk)
                    if event.get("type") == "result":
                        success = bool((event.get("result") or {}).get("success"))
            finally:
                if release_rnsd:
                    yield _ndjson({
                        "type": "line", "stream": "stdout",
                        "text": "Waiting for the board to finish rebooting…",
                    })
                    await asyncio.sleep(3.0)
                    yield _ndjson({
                        "type": "line", "stream": "stdout",
                        "text": "Restarting rnsd…",
                    })
                    await _run_systemctl("start", "rnsd")
                    rc, out = await _run_systemctl("is-active", "rnsd")
                    yield _ndjson({
                        "type": "line", "stream": "stdout",
                        "text": (
                            "rnsd reconnected." if rc == 0
                            else f"rnsd did NOT come back up (status: {out}) -- "
                                 "check `systemctl status rnsd`."
                        ),
                    })

            ctx.set_result("success" if success else "error")

    return StreamingResponse(
        body(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )
