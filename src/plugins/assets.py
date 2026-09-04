"""Inject a loaded panel/sidebar/hook plugin's frontend files into the
dashboard HTML.

The counterpart of ``src.api.theme_registry.inject_theme_links``: at serve
time, ``server.serve_dashboard_root`` calls :func:`inject_plugin_assets` so a
plugin's ``<script>`` runs before ``app.js`` builds ``ListenerPanel`` and its
``window.registerListenerPanel(...)`` call lands (a ``panel`` plugin), before
``app.js`` calls ``window.mountPluginSidebarPages()`` (a ``sidebar`` plugin),
or before that same call reaches a host page's own ``mount()`` and its
``window.mountPageHooks(...)`` call (a ``hook`` plugin -- it must register
before the host looks up what's registered for it, see
``frontend/sidebar/page_hook_registry.js``).

Assets are served by a scoped route in ``server.py`` at
``/plugins/apps/<id>/<rel-path>`` (only files the manifest declared, from
either the built-in or the community tier).

Kept free of FastAPI imports.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.plugins.manifest import PluginManifest

# Emitted verbatim into index.html; server.py runs bust_asset_urls() after
# this, which appends the ?v=<boot> cache token to each URL.
_MARKER = "<!-- meshpoint:plugin-panels -->"


def plugin_asset_url(plugin_id: str, rel_path: str) -> str:
    return f"/plugins/apps/{plugin_id}/{rel_path}"


def sidebar_descriptor_tags(manifests: list[PluginManifest]) -> str:
    """One ``<script>`` pushing every sidebar-page plugin's
    ``{id, route, label, category, icon}`` onto
    ``window.MESHPOINT_SIDEBAR_PLUGINS`` -- read by ``frontend/sidebar/
    sidebar_plugin_registry.js``'s ``mountPluginSidebarPages()``, which
    builds the actual nav `<li>` + content `<section>` before the plugin's
    own script (also injected here, via :func:`plugin_asset_tags`) calls
    ``window.registerSidebarPage(...)``. ``icon`` is a key into that
    script's own curated glyph set (:data:`~src.plugins.manifest.
    KNOWN_SIDEBAR_ICONS`), never raw markup.
    """
    descriptors = [
        {
            "id": m.name,
            "route": m.sidebar.route,
            "label": m.sidebar.label,
            "category": m.sidebar.category,
            "icon": m.sidebar.icon,
        }
        for m in manifests
        if "sidebar" in m.provides and m.sidebar is not None
    ]
    if not descriptors:
        return ""
    # separators=(",", ":") for a compact payload; </script>-safe (a plugin's
    # own label -- user-authored TOML, not attacker input, but cheap to guard).
    payload = json.dumps(descriptors, separators=(",", ":")).replace("</", "<\\/")
    return (
        "<script>window.MESHPOINT_SIDEBAR_PLUGINS="
        f"(window.MESHPOINT_SIDEBAR_PLUGINS||[]).concat({payload});</script>"
    )


def plugin_asset_tags(manifests: list[PluginManifest]) -> str:
    tags: list[str] = []
    for m in manifests:
        if (
            "panel" not in m.provides
            and "sidebar" not in m.provides
            and "hook" not in m.provides
        ):
            continue
        for css in m.frontend_styles:
            tags.append(
                f'<link rel="stylesheet" href="{plugin_asset_url(m.name, css)}">'
            )
        for js in m.frontend_scripts:
            # Plain <script>, matching every other dashboard script: runs in
            # document order at the marker -- after listener_panel_registry.js
            # / sidebar_plugin_registry.js / page_hook_registry.js (define
            # registerListenerPanel / registerSidebarPage / registerPageHook),
            # before app.js. Guarantees the plugin is registered before any
            # app code runs, without depending on app.js constructing panels
            # lazily (a deferred script runs after app.js, so it would only
            # work while that stays true).
            tags.append(
                f'<script src="{plugin_asset_url(m.name, js)}"></script>'
            )
    return "".join(tags)


def resolve_plugin_asset(
    manifests: list[PluginManifest], plugin_id: str, asset_path: str,
) -> Path | None:
    """The on-disk file for ``/plugins/apps/<plugin_id>/<asset_path>``, or
    ``None`` (-> 404). Serves **only** a file the plugin's manifest declared,
    from either tier, and never one outside the plugin dir."""
    plugin = next((m for m in manifests if m.name == plugin_id), None)
    if plugin is None:
        return None
    if asset_path not in set(plugin.frontend_scripts + plugin.frontend_styles):
        return None
    root = plugin.path.resolve()
    full = (root / asset_path).resolve()
    if not full.is_file() or root not in full.parents:
        return None
    return full


def inject_plugin_assets(html: str, manifests: list[PluginManifest]) -> str:
    """Insert the sidebar-descriptor script + `<link>`/`<script>` tags for
    every loaded panel/sidebar plugin at the
    ``<!-- meshpoint:plugin-panels -->`` marker (or, failing that, just before
    ``</body>``)."""
    tags = sidebar_descriptor_tags(manifests) + plugin_asset_tags(manifests)
    if not tags:
        return html
    if _MARKER in html:
        return html.replace(_MARKER, tags + _MARKER, 1)
    if "</body>" in html:
        return html.replace("</body>", tags + "</body>", 1)
    return html + tags
