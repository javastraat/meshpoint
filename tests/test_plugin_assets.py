"""Tests for src.plugins.assets.inject_plugin_assets. Pure Python."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.plugins.assets import (
    inject_plugin_assets,
    plugin_asset_tags,
    resolve_plugin_asset,
    sidebar_descriptor_tags,
)
from src.plugins.manifest import PluginManifest, SidebarSpec

_HTML = "<html><head></head><body><script src='app.js'></script>\n" \
        "<!-- meshpoint:plugin-panels -->\n</body></html>"


def _m(name: str, *, provides=("panel",), scripts=("frontend/p.js",),
       styles=(), sidebar=None) -> PluginManifest:
    return PluginManifest(
        name=name, version="1", api_version=1, provides=tuple(provides),
        apt=(), setup=None, description="", homepage="", author="",
        frontend_scripts=tuple(scripts), frontend_styles=tuple(styles),
        path=Path("/x") / name, sidebar=sidebar,
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

    def test_sidebar_plugin_assets_are_served_too(self) -> None:
        out = plugin_asset_tags([
            _m("hello-world", provides=("sidebar",), scripts=("frontend/h.js",)),
        ])
        self.assertIn('/plugins/apps/hello-world/frontend/h.js', out)


class TestSidebarDescriptorTags(unittest.TestCase):
    def _sidebar_plugin(self, **kw) -> PluginManifest:
        spec = SidebarSpec(
            route=kw.pop("route", "hello-world"),
            label=kw.pop("label", "Hello World"),
            category=kw.pop("category", "networks"),
        )
        return _m("hello-world", provides=("sidebar",), sidebar=spec, **kw)

    def test_descriptor_pushed_for_sidebar_plugin(self) -> None:
        out = sidebar_descriptor_tags([self._sidebar_plugin()])
        self.assertIn("window.MESHPOINT_SIDEBAR_PLUGINS", out)
        self.assertIn('"id":"hello-world"', out)
        self.assertIn('"route":"hello-world"', out)
        self.assertIn('"label":"Hello World"', out)
        self.assertIn('"category":"networks"', out)

    def test_no_sidebar_plugins_returns_empty(self) -> None:
        self.assertEqual(sidebar_descriptor_tags([_m("acars")]), "")

    def test_non_sidebar_plugin_with_no_spec_is_skipped(self) -> None:
        # "sidebar" not in provides -> sidebar is None, must not crash/include.
        self.assertEqual(sidebar_descriptor_tags([_m("acars", provides=("panel",))]), "")

    def test_script_close_tag_is_escaped(self) -> None:
        spec = SidebarSpec(route="x", label="</script><script>evil()", category="ops")
        out = sidebar_descriptor_tags([_m("x", provides=("sidebar",), sidebar=spec)])
        self.assertNotIn("</script><script>evil()", out)
        self.assertIn("<\\/script>", out)

    def test_injected_before_plugin_scripts(self) -> None:
        out = inject_plugin_assets(_HTML, [self._sidebar_plugin()])
        self.assertLess(
            out.index("MESHPOINT_SIDEBAR_PLUGINS"),
            out.index("/plugins/apps/hello-world/frontend/p.js"),
        )


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
