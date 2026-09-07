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

A plugin that declares ``[deps] check`` gets an unprivileged "are its deps
installed?" probe, run at boot by the loader and re-runnable on demand via
``POST /api/plugins/{id}/check`` -- ``GET`` reports the verdict as
``deps_ok`` / ``deps_detail``. ``POST /api/plugins/{id}/setup/stream`` runs
the plugin's ``[deps] setup`` script (``sudo bash setup.sh``, same sudoers
grant + audit as ``meshpoint plugin setup``) and streams its output back as
NDJSON so an admin can install a plugin's system dependencies from the page
without SSHing in; it re-probes ``check`` afterwards so the row clears
itself.

An admin can also delete a community plugin's folder outright (an
"uninstall") -- refused for built-ins and for a ``locked`` community plugin
(a shipped/bundled one, like ACARS, that ``git`` tracks; deleting it
wouldn't stick past the next update anyway). Mirrors the exact
built-in/locked-vs-custom split ``src/api/theme_store.py`` already uses for
plugin themes.
"""

from __future__ import annotations

import asyncio
import getpass
import json
import logging
import shutil
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.api.audit import AuditLogWriter
from src.api.audit.dependencies import get_audit_writer
from src.api.auth.dependencies import require_admin
from src.api.auth.jwt_session import SessionClaims
from src.config import AppConfig, remove_subsection_key, save_section_to_yaml
from src.plugins.loader import LoadedPlugin, is_plugin_enabled, run_deps_check
from src.plugins.manifest import SOURCE_COMMUNITY, PluginManifest, discover_plugins

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/plugins", tags=["plugins"])

_config: AppConfig | None = None
_builtin_dir: Path | None = None
_community_dir: Path | None = None
_loaded_plugins: list[LoadedPlugin] = []
# Fresher [deps]-check results than the boot-time snapshot on _loaded_plugins,
# keyed by plugin id -- written by POST /api/plugins/{id}/check (and the setup
# stream) so an admin who just ran setup on the device can clear the "setup
# needed" warning without a full service restart. Lost on restart (boot re-runs
# every check); that's fine.
_deps_overrides: dict[str, tuple[bool | None, str]] = {}

# Only one setup.sh at a time -- setup scripts are apt/pip/build steps that
# already serialise on the dpkg lock; two in parallel just deadlock noisily.
_setup_lock = asyncio.Lock()

# setup.sh is apt-get + pip + from-source builds -- minutes, not seconds.
_SETUP_TIMEOUT_S = 1800


def _ndjson(payload: dict) -> bytes:
    return (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")


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
    _deps_overrides.clear()


def _is_enabled(manifest: PluginManifest) -> bool:
    conf = _config.plugins.get(manifest.name)
    conf = conf if isinstance(conf, dict) else {}
    return is_plugin_enabled(manifest, conf)


def _deps_status(plugin_id: str) -> tuple[bool | None, str]:
    """This plugin's dependency-check verdict: an on-demand re-check result
    if one has been recorded this session, otherwise the boot-time snapshot
    from the loader. ``(None, "")`` when the plugin declares no check or
    isn't loaded."""
    if plugin_id in _deps_overrides:
        return _deps_overrides[plugin_id]
    for lp in _loaded_plugins:
        if lp.manifest.name == plugin_id:
            return lp.deps_ok, lp.deps_detail
    return None, ""


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
    deps_ok, deps_detail = _deps_status(manifest.name)
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
        "has_deps_check": manifest.check is not None,
        # None  = no check declared / plugin not loaded -> UI falls back to the
        #         static "Requires: … run setup" hint.
        # True  = deps satisfied.  False = setup needed (deps_detail says why).
        "deps_ok": deps_ok,
        "deps_detail": deps_detail,
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


@router.post("/{plugin_id}/check")
async def recheck_plugin_deps(
    plugin_id: str,
    _claims: SessionClaims = Depends(require_admin),
    audit: AuditLogWriter = Depends(get_audit_writer),
):
    """Re-run a plugin's ``[deps] check`` script now and record the result,
    so an admin who just ran setup on the device can clear the "setup
    needed" warning without restarting the service. The script runs
    unprivileged, same as at boot. 400 if the plugin declares no check."""
    if _config is None:
        raise HTTPException(503, "Config not loaded")

    manifest = _find_manifest(plugin_id)
    if manifest.check is None:
        raise HTTPException(400, f"{plugin_id!r} declares no [deps] check script.")

    with audit.timed_action(
        user=_claims.subject,
        action="config.plugin_deps_check",
        params={"plugin_id": plugin_id},
    ):
        deps_ok, detail = run_deps_check(manifest)

    _deps_overrides[plugin_id] = (deps_ok, detail)
    logger.info("plugin %s dependency re-check: deps_ok=%s", plugin_id, deps_ok)

    loaded_names = {p.manifest.name for p in _loaded_plugins}
    route_map = _route_map(discover_plugins(_builtin_dir, _community_dir))
    return {"checked": True, "plugin": _describe(manifest, loaded_names, route_map)}


async def _stream_plugin_setup(
    manifest: PluginManifest, audit: AuditLogWriter, user: str,
) -> AsyncIterator[bytes]:
    """Run ``sudo bash <plugin>/setup.sh`` and stream its stdout+stderr as
    NDJSON lines (``{"type":"line","stream":...,"text":...}``), then a final
    ``{"type":"result","result":{...}}``. Same wire shape the firmware
    flashers use (``UpdateStreamClient.postNdjson`` on the client).

    The absolute path matters: ``config/sudoers-meshpoint`` grants NOPASSWD
    only for ``/bin/bash /opt/meshpoint/.../setup.sh`` as an absolute
    pattern -- a relative argv (``config.dashboard.plugins_dir`` is
    CWD-relative by convention) would silently fall back to a password
    prompt and hang. Mirrors ``src.cli.plugin_command``'s own ``.resolve()``.
    """
    setup_path = manifest.setup_path
    if setup_path is None:  # pragma: no cover - guarded by the caller
        yield _ndjson({"type": "result", "result": {"returncode": -1, "success": False}})
        return
    cmd = ["sudo", "bash", str(setup_path.resolve())]

    if _setup_lock.locked():
        yield _ndjson({
            "type": "line", "stream": "stderr",
            "text": "Another plugin setup is already running -- try again once it finishes.",
        })
        yield _ndjson({"type": "result", "result": {"returncode": -1, "success": False}})
        return

    await _setup_lock.acquire()
    try:
        with audit.timed_action(
            user=user, action="config.plugin_setup",
            params={"plugin_id": manifest.name, "cmd": cmd},
        ) as ctx:
            async for chunk, result in _drive_setup(cmd, manifest):
                if result is not None:
                    ctx.set_result("success" if result.get("success") else "error")
                yield chunk
    finally:
        _setup_lock.release()


async def _drive_setup(cmd: list[str], manifest: PluginManifest):
    """Spawn ``cmd``, yield ``(ndjson_bytes, result_dict_or_None)`` for every
    line and the final result. Split out of :func:`_stream_plugin_setup` only
    to keep the lock/audit wrapper readable."""
    yield _ndjson({"type": "started", "cmd": cmd}), None
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        res = {"returncode": -1, "success": False}
        yield _ndjson({"type": "line", "stream": "stderr", "text": str(exc)}), None
        yield _ndjson({"type": "result", "result": res}), res
        return

    queue: asyncio.Queue = asyncio.Queue()

    async def pump(stream, name: str) -> None:
        if stream is not None:
            while True:
                line = await stream.readline()
                if not line:
                    break
                await queue.put(
                    (name, line.decode("utf-8", errors="replace").rstrip("\n")),
                )
        await queue.put(None)

    tasks = [
        asyncio.create_task(pump(proc.stdout, "stdout")),
        asyncio.create_task(pump(proc.stderr, "stderr")),
    ]
    pending = len(tasks)
    try:
        while pending:
            item = await asyncio.wait_for(queue.get(), timeout=_SETUP_TIMEOUT_S)
            if item is None:
                pending -= 1
                continue
            name, text = item
            yield _ndjson({"type": "line", "stream": name, "text": text}), None
        returncode = await asyncio.wait_for(proc.wait(), timeout=30)
    except asyncio.TimeoutError:
        proc.kill()
        for t in tasks:
            t.cancel()
        res = {"returncode": -1, "success": False}
        yield _ndjson({
            "type": "line", "stream": "stderr",
            "text": f"setup.sh timed out after {_SETUP_TIMEOUT_S // 60} min -- killed.",
        }), None
        yield _ndjson({"type": "result", "result": res}), res
        return

    for t in tasks:
        await t

    # Re-probe deps so the row updates without a restart (same as
    # POST /{id}/check), and hand the verdict back in the result.
    deps_ok: bool | None = None
    if manifest.check is not None:
        deps_ok, detail = run_deps_check(manifest)
        _deps_overrides[manifest.name] = (deps_ok, detail)

    res = {"returncode": returncode, "success": returncode == 0, "deps_ok": deps_ok}
    logger.info(
        "plugin %s setup finished rc=%s deps_ok=%s", manifest.name, returncode, deps_ok,
    )
    yield _ndjson({"type": "result", "result": res}), res


@router.post("/{plugin_id}/setup/stream")
async def run_plugin_setup_stream(
    plugin_id: str,
    claims: SessionClaims = Depends(require_admin),
    audit: AuditLogWriter = Depends(get_audit_writer),
) -> StreamingResponse:
    """Run the plugin's ``[deps] setup`` script on the device (``sudo bash
    setup.sh``) and stream its output back live, so an admin can install a
    plugin's system dependencies from Settings -> Plugins without SSHing in.
    Same thing ``meshpoint plugin setup <id>`` does from the CLI, same
    sudoers grant, admin-only and audited. 400 if the plugin has no setup
    script."""
    if _config is None:
        raise HTTPException(503, "Config not loaded")

    manifest = _find_manifest(plugin_id)
    if manifest.setup is None:
        raise HTTPException(400, f"{plugin_id!r} has no [deps] setup script to run.")

    return StreamingResponse(
        _stream_plugin_setup(manifest, audit, claims.subject),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


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
