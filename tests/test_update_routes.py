"""Route-level coverage for the update apply/rollback endpoints."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Optional
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.audit import AuditLogWriter
from src.api.audit import dependencies as audit_deps
from src.api.auth import dependencies as auth_deps
from src.api.auth.jwt_session import JwtSessionService
from src.api.routes import update_routes
from src.api.update import ReleaseChannelRegistry, UpdateApplier

_SECRET = "update-routes-secret-" + "u" * 32


class _FakeRunner:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(
        self, args: list[str], cwd: Optional[str], timeout_seconds: float,
    ) -> tuple[int, str, str]:
        self.calls.append(list(args))
        if args[:2] == ["git", "rev-parse"]:
            return 0, "abc123\n", ""
        return 0, "ok", ""


class TestUpdateRoutes(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.audit = AuditLogWriter(log_path=Path(self.tmp.name) / "a.jsonl")
        self.jwt = JwtSessionService(_SECRET, expiry_minutes=60, session_version=1)
        self.runner = _FakeRunner()
        self.applier = UpdateApplier(runner=self.runner, repo_path=".")
        update_routes.init_routes(
            applier=self.applier,
            registry=ReleaseChannelRegistry(),
        )
        auth_deps.init_auth(self.jwt)
        audit_deps.init_audit(self.audit)
        app = FastAPI()
        app.include_router(update_routes.router)
        self.client = TestClient(app)
        self.admin_token = self.jwt.issue("admin", "admin")
        self.viewer_token = self.jwt.issue("viewer", "viewer")

    def tearDown(self) -> None:
        update_routes.reset_routes()
        auth_deps.reset_auth()
        audit_deps.reset_audit()
        self.tmp.cleanup()

    def test_channels_returned_for_admin(self) -> None:
        self.client.cookies.set("meshpoint_session", self.admin_token)
        response = self.client.get("/api/update/channels")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("channels", body)
        self.assertGreater(len(body["channels"]), 0)

    def test_install_status_returned_for_admin(self) -> None:
        self.client.cookies.set("meshpoint_session", self.admin_token)
        with mock.patch(
            "src.api.routes.update_routes.build_install_status_payload",
            return_value={
                "local_version": "0.7.3.1",
                "install_branch": "feat/v0.7.8",
                "install_sha_short": "ac6895a",
                "active_channel_id": "rc-078",
                "active_channel_label": "Release candidate (v0.7.8)",
                "channel_tier": "rc",
                "remote_version": "0.7.3.1",
                "remote_branch": "feat/v0.7.8",
                "update_available": False,
            },
        ):
            response = self.client.get("/api/update/install_status")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["active_channel_id"], "rc-078")
        self.assertEqual(body["install_branch"], "feat/v0.7.8")

    def test_check_for_updates_syncs_for_admin(self) -> None:
        self.client.cookies.set("meshpoint_session", self.admin_token)
        with mock.patch(
            "src.api.routes.update_routes.build_install_status_payload",
            return_value={
                "local_version": "0.7.3.1",
                "install_branch": "feat/v0.7.8",
                "install_sha_short": "ac6895a",
                "compare_branch": "feat/v0.7.8",
                "commits_behind": 12,
                "commits_ahead": 0,
                "update_available": True,
                "checked_at": "2026-05-21T12:00:00+00:00",
            },
        ) as build_mock:
            response = self.client.post(
                "/api/update/check",
                json={"channel_id": "rc-078"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["commits_behind"], 12)
        build_mock.assert_called_once()
        _args, kwargs = build_mock.call_args
        self.assertTrue(kwargs.get("sync_remote"))

    def test_channels_rejects_anonymous(self) -> None:
        client = TestClient(self.client.app)
        response = client.get("/api/update/channels")
        self.assertEqual(response.status_code, 401)

    def test_channels_rejects_viewer(self) -> None:
        self.client.cookies.set("meshpoint_session", self.viewer_token)
        response = self.client.get("/api/update/channels")
        self.assertEqual(response.status_code, 403)

    def test_apply_runs_chain_for_known_channel(self) -> None:
        self.client.cookies.set("meshpoint_session", self.admin_token)
        response = self.client.post(
            "/api/update/apply", json={"channel_id": "stable"},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["success"])
        self.assertEqual(body["target_branch"], "main")

    def test_apply_rejects_unknown_channel(self) -> None:
        self.client.cookies.set("meshpoint_session", self.admin_token)
        response = self.client.post(
            "/api/update/apply", json={"channel_id": "bogus"},
        )
        self.assertEqual(response.status_code, 400)

    def test_apply_rejects_custom_without_branch(self) -> None:
        self.client.cookies.set("meshpoint_session", self.admin_token)
        response = self.client.post(
            "/api/update/apply", json={"channel_id": "custom"},
        )
        self.assertEqual(response.status_code, 400)

    def test_rollback_runs_for_admin(self) -> None:
        self.client.cookies.set("meshpoint_session", self.admin_token)
        response = self.client.post(
            "/api/update/rollback", json={"sha": "deadbeef"},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["success"])

    def test_rollback_rejects_viewer(self) -> None:
        self.client.cookies.set("meshpoint_session", self.viewer_token)
        response = self.client.post(
            "/api/update/rollback", json={"sha": "deadbeef"},
        )
        self.assertEqual(response.status_code, 403)


_CHANGELOG_FIXTURE = """# Changelog

### Unreleased

Queued for the next bump.

### v0.7.4 (May 2026)

- **Smart upgrade indicator landed.** Operators get a what's-coming preview before clicking Apply.

### v0.7.3.1 (May 13, 2026)

- **WS auth close frame fix.** Accept-then-close pattern restored.
"""


class TestReleaseNotesRoute(unittest.TestCase):
    """Coverage for ``GET /api/update/release_notes``."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.audit = AuditLogWriter(log_path=Path(self.tmp.name) / "a.jsonl")
        self.jwt = JwtSessionService(_SECRET, expiry_minutes=60, session_version=1)
        self.runner = _FakeRunner()
        self.applier = UpdateApplier(runner=self.runner, repo_path=".")
        self.changelog_path = Path(self.tmp.name) / "CHANGELOG.md"
        self.changelog_path.write_text(_CHANGELOG_FIXTURE, encoding="utf-8")
        update_routes.init_routes(
            applier=self.applier,
            registry=ReleaseChannelRegistry(),
            changelog_path=self.changelog_path,
        )
        auth_deps.init_auth(self.jwt)
        audit_deps.init_audit(self.audit)
        app = FastAPI()
        app.include_router(update_routes.router)
        self.client = TestClient(app)
        self.admin_token = self.jwt.issue("admin", "admin")
        self.viewer_token = self.jwt.issue("viewer", "viewer")

    def tearDown(self) -> None:
        update_routes.reset_routes()
        auth_deps.reset_auth()
        audit_deps.reset_audit()
        self.tmp.cleanup()

    def test_retired_rc_ids_normalize_to_stable(self) -> None:
        # Fork catalog has no RC channels; retired picker ids alias to stable.
        self.client.cookies.set("meshpoint_session", self.admin_token)
        for retired_id in ("rc-074", "rc-077", "rc-078", "wismesh-node"):
            response = self.client.get(
                f"/api/update/release_notes?channel_id={retired_id}",
            )
            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body["channel_id"], "stable")
            self.assertEqual(body["channel_tier"], "stable")

    def test_stable_channel_returns_first_released(self) -> None:
        self.client.cookies.set("meshpoint_session", self.admin_token)
        response = self.client.get("/api/update/release_notes?channel_id=stable")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIsNotNone(body["preview_section"])
        self.assertFalse(body["preview_section"]["is_unreleased"])
        self.assertEqual(body["preview_section"]["version"], "0.7.4")

    def test_custom_channel_yields_null_preview(self) -> None:
        self.client.cookies.set("meshpoint_session", self.admin_token)
        response = self.client.get("/api/update/release_notes?channel_id=custom")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIsNone(body["preview_section"])

    def test_unknown_channel_returns_400(self) -> None:
        self.client.cookies.set("meshpoint_session", self.admin_token)
        response = self.client.get("/api/update/release_notes?channel_id=bogus")
        self.assertEqual(response.status_code, 400)

    def test_rejects_viewer(self) -> None:
        self.client.cookies.set("meshpoint_session", self.viewer_token)
        response = self.client.get("/api/update/release_notes?channel_id=stable")
        self.assertEqual(response.status_code, 403)

    def test_rejects_anonymous(self) -> None:
        client = TestClient(self.client.app)
        response = client.get("/api/update/release_notes?channel_id=stable")
        self.assertEqual(response.status_code, 401)

    def test_response_includes_installed_version(self) -> None:
        self.client.cookies.set("meshpoint_session", self.admin_token)
        response = self.client.get("/api/update/release_notes?channel_id=rc-074")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("current_installed_version", body)
        self.assertTrue(body["current_installed_version"])


class TestUpdateBadgeAndCheckSettings(unittest.TestCase):
    """GET /api/update/badge and PUT /api/update/check-settings -- the
    periodic-check cache read and the automatic-check config editor.
    """

    def setUp(self) -> None:
        from src.config import AppConfig

        self.tmp = tempfile.TemporaryDirectory()
        self.audit = AuditLogWriter(log_path=Path(self.tmp.name) / "a.jsonl")
        self.jwt = JwtSessionService(_SECRET, expiry_minutes=60, session_version=1)
        self.config = AppConfig()
        update_routes.init_routes(
            applier=UpdateApplier(runner=_FakeRunner(), repo_path="."),
            registry=ReleaseChannelRegistry(),
            config=self.config,
        )
        auth_deps.init_auth(self.jwt)
        audit_deps.init_audit(self.audit)
        app = FastAPI()
        app.include_router(update_routes.router)
        self.client = TestClient(app)
        self.admin_token = self.jwt.issue("admin", "admin")
        self.viewer_token = self.jwt.issue("viewer", "viewer")

    def tearDown(self) -> None:
        update_routes.reset_routes()
        auth_deps.reset_auth()
        audit_deps.reset_audit()
        self.tmp.cleanup()

    def test_badge_reports_unavailable_before_any_periodic_check(self) -> None:
        self.client.cookies.set("meshpoint_session", self.admin_token)
        response = self.client.get("/api/update/badge")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["update_available"])
        self.assertIsNone(body["commits_behind"])

    def test_badge_reflects_cached_periodic_check_result(self) -> None:
        update_routes._last_periodic_check = {
            "commits_behind": 3, "checked_at": "2026-07-12T10:00:00+00:00",
        }
        self.client.cookies.set("meshpoint_session", self.admin_token)
        response = self.client.get("/api/update/badge")
        body = response.json()
        self.assertTrue(body["update_available"])
        self.assertEqual(body["commits_behind"], 3)

    def test_badge_reports_unavailable_when_zero_commits_behind(self) -> None:
        update_routes._last_periodic_check = {
            "commits_behind": 0, "checked_at": "2026-07-12T10:00:00+00:00",
        }
        self.client.cookies.set("meshpoint_session", self.admin_token)
        response = self.client.get("/api/update/badge")
        self.assertFalse(response.json()["update_available"])

    def test_badge_requires_admin(self) -> None:
        self.client.cookies.set("meshpoint_session", self.viewer_token)
        response = self.client.get("/api/update/badge")
        self.assertEqual(response.status_code, 403)

    def test_check_settings_saves_and_updates_live_config(self) -> None:
        self.client.cookies.set("meshpoint_session", self.admin_token)
        with mock.patch.object(update_routes, "save_section_to_yaml") as mock_save:
            response = self.client.put(
                "/api/update/check-settings",
                json={"enabled": False, "interval_minutes": 30},
            )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["saved"])
        self.assertTrue(body["restart_required"])
        self.assertFalse(self.config.update_check.enabled)
        self.assertEqual(self.config.update_check.interval_minutes, 30)
        mock_save.assert_called_once()
        section, updates = mock_save.call_args[0]
        self.assertEqual(section, "update_check")
        self.assertEqual(updates["interval_minutes"], 30)

    def test_check_settings_rejects_interval_below_floor(self) -> None:
        self.client.cookies.set("meshpoint_session", self.admin_token)
        response = self.client.put(
            "/api/update/check-settings",
            json={"enabled": True, "interval_minutes": 1},
        )
        self.assertEqual(response.status_code, 422)

    def test_check_settings_requires_admin(self) -> None:
        self.client.cookies.set("meshpoint_session", self.viewer_token)
        response = self.client.put(
            "/api/update/check-settings",
            json={"enabled": True, "interval_minutes": 60},
        )
        self.assertEqual(response.status_code, 403)

    def test_plain_manual_check_refreshes_the_badge_cache(self) -> None:
        # No channel_id/custom_branch override -- this checks the same
        # thing the periodic loop checks, so the badge should reflect
        # it immediately rather than waiting for the next loop tick.
        self.client.cookies.set("meshpoint_session", self.admin_token)
        with mock.patch(
            "src.api.routes.update_routes.build_install_status_payload",
            return_value={"commits_behind": 5, "checked_at": "2026-07-12T10:00:00+00:00"},
        ):
            self.client.post("/api/update/check", json={})
        badge = self.client.get("/api/update/badge").json()
        self.assertTrue(badge["update_available"])
        self.assertEqual(badge["commits_behind"], 5)

    def test_channel_override_check_does_not_corrupt_the_badge_cache(self) -> None:
        # Checking a DIFFERENT channel/branch than what's installed
        # must not make the badge claim an update on the real install.
        self.client.cookies.set("meshpoint_session", self.admin_token)
        with mock.patch(
            "src.api.routes.update_routes.build_install_status_payload",
            return_value={"commits_behind": 5, "checked_at": "2026-07-12T10:00:00+00:00"},
        ):
            self.client.post("/api/update/check", json={"channel_id": "rc-078"})
        badge = self.client.get("/api/update/badge").json()
        self.assertFalse(badge["update_available"])
        self.assertIsNone(badge["commits_behind"])


if __name__ == "__main__":
    unittest.main()
