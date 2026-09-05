"""Tests for POST /api/messages/send with protocol="reticulum".

Regression coverage for a real bug: the unified Messages panel (which
lists Reticulum conversations alongside Meshtastic/MeshCore, since all
three share the `messages` table) posts replies through this one route
-- but TxService.send_text() only ever knew "meshtastic"/"meshcore" and
returned "Unknown protocol: reticulum" for anything else. The dedicated
Reticulum page's own Send tab (POST /api/reticulum/send) always worked,
since it calls LxmfService.send_message() directly -- this route now
does the same for protocol="reticulum" instead of falling through to
TxService, which never should learn Reticulum (see its own docstring).
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth.dependencies import require_admin, require_auth
from src.api.auth.jwt_session import ROLE_ADMIN, SessionClaims

from src.api.routes import messages as messages_module


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(messages_module.router)
    app.dependency_overrides[require_admin] = lambda: SessionClaims("test-admin", ROLE_ADMIN, 1)
    app.dependency_overrides[require_auth] = lambda: SessionClaims("test-admin", ROLE_ADMIN, 1)
    return app


def _reset_module_state() -> None:
    messages_module._tx_service = None
    messages_module._message_repo = None
    messages_module._node_repo = None
    messages_module._meshcore_tx = None
    messages_module._config = None
    messages_module._reticulum_service = None


class TestReticulumSendViaMessagesRoute(unittest.TestCase):
    def setUp(self) -> None:
        _reset_module_state()
        self.app = _build_app()
        self.client = TestClient(self.app)
        # TxService/message_repo just need to exist for the route's own
        # early 503 guards to pass -- the Reticulum branch never touches
        # either of them.
        messages_module._tx_service = AsyncMock()
        messages_module._message_repo = AsyncMock()

    def tearDown(self) -> None:
        _reset_module_state()

    def _post(self, **overrides):
        body = {"text": "hello", "destination": "abc123", "protocol": "reticulum"}
        body.update(overrides)
        return self.client.post("/api/messages/send", json=body)

    def test_success_calls_lxmf_service_not_tx_service(self):
        reticulum = AsyncMock()
        reticulum.available = True
        reticulum.send_message.return_value = 42
        messages_module._reticulum_service = reticulum

        res = self._post()

        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertTrue(body["success"])
        self.assertEqual(body["protocol"], "reticulum")
        self.assertEqual(body["packet_id"], "42")
        reticulum.send_message.assert_awaited_once_with("abc123", "hello")
        messages_module._tx_service.send_text.assert_not_called()

    def test_does_not_double_save_sent_message(self):
        # LxmfService.send_message() already persists the sent row
        # itself -- this route must not also call message_repo.save_sent
        # for the reticulum branch, unlike the TxService path below it.
        reticulum = AsyncMock()
        reticulum.available = True
        reticulum.send_message.return_value = 1
        messages_module._reticulum_service = reticulum

        self._post()

        messages_module._message_repo.save_sent.assert_not_called()

    def test_unknown_destination_returns_failure_not_500(self):
        reticulum = AsyncMock()
        reticulum.available = True
        reticulum.send_message.side_effect = ValueError("Unknown destination")
        messages_module._reticulum_service = reticulum

        res = self._post()

        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertFalse(body["success"])
        self.assertEqual(body["error"], "Unknown destination")

    def test_service_not_running_returns_failure(self):
        reticulum = AsyncMock()
        reticulum.available = True
        reticulum.send_message.side_effect = RuntimeError("Reticulum service is not running")
        messages_module._reticulum_service = reticulum

        res = self._post()

        self.assertFalse(res.json()["success"])

    def test_503_when_reticulum_service_not_configured(self):
        messages_module._reticulum_service = None
        res = self._post()
        self.assertEqual(res.status_code, 503)

    def test_503_when_reticulum_service_unavailable(self):
        reticulum = AsyncMock()
        reticulum.available = False
        messages_module._reticulum_service = reticulum
        res = self._post()
        self.assertEqual(res.status_code, 503)

    def test_empty_text_still_rejected_before_reticulum_branch(self):
        reticulum = AsyncMock()
        reticulum.available = True
        messages_module._reticulum_service = reticulum

        res = self._post(text="   ")

        self.assertEqual(res.status_code, 400)
        reticulum.send_message.assert_not_awaited()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
