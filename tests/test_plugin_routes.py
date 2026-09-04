"""Tests for the Settings -> Plugins management API (GET/PUT /api/plugins)."""

from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth.dependencies import require_admin
from src.api.auth.jwt_session import ROLE_ADMIN, SessionClaims
from src.api.routes import plugin_routes as plugin_module
from src.plugins.loader import LoadedPlugin
from src.plugins.manifest import parse_manifest

_MANIFEST = """\
name = "{name}"
version = "{version}"
meshpoint_api = 1
provides = ["routes"]
{locked_line}
[meta]
description = "{description}"
"""


def _admin_claims() -> SessionClaims:
    return SessionClaims(subject="admin", role=ROLE_ADMIN, session_version=1)


def _build_app() -> FastAPI:
    app = FastAPI()
    app.dependency_overrides[require_admin] = _admin_claims
    app.include_router(plugin_module.router)
    return app


def _make_plugin_dir(
    apps: Path, name: str, *, version: str = "1.0.0", description: str = "",
    locked: bool = False,
) -> Path:
    d = apps / name
    d.mkdir(parents=True)
    toml = textwrap.dedent(_MANIFEST.format(
        name=name, version=version, description=description,
        locked_line="locked = true" if locked else "",
    ))
    (d / "plugin.toml").write_text(toml, encoding="utf-8")
    (d / "backend").mkdir()
    (d / "backend" / "__init__.py").write_text(
        "def register(reg): pass\n", encoding="utf-8",
    )
    return d


class _PluginRoutesTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.builtin = root / "builtin"
        self.community = root / "community"
        self.builtin.mkdir()
        self.community.mkdir()

    def tearDown(self) -> None:
        plugin_module.reset_routes()
        self._tmp.cleanup()

    def _init(self, config: MagicMock, loaded: list[LoadedPlugin] | None = None) -> None:
        plugin_module.init_routes(
            config=config,
            builtin_dir=self.builtin,
            community_dir=self.community,
            loaded_plugins=loaded or [],
        )


class TestListPlugins(_PluginRoutesTestBase):
    def test_returns_builtin_and_community_with_enabled_and_loaded_state(self) -> None:
        _make_plugin_dir(self.builtin, "core-thing", description="ships in core")
        _make_plugin_dir(self.community, "acars", description="community decoder")

        config = MagicMock()
        config.plugins = {"acars": {"enabled": True, "squelch": -20}}

        acars_manifest = parse_manifest(self.community / "acars", source="community")
        self._init(config, loaded=[LoadedPlugin(acars_manifest, MagicMock())])

        client = TestClient(_build_app())
        resp = client.get("/api/plugins")
        self.assertEqual(resp.status_code, 200)
        by_id = {p["id"]: p for p in resp.json()["plugins"]}

        self.assertEqual(set(by_id), {"core-thing", "acars"})

        core = by_id["core-thing"]
        self.assertEqual(core["source"], "builtin")
        self.assertTrue(core["enabled"])  # builtins default enabled
        self.assertFalse(core["loaded"])  # not in the loaded_plugins list
        self.assertTrue(core["restart_required"])
        self.assertFalse(core["deletable"])  # built-ins are never deletable

        acars = by_id["acars"]
        self.assertEqual(acars["source"], "community")
        self.assertTrue(acars["enabled"])
        self.assertTrue(acars["loaded"])
        self.assertFalse(acars["restart_required"])
        self.assertEqual(acars["description"], "community decoder")
        self.assertFalse(acars["locked"])
        self.assertTrue(acars["deletable"])

    def test_locked_community_plugin_is_not_deletable(self) -> None:
        _make_plugin_dir(self.community, "acars", locked=True)
        config = MagicMock()
        config.plugins = {}
        self._init(config)

        client = TestClient(_build_app())
        body = client.get("/api/plugins").json()
        self.assertTrue(body["plugins"][0]["locked"])
        self.assertFalse(body["plugins"][0]["deletable"])

    def test_community_plugin_defaults_to_disabled(self) -> None:
        _make_plugin_dir(self.community, "off-by-default")
        config = MagicMock()
        config.plugins = {}
        self._init(config)

        client = TestClient(_build_app())
        body = client.get("/api/plugins").json()
        self.assertFalse(body["plugins"][0]["enabled"])
        self.assertFalse(body["plugins"][0]["loaded"])
        self.assertFalse(body["plugins"][0]["restart_required"])

    def test_no_plugins_returns_empty_list(self) -> None:
        config = MagicMock()
        config.plugins = {}
        self._init(config)

        client = TestClient(_build_app())
        resp = client.get("/api/plugins")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"plugins": []})


class TestUpdatePlugin(_PluginRoutesTestBase):
    def setUp(self) -> None:
        super().setUp()
        _make_plugin_dir(self.community, "acars")
        self.config = MagicMock()
        self.config.plugins = {"acars": {"enabled": False, "squelch": -20}}
        self._init(self.config)
        self.client = TestClient(_build_app())

    def test_enable_persists_and_preserves_other_plugin_keys(self) -> None:
        with patch("src.api.routes.plugin_routes.save_section_to_yaml") as mock_save:
            resp = self.client.put("/api/plugins/acars", json={"enabled": True})

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["saved"])
        self.assertTrue(body["restart_required"])
        self.assertTrue(body["plugin"]["enabled"])

        self.assertEqual(self.config.plugins["acars"]["enabled"], True)
        self.assertEqual(self.config.plugins["acars"]["squelch"], -20)

        mock_save.assert_called_once_with(
            "plugins", {"acars": {"enabled": True, "squelch": -20}},
        )

    def test_unknown_plugin_returns_404(self) -> None:
        resp = self.client.put("/api/plugins/nope", json={"enabled": True})
        self.assertEqual(resp.status_code, 404)

    def test_permission_error_returns_403(self) -> None:
        with patch(
            "src.api.routes.plugin_routes.save_section_to_yaml",
            side_effect=PermissionError("cannot write to local.yaml"),
        ):
            resp = self.client.put("/api/plugins/acars", json={"enabled": True})
        self.assertEqual(resp.status_code, 403)


class TestDeletePlugin(_PluginRoutesTestBase):
    def setUp(self) -> None:
        super().setUp()
        self.config = MagicMock()
        self.config.plugins = {"acars": {"enabled": True, "squelch": -20}}
        self.client = None  # built per-test after _init, since plugins vary

    def _client(self) -> TestClient:
        return TestClient(_build_app())

    def test_deletes_community_plugin_folder_and_config(self) -> None:
        d = _make_plugin_dir(self.community, "acars")
        self._init(self.config)
        client = self._client()

        with patch("src.api.routes.plugin_routes.remove_subsection_key") as mock_remove:
            resp = client.delete("/api/plugins/acars")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["deleted"])
        self.assertEqual(body["id"], "acars")
        self.assertTrue(body["restart_required"])
        self.assertFalse(d.exists())
        self.assertNotIn("acars", self.config.plugins)
        mock_remove.assert_called_once_with("plugins", "acars")

    def test_builtin_plugin_cannot_be_deleted(self) -> None:
        d = _make_plugin_dir(self.builtin, "core-thing")
        self._init(self.config)
        resp = self._client().delete("/api/plugins/core-thing")
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(d.exists())  # never touched

    def test_locked_community_plugin_cannot_be_deleted(self) -> None:
        d = _make_plugin_dir(self.community, "acars", locked=True)
        self._init(self.config)
        resp = self._client().delete("/api/plugins/acars")
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(d.exists())

    def test_unknown_plugin_returns_404(self) -> None:
        self._init(self.config)
        resp = self._client().delete("/api/plugins/nope")
        self.assertEqual(resp.status_code, 404)

    def test_permission_error_on_rmtree_returns_403(self) -> None:
        _make_plugin_dir(self.community, "acars")
        self._init(self.config)
        with patch(
            "src.api.routes.plugin_routes.shutil.rmtree",
            side_effect=PermissionError("nope"),
        ):
            resp = self._client().delete("/api/plugins/acars")
        self.assertEqual(resp.status_code, 403)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
