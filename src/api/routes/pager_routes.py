"""P2000, Pagers, and POCSAG RTL-SDR decoder endpoints: start / stop / status.

Three nearly-identical REST surfaces (one router per kind, same shape) --
see src/audio/pager_listener.py for the shared PagerListener class all
three wrap, and src/audio/sdr_registry.py for why starting one can fail
with a 503 while the FM listener or another pager kind is active (only
one can hold the RTL-SDR dongle at a time; manual stop required by
design).
"""

from __future__ import annotations

from typing import Callable, Optional

from fastapi import APIRouter, Depends, HTTPException

from src.api.auth.dependencies import require_admin
from src.api.auth.jwt_session import SessionClaims
from src.audio.pager_listener import PagerListener

p2000_router = APIRouter(prefix="/api/p2000", tags=["p2000"])
pagers_router = APIRouter(prefix="/api/pagers", tags=["pagers"])
pocsag_router = APIRouter(prefix="/api/pocsag", tags=["pocsag"])

_p2000: Optional[PagerListener] = None
_pagers: Optional[PagerListener] = None
_pocsag: Optional[PagerListener] = None


def init_routes(p2000: PagerListener, pagers: PagerListener, pocsag: PagerListener) -> None:
    global _p2000, _pagers, _pocsag
    _p2000 = p2000
    _pagers = pagers
    _pocsag = pocsag


def reset_routes() -> None:
    global _p2000, _pagers, _pocsag
    _p2000 = None
    _pagers = None
    _pocsag = None


def _add_endpoints(router: APIRouter, get_listener: Callable[[], Optional[PagerListener]]) -> None:
    @router.get("/status")
    async def status():
        listener = get_listener()
        if listener is None:
            raise HTTPException(503, "Listener not initialised")
        return listener.poll()

    @router.post("/start")
    async def start(_claims: SessionClaims = Depends(require_admin)):
        listener = get_listener()
        if listener is None:
            raise HTTPException(503, "Listener not initialised")
        try:
            await listener.start()
        except RuntimeError as exc:
            raise HTTPException(503, str(exc))
        return listener.status()

    @router.post("/stop")
    async def stop(_claims: SessionClaims = Depends(require_admin)):
        listener = get_listener()
        if listener is None:
            raise HTTPException(503, "Listener not initialised")
        await listener.stop()
        return listener.status()


_add_endpoints(p2000_router, lambda: _p2000)
_add_endpoints(pagers_router, lambda: _pagers)
_add_endpoints(pocsag_router, lambda: _pocsag)
