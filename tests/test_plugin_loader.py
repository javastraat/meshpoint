"""Tests for src.plugins.loader.load_plugins.

Pure Python -- the loader, the manifest parser, PluginRegistry and both
underlying registries are all FastAPI-free, so a temp plugin folder with a
real backend/__init__.py exercises the whole path on the Mac. The create_app
integration (that the registered routers/listeners actually mount) is left to
tests/test_create_app_routers.py + the ACARS plugin itself (B5).
"""

from __future__ import annotations

import logging
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from src.api import listener_registry, route_registry
from src.plugins.loader import load_plugins

_MANIFEST = """\
name = "{name}"
version = "0.1.0"
meshpoint_api = 1
provides = {provides}
"""


def _make_plugin(apps: Path, name: str, backend_init: str, *,
                 provides: str = '["routes", "listener"]',
                 extra: dict[str, str] | None = None) -> None:
    d = apps / name / "backend"
    d.mkdir(parents=True)
    (apps / name / "plugin.toml").write_text(
        _MANIFEST.format(name=name, provides=provides), encoding="utf-8",
    )
    (d / "__init__.py").write_text(textwrap.dedent(backend_init), encoding="utf-8")
    for fname, body in (extra or {}).items():
        (d / fname).write_text(textwrap.dedent(body), encoding="utf-8")


class TestLoadPlugins(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.builtin = root / "builtin"
        self.apps = root / "apps"  # community drop-ins
        self.builtin.mkdir()
        self.apps.mkdir()
        route_registry.reset()
        listener_registry.reset()
        self._mods_before = set(sys.modules)

    def _load(self, config: dict):
        return load_plugins(self.builtin, self.apps, config)

    def tearDown(self) -> None:
        for name in set(sys.modules) - self._mods_before:
            if name.startswith("meshpoint_plugin_"):
                del sys.modules[name]
        route_registry.reset()
        listener_registry.reset()
        self._tmp.cleanup()

    def test_enabled_plugin_registers(self) -> None:
        _make_plugin(self.apps, "acars", """
            SENTINEL_ROUTER = object()

            def register(reg):
                reg.add_router(SENTINEL_ROUTER, public=True)
        """, provides='["routes"]')

        loaded = self._load({"acars": {"enabled": True}})

        self.assertEqual([p.manifest.name for p in loaded], ["acars"])
        specs = route_registry.registered()
        self.assertEqual(len(specs), 1)
        self.assertTrue(specs[0].public)

    def test_disabled_and_absent_are_skipped(self) -> None:
        _make_plugin(self.apps, "off", "def register(reg): raise AssertionError")
        _make_plugin(self.apps, "unset", "def register(reg): raise AssertionError")

        with self.assertLogs("src.plugins.loader", level=logging.INFO):
            loaded = self._load({"off": {"enabled": False}})

        self.assertEqual(loaded, [])
        self.assertEqual(route_registry.registered(), [])

    def test_failing_register_is_skipped_others_still_load(self) -> None:
        _make_plugin(self.apps, "aaa-bad", """
            def register(reg):
                raise RuntimeError("boom")
        """, provides='["routes"]')
        _make_plugin(self.apps, "zzz-good", """
            def register(reg):
                reg.add_router(object())
        """, provides='["routes"]')

        with self.assertLogs("src.plugins.loader", level=logging.ERROR):
            loaded = self._load(
                {"aaa-bad": {"enabled": True}, "zzz-good": {"enabled": True}},
            )

        self.assertEqual([p.manifest.name for p in loaded], ["zzz-good"])
        self.assertEqual(len(route_registry.registered()), 1)

    def test_builtin_plugin_loads_without_config(self) -> None:
        _make_plugin(self.builtin, "acars", """
            def register(reg):
                reg.add_router(object())
        """, provides='["routes"]')

        loaded = self._load({})  # no plugins.acars entry at all

        self.assertEqual([(p.manifest.name, p.manifest.source) for p in loaded],
                         [("acars", "builtin")])
        self.assertEqual(len(route_registry.registered()), 1)

    def test_builtin_plugin_can_be_explicitly_disabled(self) -> None:
        _make_plugin(self.builtin, "acars", """
            def register(reg):
                raise AssertionError("should not run")
        """, provides='["routes"]')

        with self.assertLogs("src.plugins.loader", level=logging.INFO):
            loaded = self._load({"acars": {"enabled": False}})

        self.assertEqual(loaded, [])

    def test_builtin_wins_id_collision_with_community(self) -> None:
        _make_plugin(self.builtin, "acars", """
            def register(reg):
                reg.add_router("builtin-router")
        """, provides='["routes"]')
        _make_plugin(self.apps, "acars", """
            def register(reg):
                raise AssertionError("community dupe should be skipped")
        """, provides='["routes"]')

        with self.assertLogs(level=logging.WARNING):
            loaded = self._load({"acars": {"enabled": True}})

        self.assertEqual([p.manifest.source for p in loaded], ["builtin"])
        self.assertEqual(route_registry.registered()[0].router, "builtin-router")

    def test_provides_mismatch_skips_plugin(self) -> None:
        _make_plugin(self.apps, "acars", """
            def register(reg):
                reg.add_listener(object())
        """, provides='["routes"]')

        with self.assertLogs("src.plugins.loader", level=logging.ERROR):
            loaded = self._load({"acars": {"enabled": True}})

        self.assertEqual(loaded, [])
        self.assertEqual(listener_registry.plugin_specs(), [])

    def test_relative_import_in_backend_resolves(self) -> None:
        _make_plugin(self.apps, "acars", """
            from .helper import ROUTER

            def register(reg):
                reg.add_router(ROUTER)
        """, provides='["routes"]', extra={"helper.py": "ROUTER = object()"})

        loaded = self._load({"acars": {"enabled": True}})

        self.assertEqual(len(loaded), 1)
        self.assertEqual(len(route_registry.registered()), 1)

    def test_no_register_callable_is_skipped(self) -> None:
        _make_plugin(self.apps, "acars", "register = 'not callable'",
                     provides='["routes"]')

        with self.assertLogs("src.plugins.loader", level=logging.ERROR):
            loaded = self._load({"acars": {"enabled": True}})

        self.assertEqual(loaded, [])

    def test_missing_apps_dir_returns_empty(self) -> None:
        self.assertEqual(load_plugins(self.builtin / "nope", None, {}), [])

    def test_logs_a_summary_line_when_nothing_found(self) -> None:
        with self.assertLogs("src.plugins.loader", level=logging.INFO) as logs:
            self._load({})
        self.assertTrue(any("no app plugins found" in m for m in logs.output))

    def test_logs_a_summary_line_with_counts(self) -> None:
        _make_plugin(self.apps, "acars", "def register(reg): reg.add_router(object())",
                     provides='["routes"]')
        _make_plugin(self.apps, "off", "def register(reg): pass", provides='["routes"]')
        with self.assertLogs("src.plugins.loader", level=logging.INFO) as logs:
            self._load({"acars": {"enabled": True}})
        self.assertTrue(any("1 of 2 loaded" in m for m in logs.output))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
