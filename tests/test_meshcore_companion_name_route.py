"""Tests for PUT /api/config/meshcore/companion-name.

Validates the route's contract: 503 when the companion is not
reachable, 400 when the rename was rejected (validation locally or
ERROR from the companion), 200 with the cleaned name on success,
and the yaml-persistence side effect that drives the
on-USB-connect re-apply path. The actual rename / validation logic
lives on MeshCoreTxClient and is covered separately in
test_meshcore_tx_client.py; here we just exercise the HTTP surface.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth.dependencies import require_admin, require_auth
from src.api.auth.jwt_session import ROLE_ADMIN, SessionClaims

from src.api.routes import meshcore_config_routes as mc_routes

class _RenameResult:
    def __init__(
        self,
        success: bool,
        error: str | None = None,
        event_type: str | None = None,
    ):
        self.success = success
        self.error = error
        self.event_type = event_type


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(mc_routes.router)
    # Routes are auth-gated (fork viewer lockdown); satisfy the dependencies
    # with an admin session so these tests exercise the route logic itself.
    app.dependency_overrides[require_admin] = lambda: SessionClaims("test-admin", ROLE_ADMIN, 1)
    app.dependency_overrides[require_auth] = lambda: SessionClaims("test-admin", ROLE_ADMIN, 1)
    return app


def _reset_module_state() -> None:
    mc_routes._config = None
    mc_routes._tx_service = None
    mc_routes._meshcore_sources = []


class TestCompanionNameEndpoint(unittest.TestCase):

    def setUp(self) -> None:
        _reset_module_state()
        self.app = _build_app()
        self.client = TestClient(self.app)
        # Real-shape stub: the route persists the rename onto this
        # companion's own capture.meshcore_usb[i] entry now (matched by
        # label, "" for the bare/default companion these tests use),
        # not the legacy singular meshcore.companion_name field.
        self._fake_config = SimpleNamespace(
            meshcore=SimpleNamespace(companion_name=None),
            capture=SimpleNamespace(
                meshcore_usb=[
                    SimpleNamespace(
                        label="",
                        serial_port=None,
                        baud_rate=115200,
                        auto_detect=True,
                        companion_name=None,
                    ),
                ],
            ),
        )

    def tearDown(self) -> None:
        _reset_module_state()

    def _wire(self, mc_tx) -> None:
        mc_routes._config = self._fake_config
        tx_service = MagicMock()
        tx_service._meshcore_tx = mc_tx
        mc_routes._tx_service = tx_service
        # Route resolves the target companion via _meshcore_sources now
        # (label-scoped, not the old singular _tx_service._meshcore_tx)
        # -- .name must be a real string ("meshcore_usb", matching the
        # request's default empty label) for _resolve_companion_source
        # to find it.
        mc_tx.name = "meshcore_usb"
        mc_routes._meshcore_sources = [mc_tx]

    def test_503_when_config_not_loaded(self):
        # Simulate the very-early-startup window where init_routes has
        # not been called yet.
        res = self.client.put(
            "/api/config/meshcore/companion-name",
            json={"name": "Test"},
        )
        self.assertEqual(res.status_code, 503)
        self.assertIn("config", res.json()["detail"].lower())

    def test_503_when_tx_service_missing_meshcore_tx(self):
        mc_routes._config = self._fake_config
        tx_service = MagicMock(spec=[])
        mc_routes._tx_service = tx_service
        res = self.client.put(
            "/api/config/meshcore/companion-name",
            json={"name": "Test"},
        )
        self.assertEqual(res.status_code, 503)
        self.assertIn("not connected", res.json()["detail"].lower())

    def test_503_when_meshcore_disconnected(self):
        mc = MagicMock()
        mc.connected = False
        mc.set_companion_name = AsyncMock()
        self._wire(mc)
        res = self.client.put(
            "/api/config/meshcore/companion-name",
            json={"name": "Test"},
        )
        self.assertEqual(res.status_code, 503)
        mc.set_companion_name.assert_not_called()

    def test_success_returns_cleaned_name(self):
        mc = MagicMock()
        mc.connected = True
        mc.set_companion_name = AsyncMock(
            return_value=_RenameResult(success=True, event_type="OK")
        )
        self._wire(mc)
        with patch.object(mc_routes, "save_section_to_yaml") as save:
            res = self.client.put(
                "/api/config/meshcore/companion-name",
                json={"name": "  Mesh Lab East  "},
            )
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertTrue(body["saved"])
        # Server-side strip happens in the route response so the UI
        # readout matches what the companion actually stored.
        self.assertEqual(body["name"], "Mesh Lab East")
        self.assertEqual(body["event_type"], "OK")
        mc.set_companion_name.assert_awaited_once_with("  Mesh Lab East  ")
        # Cleaned (stripped) name lands in both the in-memory config
        # (this companion's own capture.meshcore_usb[i] entry, matched
        # by label -- not the legacy singular meshcore.companion_name
        # field) and the persisted yaml so the on-connect re-apply has
        # the right value next time the companion comes back online.
        self.assertEqual(
            self._fake_config.capture.meshcore_usb[0].companion_name, "Mesh Lab East",
        )
        save.assert_called_once_with("capture", {
            "meshcore_usb": [{
                "serial_port": None, "baud_rate": 115200, "auto_detect": True,
                "label": "", "companion_name": "Mesh Lab East",
            }],
        })

    def test_yaml_permission_error_does_not_fail_request(self):
        # If local.yaml is not writable, the rename already stuck on
        # the device's flash for the current session. Failing the
        # HTTP request would mislead the UI into rolling back the
        # name in its readout while the device actually has the new
        # name. We log a WARNING and return success.
        mc = MagicMock()
        mc.connected = True
        mc.set_companion_name = AsyncMock(
            return_value=_RenameResult(success=True, event_type="OK")
        )
        self._wire(mc)
        with patch.object(
            mc_routes,
            "save_section_to_yaml",
            side_effect=PermissionError("config/local.yaml"),
        ):
            res = self.client.put(
                "/api/config/meshcore/companion-name",
                json={"name": "Mesh Lab East"},
            )
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["saved"])
        # In-memory copy still updates -- the yaml write is the only
        # thing that failed.
        self.assertEqual(
            self._fake_config.capture.meshcore_usb[0].companion_name, "Mesh Lab East",
        )

    def test_400_when_companion_rejects(self):
        mc = MagicMock()
        mc.connected = True
        mc.set_companion_name = AsyncMock(
            return_value=_RenameResult(
                success=False, error="Companion rejected name: name in use"
            )
        )
        self._wire(mc)
        res = self.client.put(
            "/api/config/meshcore/companion-name",
            json={"name": "Existing"},
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("rejected", res.json()["detail"].lower())

    def test_400_when_validation_fails_locally(self):
        # The set_companion_name client returns success=False without
        # ever talking to the device when validation fails (empty,
        # oversize, etc.). Route must surface that as 400, not 503.
        mc = MagicMock()
        mc.connected = True
        mc.set_companion_name = AsyncMock(
            return_value=_RenameResult(
                success=False, error="Name must not be empty"
            )
        )
        self._wire(mc)
        res = self.client.put(
            "/api/config/meshcore/companion-name",
            json={"name": ""},
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("empty", res.json()["detail"].lower())

    def test_422_when_body_missing_name(self):
        mc = MagicMock()
        mc.connected = True
        mc.set_companion_name = AsyncMock()
        self._wire(mc)
        res = self.client.put(
            "/api/config/meshcore/companion-name",
            json={},
        )
        # Pydantic-level validation: 422 before we even reach the route.
        self.assertEqual(res.status_code, 422)
        mc.set_companion_name.assert_not_called()


if __name__ == "__main__":
    unittest.main()
