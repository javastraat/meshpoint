"""GET/POST/DELETE /api/plugin-sources + GET /catalog.

FastAPI-gated (CI / Pi only). The catalog fetch is monkeypatched -- no
network in the test.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

try:
    import fastapi  # noqa: F401
    _HAS_FASTAPI = True
except ImportError:
    _HAS_FASTAPI = False


@unittest.skipUnless(_HAS_FASTAPI, "routes import fastapi (CI / Pi only)")
class TestPluginSourceRoutes(unittest.TestCase):
    def setUp(self) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from src.api.auth.dependencies import require_admin
        from src.api.auth.jwt_session import ROLE_ADMIN, SessionClaims
        from src.api.routes import plugin_source_routes
        from src.config import AppConfig

        self._mod = plugin_source_routes
        plugin_source_routes.reset_routes()

        self._tmp = tempfile.TemporaryDirectory()
        self._local_yaml = Path(self._tmp.name) / "local.yaml"
        # save_top_level_to_yaml writes to _get_local_yaml_path()
        import os
        os.environ["CONCENTRATOR_CONFIG"] = str(self._local_yaml)
        self.addCleanup(os.environ.pop, "CONCENTRATOR_CONFIG", None)

        self.cfg = AppConfig()
        self.cfg.plugin_sources_enabled = True  # off by default; most tests need it on
        plugin_source_routes.init_routes(
            config=self.cfg,
            builtin_dir=Path(self._tmp.name) / "builtin",
            community_dir=Path(self._tmp.name) / "community",
        )

        app = FastAPI()
        app.dependency_overrides[require_admin] = lambda: SessionClaims(
            subject="admin", role=ROLE_ADMIN, session_version=1,
        )
        app.include_router(plugin_source_routes.router)
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self._mod.reset_routes()
        self._tmp.cleanup()

    def test_add_requires_confirm(self) -> None:
        r = self.client.post("/api/plugin-sources", json={
            "url": "https://github.com/you/meshpoint-plugins",
        })
        self.assertEqual(r.status_code, 400)
        self.assertIn("confirm", r.json()["detail"])

    def test_add_list_remove_roundtrip(self) -> None:
        r = self.client.post("/api/plugin-sources", json={
            "url": "https://github.com/you/meshpoint-plugins.git", "confirm": True,
        })
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["source"]["url"], "https://github.com/you/meshpoint-plugins")

        r = self.client.get("/api/plugin-sources")
        self.assertEqual(len(r.json()["sources"]), 1)
        self.assertEqual(self.cfg.plugin_sources[0]["ref"], "main")

        # dupe -> 409
        r = self.client.post("/api/plugin-sources", json={
            "url": "https://github.com/you/meshpoint-plugins", "confirm": True,
        })
        self.assertEqual(r.status_code, 409)

        r = self.client.delete(
            "/api/plugin-sources?url=https://github.com/you/meshpoint-plugins",
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.cfg.plugin_sources, [])

    def test_add_rejects_non_github(self) -> None:
        r = self.client.post("/api/plugin-sources", json={
            "url": "https://gitlab.com/x/y", "confirm": True,
        })
        self.assertEqual(r.status_code, 400)

    def test_catalog_annotates_entries(self) -> None:
        catalog = {
            "name": "t", "description": "", "owner": "you", "repo": "p", "ref": "main",
            "url": "https://github.com/you/p",
            "plugins": [
                {"id": "a", "kind": "app", "path": "apps/a", "version": "2.0",
                 "meshpoint_api": 1, "provides": [], "description": "", "author": "",
                 "homepage": "", "has_setup": False, "compatible": True},
            ],
            "themes": [],
        }
        self._mod.fetch_catalog = lambda url, ref: dict(catalog)
        self._mod._installed_index = lambda: {"a": "1.0"}

        r = self.client.get(
            "/api/plugin-sources/catalog?url=https://github.com/you/p&ref=main",
        )
        self.assertEqual(r.status_code, 200)
        entry = r.json()["plugins"][0]
        self.assertTrue(entry["installed"])
        self.assertTrue(entry["update_available"])
        self.assertEqual(entry["installed_version"], "1.0")

    def _catalog_with(self, entry_overrides: dict) -> dict:
        entry = {
            "id": "demo", "kind": "app", "path": "apps/demo", "version": "2.0",
            "meshpoint_api": 1, "provides": ["service"], "description": "",
            "author": "", "homepage": "", "has_setup": False, "compatible": True,
        }
        entry.update(entry_overrides)
        return {
            "name": "t", "description": "", "owner": "you", "repo": "p", "ref": "main",
            "url": "https://github.com/you/p", "plugins": [entry], "themes": [],
        }

    def test_install_requires_a_configured_source(self) -> None:
        self._mod.fetch_catalog = lambda url, ref: self._catalog_with({})
        r = self.client.post("/api/plugin-sources/install", json={
            "url": "https://github.com/you/p", "id": "demo",
        })
        self.assertEqual(r.status_code, 400)
        self.assertIn("not a configured", r.json()["detail"])

    def test_install_places_and_records_provenance(self) -> None:
        self.client.post("/api/plugin-sources", json={
            "url": "https://github.com/you/p", "confirm": True,
        })
        self._mod.fetch_catalog = lambda url, ref: self._catalog_with({})
        seen = {}
        self._mod.install_from_source = lambda owner, repo, ref, entry, cdir: (
            seen.update(owner=owner, repo=repo, ref=ref, id=entry["id"])
            or {"id": entry["id"], "kind": "app", "version": entry["version"],
                "has_setup": False, "commit": "abc1234"}
        )
        r = self.client.post("/api/plugin-sources/install", json={
            "url": "https://github.com/you/p", "id": "demo",
        })
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertTrue(body["installed"])
        self.assertFalse(body["updated"])
        self.assertEqual(body["commit"], "abc1234")
        self.assertEqual(seen["id"], "demo")
        prov = self.cfg.plugins["demo"]["source"]
        self.assertEqual(prov["url"], "https://github.com/you/p")
        self.assertEqual(prov["version"], "2.0")
        self.assertEqual(prov["commit"], "abc1234")

    def test_install_refuses_incompatible(self) -> None:
        self.client.post("/api/plugin-sources", json={
            "url": "https://github.com/you/p", "confirm": True,
        })
        self._mod.fetch_catalog = lambda url, ref: self._catalog_with(
            {"compatible": False, "meshpoint_api": 9},
        )
        r = self.client.post("/api/plugin-sources/install", json={
            "url": "https://github.com/you/p", "id": "demo",
        })
        self.assertEqual(r.status_code, 400)

    def test_resolve_ref_returns_commit(self) -> None:
        self._mod.resolve_commit = lambda url, ref: {
            "sha": "9" * 40, "short_sha": "9999999",
            "message": "do a thing", "committed_at": "2026-09-09T00:00:00Z",
            "html_url": "https://github.com/you/p/commit/9999999",
        }
        r = self.client.get(
            "/api/plugin-sources/resolve?url=https://github.com/you/p&ref=main",
        )
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["short_sha"], "9999999")
        self.assertFalse(body["ref_is_pinned"])

    def test_pin_then_unpin_roundtrip(self) -> None:
        self.client.post("/api/plugin-sources", json={
            "url": "https://github.com/you/p", "confirm": True,
        })
        sha = "a" * 40
        r = self.client.patch("/api/plugin-sources", json={
            "url": "https://github.com/you/p", "ref": sha,
        })
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["changed"])
        src = self.cfg.plugin_sources[0]
        self.assertEqual(src["ref"], sha)
        self.assertEqual(src["pinned_from"], "main")   # remembered the branch

        r = self.client.patch("/api/plugin-sources", json={
            "url": "https://github.com/you/p", "ref": "main",
        })
        self.assertEqual(r.status_code, 200)
        src = self.cfg.plugin_sources[0]
        self.assertEqual(src["ref"], "main")
        self.assertNotIn("pinned_from", src)

    def test_pin_unknown_source_404(self) -> None:
        r = self.client.patch("/api/plugin-sources", json={
            "url": "https://github.com/you/p", "ref": "b" * 40,
        })
        self.assertEqual(r.status_code, 404)

    def test_list_reports_sources_enabled(self) -> None:
        r = self.client.get("/api/plugin-sources")
        self.assertTrue(r.json()["sources_enabled"])


@unittest.skipUnless(_HAS_FASTAPI, "routes import fastapi (CI / Pi only)")
class TestPluginSourcesDisabledByDefault(unittest.TestCase):
    """``plugin_sources_enabled`` defaults False and has no API to flip it --
    add/install must 403 until it's hand-set in local.yaml, while read-only
    list/catalog/resolve and source removal stay unaffected."""

    def setUp(self) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from src.api.auth.dependencies import require_admin
        from src.api.auth.jwt_session import ROLE_ADMIN, SessionClaims
        from src.api.routes import plugin_source_routes
        from src.config import AppConfig

        self._mod = plugin_source_routes
        plugin_source_routes.reset_routes()

        self._tmp = tempfile.TemporaryDirectory()
        import os
        os.environ["CONCENTRATOR_CONFIG"] = str(Path(self._tmp.name) / "local.yaml")
        self.addCleanup(os.environ.pop, "CONCENTRATOR_CONFIG", None)

        self.cfg = AppConfig()  # plugin_sources_enabled left at its False default
        plugin_source_routes.init_routes(
            config=self.cfg,
            builtin_dir=Path(self._tmp.name) / "builtin",
            community_dir=Path(self._tmp.name) / "community",
        )

        app = FastAPI()
        app.dependency_overrides[require_admin] = lambda: SessionClaims(
            subject="admin", role=ROLE_ADMIN, session_version=1,
        )
        app.include_router(plugin_source_routes.router)
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self._mod.reset_routes()
        self._tmp.cleanup()

    def test_config_defaults_disabled(self) -> None:
        from src.config import AppConfig
        self.assertFalse(AppConfig().plugin_sources_enabled)

    def test_add_source_403_when_disabled(self) -> None:
        r = self.client.post("/api/plugin-sources", json={
            "url": "https://github.com/you/meshpoint-plugins", "confirm": True,
        })
        self.assertEqual(r.status_code, 403)
        self.assertIn("plugin_sources_enabled", r.json()["detail"])

    def test_install_403_when_disabled(self) -> None:
        r = self.client.post("/api/plugin-sources/install", json={
            "url": "https://github.com/you/p", "id": "demo",
        })
        self.assertEqual(r.status_code, 403)

    def test_list_reports_disabled(self) -> None:
        r = self.client.get("/api/plugin-sources")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["sources_enabled"])

    def test_no_route_can_enable_it(self) -> None:
        """There is deliberately no PUT/PATCH that touches this flag --
        confirm the config object is untouched by every other verb this
        router exposes."""
        self.client.patch("/api/plugin-sources", json={
            "url": "https://github.com/you/p", "ref": "main",
        })
        self.client.delete("/api/plugin-sources?url=https://github.com/you/p")
        self.assertFalse(self.cfg.plugin_sources_enabled)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
