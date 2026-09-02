"""Inject a loaded panel plugin's frontend files into the dashboard HTML.

The counterpart of ``src.api.theme_registry.inject_theme_links``: at serve
time, ``server.serve_dashboard_root`` calls :func:`inject_plugin_assets` so a
plugin's ``<script>`` runs before ``app.js`` builds ``ListenerPanel`` and its
``window.registerListenerPanel(...)`` call lands.

Assets are served by a scoped route in ``server.py`` at
``/plugins/apps/<id>/<rel-path>`` (only files the manifest declared, from
either the built-in or the community tier).

Kept free of FastAPI imports.
"""

from __future__ import annotations

from pathlib import Path

from src.plugins.manifest import PluginManifest

# Emitted verbatim into index.html; server.py runs bust_asset_urls() after
# this, which appends the ?v=<boot> cache token to each URL.
_MARKER = "<!-- meshpoint:plugin-panels -->"


def plugin_asset_url(plugin_id: str, rel_path: str) -> str:
    return f"/plugins/apps/{plugin_id}/{rel_path}"


def plugin_asset_tags(manifests: list[PluginManifest]) -> str:
    tags: list[str] = []
    for m in manifests:
        if "panel" not in m.provides:
            continue
        for css in m.frontend_styles:
            tags.append(
                f'<link rel="stylesheet" href="{plugin_asset_url(m.name, css)}">'
            )
        for js in m.frontend_scripts:
            tags.append(
                f'<script src="{plugin_asset_url(m.name, js)}" defer></script>'
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
    """Insert `<link>`/`<script defer>` tags for every loaded panel plugin at
    the ``<!-- meshpoint:plugin-panels -->`` marker (or, failing that, just
    before ``</body>``)."""
    tags = plugin_asset_tags(manifests)
    if not tags:
        return html
    if _MARKER in html:
        return html.replace(_MARKER, tags + _MARKER, 1)
    if "</body>" in html:
        return html.replace("</body>", tags + "</body>", 1)
    return html + tags
