"""GET /api/config (dashboard block) + PUT /api/config/dashboard gating.

FastAPI-gated (CI / Pi only) -- config_routes.py imports fastapi.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

try:
    import fastapi  # noqa: F401
    _HAS_FASTAPI = True
except ImportError:
    _HAS_FASTAPI = False


@unittest.skipUnless(_HAS_FASTAPI, "routes import fastapi (CI / Pi only)")
class TestWebTerminalToggleGate(unittest.TestCase):
    """dashboard.web_terminal_toggle is the filesystem-only master switch
    (src/config.py) -- PUT /api/config/dashboard must refuse to change
    web_terminal_enabled until it's true, and GET /api/config must surface
    its current value so the frontend knows whether to render the card."""

    def setUp(self) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from src.api.auth.dependencies import require_admin, require_auth
        from src.api.auth.jwt_session import ROLE_ADMIN, SessionClaims
        from src.api.routes import config_routes
        from src.config import AppConfig

        self._mod = config_routes
        self.cfg = AppConfig()
        config_routes.init_routes(config=self.cfg)

        # save_section_to_yaml("dashboard", ...) writes to whatever
        # CONCENTRATOR_CONFIG points at -- redirect to a throwaway file so
        # test_enable_allowed_once_toggle_on doesn't touch the real
        # config/local.yaml (same pattern as test_plugin_source_routes.py).
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        os.environ["CONCENTRATOR_CONFIG"] = str(Path(self._tmp.name) / "local.yaml")
        self.addCleanup(os.environ.pop, "CONCENTRATOR_CONFIG", None)

        claims = SessionClaims(subject="admin", role=ROLE_ADMIN, session_version=1)
        app = FastAPI()
        app.dependency_overrides[require_admin] = lambda: claims
        app.dependency_overrides[require_auth] = lambda: claims
        app.include_router(config_routes.router)
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self._mod._config = None

    def test_config_defaults_toggle_off(self) -> None:
        from src.config import AppConfig
        self.assertFalse(AppConfig().dashboard.web_terminal_toggle)

    def test_get_config_reports_toggle_state(self) -> None:
        r = self.client.get("/api/config")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["dashboard"], {
            "web_terminal_enabled": False,
            "web_terminal_toggle": False,
        })

    def test_enable_refused_while_toggle_off(self) -> None:
        r = self.client.put("/api/config/dashboard", json={"web_terminal_enabled": True})
        self.assertEqual(r.status_code, 403)
        self.assertIn("web_terminal_toggle", r.json()["detail"])
        self.assertFalse(self.cfg.dashboard.web_terminal_enabled)

    def test_disable_also_refused_while_toggle_off(self) -> None:
        """Symmetric -- there's nothing to legitimately disable via the API
        either when the master switch itself was never opted into; the
        gate applies to any change to web_terminal_enabled, not just
        turning it on."""
        self.cfg.dashboard.web_terminal_enabled = True  # pre-set some other way
        r = self.client.put("/api/config/dashboard", json={"web_terminal_enabled": False})
        self.assertEqual(r.status_code, 403)
        self.assertTrue(self.cfg.dashboard.web_terminal_enabled)  # unchanged

    def test_enable_allowed_once_toggle_on(self) -> None:
        self.cfg.dashboard.web_terminal_toggle = True
        r = self.client.put("/api/config/dashboard", json={"web_terminal_enabled": True})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(self.cfg.dashboard.web_terminal_enabled)
        self.assertTrue(r.json()["restart_required"])

    def test_no_route_can_set_the_toggle_itself(self) -> None:
        """DashboardUpdate has no web_terminal_toggle field -- confirm a
        client can't smuggle it in and have it silently accepted."""
        self.cfg.dashboard.web_terminal_toggle = True
        r = self.client.put("/api/config/dashboard", json={
            "web_terminal_enabled": True, "web_terminal_toggle": False,
        })
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(self.cfg.dashboard.web_terminal_toggle)  # untouched


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
