"""Band-spectrum API backed by the SX1302 spectral-scan sweep.

GET returns the latest sweep envelope (median/p95 per frequency step)
for the Hardware page spectrum card; POST triggers an on-demand sweep.
The service reference is bound in the FastAPI lifespan after the
concentrator starts (same pattern as listener_routes); on boxes without
spectral-scan support it stays None and GET reports unavailable.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from fastapi import APIRouter, Depends, HTTPException

from src.api.auth.dependencies import require_admin
from src.api.auth.jwt_session import SessionClaims
from src.api.telemetry.spectral_scan_service import SpectralScanService

if TYPE_CHECKING:
    from src.api.telemetry.rfenv_companion_scan_service import RfEnvCompanionScanService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/device/spectrum", tags=["spectrum"])

_service: Optional[SpectralScanService | RfEnvCompanionScanService] = None


def init_routes(service: Optional[SpectralScanService | RfEnvCompanionScanService]) -> None:
    global _service
    _service = service


@router.get("")
async def get_spectrum():
    """Latest band sweep, or availability info before/without one."""
    if _service is None or not _service.sweep_supported:
        return {"available": False, "sweep": None}
    body = {"available": True, "sweep": _service.latest_sweep}
    # Only the capture-RAM fallback has (or needs) a baseline calibration.
    if hasattr(_service, "calibration_status"):
        body["calibration"] = _service.calibration_status()
    return body


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


def _calibratable():
    if _service is None or not hasattr(_service, "request_calibration"):
        raise HTTPException(404, "Calibration only applies to the capture-RAM spectrum")
    return _service


@router.post("/calibrate")
async def calibrate(
    _claims: SessionClaims = Depends(require_admin),
):
    """Run a calibration sweep; its median shape becomes the baseline."""
    service = _calibratable()
    if not service.request_calibration():
        raise HTTPException(503, "Spectral scan loop is not running")
    return {"requested": True}


@router.delete("/calibrate")
async def clear_calibration(
    _claims: SessionClaims = Depends(require_admin),
):
    """Forget the baseline; sweeps show the radios' raw shape again."""
    _calibratable().clear_calibration()
    return {"cleared": True}
