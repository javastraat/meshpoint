"""Tests for plugins/apps/<name>/plugin.toml parsing + discovery.

Pure Python -- src/plugins/manifest.py has no FastAPI import (stdlib tomllib
only), same as src/api/theme_registry.py.
"""

from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path

from src.plugins.manifest import (
    PLUGIN_API_VERSION,
    PluginManifestError,
    discover_plugins,
    parse_manifest,
)

_VALID = """\
name = "acars"
version = "0.1.0"
meshpoint_api = 1
provides = ["listener", "routes", "panel"]
"""


def _write_plugin(root: Path, name: str, toml: str, *, extra_files=()) -> Path:
    d = root / name
    d.mkdir(parents=True)
    (d / "plugin.toml").write_text(toml, encoding="utf-8")
    for fname in extra_files:
        (d / fname).write_text("#!/bin/sh\n", encoding="utf-8")
    return d


class TestParseManifest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _code(self, name: str, toml: str, **kw) -> str:
        d = _write_plugin(self.root, name, toml, **kw)
        with self.assertRaises(PluginManifestError) as ctx:
            parse_manifest(d)
        return ctx.exception.code

    def test_valid_minimal(self) -> None:
        d = _write_plugin(self.root, "acars", _VALID)
        m = parse_manifest(d)
        self.assertEqual(m.name, "acars")
        self.assertEqual(m.version, "0.1.0")
        self.assertEqual(m.api_version, 1)
        self.assertEqual(m.provides, ("listener", "routes", "panel"))
        self.assertEqual(m.apt, ())
        self.assertIsNone(m.setup)
        self.assertEqual(m.description, "")
        self.assertEqual(m.homepage, "")
        self.assertEqual(m.author, "")
        self.assertEqual(m.path, d)
        self.assertIsNone(m.setup_path)

    def test_valid_full(self) -> None:
        toml = _VALID + """
[deps]
apt = ["cmake", "pkg-config"]
setup = "setup.sh"

[meta]
description = "ACARS decoding"
homepage = "https://example.org"
author = "Einstein"
"""
        d = _write_plugin(self.root, "acars", toml, extra_files=("setup.sh",))
        m = parse_manifest(d)
        self.assertEqual(m.apt, ("cmake", "pkg-config"))
        self.assertEqual(m.setup, "setup.sh")
        self.assertEqual(m.setup_path, d / "setup.sh")
        self.assertEqual(m.description, "ACARS decoding")
        self.assertEqual(m.author, "Einstein")

    def test_missing_manifest(self) -> None:
        d = self.root / "empty"
        d.mkdir()
        with self.assertRaises(PluginManifestError) as ctx:
            parse_manifest(d)
        self.assertEqual(ctx.exception.code, "missing")

    def test_bad_toml(self) -> None:
        self.assertEqual(self._code("x", "name = "), "toml")

    def test_bad_name_slug(self) -> None:
        self.assertEqual(
            self._code("Acars", _VALID.replace('"acars"', '"Acars"')), "name",
        )

    def test_name_must_match_folder(self) -> None:
        self.assertEqual(self._code("other", _VALID), "name")

    def test_missing_version(self) -> None:
        toml = _VALID.replace('version = "0.1.0"\n', "")
        self.assertEqual(self._code("acars", toml), "version")

    def test_api_not_int(self) -> None:
        self.assertEqual(
            self._code("acars", _VALID.replace("meshpoint_api = 1", 'meshpoint_api = "1"')),
            "api",
        )

    def test_api_too_new(self) -> None:
        toml = _VALID.replace("meshpoint_api = 1", f"meshpoint_api = {PLUGIN_API_VERSION + 1}")
        self.assertEqual(self._code("acars", toml), "api")

    def test_api_zero(self) -> None:
        self.assertEqual(
            self._code("acars", _VALID.replace("meshpoint_api = 1", "meshpoint_api = 0")),
            "api",
        )

    def test_provides_empty(self) -> None:
        self.assertEqual(
            self._code("acars", _VALID.replace('["listener", "routes", "panel"]', "[]")),
            "provides",
        )

    def test_provides_unknown(self) -> None:
        self.assertEqual(
            self._code("acars", _VALID.replace('"panel"', '"telepathy"')),
            "provides",
        )

    def test_apt_not_strings(self) -> None:
        toml = _VALID + '\n[deps]\napt = ["cmake", 3]\n'
        self.assertEqual(self._code("acars", toml), "deps")

    def test_setup_file_absent(self) -> None:
        toml = _VALID + '\n[deps]\nsetup = "setup.sh"\n'
        self.assertEqual(self._code("acars", toml), "deps")

    def test_meta_not_string(self) -> None:
        toml = _VALID + "\n[meta]\nauthor = 42\n"
        self.assertEqual(self._code("acars", toml), "meta")


class TestDiscoverPlugins(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.apps = Path(self._tmp.name) / "apps"
        self.apps.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_missing_dir_returns_empty(self) -> None:
        self.assertEqual(discover_plugins(self.apps / "nope"), [])

    def test_returns_valid_sorted_skips_bad(self) -> None:
        _write_plugin(self.apps, "zulu", _VALID.replace('"acars"', '"zulu"'))
        _write_plugin(self.apps, "acars", _VALID)
        _write_plugin(self.apps, "broken", 'name = "broken"\nmeshpoint_api = 99\n')
        (self.apps / "not-a-plugin").mkdir()  # no plugin.toml
        (self.apps / "loose.txt").write_text("x", encoding="utf-8")

        with self.assertLogs("src.plugins.manifest", level=logging.WARNING) as logs:
            found = discover_plugins(self.apps)

        self.assertEqual([m.name for m in found], ["acars", "zulu"])
        self.assertTrue(any("broken" in line for line in logs.output))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
