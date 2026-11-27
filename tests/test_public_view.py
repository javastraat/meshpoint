"""Public view stays opt-in, page-scoped and separate from authenticated APIs (TODO 37c).

Ported from upstream KMX415/meshpoint tests/test_public_view.py (b91d994b),
rewritten for unittest so it also runs on the Pi (no pytest there). Uses
TestClient: on rakv21 (newer starlette, no httpx2) run it on the COTX.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from src.api import server
from src.api.audit import AuditLogWriter
from src.api.auth import auth_bootstrap, dependencies
from src.api.auth.jwt_session import JwtSessionService
from src.api.routes import stats_routes
from src.config import AppConfig


class PublicViewTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        config = AppConfig()
        config.storage.database_path = str(tmp / "test.db")
        config.dashboard.static_dir = str(Path(__file__).resolve().parents[1] / "frontend")
        config.web_auth.jwt_secret = "public-view-test-" + "x" * 32
        config.web_auth.admin_password_hash = "test-setup-complete"
        self.config = config
        self.persisted: list[dict] = []
        writer = AuditLogWriter(log_path=tmp / "audit.jsonl")
        self.nodes = AsyncMock()
        self.nodes.get_count.return_value = 25
        self.nodes.get_active_count.return_value = 8
        traffic = AsyncMock()
        traffic.get_traffic_summary.return_value = {
            "total_packets": 300, "packets_last_hour": 60, "packets_per_minute": 1,
            "private_field": "MUST-NOT-LEAK",
        }
        signal = AsyncMock()
        signal.get_signal_summary.return_value = {
            "avg_rssi": -90, "avg_snr": 7, "private_field": "MUST-NOT-LEAK",
        }
        self._patches = [
            patch.object(auth_bootstrap, "_make_persister", lambda: self.persisted.append),
            patch.object(server, "AuditLogWriter", lambda: writer),
            patch.object(stats_routes, "_node_repo", self.nodes),
            patch.object(stats_routes, "_traffic_monitor", traffic),
            patch.object(stats_routes, "_signal_analyzer", signal),
        ]
        for p in self._patches:
            p.start()
        app = server.create_app(config)
        jwt = JwtSessionService(config.web_auth.jwt_secret, 60, 1)
        self.public, self.admin, self.viewer = (TestClient(app) for _ in range(3))
        self.admin.headers["Authorization"] = f"Bearer {jwt.issue('admin', 'admin')}"
        self.admin.cookies.set("meshpoint_session", jwt.issue("admin", "admin"))
        self.viewer.headers["Authorization"] = f"Bearer {jwt.issue('viewer', 'viewer')}"

    def tearDown(self) -> None:
        for p in reversed(self._patches):
            p.stop()
        dependencies.reset_auth()
        self._tmp.cleanup()

    def _enable(self, pages):
        result = self.admin.put("/api/config/public_view", json={"enabled": True, "pages": pages})
        self.assertEqual(result.status_code, 200, result.text)
        return result

    def test_default_disabled(self) -> None:
        self.assertFalse(self.config.web_auth.public_view_enabled)
        self.assertEqual(self.public.get("/", follow_redirects=False).headers["location"], "/login")
        for path in ("", "/dashboard", "/stats", "/radio"):
            self.assertEqual(self.public.get("/api/public/view" + path).status_code, 404, path)

    def test_setup_required_even_if_enabled(self) -> None:
        self._enable(["dashboard"])
        self.config.web_auth.admin_password_hash = ""
        self.assertEqual(self.public.get("/api/public/view").status_code, 404)
        self.assertEqual(self.public.get("/", follow_redirects=False).headers["location"], "/setup")

    def test_only_admin_can_configure_and_values_persist(self) -> None:
        payload = {"enabled": True, "pages": ["dashboard", "radio"]}
        self.assertEqual(self.public.put("/api/config/public_view", json=payload).status_code, 401)
        self.assertEqual(self.viewer.put("/api/config/public_view", json=payload).status_code, 403)
        self.assertEqual(self.persisted, [])
        self._enable(payload["pages"])
        self.assertEqual(self.persisted, [{"public_view_enabled": True, "public_view_pages": payload["pages"]}])
        self.assertTrue(self.config.web_auth.public_view_enabled)
        settings = self.admin.get("/api/config/auth_settings").json()
        self.assertEqual(settings["public_view_pages"], payload["pages"])

    def test_invalid_selection_rejected(self) -> None:
        for pages in ([], ["messages"], ["configuration"], ["../config"]):
            with self.subTest(pages=pages):
                r = self.admin.put("/api/config/public_view", json={"enabled": True, "pages": pages})
                self.assertEqual(r.status_code, 422)
                self.assertFalse(self.config.web_auth.public_view_enabled)
                self.assertEqual(self.persisted, [])

    def test_selected_pages_and_explicit_fields_only(self) -> None:
        self._enable(["dashboard", "stats", "radio"])
        self.assertEqual(self.public.get("/api/public/view").json(), {"pages": ["dashboard", "stats", "radio"]})
        dashboard = self.public.get("/api/public/view/dashboard")
        self.assertEqual(dashboard.json(), {"total_nodes": 25, "active_24h": 8})
        self.assertEqual(dashboard.headers["cache-control"], "no-store")
        self.assertNotIn("set-cookie", dashboard.headers)
        self.assertEqual(self.public.get("/api/public/view/stats").json(), {
            "total_packets": 300, "packets_last_hour": 60,
            "packets_per_minute": 1, "avg_rssi": -90, "avg_snr": 7,
        })
        radio = self.config.radio
        self.assertEqual(self.public.get("/api/public/view/radio").json(), {
            "region": radio.region, "frequency_mhz": radio.frequency_mhz,
            "bandwidth_khz": radio.bandwidth_khz, "spreading_factor": radio.spreading_factor,
        })
        self.assertEqual(self.public.get("/api/public/view/messages").status_code, 404)

    def test_revocation_blocks_cached_page_immediately(self) -> None:
        self._enable(["dashboard", "radio"])
        self.assertEqual(self.public.get("/api/public/view/radio").status_code, 200)
        self._enable(["dashboard"])
        self.assertEqual(self.public.get("/api/public/view/radio").status_code, 404)
        self.assertEqual(self.public.get("/api/public/view/dashboard").status_code, 200)
        r = self.admin.put("/api/config/public_view", json={"enabled": False, "pages": []})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.public.get("/api/public/view/dashboard").status_code, 404)
        self.assertEqual(self.public.get("/", follow_redirects=False).status_code, 302)

    def test_public_landing_does_not_unlock_private_routes_or_socket(self) -> None:
        self._enable(["dashboard"])
        html = self.public.get("/")
        self.assertEqual(html.status_code, 200)
        self.assertIn("Admin sign in", html.text)
        self.assertNotIn("js/app.js", html.text)
        self.assertIn("js/app.js", self.admin.get("/").text)
        self.assertEqual(self.public.get("/login").status_code, 200)
        # The page's own assets load without a session (no dashboard JS needed).
        for asset in ("/css/public_view.css", "/js/public_view.js", "/assets/favicon.png"):
            self.assertEqual(self.public.get(asset).status_code, 200, asset)
        for path in ("/api/config", "/api/messages/conversations", "/api/nodes", "/api/stats/summary"):
            self.assertEqual(self.public.get(path).status_code, 401, path)
        with self.public.websocket_connect("/ws") as ws:
            with self.assertRaises(WebSocketDisconnect) as exc:
                ws.receive_json()
        self.assertEqual(exc.exception.code, 4401)

    def test_failed_persistence_keeps_public_disabled(self) -> None:
        from src.api.routes import auth_config_routes

        def fail(_values):
            raise OSError("test failure")

        service = auth_config_routes._service()
        with patch.object(service, "_persist", fail), self.assertRaises(OSError):
            service.update_public_view(True, ["radio"])
        self.assertFalse(self.config.web_auth.public_view_enabled)

    def test_revocation_during_query(self) -> None:
        self._enable(["dashboard"])

        async def revoke(_page):
            self.config.web_auth.public_view_enabled = False
            return {"total_nodes": 25}

        with patch.object(stats_routes, "public_snapshot", revoke):
            self.assertEqual(self.public.get("/api/public/view/dashboard").status_code, 404)

    def test_startup_has_no_fabricated_counts(self) -> None:
        self._enable(["dashboard"])
        with patch.object(stats_routes, "_node_repo", None):
            self.assertEqual(self.public.get("/api/public/view/dashboard").status_code, 503)

    def test_repeated_requests_share_aggregate_cache(self) -> None:
        self._enable(["dashboard"])
        self.assertEqual(self.public.get("/api/public/view/dashboard").status_code, 200)
        self.assertEqual(self.public.get("/api/public/view/dashboard").status_code, 200)
        self.nodes.get_count.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
