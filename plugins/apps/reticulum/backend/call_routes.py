"""Voice call endpoints -- initiate/hangup (plain REST) and the audio
byte bridge itself (a WebSocket). Backs the ``reticulum-call`` plugin's
UI; none of this does anything unless ``plugins.reticulum.
audio_calls_enabled`` is also on (see ``backend/audio_call.py``).

Registered ``public=True`` (see ``register()`` in ``backend/__init__.py``)
-- **not** open to the world. The REST routes each carry their own
``Depends(require_admin)`` exactly like every other route in this
plugin; ``public=True`` only means the router-level blanket
``Depends(require_auth)`` safety net (every *other* plugin route relies
on that net in addition to its own explicit dependency) is skipped for
this router, because it cannot apply correctly to the websocket route
below in the first place. The websocket route gates itself manually --
see ``call_audio_bridge``'s own docstring for why a plain ``Depends()``
doesn't work here.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from src.api.auth.dependencies import get_jwt_service, require_admin
from src.api.auth.jwt_session import ROLE_ADMIN, SessionClaims
from src.api.auth.ws_guard import WS_AUTH_CLOSE_CODE, authenticate_websocket

from .lxmf_service import LxmfService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/reticulum", tags=["reticulum"])

_service: LxmfService | None = None


def init_routes(service: LxmfService) -> None:
    global _service
    _service = service


def reset_routes() -> None:
    global _service
    _service = None


class InitiateCallRequest(BaseModel):
    destination_hash: str = Field(..., min_length=1)


@router.post("/call/initiate")
async def call_initiate(
    req: InitiateCallRequest, _claims: SessionClaims = Depends(require_admin),
):
    if _service is None:
        raise HTTPException(503, "Reticulum companion is disabled")
    try:
        call = await _service.initiate_call(req.destination_hash)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))
    return call


@router.post("/call/{call_hash}/hangup")
async def call_hangup(
    call_hash: str, _claims: SessionClaims = Depends(require_admin),
):
    if _service is None:
        raise HTTPException(503, "Reticulum companion is disabled")
    if not _service.hangup_call(call_hash):
        raise HTTPException(404, "No such call")
    return {"hung_up": True}


@router.websocket("/call/{call_hash}/audio")
async def call_audio_bridge(websocket: WebSocket, call_hash: str):
    """The actual call: every inbound WS frame is a Codec2-encoded audio
    packet forwarded as-is onto the RNS Link (``AudioCall.
    send_audio_packet``), and every packet the link receives is pushed
    back out as a WS frame the same way. This route knows nothing about
    audio, codecs or framing -- it's exactly as dumb a byte pipe as
    ``AudioCall`` itself; all of that lives client-side in the
    ``reticulum-call`` plugin's own JS.

    Auth is manual, not a plain ``Depends(require_admin)``: that
    dependency is typed for an HTTP ``Request``, and doesn't resolve the
    same way against a WebSocket connection's scope -- confirmed by
    core's own dashboard ``/ws`` route needing the exact same manual
    ``authenticate_websocket()`` call instead (src/api/server.py,
    ``_gate_ws_or_close``). Mirrors its accept-before-close sequencing
    for the same reason: closing pre-accept surfaces to the browser as
    an abnormal-closure code, not the negotiated auth-rejection one.
    """
    claims = authenticate_websocket(websocket, get_jwt_service())
    if claims is None or claims.role != ROLE_ADMIN:
        await websocket.accept()
        await websocket.close(code=WS_AUTH_CLOSE_CODE)
        return

    if _service is None:
        await websocket.close(code=1011)
        return
    call = _service.get_call(call_hash)
    if call is None or not call.is_active():
        await websocket.close(code=1011)
        return

    await websocket.accept()
    loop = asyncio.get_running_loop()

    def on_audio_packet(data: bytes) -> None:
        # Runs on RNS's own callback thread -- hand the actual send to
        # the loop this connection is running on, same threading fix
        # used throughout lxmf_service.py for RNS callbacks.
        asyncio.run_coroutine_threadsafe(_safe_send(websocket, data), loop)

    call.register_audio_packet_listener(on_audio_packet)
    try:
        while call.is_active():
            data = await websocket.receive_bytes()
            call.send_audio_packet(data)
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001 -- never let a call bridge crash the worker
        logger.debug("call audio bridge error", exc_info=True)
    finally:
        call.unregister_audio_packet_listener(on_audio_packet)


async def _safe_send(websocket: WebSocket, data: bytes) -> None:
    try:
        await websocket.send_bytes(data)
    except Exception:  # noqa: BLE001 -- the other side may have already gone away
        logger.debug("call audio bridge send failed", exc_info=True)
