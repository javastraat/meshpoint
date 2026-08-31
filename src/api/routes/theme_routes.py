"""``GET /api/themes`` -- the dashboard theme picker's manifest.

Lists whatever lives in ``frontend/themes/<id>/`` (see
``src/api/theme_registry.py``). Unauthenticated on purpose: it carries no
device data and the ``theme.css`` files it points at are already served
unauthenticated through the static mount.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter

from src.api.theme_registry import DEFAULT_THEME_ID, scan_themes

router = APIRouter(prefix="/api", tags=["themes"])

_themes_dir: Path | None = None


def init_routes(themes_dir: Path) -> None:
    global _themes_dir
    _themes_dir = themes_dir


@router.get("/themes")
async def list_themes() -> dict:
    themes = scan_themes(_themes_dir) if _themes_dir is not None else []
    return {"themes": themes, "default": DEFAULT_THEME_ID}
