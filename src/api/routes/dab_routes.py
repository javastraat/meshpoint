"""DAB/DAB+ web listener endpoints: tune / stop / status / MP3 stream proxy.

See src/audio/dab_listener.py for the listener class (wraps a welle-cli
subprocess) and src/audio/sdr_registry.py for why tuning can fail with a
503 while another RTL-SDR listener (Radio/P2000/Pagers/POCSAG/RTL433) is
active -- only one process can hold the dongle at a time.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.api.auth.dependencies import require_admin
from src.api.auth.jwt_session import SessionClaims
from src.audio.dab_listener import DabListener

router = APIRouter(prefix="/api/dab", tags=["dab"])

_listener: Optional[DabListener] = None


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
