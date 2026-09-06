"""Native Reticulum/LXMF messaging endpoints -- peer roster, message
history (reusing the existing ``messages`` table with
protocol='reticulum'), and send. Backed by ``backend/lxmf_service.py``.

Moved from ``src/api/routes/reticulum_routes.py`` as part of the
core->plugin extraction. Only the ``LxmfService`` import path changed
(now ``.lxmf_service``); ``init_routes`` is called from the plugin's
``add_service`` wire() callback once the service + message repo exist.

Read endpoints stay open to any authenticated viewer, same as core's
``messages.py`` GET routes -- only sending requires admin.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.api.auth.dependencies import require_admin
from src.api.auth.jwt_session import SessionClaims
from src.storage.message_repository import MessageRepository

from .lxmf_service import LxmfService

router = APIRouter(prefix="/api/reticulum", tags=["reticulum"])

_service: LxmfService | None = None
_message_repo: MessageRepository | None = None


def init_routes(service: LxmfService, message_repo: MessageRepository) -> None:
    global _service, _message_repo
    _service = service
    _message_repo = message_repo


def reset_routes() -> None:
    global _service, _message_repo
    _service = None
    _message_repo = None


@router.get("/status")
async def reticulum_status():
    if _service is None:
        return {"enabled": False, "running": False}
    peer_count = len(await _service.list_peers()) if _service.own_address else 0
    return {
        "enabled": True,
        "running": _service.own_address is not None,
        "available": _service.available,
        "own_address": _service.own_address,
        "peer_count": peer_count,
    }


@router.get("/peers")
async def reticulum_peers():
    if _service is None:
        raise HTTPException(503, "Reticulum companion is disabled")
    peers = await _service.list_peers()
    return [p.to_dict() for p in peers]


@router.get("/messages/{destination_hash}")
async def reticulum_conversation(destination_hash: str, limit: int = 50):
    if _message_repo is None:
        raise HTTPException(503, "Routes not initialised")
    messages = await _message_repo.get_conversation(destination_hash, limit=limit)
    return [m.to_dict() for m in messages]


class SendRequest(BaseModel):
    destination_hash: str = Field(..., min_length=1)
    text: str = Field(..., min_length=1, max_length=10_000)


@router.post("/send")
async def reticulum_send(
    req: SendRequest, _claims: SessionClaims = Depends(require_admin),
):
    if _service is None:
        raise HTTPException(503, "Reticulum companion is disabled")
    try:
        row_id = await _service.send_message(req.destination_hash, req.text)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))
    return {"id": row_id, "status": "sent"}


@router.post("/announce")
async def reticulum_announce(_claims: SessionClaims = Depends(require_admin)):
    if _service is None:
        raise HTTPException(503, "Reticulum companion is disabled")
    try:
        _service.announce()
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))
    return {"status": "announced"}
