"""The `radio` block on GET /api/reticulum/status (feeds the topbar chip).

FastAPI-gated (CI / Pi only), same `_HAS_FASTAPI` pattern the other
route tests use.
"""

from __future__ import annotations

import unittest

try:
    import fastapi  # noqa: F401
    _HAS_FASTAPI = True
except ImportError:
    _HAS_FASTAPI = False

from plugins.apps.reticulum.backend import state


@unittest.skipUnless(_HAS_FASTAPI, "routes imports fastapi (CI / Pi only)")
class TestStatusRadioBlock(unittest.TestCase):
    def setUp(self) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from plugins.apps.reticulum.backend import routes

        self._routes = routes
        routes.reset_routes()

        class _FakeService:
            available = True
            own_address = "<abc123>"
            propagation = None

            async def peer_count(self):
                return 42

            def node_status(self):
                return None

            def propagation_status(self):
                return self.propagation

            def propagation_client_status(self):
                return None

        self._svc = _FakeService()
        routes.init_routes(self._svc, object())
        app = FastAPI()
        app.include_router(routes.router)
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self._routes.reset_routes()
        state.init({})

    def _radio(self) -> dict:
        return self.client.get("/api/reticulum/status").json()["radio"]

    def test_rf_frequency_shown_when_rnode_enabled_with_a_port(self) -> None:
        state.init({
            "rnode_enabled": True, "rnode_serial_port": "/dev/ttyUSB0",
            "rnode_frequency_hz": 869_463_000,
        })
        r = self._radio()
        self.assertTrue(r["rf"])
        self.assertEqual(r["frequency_hz"], 869_463_000)

    def test_no_frequency_when_serial_port_is_blank(self) -> None:
        state.init({"rnode_enabled": True, "rnode_serial_port": ""})
        r = self._radio()
        self.assertFalse(r["rf"])
        self.assertIsNone(r["frequency_hz"])

    def test_backbone_flag_passes_through(self) -> None:
        state.init({"rnode_serial_port": "", "backbone_enabled": True})
        self.assertTrue(self._radio()["backbone"])

    def test_propagation_block_is_none_by_default(self) -> None:
        self.assertIsNone(self.client.get("/api/reticulum/status").json()["propagation"])

    def test_propagation_block_passes_through_when_enabled(self) -> None:
        self._svc.propagation = {"enabled": True, "address": "<pn>", "messages_held": 3}
        p = self.client.get("/api/reticulum/status").json()["propagation"]
        self.assertEqual(p["messages_held"], 3)
        self.assertEqual(p["address"], "<pn>")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
