"""Prometheus /metrics endpoint settings for Configuration -> Metrics."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.api.audit import AuditLogWriter
from src.api.audit.dependencies import get_audit_writer
from src.api.auth.dependencies import require_admin
from src.api.auth.jwt_session import SessionClaims
from src.config import AppConfig, save_section_to_yaml

router = APIRouter(prefix="/api/config", tags=["config"])

_config: AppConfig | None = None


def init_routes(config: AppConfig) -> None:
    global _config
    _config = config


def reset_routes() -> None:
    global _config
    _config = None


class MetricsUpdate(BaseModel):
    enabled: Optional[bool] = None
    require_auth: Optional[bool] = None


@router.put("/metrics")
async def update_metrics(
    req: MetricsUpdate,
    claims: SessionClaims = Depends(require_admin),
    audit: AuditLogWriter = Depends(get_audit_writer),
):
    """Mutates the shared MetricsConfig instance in place -- metrics_routes.py
    reads config.metrics.enabled/require_auth fresh on every request, so
    this takes effect immediately, no restart needed (unlike most other
    config pages).
    """
    if _config is None:
        raise HTTPException(503, "Config not loaded")

    metrics = _config.metrics
    yaml_updates: dict = {}

    if req.enabled is not None:
        metrics.enabled = req.enabled
        yaml_updates["enabled"] = req.enabled

    if req.require_auth is not None:
        metrics.require_auth = req.require_auth
        yaml_updates["require_auth"] = req.require_auth

    if not yaml_updates:
        return {"saved": False, "restart_required": False}

    with audit.timed_action(
        user=claims.subject,
        action="config.metrics_update",
        params=yaml_updates,
    ):
        try:
            save_section_to_yaml("metrics", yaml_updates)
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc

    return {"saved": True, "restart_required": False}
