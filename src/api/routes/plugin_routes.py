"""Plugins management page (Settings -> Plugins).

Lists every discovered app plugin (``src/plugins/apps/`` built-ins +
``<plugins_dir>/apps/`` community drop-ins) with its current
``plugins.<id>.enabled`` state, and lets an admin flip that flag -- persisted
to ``local.yaml`` via :func:`~src.config.save_section_to_yaml`, same as every
other Configuration/Settings card. Enabling/disabling a plugin only takes
effect on the next restart (plugins are loaded once at ``create_app`` time),
so the response always reports both the *configured* state and whether the
plugin is actually ``loaded`` in this running process.

An admin can also delete a community plugin's folder outright (an
"uninstall") -- refused for built-ins and for a ``locked`` community plugin
(a shipped/bundled one, like ACARS, that ``git`` tracks; deleting it
wouldn't stick past the next update anyway). Mirrors the exact
built-in/locked-vs-custom split ``src/api/theme_store.py`` already uses for
plugin themes.
"""

from __future__ import annotations

import getpass
import logging
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.api.audit import AuditLogWriter
from src.api.audit.dependencies import get_audit_writer
from src.api.auth.dependencies import require_admin
from src.api.auth.jwt_session import SessionClaims
from src.config import AppConfig, remove_subsection_key, save_section_to_yaml
from src.plugins.loader import LoadedPlugin, is_plugin_enabled
from src.plugins.manifest import SOURCE_COMMUNITY, PluginManifest, discover_plugins

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/plugins", tags=["plugins"])

_config: AppConfig | None = None
_builtin_dir: Path | None = None
_community_dir: Path | None = None
_loaded_plugins: list[LoadedPlugin] = []


def init_routes(
    config: AppConfig,
    builtin_dir: Path,
    community_dir: Path,
    loaded_plugins: list[LoadedPlugin],
) -> None:
    global _config, _builtin_dir, _community_dir, _loaded_plugins
    _config = config
    _builtin_dir = builtin_dir
    _community_dir = community_dir
    _loaded_plugins = loaded_plugins


def reset_routes() -> None:
    global _config, _builtin_dir, _community_dir, _loaded_plugins
    _config = None
    _builtin_dir = None
    _community_dir = None
    _loaded_plugins = []


def _describe(manifest: PluginManifest, loaded_names: set[str]) -> dict:
    conf = _config.plugins.get(manifest.name)
    conf = conf if isinstance(conf, dict) else {}
    enabled = is_plugin_enabled(manifest, conf)
    loaded = manifest.name in loaded_names
    return {
        "id": manifest.name,
        "version": manifest.version,
        "source": manifest.source,
        "provides": list(manifest.provides),
        "description": manifest.description,
        "homepage": manifest.homepage,
        "author": manifest.author,
        "apt_deps": list(manifest.apt),
        "setup_script": manifest.setup,
        "enabled": enabled,
        "loaded": loaded,
        "restart_required": enabled != loaded,
        "locked": manifest.locked,
        "deletable": manifest.source == SOURCE_COMMUNITY and not manifest.locked,
    }


def _find_manifest(plugin_id: str) -> PluginManifest:
    for manifest in discover_plugins(_builtin_dir, _community_dir):
        if manifest.name == plugin_id:
            return manifest
    raise HTTPException(404, f"No plugin {plugin_id!r} found")


@router.get("")
async def list_plugins():
    """Every discovered plugin, built-ins first, with its config + load state."""
    if _config is None:
        raise HTTPException(503, "Config not loaded")
    loaded_names = {p.manifest.name for p in _loaded_plugins}
    manifests = discover_plugins(_builtin_dir, _community_dir)
    return {"plugins": [_describe(m, loaded_names) for m in manifests]}


class PluginUpdate(BaseModel):
    enabled: bool


@router.put("/{plugin_id}")
async def update_plugin(
    plugin_id: str,
    req: PluginUpdate,
    _claims: SessionClaims = Depends(require_admin),
    audit: AuditLogWriter = Depends(get_audit_writer),
):
    """Persist ``plugins.<id>.enabled``. Takes effect on the next restart."""
    if _config is None:
        raise HTTPException(503, "Config not loaded")

    manifest = _find_manifest(plugin_id)

    with audit.timed_action(
        user=_claims.subject,
        action="config.plugin_update",
        params={"plugin_id": plugin_id, "enabled": req.enabled},
    ):
        existing = _config.plugins.get(plugin_id)
        existing = dict(existing) if isinstance(existing, dict) else {}
        existing["enabled"] = req.enabled
        _config.plugins[plugin_id] = existing

        try:
            save_section_to_yaml("plugins", {plugin_id: existing})
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc

    logger.info("plugin %s enabled=%s (restart required)", plugin_id, req.enabled)

    loaded_names = {p.manifest.name for p in _loaded_plugins}
    return {
        "saved": True,
        "restart_required": True,
        "plugin": _describe(manifest, loaded_names),
    }


@router.delete("/{plugin_id}")
async def delete_plugin(
    plugin_id: str,
    _claims: SessionClaims = Depends(require_admin),
    audit: AuditLogWriter = Depends(get_audit_writer),
):
    """Delete a community plugin's folder from disk (an "uninstall"). Refuses
    built-ins and ``locked`` plugins (shipped/bundled community plugins like
    ACARS -- ``git`` tracks them, so deleting one wouldn't even stick past
    the next update). Takes effect on the next restart, same as disabling."""
    if _config is None:
        raise HTTPException(503, "Config not loaded")

    manifest = _find_manifest(plugin_id)
    if manifest.source != SOURCE_COMMUNITY:
        raise HTTPException(403, f"{plugin_id!r} is a built-in plugin and can't be deleted.")
    if manifest.locked:
        raise HTTPException(403, f"{plugin_id!r} is a locked plugin and can't be deleted.")

    with audit.timed_action(
        user=_claims.subject,
        action="config.plugin_delete",
        params={"plugin_id": plugin_id},
    ):
        try:
            shutil.rmtree(manifest.path)
        except PermissionError as exc:
            hint_user = getpass.getuser() or "meshpoint"
            raise HTTPException(
                403,
                f"Cannot delete {manifest.path} -- the service user lacks "
                f"permission. Fix with: sudo chown -R {hint_user}:{hint_user} "
                f"{manifest.path.parent}",
            ) from exc

        _config.plugins.pop(plugin_id, None)
        try:
            remove_subsection_key("plugins", plugin_id)
        except PermissionError:
            pass  # folder's already gone; a stray local.yaml entry is harmless

    logger.info("plugin %s deleted from %s (restart required)", plugin_id, manifest.path)

    return {"deleted": True, "id": plugin_id, "restart_required": True}
