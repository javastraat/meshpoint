"""Plugin *sources* -- operator-added GitHub repos of installable plugins
and themes (Settings -> Plugins -> "Add source").

Phase 2 (this file): add / remove a source, and browse its catalog. No
install yet -- ``GET /api/plugin-sources/catalog`` returns what a repo
offers, annotated with whether each entry is already installed / an
update is available / compatible with this Meshpoint.

Sources are persisted to ``local.yaml`` (``plugin_sources:``) so they
survive restarts and self-updates -- ``local.yaml`` is user-owned and
git never touches it, same as ``plugins.<id>.enabled``.

**Trust model:** adding a source is the consent point. A source repo can
later install code that runs in-process with the service's privileges
(and root, via a plugin's ``setup.sh``), so ``POST`` requires an explicit
``confirm: true`` and is audited. Installing (Phase 3) and running a
setup script stay separate, explicit actions.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.api.audit import AuditLogWriter
from src.api.audit.dependencies import get_audit_writer
from src.api.auth.dependencies import require_admin
from src.api.auth.jwt_session import SessionClaims
from src.config import AppConfig, save_top_level_to_yaml
from src.plugins.manifest import discover_plugins
from src.plugins.sources import (
    PluginSourceError,
    canonical_url,
    fetch_catalog,
    parse_github_url,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/plugin-sources", tags=["plugins"])

_config: AppConfig | None = None
_builtin_dir: Path | None = None
_community_dir: Path | None = None


def init_routes(
    config: AppConfig, builtin_dir: Path, community_dir: Path,
) -> None:
    global _config, _builtin_dir, _community_dir
    _config = config
    _builtin_dir = builtin_dir
    _community_dir = community_dir


def reset_routes() -> None:
    global _config, _builtin_dir, _community_dir
    _config = None
    _builtin_dir = None
    _community_dir = None


def _require_config() -> AppConfig:
    if _config is None:
        raise HTTPException(503, "Config not loaded")
    return _config


def _sources() -> list[dict]:
    return [s for s in _require_config().plugin_sources if isinstance(s, dict)]


def _persist(sources: list[dict]) -> None:
    _require_config().plugin_sources = sources
    try:
        save_top_level_to_yaml("plugin_sources", sources)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc


def _installed_index() -> dict[str, str]:
    """id -> installed version, for every discovered plugin (built-in +
    community drop-in). Used to annotate catalog entries."""
    return {m.name: m.version for m in discover_plugins(_builtin_dir, _community_dir)}


@router.get("")
async def list_sources():
    """Every configured plugin source (not fetched -- just what's in config)."""
    return {"sources": _sources()}


class AddSource(BaseModel):
    url: str = Field(..., min_length=4)
    ref: str = "main"
    confirm: bool = False


@router.post("")
async def add_source(
    req: AddSource,
    claims: SessionClaims = Depends(require_admin),
    audit: AuditLogWriter = Depends(get_audit_writer),
):
    """Add a plugin source. ``confirm: true`` is required -- the caller has
    acknowledged that a source can install privileged code."""
    _require_config()
    if not req.confirm:
        raise HTTPException(
            400,
            "Adding a plugin source is a trust decision -- it can later install "
            "code that runs with the service's privileges. Re-send with "
            "confirm=true once you've acknowledged that.",
        )
    try:
        owner, repo = parse_github_url(req.url)
    except PluginSourceError as exc:
        raise HTTPException(400, str(exc)) from exc

    url = canonical_url(owner, repo)
    sources = _sources()
    if any(s.get("url") == url for s in sources):
        raise HTTPException(409, f"{url} is already a source")

    entry = {
        "url": url,
        "ref": (req.ref or "main").strip() or "main",
        "added_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "added_by": claims.subject,
    }
    with audit.timed_action(
        user=claims.subject, action="config.plugin_source_add",
        params={"url": url, "ref": entry["ref"]},
    ):
        _persist([*sources, entry])

    logger.info("plugin source added: %s @ %s (by %s)", url, entry["ref"], claims.subject)
    return {"added": True, "source": entry}


@router.delete("")
async def remove_source(
    url: str,
    claims: SessionClaims = Depends(require_admin),
    audit: AuditLogWriter = Depends(get_audit_writer),
):
    """Forget a source. Does not touch any plugin already installed from it."""
    _require_config()
    try:
        owner, repo = parse_github_url(url)
    except PluginSourceError as exc:
        raise HTTPException(400, str(exc)) from exc
    url = canonical_url(owner, repo)

    sources = _sources()
    kept = [s for s in sources if s.get("url") != url]
    if len(kept) == len(sources):
        raise HTTPException(404, f"{url} is not a configured source")

    with audit.timed_action(
        user=claims.subject, action="config.plugin_source_remove", params={"url": url},
    ):
        _persist(kept)

    logger.info("plugin source removed: %s (by %s)", url, claims.subject)
    return {"removed": True, "url": url}


@router.get("/catalog")
async def source_catalog(
    url: str, ref: str | None = None,
    _claims: SessionClaims = Depends(require_admin),
):
    """Fetch a source's ``meshpoint.json`` and return its offerings,
    annotated with install/compat state. ``ref`` defaults to the source's
    configured ref, then ``main``."""
    _require_config()
    if ref is None:
        try:
            owner, repo = parse_github_url(url)
            canon = canonical_url(owner, repo)
        except PluginSourceError as exc:
            raise HTTPException(400, str(exc)) from exc
        ref = next(
            (s.get("ref") for s in _sources() if s.get("url") == canon), None,
        )

    try:
        catalog = fetch_catalog(url, ref)
    except PluginSourceError as exc:
        raise HTTPException(400 if exc.code in ("url", "ref") else 502, str(exc)) from exc

    installed = _installed_index()
    for entry in catalog["plugins"] + catalog["themes"]:
        cur = installed.get(entry["id"])
        entry["installed"] = cur is not None
        entry["installed_version"] = cur
        entry["update_available"] = bool(cur and cur != entry["version"])
    return catalog
