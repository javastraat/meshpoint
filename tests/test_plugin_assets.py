"""Tests for src.plugins.assets.inject_plugin_assets. Pure Python."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.plugins.assets import (
    inject_plugin_assets,
    plugin_asset_tags,
    resolve_plugin_asset,
)
from src.plugins.manifest import PluginManifest

_HTML = "<html><head></head><body><script src='app.js'></script>\n" \
        "<!-- meshpoint:plugin-panels -->\n</body></html>"


def _m(name: str, *, provides=("panel",), scripts=("frontend/p.js",),
       styles=()) -> PluginManifest:
    return PluginManifest(
        name=name, version="1", api_version=1, provides=tuple(provides),
        apt=(), setup=None, description="", homepage="", author="",
        frontend_scripts=tuple(scripts), frontend_styles=tuple(styles),
        path=Path("/x") / name,
    )


class TestInjectPluginAssets(unittest.TestCase):
    def test_script_and_style_at_marker(self) -> None:
        out = inject_plugin_assets(
            _HTML, [_m("acars", scripts=("frontend/a.js",), styles=("frontend/a.css",))],
        )
        self.assertIn(
            '<link rel="stylesheet" href="/plugins/apps/acars/frontend/a.css">', out,
        )
        self.assertIn(
            '<script src="/plugins/apps/acars/frontend/a.js"></script>', out,
        )
        # injected before the marker, i.e. before app.js has already run? no --
        # after the app.js line but style before script
        self.assertLess(out.index("a.css"), out.index("a.js"))
        self.assertLess(out.index("a.js"), out.index("<!-- meshpoint:plugin-panels -->"))

    def test_falls_back_to_body_close(self) -> None:
        out = inject_plugin_assets("<body>x</body>", [_m("acars")])
        self.assertIn('/plugins/apps/acars/frontend/p.js', out)
        self.assertLess(out.index("/plugins/apps"), out.index("</body>"))

    def test_non_panel_plugin_injects_nothing(self) -> None:
        self.assertEqual(
            plugin_asset_tags([_m("x", provides=("routes",), scripts=())]), "",
        )

    def test_no_plugins_returns_html_unchanged(self) -> None:
        self.assertEqual(inject_plugin_assets(_HTML, []), _HTML)

    def test_two_plugins_in_order(self) -> None:
        out = plugin_asset_tags([
            _m("aaa", scripts=("frontend/a.js",)),
            _m("bbb", scripts=("frontend/b.js",)),
        ])
        self.assertLess(out.index("aaa"), out.index("bbb"))


class TestResolvePluginAsset(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "acars" / "frontend").mkdir(parents=True)
        (self.root / "acars" / "frontend" / "p.js").write_text("//", encoding="utf-8")
        (self.root / "acars" / "plugin.toml").write_text("x", encoding="utf-8")
        self.m = PluginManifest(
            name="acars", version="1", api_version=1, provides=("panel",),
            apt=(), setup=None, description="", homepage="", author="",
            frontend_scripts=("frontend/p.js",), frontend_styles=(),
            path=self.root / "acars",
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_declared_file_resolves(self) -> None:
        got = resolve_plugin_asset([self.m], "acars", "frontend/p.js")
        self.assertEqual(got, (self.root / "acars" / "frontend" / "p.js").resolve())

    def test_unknown_plugin_is_none(self) -> None:
        self.assertIsNone(resolve_plugin_asset([self.m], "nope", "frontend/p.js"))

    def test_undeclared_file_is_none(self) -> None:
        self.assertIsNone(resolve_plugin_asset([self.m], "acars", "plugin.toml"))

    def test_traversal_is_none(self) -> None:
        self.assertIsNone(
            resolve_plugin_asset([self.m], "acars", "frontend/../plugin.toml"),
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
