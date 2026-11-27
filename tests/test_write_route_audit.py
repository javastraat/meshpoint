"""Every write route in the real app needs an admin or a write-checked session.

Walks ``create_app()``'s routes (core and every mounted plugin router) and
checks each POST/PUT/PATCH/DELETE route depends on ``require_admin`` or
``require_auth`` (which refuses a Viewer anything but GET/HEAD/OPTIONS), so a
newly added route that forgets its guard fails here instead of quietly
letting a Viewer, or nobody at all, write. Adapted from upstream
``tests/test_viewer_read_only.py`` (b91d994b, 471a81da: newer FastAPI keeps
included routers instead of flattening ``app.routes``).

Uses TestClient, so on rakv21 (newer starlette, no httpx2) run it on the COTX.
"""

import tempfile
import unittest
from pathlib import Path

from fastapi import routing
from fastapi.testclient import TestClient

from src.api.auth import dependencies
from src.api.server import create_app
from src.config import AppConfig

# Before login, or the Viewer's own password: require_session or public by design.
_SESSION_ROUTES = {
    "/api/auth/setup", "/api/auth/login", "/api/auth/logout",
    "/api/auth/change_password",
}
_WRITES = {"POST", "PUT", "PATCH", "DELETE"}


def _guards(dependant) -> set:
    found = {dependant.call}
    for child in dependant.dependencies:
        found |= _guards(child)
    return found


def _routes(app):
    iter_contexts = getattr(routing, "iter_route_contexts", None)
    return iter_contexts(app.routes) if iter_contexts else app.routes


class WriteRouteAuditTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        config = AppConfig()
        config.storage.database_path = str(Path(self._tmp.name) / "test.db")
        config.web_auth.jwt_secret = "route-audit-test-" + "x" * 32
        config.web_auth.admin_password_hash = "test-setup-complete"
        self.app = create_app(config)

    def tearDown(self) -> None:
        dependencies.reset_auth()
        self._tmp.cleanup()

    def test_every_write_route_is_guarded(self) -> None:
        unguarded, checked = [], 0
        for route in _routes(self.app):
            original = getattr(route, "original_route", route)
            if not isinstance(original, routing.APIRoute) or not (route.methods & _WRITES):
                continue
            if route.path in _SESSION_ROUTES:
                continue
            checked += 1
            if not _guards(route.dependant) & {dependencies.require_admin, dependencies.require_auth}:
                unguarded.append(f"{sorted(route.methods & _WRITES)} {route.path}")
        self.assertEqual(unguarded, [])
        self.assertGreater(checked, 20)

    def test_anonymous_is_turned_away(self) -> None:
        client = TestClient(self.app)
        self.assertEqual(client.get("/api/messages/conversations").status_code, 401)


if __name__ == "__main__":
    unittest.main()
