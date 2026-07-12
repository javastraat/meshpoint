"""Repeater poll settings for Configuration -> Repeater Poll.

Passwords are secrets like the MeshCore/MQTT ones: ``GET /api/config``
(via ``config_enrichment.py``) only ever reports ``password_set``, never
the value itself. Saving a repeater whose password is left blank keeps
whatever password is already on file for that key -- same
dirty-tracking pattern the MQTT broker password field uses.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.api.audit import AuditLogWriter
from src.api.audit.dependencies import get_audit_writer
from src.api.auth.dependencies import require_admin
from src.api.auth.jwt_session import SessionClaims
from src.config import AppConfig, RepeaterConfig, save_section_to_yaml

router = APIRouter(prefix="/api/config", tags=["config"])

_config: AppConfig | None = None


def init_routes(config: AppConfig) -> None:
    global _config
    _config = config


def reset_routes() -> None:
    global _config
    _config = None


class RepeaterEntry(BaseModel):
    key: str = Field(..., min_length=1, max_length=32)
    name: str = ""
    password: Optional[str] = None
    password_unchanged: bool = True


class RepeaterPollUpdate(BaseModel):
    enabled: Optional[bool] = None
    interval_minutes: Optional[int] = Field(None, ge=5, le=1440)
    repeaters: Optional[list[RepeaterEntry]] = None


@router.put("/repeater-poll")
async def update_repeater_poll(
    req: RepeaterPollUpdate,
    claims: SessionClaims = Depends(require_admin),
    audit: AuditLogWriter = Depends(get_audit_writer),
):
    if _config is None:
        raise HTTPException(503, "Config not loaded")

    rp = _config.repeater_poll
    yaml_updates: dict = {}
    audit_params: dict = {}

    if req.enabled is not None:
        rp.enabled = req.enabled
        yaml_updates["enabled"] = req.enabled
        audit_params["enabled"] = req.enabled

    if req.interval_minutes is not None:
        rp.interval_minutes = req.interval_minutes
        yaml_updates["interval_minutes"] = req.interval_minutes
        audit_params["interval_minutes"] = req.interval_minutes

    if req.repeaters is not None:
        existing_by_key = {r.key.strip().lower(): r for r in rp.repeaters}
        new_repeaters: list[RepeaterConfig] = []
        for entry in req.repeaters:
            key = entry.key.strip().lower()
            if not key:
                continue
            if entry.password_unchanged:
                password = existing_by_key[key].password if key in existing_by_key else ""
            else:
                password = entry.password or ""
            new_repeaters.append(
                RepeaterConfig(key=key, password=password, name=entry.name.strip())
            )
        rp.repeaters = new_repeaters
        yaml_updates["repeaters"] = [
            {"key": r.key, "password": r.password, "name": r.name}
            for r in new_repeaters
        ]
        # Never log passwords, not even indirectly -- just the count/keys.
        audit_params["repeater_keys"] = [r.key for r in new_repeaters]

    if not yaml_updates:
        return {"saved": False, "restart_required": False}

    with audit.timed_action(
        user=claims.subject,
        action="config.repeater_poll_update",
        params=audit_params,
    ):
        try:
            save_section_to_yaml("repeater_poll", yaml_updates)
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc

    return {"saved": True, "restart_required": True}
