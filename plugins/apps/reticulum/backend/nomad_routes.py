"""NomadNet browsing endpoints -- the Reticulum page's "Browse" tab.

`/api/reticulum/nomad/nodes` lists the `nomadnetwork.node` peers already
in the roster (announces the plugin's LxmfService heard); `/page` fetches
one page's Micron markup over a Link; `/file` fetches a `/file/...` path
as an attachment. See `backend/nomad.py`.
"""

from __future__ import annotations

import mimetypes

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from src.api.auth.dependencies import require_admin
from src.api.auth.jwt_session import SessionClaims

from . import nomad, state
from .lxmf_service import LxmfService

router = APIRouter(prefix="/api/reticulum/nomad", tags=["reticulum"])

_service: LxmfService | None = None


def init_routes(service: LxmfService) -> None:
    global _service
    _service = service
    nomad.set_timeouts(state.to_dict().get("nomad_timeout_s"))


def reset_routes() -> None:
    global _service
    _service = None
    nomad.reset()


# The public network has thousands of nomadnetwork.node announces; the
# picker only needs the recently-active ones (anything else is still
# reachable by pasting its hash into the address bar).
_NODE_LIMIT = 300


@router.get("/nodes")
async def nomad_nodes():
    """The most recently-seen `nomadnetwork.node` destinations (capped)."""
    if _service is None:
        raise HTTPException(503, "Reticulum companion is disabled")
    peers = await _service.list_peers()  # already sorted last_seen DESC
    nodes = [p.to_dict() for p in peers if p.aspect == "nomadnetwork.node"]
    return nodes[:_NODE_LIMIT]


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


class FileRequest(BaseModel):
    destination_hash: str = Field(..., min_length=1)
    path: str = Field(..., min_length=1)


@router.post("/file")
async def nomad_file(
    req: FileRequest, _claims: SessionClaims = Depends(require_admin),
):
    """Fetch a `/file/...` path -- returns the raw bytes as an attachment,
    or a 502 with the failure reason."""
    result = await nomad.fetch_file(req.destination_hash, req.path)
    if not result.ok:
        raise HTTPException(502, result.error or "download failed")
    name = result.file_name or "downloaded_file"
    ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
    return Response(
        content=result.file_bytes or b"",
        media_type=ctype,
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )
