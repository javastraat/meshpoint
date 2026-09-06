"""NomadNet browsing endpoints -- the Reticulum page's "Browse" tab.

`/api/reticulum/nomad/nodes` lists the `nomadnetwork.node` peers already
in the roster (announces the plugin's LxmfService heard); `/page` fetches
one page's Micron markup over a Link. See `backend/nomad.py`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.api.auth.dependencies import require_admin
from src.api.auth.jwt_session import SessionClaims

from . import nomad
from .lxmf_service import LxmfService

router = APIRouter(prefix="/api/reticulum/nomad", tags=["reticulum"])

_service: LxmfService | None = None


def init_routes(service: LxmfService) -> None:
    global _service
    _service = service


def reset_routes() -> None:
    global _service
    _service = None
    nomad.reset()


@router.get("/nodes")
async def nomad_nodes():
    """Known `nomadnetwork.node` destinations, newest-seen first."""
    if _service is None:
        raise HTTPException(503, "Reticulum companion is disabled")
    peers = await _service.list_peers()
    return [
        p.to_dict() for p in peers if p.aspect == "nomadnetwork.node"
    ]


class PageRequest(BaseModel):
    destination_hash: str = Field(..., min_length=1)
    path: str = "/page/index.mu"
    field_data: dict | None = None


@router.post("/page")
async def nomad_page(
    req: PageRequest, _claims: SessionClaims = Depends(require_admin),
):
    """Fetch one NomadNet page. Returns `{ok, content}` (Micron markup) or
    `{ok: false, error}` -- a fetch failure is a 200 with `ok: false`, not
    an HTTP error, so the Browse tab can show it inline."""
    result = await nomad.fetch_page(
        req.destination_hash, req.path or "/page/index.mu", req.field_data,
    )
    return {
        "ok": result.ok,
        "content": result.content,
        "error": result.error,
        "destination_hash": result.destination_hash,
        "path": result.path,
    }
