"""Parse and validate ``plugins/apps/<name>/plugin.toml``.

An "app" plugin is out-of-core code that hooks the seams built in the plugin
roadmap so far -- ``src.api.route_registry`` (routes), ``src.api.listener_registry``
(RTL-SDR listeners) and ``window.registerListenerPanel`` (a Listener tab). This
module only *reads* the manifest and enumerates the folders; importing the
plugin and calling its ``register()`` is a later step (B4b).

``PLUGIN_API_VERSION`` is the contract number those seams collectively define.
A manifest declaring a higher ``meshpoint_api`` targets a newer Meshpoint than
this one and is refused.

Kept free of FastAPI imports so it unit-tests on the Mac, same as
``src/api/theme_registry.py``.

Manifest shape::

    name = "acars"                 # must equal the folder name
    version = "0.1.0"
    meshpoint_api = 1
    provides = ["listener", "routes", "panel"]

    [deps]                         # optional
    apt = ["cmake", "pkg-config"]
    setup = "setup.sh"             # relative to the plugin dir, must exist

    [meta]                         # optional, all strings
    description = "..."
    homepage = "..."
    author = "..."
"""

from __future__ import annotations

import logging
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Bump when a plugin seam's contract changes in a way a plugin can observe.
PLUGIN_API_VERSION = 1

MANIFEST_NAME = "plugin.toml"

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,38}$")

KNOWN_PROVIDES = frozenset({"listener", "routes", "panel", "config"})


class PluginManifestError(Exception):
    """A ``plugin.toml`` that can't be trusted. ``code`` is a short slug
    (``name`` / ``api`` / ``provides`` / ...) for callers that want to
    branch; ``str(exc)`` is the human message."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class PluginManifest:
    name: str
    version: str
    api_version: int
    provides: tuple[str, ...]
    apt: tuple[str, ...]
    setup: str | None  # relative path within `path`, verified to exist
    description: str
    homepage: str
    author: str
    path: Path

    @property
    def setup_path(self) -> Path | None:
        return self.path / self.setup if self.setup else None


def _str_field(table: dict, key: str, code: str) -> str:
    value = table.get(key, "")
    if not isinstance(value, str):
        raise PluginManifestError(code, f"{key!r} must be a string.")
    return value


def parse_manifest(plugin_dir: Path) -> PluginManifest:
    """Read and validate ``<plugin_dir>/plugin.toml``.

    Raises :class:`PluginManifestError` on anything wrong.
    """
    manifest_file = plugin_dir / MANIFEST_NAME
    if not manifest_file.is_file():
        raise PluginManifestError("missing", f"no {MANIFEST_NAME} in {plugin_dir}")

    try:
        data = tomllib.loads(manifest_file.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError, UnicodeDecodeError) as exc:
        raise PluginManifestError("toml", f"can't read {manifest_file}: {exc}") from exc

    name = data.get("name")
    if not isinstance(name, str) or not _SLUG_RE.match(name):
        raise PluginManifestError(
            "name",
            "'name' must be lowercase [a-z0-9-], 2-39 chars, starting alphanumeric.",
        )
    if name != plugin_dir.name:
        raise PluginManifestError(
            "name", f"'name' ({name!r}) must match the folder ({plugin_dir.name!r}).",
        )

    version = data.get("version")
    if not isinstance(version, str) or not version.strip():
        raise PluginManifestError("version", "'version' must be a non-empty string.")

    api_version = data.get("meshpoint_api")
    if not isinstance(api_version, int) or isinstance(api_version, bool):
        raise PluginManifestError("api", "'meshpoint_api' must be an integer.")
    if api_version < 1:
        raise PluginManifestError("api", "'meshpoint_api' must be >= 1.")
    if api_version > PLUGIN_API_VERSION:
        raise PluginManifestError(
            "api",
            f"plugin targets meshpoint_api {api_version}; this Meshpoint "
            f"supports up to {PLUGIN_API_VERSION}.",
        )

    provides = data.get("provides")
    if not isinstance(provides, list) or not provides:
        raise PluginManifestError("provides", "'provides' must be a non-empty list.")
    unknown = [p for p in provides if p not in KNOWN_PROVIDES]
    if unknown:
        raise PluginManifestError(
            "provides",
            f"unknown provides {unknown}; known: {sorted(KNOWN_PROVIDES)}.",
        )

    deps = data.get("deps", {})
    if not isinstance(deps, dict):
        raise PluginManifestError("deps", "'[deps]' must be a table.")
    apt = deps.get("apt", [])
    if not isinstance(apt, list) or any(
        not isinstance(p, str) or not p.strip() for p in apt
    ):
        raise PluginManifestError("deps", "'deps.apt' must be a list of package names.")
    setup = deps.get("setup")
    if setup is not None:
        if not isinstance(setup, str) or not setup.strip():
            raise PluginManifestError("deps", "'deps.setup' must be a path string.")
        if not (plugin_dir / setup).is_file():
            raise PluginManifestError(
                "deps", f"'deps.setup' ({setup!r}) does not exist in the plugin.",
            )

    meta = data.get("meta", {})
    if not isinstance(meta, dict):
        raise PluginManifestError("meta", "'[meta]' must be a table.")

    return PluginManifest(
        name=name,
        version=version,
        api_version=api_version,
        provides=tuple(provides),
        apt=tuple(apt),
        setup=setup,
        description=_str_field(meta, "description", "meta"),
        homepage=_str_field(meta, "homepage", "meta"),
        author=_str_field(meta, "author", "meta"),
        path=plugin_dir,
    )


def discover_plugins(apps_dir: Path) -> list[PluginManifest]:
    """Every valid plugin under *apps_dir* (``plugins/apps/``), sorted by name.

    A folder with a missing/invalid ``plugin.toml`` is logged and skipped, so
    one bad plugin can't stop the rest from loading.
    """
    if not apps_dir.is_dir():
        return []
    found: list[PluginManifest] = []
    for child in sorted(apps_dir.iterdir()):
        if not child.is_dir() or not (child / MANIFEST_NAME).is_file():
            continue
        try:
            found.append(parse_manifest(child))
        except PluginManifestError as exc:
            logger.warning("skipping plugin %s: %s", child.name, exc)
    return found
