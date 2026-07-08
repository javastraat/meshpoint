"""Band-spectrum API backed by the SX1302 spectral-scan sweep.

GET returns the latest sweep envelope (median/p95 per frequency step)
for the Hardware page spectrum card; POST triggers an on-demand sweep.
The service reference is bound in the FastAPI lifespan after the
concentrator starts (same pattern as listener_routes); on boxes without
spectral-scan support it stays None and GET reports unavailable.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from src.api.auth.dependencies import require_admin
from src.api.auth.jwt_session import SessionClaims
from src.api.telemetry.spectral_scan_service import SpectralScanService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/device/spectrum", tags=["spectrum"])

_service: Optional[SpectralScanService] = None


def init_routes(service: Optional[SpectralScanService]) -> None:
    global _service
    _service = service


@router.get("")
async def get_spectrum():
    """Latest band sweep, or availability info before/without one."""
    if _service is None or not _service.sweep_supported:
        return {"available": False, "sweep": None}
    return {"available": True, "sweep": _service.latest_sweep}


@router.post("/sweep")
async def trigger_sweep(
    _claims: SessionClaims = Depends(require_admin),
):
    """Request an on-demand sweep; the scan loop picks it up immediately."""
    if _service is None or not _service.sweep_supported:
        raise HTTPException(503, "Spectral sweep not available on this device")
    if not _service.request_sweep():
        raise HTTPException(503, "Spectral scan loop is not running")
    return {"requested": True}
