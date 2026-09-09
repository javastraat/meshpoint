"""GET /api/reticulum/telemetry + POST /api/reticulum/telemetry/send.

FastAPI-gated (CI / Pi only).
"""

from __future__ import annotations

import unittest

try:
    import fastapi  # noqa: F401
    _HAS_FASTAPI = True
except ImportError:
    _HAS_FASTAPI = False


@unittest.skipUnless(_HAS_FASTAPI, "routes imports fastapi (CI / Pi only)")
class TestTelemetryRoute(unittest.TestCase):
    def setUp(self) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from src.api.auth.dependencies import require_admin
        from src.api.auth.jwt_session import ROLE_ADMIN, SessionClaims
        from plugins.apps.reticulum.backend import routes

        self._routes = routes
        routes.reset_routes()

        class _FakeService:
            def __init__(self):
                self.sent = False
                self.ok = True

            def telemetry_status(self):
                return {
                    "enabled": True, "collector": "cd" * 16, "interval_s": 900,
                    "last_sent_at": None, "last_error": None,
                }

            def send_telemetry(self):
                self.sent = True
                return {"ok": self.ok, "error": None if self.ok else "Collector path unknown"}

        self.svc = _FakeService()
        routes.init_routes(self.svc, object())

        app = FastAPI()
        app.dependency_overrides[require_admin] = lambda: SessionClaims(
            subject="admin", role=ROLE_ADMIN, session_version=1,
        )
        app.include_router(routes.router)
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self._routes.reset_routes()

    def test_get_status(self) -> None:
        r = self.client.get("/api/reticulum/telemetry")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["collector"], "cd" * 16)

    def test_send_ok(self) -> None:
        r = self.client.post("/api/reticulum/telemetry/send")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(self.svc.sent)

    def test_send_error_is_400(self) -> None:
        self.svc.ok = False
        r = self.client.post("/api/reticulum/telemetry/send")
        self.assertEqual(r.status_code, 400)

    def test_503_without_service(self) -> None:
        self._routes.reset_routes()
        r = self.client.get("/api/reticulum/telemetry")
        self.assertEqual(r.status_code, 503)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
