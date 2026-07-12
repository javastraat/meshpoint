"""rtl_433 (generic RTL-SDR OOK/FSK decoder) endpoints: start / stop / status.

See src/audio/rtl433_listener.py for the listener class, and
src/audio/sdr_registry.py for why starting this can fail with a 503
while the FM listener or a pager kind is active (only one process can
hold the RTL-SDR dongle at a time; manual stop required by design).
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException

from src.audio.rtl433_listener import Rtl433Listener

router = APIRouter(prefix="/api/rtl433", tags=["rtl433"])

_listener: Optional[Rtl433Listener] = None


def init_routes(listener: Rtl433Listener) -> None:
    global _listener
    _listener = listener


def reset_routes() -> None:
    global _listener
    _listener = None


@router.get("/status")
async def status():
    if _listener is None:
        raise HTTPException(503, "Listener not initialised")
    return _listener.poll()


@router.post("/start")
async def start():
    if _listener is None:
        raise HTTPException(503, "Listener not initialised")
    try:
        await _listener.start()
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))
    return _listener.status()


@router.post("/stop")
async def stop():
    if _listener is None:
        raise HTTPException(503, "Listener not initialised")
    await _listener.stop()
    return _listener.status()
