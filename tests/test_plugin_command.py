"""Tests for the `meshpoint plugin` CLI (list/setup)."""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.cli.plugin_command import _confirm, _print_plugin_row, run_plugin_setup
from src.plugins.manifest import PluginManifest


def _manifest(**overrides) -> PluginManifest:
    base = dict(
        name="acars", version="1.0.0", api_version=1,
        provides=("listener",), apt=(), setup=None,
        description="", homepage="", author="",
        frontend_scripts=(), frontend_styles=(),
        path=Path("/fake/acars"), source="community", locked=False,
    )
    base.update(overrides)
    return PluginManifest(**base)


class TestConfirm(unittest.TestCase):
    def test_yes(self) -> None:
        with patch("builtins.input", return_value="y"):
            self.assertTrue(_confirm("ok?"))

    def test_blank_defaults_no(self) -> None:
        with patch("builtins.input", return_value=""):
            self.assertFalse(_confirm("ok?"))

    def test_blank_defaults_yes(self) -> None:
        with patch("builtins.input", return_value=""):
            self.assertTrue(_confirm("ok?", default_yes=True))

    def test_explicit_no_overrides_default_yes(self) -> None:
        with patch("builtins.input", return_value="n"):
            self.assertFalse(_confirm("ok?", default_yes=True))


class TestPrintPluginRow(unittest.TestCase):
    def _render(self, **kw) -> str:
        p = {
            "id": "acars", "version": "1.0.0", "source": "community",
            "enabled": True, "loaded": True, "restart_required": False,
            "apt_deps": [],
        }
        p.update(kw)
        buf = io.StringIO()
        with redirect_stdout(buf):
            _print_plugin_row(p)
        return buf.getvalue()

    def test_enabled_and_loaded(self) -> None:
        out = self._render()
        self.assertIn("acars (v1.0.0)", out)
        self.assertIn("community", out)
        self.assertIn("enabled, loaded", out)

    def test_restart_required_shown(self) -> None:
        out = self._render(enabled=True, loaded=False, restart_required=True)
        self.assertIn("restart required", out)

    def test_disabled_shown_without_restart_note(self) -> None:
        out = self._render(enabled=False, loaded=False, restart_required=False)
        self.assertIn("disabled", out)
        self.assertNotIn("restart required", out)

    def test_apt_deps_hint(self) -> None:
        out = self._render(apt_deps=["cmake", "pkg-config"])
        self.assertIn("cmake, pkg-config", out)
        self.assertIn("meshpoint plugin setup acars", out)

    def test_no_apt_deps_no_hint(self) -> None:
        out = self._render(apt_deps=[])
        self.assertNotIn("deps:", out)


class TestRunPluginSetup(unittest.TestCase):
    def setUp(self) -> None:
        self.config = MagicMock()
        self.config.dashboard.plugins_dir = "/fake/plugins-dir"

    def test_unknown_plugin_returns_1(self) -> None:
        with patch("src.config.load_config", return_value=self.config), \
             patch("src.plugins.manifest.discover_plugins", return_value=[]):
            code = run_plugin_setup("nope", skip_confirm=True)
        self.assertEqual(code, 1)

    def test_no_setup_step_returns_0(self) -> None:
        manifest = _manifest(setup=None)
        with patch("src.config.load_config", return_value=self.config), \
             patch("src.plugins.manifest.discover_plugins", return_value=[manifest]):
            code = run_plugin_setup("acars", skip_confirm=True)
        self.assertEqual(code, 0)

    def test_declining_confirmation_skips_setup(self) -> None:
        manifest = _manifest(setup="setup.sh")
        with patch("src.config.load_config", return_value=self.config), \
             patch("src.plugins.manifest.discover_plugins", return_value=[manifest]), \
             patch("builtins.input", return_value="n"), \
             patch("src.cli.plugin_command.subprocess.run") as mock_run:
            code = run_plugin_setup("acars", skip_confirm=False)
        self.assertEqual(code, 1)
        mock_run.assert_not_called()

    def test_confirmed_runs_setup_script(self) -> None:
        manifest = _manifest(setup="setup.sh")
        with patch("src.config.load_config", return_value=self.config), \
             patch("src.plugins.manifest.discover_plugins", return_value=[manifest]), \
             patch("src.cli.plugin_command.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            code = run_plugin_setup("acars", skip_confirm=True)
        self.assertEqual(code, 0)
        mock_run.assert_called_once_with(
            ["sudo", "bash", str(manifest.setup_path)], check=False,
        )

    def test_nonzero_exit_from_setup_script_is_propagated(self) -> None:
        manifest = _manifest(setup="setup.sh")
        with patch("src.config.load_config", return_value=self.config), \
             patch("src.plugins.manifest.discover_plugins", return_value=[manifest]), \
             patch("src.cli.plugin_command.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=7)
            code = run_plugin_setup("acars", skip_confirm=True)
        self.assertEqual(code, 7)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
