"""Pagers RTL-SDR decoder endpoints: start / stop / status.

See src/audio/pager_listener.py for the PagerListener class this wraps,
and src/audio/sdr_registry.py for why starting it can fail with a 503
while the FM listener or another RTL-SDR listener is active (only one can
hold the dongle at a time; manual stop required by design).

(P2000/FLEX and POCSAG both have their own routes now --
plugins/apps/p2000/backend/routes.py and
plugins/apps/pocsag/backend/routes.py -- since both split out into their
own plugins, leaving just "pagers" here. `_add_endpoints` stays a
separate helper rather than being inlined, even for one router now,
since "pagers" itself may be the next one extracted the same way.)
"""

from __future__ import annotations

from typing import Callable, Optional

from fastapi import APIRouter, Depends, HTTPException

from src.api.auth.dependencies import require_admin
from src.api.auth.jwt_session import SessionClaims
from src.audio.pager_listener import PagerListener

pagers_router = APIRouter(prefix="/api/pagers", tags=["pagers"])

_pagers: Optional[PagerListener] = None


def init_routes(pagers: PagerListener) -> None:
    global _pagers
    _pagers = pagers


def reset_routes() -> None:
    global _pagers
    _pagers = None


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

    @router.post("/clear")
    async def clear(_claims: SessionClaims = Depends(require_admin)):
        listener = get_listener()
        if listener is None:
            raise HTTPException(503, "Listener not initialised")
        listener.clear()
        return listener.status()


_add_endpoints(pagers_router, lambda: _pagers)
