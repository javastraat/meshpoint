"""Prometheus /metrics endpoint settings for Configuration -> Metrics."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.api.audit import AuditLogWriter
from src.api.audit.dependencies import get_audit_writer
from src.api.auth.dependencies import require_admin
from src.api.auth.jwt_session import SessionClaims
from src.config import AppConfig, MetricsApiKey, save_section_to_yaml

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


def _key_to_yaml(key: MetricsApiKey) -> dict:
    return {
        "id": key.id,
        "label": key.label,
        "key_hash": key.key_hash,
        "created_at": key.created_at,
        "last_used_at": key.last_used_at,
    }


class ApiKeyCreate(BaseModel):
    label: str = Field(..., min_length=1, max_length=64)


@router.post("/metrics/api-keys")
async def create_metrics_api_key(
    req: ApiKeyCreate,
    claims: SessionClaims = Depends(require_admin),
    audit: AuditLogWriter = Depends(get_audit_writer),
):
    """Mint a new /metrics-scoped bearer key. The raw key is returned once
    and never stored -- only its SHA-256 hash is kept, matching how admin
    passwords are handled.
    """
    if _config is None:
        raise HTTPException(503, "Config not loaded")

    raw_key = secrets.token_urlsafe(32)
    key = MetricsApiKey(
        id=secrets.token_hex(8),
        label=req.label.strip(),
        key_hash=hashlib.sha256(raw_key.encode()).hexdigest(),
        created_at=datetime.now(timezone.utc).isoformat(),
        last_used_at=None,
    )

    with audit.timed_action(
        user=claims.subject,
        action="config.metrics_api_key_create",
        params={"label": key.label, "id": key.id},
    ):
        _config.metrics.api_keys.append(key)
        try:
            save_section_to_yaml(
                "metrics",
                {"api_keys": [_key_to_yaml(k) for k in _config.metrics.api_keys]},
            )
        except PermissionError as exc:
            _config.metrics.api_keys.remove(key)
            raise HTTPException(403, str(exc)) from exc

    return {
        "id": key.id,
        "label": key.label,
        "created_at": key.created_at,
        "key": raw_key,
    }


@router.delete("/metrics/api-keys/{key_id}")
async def revoke_metrics_api_key(
    key_id: str,
    claims: SessionClaims = Depends(require_admin),
    audit: AuditLogWriter = Depends(get_audit_writer),
):
    if _config is None:
        raise HTTPException(503, "Config not loaded")

    metrics = _config.metrics
    match = next((k for k in metrics.api_keys if k.id == key_id), None)
    if match is None:
        raise HTTPException(404, "API key not found")

    with audit.timed_action(
        user=claims.subject,
        action="config.metrics_api_key_revoke",
        params={"label": match.label, "id": match.id},
    ):
        metrics.api_keys = [k for k in metrics.api_keys if k.id != key_id]
        try:
            save_section_to_yaml(
                "metrics",
                {"api_keys": [_key_to_yaml(k) for k in metrics.api_keys]},
            )
        except PermissionError as exc:
            metrics.api_keys.append(match)
            raise HTTPException(403, str(exc)) from exc

    return {"deleted": True}
