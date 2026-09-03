"""Regression guard for src.api.server's built-in router list.

Nothing else asserts the create_app router set, so a dropped router or an
accidental public/protected flip would ship silently. Needs fastapi
(APIRouter introspection + TestClient), so it runs on CI / the Pi, not on
the fastapi-less dev Mac.

The wiring check mirrors tests/test_protected_router_wiring.py rather than
calling create_app() (whose lifespan builds the whole pipeline) -- it
mounts _BUILTIN_ROUTERS onto a bare FastAPI app the same way create_app
does.

Note: "public" here means the router is mounted with no
Depends(require_auth) gate. Several such routers still guard their own
endpoints with Depends(require_admin) inline (backup, dangerous,
auth-config) -- that's unchanged and out of scope for this test.
"""

from __future__ import annotations

import unittest

from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient

from src.api import route_registry
from src.api.auth import dependencies as auth_deps
from src.api.auth.dependencies import require_auth
from src.api.auth.jwt_session import JwtSessionService
from src.api.routes import (
    auth_routes,
    config_routes,
    device,
    messages,
    metrics_routes,
    nodes,
    theme_routes,
)
from src.api.server import _BUILTIN_ROUTERS

_SECRET = "router-snapshot-secret-" + "z" * 16

# Deliberate security choices -- a flip in either direction should fail
# this test and force a conscious edit here.
_MUST_BE_PUBLIC = [auth_routes.router, metrics_routes.router, theme_routes.router]
_MUST_BE_PROTECTED = [
    nodes.router, config_routes.router, messages.router, device.router,
]


class TestBuiltinRouterList(unittest.TestCase):
    def setUp(self) -> None:
        self.by_id = {id(r): pub for r, pub in _BUILTIN_ROUTERS}

    def test_shape(self) -> None:
        self.assertEqual(len(_BUILTIN_ROUTERS), 60)
        for entry in _BUILTIN_ROUTERS:
            self.assertIsInstance(entry, tuple)
            router, public = entry
            self.assertIsInstance(router, APIRouter)
            self.assertIsInstance(public, bool)

    def test_public_count_snapshot(self) -> None:
        self.assertEqual(sum(1 for _, pub in _BUILTIN_ROUTERS if pub), 12)

    def test_known_auth_levels(self) -> None:
        for r in _MUST_BE_PUBLIC:
            self.assertTrue(self.by_id.get(id(r)), f"{r.tags} should be public")
        for r in _MUST_BE_PROTECTED:
            self.assertIn(id(r), self.by_id)
            self.assertFalse(self.by_id[id(r)], f"{r.tags} must stay protected")

    def test_no_two_routers_share_an_exact_route(self) -> None:
        seen: set[str] = set()
        for router, _ in _BUILTIN_ROUTERS:
            for rt in router.routes:
                methods = sorted(getattr(rt, "methods", []) or [])
                key = f"{methods} {getattr(rt, 'path', '')}"
                self.assertNotIn(key, seen, f"duplicate route {key}")
                seen.add(key)


class TestBuiltinRouterWiring(unittest.TestCase):
    def setUp(self) -> None:
        self.service = JwtSessionService(
            secret=_SECRET, expiry_minutes=60, session_version=1,
        )
        auth_deps.init_auth(self.service)
        route_registry.reset()

        protected = [Depends(require_auth)]
        app = FastAPI()
        for router, public in _BUILTIN_ROUTERS:
            app.include_router(router, dependencies=None if public else protected)

        # a plugin router registered before create_app must show up mounted
        pub = APIRouter(prefix="/api/plugintest")

        @pub.get("/ping")
        def _ping():
            return {"ok": True}

        route_registry.register_router(pub, public=True)
        for spec in route_registry.registered():
            app.include_router(
                spec.router, dependencies=None if spec.public else protected,
            )
        self.client = TestClient(app)

    def tearDown(self) -> None:
        auth_deps.reset_auth()
        route_registry.reset()

    def test_protected_router_401_without_session(self) -> None:
        self.assertEqual(self.client.get("/api/nodes").status_code, 401)

    def test_core_page_prefixes_are_all_mounted(self) -> None:
        """Live requests, not static ``app.routes`` introspection -- FastAPI
        has changed how an included router's routes show up on ``app.routes``
        before (e.g. 0.141's ``_IncludedRouter`` wrapper no longer flattens
        them into plain ``APIRoute`` objects with a ``.path``), which broke
        this check without anything actually being unmounted. An HTTP
        request is stable across that: a matched protected route 401s (no
        session) rather than 404s, and a matched public route doesn't 404
        either -- both prove the router is really mounted regardless of how
        the framework represents it internally."""
        checks = (
            ("/api/nodes", False),
            ("/api/messages/status", False),
            ("/api/config", False),
            ("/api/themes", True),
            ("/api/topology/graph", False),
            ("/api/rf/status", False),
        )
        for path, public in checks:
            resp = self.client.get(path)
            self.assertNotEqual(resp.status_code, 404, f"no route under {path}")
            if not public:
                self.assertEqual(resp.status_code, 401, f"{path} should require auth")

    def test_registered_plugin_router_is_mounted_and_public(self) -> None:
        r = self.client.get("/api/plugintest/ping")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"ok": True})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
