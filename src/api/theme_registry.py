"""Discover dashboard themes from two locations.

* ``frontend/themes/<id>/`` -- the built-in themes, curated and reviewed
  as part of the app. Served through the ``/`` static mount at
  ``/themes/<id>/theme.css``.
* ``plugins/themes/<id>/`` -- extra / community themes, dropped in
  without touching the app. Served through a dedicated
  ``/plugins/themes`` mount. This is the first concrete ``plugins/``
  directory (see ``memory/plugin-architecture-review.md``).

Each theme folder holds a ``theme.json`` manifest and a ``theme.css``;
adding one and restarting makes the theme show up in the picker with no
code change. A built-in theme id always wins an id collision with a
plugin theme, and a plugin folder can never claim ``dark``.

``dark`` is a folder too, but a registry-entry-only one: its ``theme.css``
is empty because the baseline palette lives on bare ``:root`` in
``dashboard.css`` (a synchronously-loaded stylesheet, so no flash).

Kept free of FastAPI imports so the scan + HTML injection unit-test on
the Mac, same pattern as ``src/api/html_assets.py``.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from src.api.html_assets import BOOT_TOKEN

logger = logging.getLogger(__name__)

# The built-in baseline. Always present in the returned list and always
# the fallback selection even if its folder is missing.
DEFAULT_THEME_ID = "dark"


def scan_themes(themes_dir: Path, plugin_themes_dir: Path | None = None) -> list[dict]:
    """Return the sorted theme manifest list.

    Built-in themes come from *themes_dir* (``/themes/<id>/theme.css``);
    optional extra themes from *plugin_themes_dir*
    (``/plugins/themes/<id>/theme.css``). Each entry:
    ``{"id", "label", "order", "icon", "css"}`` where ``css`` is the
    browser URL for a non-empty ``theme.css`` or ``None``. Folders with a
    missing/unparseable ``theme.json`` are skipped with a warning. A
    built-in id wins an id collision with a plugin theme; a plugin folder
    can't claim ``dark``. Sorted by ``(order, label)``.
    """
    themes: list[dict] = []
    seen: set[str] = set()

    _scan_dir(themes_dir, "/themes", themes, seen)
    if plugin_themes_dir is not None:
        _scan_dir(
            plugin_themes_dir, "/plugins/themes", themes, seen,
            block={DEFAULT_THEME_ID},
        )

    if DEFAULT_THEME_ID not in seen:
        # The baseline is valid even without a folder on disk.
        themes.append(
            {"id": DEFAULT_THEME_ID, "label": "Dark", "order": 0, "icon": "moon", "css": None}
        )

    themes.sort(key=lambda t: (t["order"], t["label"].lower()))
    return themes


def _scan_dir(
    themes_dir: Path,
    css_url_prefix: str,
    themes: list[dict],
    seen: set[str],
    block: set[str] | None = None,
) -> None:
    """Append the themes found in *themes_dir* to *themes*, in place.

    *seen* is shared across calls so an id discovered by an earlier call
    (a built-in) shadows a later one (a plugin). *block* is a set of ids
    this call must never emit regardless of *seen*.
    """
    block = block or set()
    if not themes_dir.is_dir():
        return
    for entry in sorted(themes_dir.iterdir()):
        if not entry.is_dir():
            continue
        manifest_path = entry / "theme.json"
        if not manifest_path.is_file():
            continue
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            logger.warning("theme: skipping %s -- unreadable theme.json", entry.name)
            continue
        if not isinstance(raw, dict):
            logger.warning("theme: skipping %s -- theme.json is not an object", entry.name)
            continue

        theme_id = str(raw.get("id") or entry.name).strip()
        if not theme_id or theme_id in seen:
            continue
        if theme_id in block:
            logger.warning("theme: skipping %s -- %r is reserved", entry.name, theme_id)
            continue
        seen.add(theme_id)

        has_css = _has_css_rules(entry / "theme.css")

        themes.append(
            {
                "id": theme_id,
                "label": str(raw.get("label") or theme_id.replace("-", " ").title()),
                "order": _as_int(raw.get("order"), default=100),
                "icon": str(raw.get("icon") or ""),
                "css": f"{css_url_prefix}/{theme_id}/theme.css" if has_css else None,
            }
        )


def theme_link_tags(themes: list[dict], token: str = BOOT_TOKEN) -> str:
    """``<link>`` tags for every theme that ships its own CSS.

    Server-rendered into ``<head>`` so a persisted non-default theme
    paints correctly on first load instead of flashing the baseline
    while a script fetches the manifest.
    """
    return "".join(
        f'<link rel="stylesheet" href="{t["css"]}?v={token}">'
        for t in themes
        if t.get("css")
    )


def inject_theme_links(
    html: str,
    themes_dir: Path,
    plugin_themes_dir: Path | None = None,
    token: str = BOOT_TOKEN,
) -> str:
    """Insert :func:`theme_link_tags` just before ``</head>`` in *html*."""
    tags = theme_link_tags(scan_themes(themes_dir, plugin_themes_dir), token)
    if not tags or "</head>" not in html:
        return html
    return html.replace("</head>", tags + "</head>", 1)


_HTML_TAG_RE = re.compile(r"<html\b(?![^>]*\bdata-theme=)", re.IGNORECASE)


def stamp_default_theme(
    html: str,
    theme_id: str,
    themes_dir: Path,
    plugin_themes_dir: Path | None = None,
) -> str:
    """Stamp ``data-theme`` on the ``<html>`` tag so the server default
    paints on first load with no flash. No-op for ``dark`` (the bare
    ``:root`` baseline) or an unknown id. A per-browser choice in
    localStorage still overrides this once ``theme_controller.js`` runs.
    """
    theme_id = (theme_id or "").strip()
    if not theme_id or theme_id == DEFAULT_THEME_ID:
        return html
    if theme_id not in {t["id"] for t in scan_themes(themes_dir, plugin_themes_dir)}:
        return html
    return _HTML_TAG_RE.sub(f'<html data-theme="{theme_id}"', html, count=1)


_CSS_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)


def _has_css_rules(css_file: Path) -> bool:
    """True when ``theme.css`` carries anything past comments/whitespace.

    A comment-only placeholder (``dark``'s) counts as no CSS, so it gets
    no ``<link>`` and no wasted request.
    """
    if not css_file.is_file():
        return False
    try:
        body = css_file.read_text(encoding="utf-8")
    except OSError:
        return False
    return bool(_CSS_COMMENT_RE.sub("", body).strip())


def _as_int(value, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
