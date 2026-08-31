"""Dashboard theme endpoints.

``GET /api/themes`` -- the theme picker's manifest (list + the
server-configured default). Unauthenticated on purpose: it carries no
device data and the ``theme.css`` files it points at are already served
unauthenticated through the static mount.

``PUT /api/config/dashboard/theme`` -- admin-only; sets the default theme
for browsers that haven't picked one (``dashboard.theme`` in local.yaml).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.api.audit import AuditLogWriter
from src.api.audit.dependencies import get_audit_writer
from src.api.auth.jwt_session import SessionClaims
from src.api.auth.dependencies import require_admin
from src.api.theme_registry import DEFAULT_THEME_ID, scan_themes
from src.config import AppConfig, save_section_to_yaml

router = APIRouter(prefix="/api", tags=["themes"])

_themes_dir: Path | None = None
_plugin_themes_dir: Path | None = None
_config: AppConfig | None = None


def init_routes(
    themes_dir: Path,
    plugin_themes_dir: Path | None = None,
    config: AppConfig | None = None,
) -> None:
    global _themes_dir, _plugin_themes_dir, _config
    _themes_dir = themes_dir
    _plugin_themes_dir = plugin_themes_dir
    _config = config


def _theme_ids() -> set[str]:
    if _themes_dir is None:
        return {DEFAULT_THEME_ID}
    return {t["id"] for t in scan_themes(_themes_dir, _plugin_themes_dir)}


def _current_default() -> str:
    configured = getattr(getattr(_config, "dashboard", None), "theme", None)
    if configured and configured in _theme_ids():
        return configured
    return DEFAULT_THEME_ID


@router.get("/themes")
async def list_themes() -> dict:
    themes = (
        scan_themes(_themes_dir, _plugin_themes_dir)
        if _themes_dir is not None
        else []
    )
    return {"themes": themes, "default": _current_default()}


class ThemeUpdate(BaseModel):
    theme: str


@router.put("/config/dashboard/theme")
async def set_default_theme(
    req: ThemeUpdate,
    _claims: SessionClaims = Depends(require_admin),
    audit: AuditLogWriter = Depends(get_audit_writer),
) -> dict:
    theme = (req.theme or "").strip()
    if theme not in _theme_ids():
        raise HTTPException(400, f"Unknown theme {theme!r}")

    with audit.timed_action(
        user=_claims.subject,
        action="config.dashboard_theme",
        params={"theme": theme},
    ):
        try:
            save_section_to_yaml("dashboard", {"theme": theme})
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc

    if _config is not None:
        _config.dashboard.theme = theme

    return {"saved": True, "theme": theme}
