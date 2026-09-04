"""Plugins management page (Settings -> Plugins).

Lists every discovered app plugin (``src/plugins/apps/`` built-ins +
``<plugins_dir>/apps/`` community drop-ins) with its current
``plugins.<id>.enabled`` state, and lets an admin flip that flag -- persisted
to ``local.yaml`` via :func:`~src.config.save_section_to_yaml`, same as every
other Configuration/Settings card. Enabling/disabling a plugin only takes
effect on the next restart (plugins are loaded once at ``create_app`` time),
so the response always reports both the *configured* state and whether the
plugin is actually ``loaded`` in this running process.

A ``"hook"`` plugin (``[hook] host = "..."``) has a real dependency on
whichever plugin provides that ``[sidebar].route`` -- with nothing enforcing
it, a hook could be enabled with its host off and end up permanently
orphaned (enabled, loaded, but nowhere to render). ``PUT`` refuses to enable
a hook plugin unless its host is already enabled, and disabling a host
plugin cascades: every enabled plugin that hooks into it (directly, or
transitively through another hook) gets disabled right along with it,
reported back as ``also_disabled`` so it's never a silent side effect.
``GET`` surfaces the same relationship per plugin as a ``dependency`` field
so the UI can grey out a not-yet-enableable toggle before anyone touches it.

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


def _is_enabled(manifest: PluginManifest) -> bool:
    conf = _config.plugins.get(manifest.name)
    conf = conf if isinstance(conf, dict) else {}
    return is_plugin_enabled(manifest, conf)


def _route_map(manifests: list[PluginManifest]) -> dict[str, PluginManifest]:
    """Every sidebar-providing plugin's route -> its manifest -- what a
    hook plugin's ``[hook].host`` actually resolves against (a route, not
    necessarily the same string as the host's own plugin id)."""
    return {m.sidebar.route: m for m in manifests if m.sidebar is not None}


def _host_manifest(
    manifest: PluginManifest, route_map: dict[str, PluginManifest]
) -> PluginManifest | None:
    """The host this plugin hooks into, or None if it isn't a hook plugin
    or its declared host route doesn't match any known plugin."""
    if manifest.hook is None:
        return None
    return route_map.get(manifest.hook.host)


def _describe(
    manifest: PluginManifest,
    loaded_names: set[str],
    route_map: dict[str, PluginManifest],
) -> dict:
    enabled = _is_enabled(manifest)
    loaded = manifest.name in loaded_names
    host = _host_manifest(manifest, route_map)
    dependency = None
    if manifest.hook is not None:
        dependency = {
            "host_route": manifest.hook.host,
            "host_id": host.name if host else None,
            "host_enabled": _is_enabled(host) if host else False,
        }
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
        "dependency": dependency,
    }


def _find_manifest(plugin_id: str) -> PluginManifest:
    for manifest in discover_plugins(_builtin_dir, _community_dir):
        if manifest.name == plugin_id:
            return manifest
    raise HTTPException(404, f"No plugin {plugin_id!r} found")


def _save_enabled(plugin_id: str, enabled: bool) -> None:
    existing = _config.plugins.get(plugin_id)
    existing = dict(existing) if isinstance(existing, dict) else {}
    existing["enabled"] = enabled
    _config.plugins[plugin_id] = existing
    try:
        save_section_to_yaml("plugins", {plugin_id: existing})
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc


def _cascade_disable_dependents(
    disabled_id: str,
    manifests: list[PluginManifest],
    route_map: dict[str, PluginManifest],
) -> list[str]:
    """Disable every currently-enabled plugin that hooks into
    ``disabled_id``, directly or transitively (a hook could itself be
    someone else's host, though nothing ships like that today) -- a
    plugin left enabled with its host off would just sit there loaded
    with nowhere to render. Returns the ids actually disabled, in the
    order they were processed, so the caller can report it rather than
    letting it happen silently.
    """
    disabled: list[str] = []
    frontier = {disabled_id}
    while frontier:
        newly_disabled: set[str] = set()
        for m in manifests:
            if m.name in disabled or m.name in frontier or m.hook is None:
                continue
            host = route_map.get(m.hook.host)
            if host is None or host.name not in frontier:
                continue
            if not _is_enabled(m):
                continue
            _save_enabled(m.name, False)
            disabled.append(m.name)
            newly_disabled.add(m.name)
        frontier = newly_disabled
    return disabled


@router.get("")
async def list_plugins():
    """Every discovered plugin, built-ins first, with its config + load state."""
    if _config is None:
        raise HTTPException(503, "Config not loaded")
    loaded_names = {p.manifest.name for p in _loaded_plugins}
    manifests = discover_plugins(_builtin_dir, _community_dir)
    route_map = _route_map(manifests)
    return {"plugins": [_describe(m, loaded_names, route_map) for m in manifests]}


class PluginUpdate(BaseModel):
    enabled: bool


@router.put("/{plugin_id}")
async def update_plugin(
    plugin_id: str,
    req: PluginUpdate,
    _claims: SessionClaims = Depends(require_admin),
    audit: AuditLogWriter = Depends(get_audit_writer),
):
    """Persist ``plugins.<id>.enabled``. Takes effect on the next restart.

    Enabling a hook plugin whose host isn't enabled is refused outright --
    it would just load with nowhere to render. Disabling a plugin cascades
    to every enabled plugin that hooks into it (see
    :func:`_cascade_disable_dependents`), reported back as
    ``also_disabled``.
    """
    if _config is None:
        raise HTTPException(503, "Config not loaded")

    manifests = discover_plugins(_builtin_dir, _community_dir)
    route_map = _route_map(manifests)
    manifest = next((m for m in manifests if m.name == plugin_id), None)
    if manifest is None:
        raise HTTPException(404, f"No plugin {plugin_id!r} found")

    also_disabled: list[str] = []

    with audit.timed_action(
        user=_claims.subject,
        action="config.plugin_update",
        params={"plugin_id": plugin_id, "enabled": req.enabled},
    ):
        if req.enabled and manifest.hook is not None:
            host = _host_manifest(manifest, route_map)
            if host is None:
                raise HTTPException(
                    400,
                    f"{plugin_id!r} hooks into {manifest.hook.host!r}, but no "
                    "installed plugin provides that page.",
                )
            if not _is_enabled(host):
                raise HTTPException(
                    400,
                    f"Enable {host.name!r} first -- {plugin_id!r} hooks into "
                    "its page and has nowhere to render without it.",
                )

        _save_enabled(plugin_id, req.enabled)
        if not req.enabled:
            also_disabled = _cascade_disable_dependents(plugin_id, manifests, route_map)

    logger.info(
        "plugin %s enabled=%s (restart required)%s",
        plugin_id, req.enabled,
        f"; also disabled: {', '.join(also_disabled)}" if also_disabled else "",
    )

    loaded_names = {p.manifest.name for p in _loaded_plugins}
    return {
        "saved": True,
        "restart_required": True,
        "plugin": _describe(manifest, loaded_names, route_map),
        "also_disabled": also_disabled,
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
