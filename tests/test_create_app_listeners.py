"""Regression guard for src.api.server's built-in listener list.

Mirrors tests/test_create_app_routers.py: nothing else asserts that every
RTL-SDR listener still gets built and wired into its router at startup, so
a dropped entry would ship silently. Needs fastapi (the listener classes'
import chain + a TestClient for the status routes), so it runs on CI / the
Pi, not on the fastapi-less dev Mac.

It drives listener_registry.start_all() directly rather than create_app()
(whose lifespan needs a real concentrator + DB) -- the same shortcut the
router test takes.
"""

from __future__ import annotations

import asyncio
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import listener_registry
from src.api.listener_registry import ListenerSpec
from src.api.routes import (
    dab_routes,
    listener_routes,
    pager_routes,
)
from src.api.server import _BUILTIN_LISTENERS
from src.audio.pager_listener import PagerListener

_EXPECTED_NAMES = ["radio", "pagers", "dab"]


class TestBuiltinListenerList(unittest.TestCase):
    def tearDown(self) -> None:
        listener_registry.reset()

    def test_names_and_shape(self) -> None:
        self.assertEqual([s.name for s in _BUILTIN_LISTENERS], _EXPECTED_NAMES)
        for s in _BUILTIN_LISTENERS:
            self.assertIsInstance(s, ListenerSpec)
            self.assertTrue(callable(s.build))
            self.assertTrue(callable(s.wire))

    def test_start_all_wires_every_route_module(self) -> None:
        for mod in (listener_routes, pager_routes, dab_routes):
            getattr(mod, "reset_routes", lambda: None)()

        listener_registry.start_all(_BUILTIN_LISTENERS)
        try:
            # one entry per init_routes call; pagers builds a single
            # listener now (P2000 and POCSAG both split into their own
            # plugins, leaving just this one kind here).
            names = [n for n, _ in listener_registry.live()]
            self.assertEqual(names, _EXPECTED_NAMES)
            pagers_obj = next(o for n, o in listener_registry.live() if n == "pagers")
            self.assertIsInstance(pagers_obj, PagerListener)
            self.assertEqual(pagers_obj.kind, "pagers")

            self.assertIsNotNone(listener_routes._listener)
            self.assertIsNotNone(dab_routes._listener)
            self.assertIsNotNone(pager_routes._pagers)
        finally:
            asyncio.run(listener_registry.stop_all())

    def test_status_routes_answer_after_start_all_not_running(self) -> None:
        listener_registry.start_all(_BUILTIN_LISTENERS)
        try:
            app = FastAPI()
            app.include_router(dab_routes.router)
            client = TestClient(app)
            resp = client.get("/api/dab/status")
            self.assertEqual(resp.status_code, 200)
            self.assertFalse(resp.json().get("running"))
        finally:
            asyncio.run(listener_registry.stop_all())

    def test_plugin_listener_is_built_and_wired_after_builtins(self) -> None:
        built = []
        listener_registry.register_listener(
            ListenerSpec(
                "plugtest",
                lambda: built.append("build") or _NoopListener(),
                lambda obj: built.append("wire"),
            )
        )
        listener_registry.start_all(_BUILTIN_LISTENERS)
        try:
            self.assertEqual(built, ["build", "wire"])
            self.assertEqual(listener_registry.live()[-1][0], "plugtest")
        finally:
            asyncio.run(listener_registry.stop_all())


class _NoopListener:
    async def stop(self) -> None:
        pass


class TestBuiltinListenerRouterAlignment(unittest.TestCase):
    """Every listener route module is also in the router list (else its tab
    would 404 even though the listener runs)."""

    def test_router_prefixes_present(self) -> None:
        from src.api.server import _BUILTIN_ROUTERS

        prefixes = {getattr(r, "prefix", "") for r, _ in _BUILTIN_ROUTERS}
        self.assertIn("/api/dab", prefixes)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
