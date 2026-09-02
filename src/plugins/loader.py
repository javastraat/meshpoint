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
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

from src.plugins.manifest import (
    SOURCE_BUILTIN,
    PluginManifest,
    discover_plugins,
)
from src.plugins.registry import PluginRegistry

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LoadedPlugin:
    manifest: PluginManifest
    module: ModuleType


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


def _is_enabled(manifest: PluginManifest, conf: dict) -> bool:
    """Built-ins (``src/plugins/apps/``) load unless explicitly disabled --
    they're core-authored. Community drop-ins are opt-in."""
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
    for manifest in discover_plugins(builtin_dir, community_dir):
        conf = plugins_config.get(manifest.name)
        conf = conf if isinstance(conf, dict) else {}
        if not _is_enabled(manifest, conf):
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
    return loaded
