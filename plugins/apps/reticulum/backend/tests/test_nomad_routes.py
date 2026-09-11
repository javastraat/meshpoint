"""Route tests for the Pages-tab endpoints in backend/nomad_routes.py.

Needs FastAPI (CI / Pi only -- the dev Mac has no fastapi), mirrors
tests/test_plugin_loader.py's own ``_HAS_FASTAPI`` gate. The file layer
these wrap is covered FastAPI-free by test_node_pages.py.
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

from plugins.apps.reticulum.backend import state


@unittest.skipUnless(_HAS_FASTAPI, "nomad_routes imports fastapi (CI / Pi only)")
class TestNodePagesRoutes(unittest.TestCase):
    def setUp(self) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from src.api.auth.dependencies import require_admin
        from src.api.auth.jwt_session import ROLE_ADMIN, SessionClaims

        from plugins.apps.reticulum.backend import nomad_routes

        self._tmp = tempfile.TemporaryDirectory()
        self.pages_dir = str(Path(self._tmp.name) / "pages")
        state.init({"node_enabled": True, "node_pages_dir": self.pages_dir})
        nomad_routes.reset_routes()  # _service stays None -> reload is a no-op

        app = FastAPI()
        app.dependency_overrides[require_admin] = lambda: SessionClaims(
            subject="admin", role=ROLE_ADMIN, session_version=1,
        )
        app.include_router(nomad_routes.router)
        self.client = TestClient(app)

    def tearDown(self) -> None:
        from plugins.apps.reticulum.backend import nomad_routes

        nomad_routes.reset_routes()
        state.init({})
        self._tmp.cleanup()

    def test_list_is_empty_but_lists_index(self) -> None:
        body = self.client.get("/api/reticulum/nomad/pages").json()
        self.assertEqual([p["name"] for p in body["pages"]], ["index.mu"])
        self.assertFalse(body["pages"][0]["exists"])
        self.assertEqual(body["pages_dir"], self.pages_dir)
        self.assertFalse(body["node_hosting"])  # _service is None

    def test_put_then_get_roundtrips_and_reports_not_served(self) -> None:
        r = self.client.put(
            "/api/reticulum/nomad/pages/index.mu", json={"content": "`!hi`!"},
        )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["saved"])
        self.assertFalse(r.json()["served"])  # no running node
        got = self.client.get("/api/reticulum/nomad/pages/index.mu").json()
        self.assertEqual(got["content"], "`!hi`!")

    def test_put_reserved_name_is_400(self) -> None:
        r = self.client.put(
            "/api/reticulum/nomad/pages/info.mu", json={"content": "x"},
        )
        self.assertEqual(r.status_code, 400)

    def test_get_bad_name_is_400(self) -> None:
        r = self.client.get("/api/reticulum/nomad/pages/not-a-page")
        self.assertEqual(r.status_code, 400)

    def test_delete_removes_the_file(self) -> None:
        self.client.put(
            "/api/reticulum/nomad/pages/about.mu", json={"content": "x"},
        )
        r = self.client.delete("/api/reticulum/nomad/pages/about.mu")
        self.assertEqual(r.status_code, 200)
        names = [p["name"] for p in self.client.get(
            "/api/reticulum/nomad/pages").json()["pages"]]
        self.assertNotIn("about.mu", names)

    def test_sample_page_returns_content(self) -> None:
        body = self.client.get("/api/reticulum/nomad/sample-page").json()
        self.assertTrue(body["content"].strip())


class _FakeLxmfService:
    """Just enough of LxmfService for nomad_nodes() -- an empty roster is
    fine, this class exists to prove auth passes, not to test peer data."""

    async def list_peers(self):
        return []


async def _deny_forbidden(*_a, **_kw):
    """Stand-in for require_admin as seen by a non-admin session -- same
    status/detail the real dependency raises for claims.role != admin."""
    from fastapi import HTTPException
    raise HTTPException(403, "admin role required")


async def _deny_unauthorized(*_a, **_kw):
    """Stand-in for require_auth/require_admin as seen by no session at
    all -- same status/detail the real dependency raises when unauthed."""
    from fastapi import HTTPException
    raise HTTPException(401, "authentication required")


@unittest.skipUnless(_HAS_FASTAPI, "nomad_routes imports fastapi (CI / Pi only)")
class TestBrowseAuthGating(unittest.TestCase):
    """Regression coverage for the 2026-09-09 auditor finding: /nodes,
    /page, /file are read-only "browse another node" actions and must
    accept any logged-in session (viewer included), while /pages* (this
    node's own hosted content) stays admin-only. /nodes also used to have
    no auth dependency at all -- covered here as the unauthenticated case.

    Builds its own dependency_overrides for require_auth/require_admin
    (rather than relying on a real JWT service or leaving one
    unoverridden) so each test's "session" is explicit and deterministic,
    with no dependency on global auth state set up by another test."""

    def setUp(self) -> None:
        from plugins.apps.reticulum.backend import nomad, nomad_routes

        self._tmp = tempfile.TemporaryDirectory()
        state.init({
            "node_enabled": True,
            "node_pages_dir": str(Path(self._tmp.name) / "pages"),
        })
        nomad_routes.reset_routes()
        nomad_routes.init_routes(_FakeLxmfService())

        # nomad.fetch_page/fetch_file would otherwise try a real Reticulum
        # Link -- stub them so /page and /file are fast, deterministic,
        # and prove only that auth let the request through. Restored in
        # tearDown so this can't leak into another test (see
        # tests/test_plugin_source_routes.py's setUp for the bug this
        # guards against -- a module-level monkeypatch left in place
        # bit two unrelated tests there).
        self._orig_fetch_page = nomad.fetch_page
        self._orig_fetch_file = nomad.fetch_file

        async def _fake_fetch_page(dest_hash, path="/page/index.mu", field_data=None):
            return nomad.NomadResult(ok=True, content="`!hi`!", destination_hash=dest_hash, path=path)

        async def _fake_fetch_file(dest_hash, path):
            return nomad.NomadResult(
                ok=True, file_name="x.txt", file_bytes=b"x",
                destination_hash=dest_hash, path=path,
            )

        nomad.fetch_page = _fake_fetch_page
        nomad.fetch_file = _fake_fetch_file

    def tearDown(self) -> None:
        from plugins.apps.reticulum.backend import nomad, nomad_routes

        nomad.fetch_page = self._orig_fetch_page
        nomad.fetch_file = self._orig_fetch_file
        nomad_routes.reset_routes()
        state.init({})
        self._tmp.cleanup()

    def _client_as(self, *, auth_override, admin_override):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from src.api.auth.dependencies import require_admin, require_auth
        from plugins.apps.reticulum.backend import nomad_routes

        app = FastAPI()
        app.dependency_overrides[require_auth] = auth_override
        app.dependency_overrides[require_admin] = admin_override
        app.include_router(nomad_routes.router)
        return TestClient(app)

    def _viewer_client(self):
        from src.api.auth.jwt_session import ROLE_VIEWER, SessionClaims

        viewer = SessionClaims(subject="viewer1", role=ROLE_VIEWER, session_version=1)
        return self._client_as(auth_override=lambda: viewer, admin_override=_deny_forbidden)

    def test_viewer_can_list_nodes(self) -> None:
        r = self._viewer_client().get("/api/reticulum/nomad/nodes")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json(), [])

    def test_viewer_can_fetch_a_page(self) -> None:
        r = self._viewer_client().post("/api/reticulum/nomad/page", json={
            "destination_hash": "ab" * 16,
        })
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["ok"])

    def test_viewer_can_fetch_a_file(self) -> None:
        r = self._viewer_client().post("/api/reticulum/nomad/file", json={
            "destination_hash": "ab" * 16, "path": "/file/x.txt",
        })
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.content, b"x")

    def test_viewer_is_refused_the_pages_tab(self) -> None:
        client = self._viewer_client()
        self.assertEqual(client.get("/api/reticulum/nomad/pages").status_code, 403)
        self.assertEqual(client.get("/api/reticulum/nomad/sample-page").status_code, 403)
        self.assertEqual(client.get("/api/reticulum/nomad/pages/index.mu").status_code, 403)
        self.assertEqual(
            client.put("/api/reticulum/nomad/pages/index.mu", json={"content": "x"}).status_code,
            403,
        )
        self.assertEqual(
            client.delete("/api/reticulum/nomad/pages/index.mu").status_code, 403,
        )

    def test_unauthenticated_cannot_list_nodes(self) -> None:
        """The second bug from the same pass: /nodes had no auth
        dependency at all before the fix."""
        client = self._client_as(
            auth_override=_deny_unauthorized, admin_override=_deny_unauthorized,
        )
        r = client.get("/api/reticulum/nomad/nodes")
        self.assertEqual(r.status_code, 401)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
