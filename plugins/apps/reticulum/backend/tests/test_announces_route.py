"""GET /api/reticulum/announces -- the Activity tab's backing route.

FastAPI-gated (CI / Pi only), same `_HAS_FASTAPI` pattern the other route
tests use.
"""

from __future__ import annotations

import unittest

try:
    import fastapi  # noqa: F401
    _HAS_FASTAPI = True
except ImportError:
    _HAS_FASTAPI = False


@unittest.skipUnless(_HAS_FASTAPI, "routes imports fastapi (CI / Pi only)")
class TestAnnouncesRoute(unittest.TestCase):
    def setUp(self) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from plugins.apps.reticulum.backend import routes

        self._routes = routes
        routes.reset_routes()

        class _FakeService:
            def announce_log(self):
                return [
                    {"ts": "2026-09-07T12:00:00+00:00", "destination_hash": "ab",
                     "display_name": "Bob", "aspect": "lxmf.delivery"},
                ]

        routes.init_routes(_FakeService(), object())
        app = FastAPI()
        app.include_router(routes.router)
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self._routes.reset_routes()

    def test_returns_the_service_log(self) -> None:
        r = self.client.get("/api/reticulum/announces")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(len(body), 1)
        self.assertEqual(body[0]["display_name"], "Bob")
        self.assertEqual(body[0]["aspect"], "lxmf.delivery")

    def test_503_when_service_absent(self) -> None:
        self._routes.reset_routes()
        r = self.client.get("/api/reticulum/announces")
        self.assertEqual(r.status_code, 503)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
