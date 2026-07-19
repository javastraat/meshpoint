"""DAB/DAB+ web listener endpoints: tune / stop / status / MP3 stream proxy.

See src/audio/dab_listener.py for the listener class (wraps a welle-cli
subprocess) and src/audio/sdr_registry.py for why tuning can fail with a
503 while another RTL-SDR listener (Radio/P2000/Pagers/POCSAG/RTL433) is
active -- only one process can hold the dongle at a time.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.api.auth.dependencies import require_admin
from src.api.auth.jwt_session import SessionClaims
from src.audio.dab_listener import DabListener
from src.backup.paths import resolve_meshpoint_root

router = APIRouter(prefix="/api/dab", tags=["dab"])

_listener: Optional[DabListener] = None

# scripts/dab_channel_scan.py's default --output, resolved the same
# Mac-dev-vs-Pi-install-portable way as repo_source.py -- MESHPOINT_DIR
# or cwd, so this works whether the server runs from /opt/meshpoint on
# the real device or a plain checkout on a dev machine.
_SCAN_RESULTS_RELATIVE_PATH = Path("config") / "dab_channel_scan.json"


def _scan_results_path() -> Path:
    return resolve_meshpoint_root() / _SCAN_RESULTS_RELATIVE_PATH


def init_routes(listener: DabListener) -> None:
    global _listener
    _listener = listener


def reset_routes() -> None:
    global _listener
    _listener = None


class TuneRequest(BaseModel):
    channel: str = Field(
        ..., min_length=1, max_length=4,
        description="DAB channel/ensemble code, e.g. 12C",
    )


class ChannelNameUpdate(BaseModel):
    custom_name: str = Field(
        default="", max_length=120,
        description="Display name override; empty string clears it back to the scanned label",
    )


@router.get("/status")
async def dab_status():
    if _listener is None:
        raise HTTPException(503, "Listener not initialised")
    return _listener.poll()


@router.post("/tune")
async def dab_tune(
    req: TuneRequest,
    _claims: SessionClaims = Depends(require_admin),
):
    """Start welle-cli, or retune if already running."""
    if _listener is None:
        raise HTTPException(503, "Listener not initialised")
    try:
        await _listener.tune(req.channel)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))
    return _listener.status()


@router.post("/stop")
async def dab_stop(_claims: SessionClaims = Depends(require_admin)):
    if _listener is None:
        raise HTTPException(503, "Listener not initialised")
    await _listener.stop()
    return _listener.status()


@router.get("/stream/{sid}")
async def dab_stream(sid: str):
    """Live MP3 for one DAB+ service, proxied from welle-cli's own webserver."""
    if _listener is None:
        raise HTTPException(503, "Listener not initialised")
    if not _listener.running:
        raise HTTPException(409, "Listener not running -- tune first")

    async def _gen():
        async for chunk in _listener.stream(sid):
            yield chunk

    return StreamingResponse(
        _gen(),
        media_type="audio/mpeg",
        headers={
            "Cache-Control": "no-cache, no-store",
            "X-Accel-Buffering": "no",
        },
    )


def _read_scan_results(path: Path) -> dict:
    if not path.exists():
        raise HTTPException(
            404,
            f"No DAB channel scan results found at {path} -- run scripts/dab_channel_scan.py "
            "on the device first, then reload this tab.",
        )
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise HTTPException(500, f"Couldn't read scan results at {path}: {exc}")


@router.get("/scan-results")
async def dab_scan_results():
    """Channels scripts/dab_channel_scan.py found, read straight from its JSON output."""
    return _read_scan_results(_scan_results_path())


@router.put("/scan-results/{channel}/name")
async def dab_scan_results_set_name(
    channel: str,
    body: ChannelNameUpdate,
    _claims: SessionClaims = Depends(require_admin),
):
    """Set (or, with an empty string, clear) a custom display name for a scanned channel."""
    path = _scan_results_path()
    data = _read_scan_results(path)
    entry = next((c for c in data.get("channels", []) if c.get("channel") == channel), None)
    if entry is None:
        raise HTTPException(404, f"Channel {channel} not found in scan results")

    name = body.custom_name.strip()
    if name:
        entry["custom_name"] = name
    else:
        entry.pop("custom_name", None)
    path.write_text(json.dumps(data, indent=2))
    return entry
