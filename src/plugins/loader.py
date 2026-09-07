"""Discover, import and register enabled app plugins.

Called once from ``src.api.server.create_app``. For each folder under
``plugins/apps/`` with a valid ``plugin.toml`` (see ``manifest.py``) that is
enabled in config (``plugins.<id>.enabled`` -- default **false**), this imports
its ``backend/__init__.py`` and calls ``register(reg)`` against a
:class:`~src.plugins.registry.PluginRegistry`.

A plugin that fails to import or register is logged and skipped -- one bad
plugin never stops the app (or the other plugins) from starting.

Kept free of FastAPI imports.
"""

from __future__ import annotations

import importlib.util
import logging
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path
from types import ModuleType

from src.plugins.manifest import (
    SOURCE_BUILTIN,
    PluginManifest,
    discover_plugins,
)
from src.plugins.registry import PluginRegistry

logger = logging.getLogger(__name__)


# Cap for a single plugin's [deps] check script -- a probe that hasn't
# answered by now is treated as "deps not satisfied" rather than holding
# up boot.
DEPS_CHECK_TIMEOUT_S = 15


@dataclass(frozen=True)
class LoadedPlugin:
    manifest: PluginManifest
    module: ModuleType
    # Result of the plugin's optional [deps] check = "check.sh" probe.
    # None  -> no probe declared (or not run yet); caller assumes ok.
    # True  -> probe exited 0, deps satisfied.
    # False -> probe exited non-zero / timed out / errored; setup needed.
    deps_ok: bool | None = None
    deps_detail: str = ""  # probe stdout+stderr, trimmed -- the "why" for the admin


def run_deps_check(manifest: PluginManifest) -> tuple[bool | None, str]:
    """Run a plugin's ``[deps] check`` script unprivileged and classify the
    result. Returns ``(deps_ok, detail)``: ``None`` when the plugin declares
    no check, otherwise ``True``/``False`` with the script's combined
    stdout+stderr (trimmed) as the human-readable reason.

    Shared by :func:`load_plugins` (at boot) and the Settings -> Plugins
    ``POST /api/plugins/{id}/check`` route (on demand, after the operator
    has run setup). Never uses ``sudo`` -- a check must be answerable by the
    unprivileged service account.
    """
    if not manifest.check_path:
        return None, ""
    try:
        proc = subprocess.run(
            ["bash", str(manifest.check_path)],
            capture_output=True, text=True,
            timeout=DEPS_CHECK_TIMEOUT_S, check=False,
        )
    except subprocess.TimeoutExpired:
        return False, f"dependency check timed out after {DEPS_CHECK_TIMEOUT_S}s"
    except OSError as exc:
        return False, f"could not run dependency check: {exc}"
    detail = (proc.stdout + proc.stderr).strip()
    if len(detail) > 2000:
        detail = "…" + detail[-2000:]
    return proc.returncode == 0, detail


def _attach_deps_status(loaded: list[LoadedPlugin]) -> list[LoadedPlugin]:
    """Run every loaded plugin's ``[deps] check`` concurrently and fold the
    result onto its :class:`LoadedPlugin`. Advisory only -- a failing check
    never unloads a plugin, it just lights up the warning on Settings ->
    Plugins."""
    checkable = [lp for lp in loaded if lp.manifest.check]
    if not checkable:
        return loaded
    with ThreadPoolExecutor(max_workers=min(4, len(checkable))) as pool:
        results = dict(
            zip(
                (lp.manifest.name for lp in checkable),
                pool.map(lambda lp: run_deps_check(lp.manifest), checkable),
            )
        )
    out: list[LoadedPlugin] = []
    for lp in loaded:
        res = results.get(lp.manifest.name)
        if res is None:
            out.append(lp)
            continue
        deps_ok, detail = res
        if deps_ok is False:
            logger.warning(
                "plugin %s: dependency check failed -- setup needed%s",
                lp.manifest.name, f" ({detail.splitlines()[0]})" if detail else "",
            )
        out.append(replace(lp, deps_ok=deps_ok, deps_detail=detail))
    return out


def _import_backend(manifest: PluginManifest) -> ModuleType:
    """Import ``<plugin>/backend/__init__.py`` as a package so its relative
    imports (``from .listener import X``) resolve."""
    backend_dir = manifest.path / "backend"
    init_file = backend_dir / "__init__.py"
    if not init_file.is_file():
        raise ImportError(f"{manifest.name}: no backend/__init__.py")

    mod_name = f"meshpoint_plugin_{manifest.name.replace('-', '_')}"
    spec = importlib.util.spec_from_file_location(
        mod_name, init_file, submodule_search_locations=[str(backend_dir)],
    )
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ImportError(f"{manifest.name}: could not build a module spec")

    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(mod_name, None)
        raise
    return module


def is_plugin_enabled(manifest: PluginManifest, conf: dict) -> bool:
    """Built-ins (``src/plugins/apps/``) load unless explicitly disabled --
    they're core-authored. Community drop-ins are opt-in.

    Shared with ``src.api.routes.plugin_routes`` so the management page's
    "enabled" flag matches exactly what a restart would actually load.
    """
    enabled = conf.get("enabled")
    if manifest.source == SOURCE_BUILTIN:
        return enabled is not False
    return bool(enabled)


def load_plugins(
    builtin_dir: Path, community_dir: Path | None, plugins_config: dict,
) -> list[LoadedPlugin]:
    """Load every enabled plugin.

    Built-ins come from *builtin_dir* (``src/plugins/apps/``) and load unless
    ``plugins.<id>.enabled`` is explicitly ``false``. Community plugins come
    from *community_dir* (``<plugins_dir>/apps/``) and load only when
    ``plugins.<id>.enabled`` is truthy. *plugins_config* is ``config.plugins``.
    """
    loaded: list[LoadedPlugin] = []
    manifests = discover_plugins(builtin_dir, community_dir)
    for manifest in manifests:
        conf = plugins_config.get(manifest.name)
        conf = conf if isinstance(conf, dict) else {}
        if not is_plugin_enabled(manifest, conf):
            logger.info(
                "%s plugin %s v%s present but not enabled "
                "(set plugins.%s.enabled: true)",
                manifest.source, manifest.name, manifest.version, manifest.name,
            )
            continue
        try:
            module = _import_backend(manifest)
            register = getattr(module, "register", None)
            if not callable(register):
                raise AttributeError("backend has no module-level register(reg)")
            register(PluginRegistry(manifest, conf))
        except Exception:
            logger.exception("plugin %s failed to load -- skipping", manifest.name)
            continue
        loaded.append(LoadedPlugin(manifest, module))
        logger.info(
            "loaded %s plugin %s v%s", manifest.source, manifest.name, manifest.version,
        )

    if not manifests:
        logger.info("plugins: no app plugins found")
    else:
        logger.info(
            "plugins: %d of %d loaded (%s)",
            len(loaded), len(manifests),
            ", ".join(m.name for m in manifests),
        )
    return _attach_deps_status(loaded)
