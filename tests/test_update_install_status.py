"""Tests for install branch detection and channel matching."""

from __future__ import annotations

import unittest
from typing import Optional
from unittest import mock

from src.api.update.channels import ReleaseChannelRegistry
from src.api.update.install_status import (
    build_install_status_payload,
    count_commits_behind_ahead,
    list_branch_commits,
    match_channel_for_branch,
    read_install_git_ref,
    resolve_compare_branch,
    suggest_active_channel_for_install,
)


class _FakeGitRunner:
    def __init__(
        self,
        branch: str = "feat/v0.7.4",
        sha: str = "ac6895a",
        *,
        behind: int = 12,
        ahead: int = 0,
        remote_sha: str = "f22d868a",
    ) -> None:
        self.branch = branch
        self.sha = sha
        self.behind = behind
        self.ahead = ahead
        self.remote_sha = remote_sha
        self.calls: list[list[str]] = []

    @staticmethod
    def _strip_prefix(args: list[str]) -> list[str]:
        """Drop ``sudo`` and ``-c <opt>`` pairs so matching sees plain git argv."""
        core = list(args)
        if core and core[0] == "sudo":
            core.pop(0)
        if core and core[0] == "git":
            core.pop(0)
        while core[:1] == ["-c"]:
            core = core[2:]
        return ["git", *core]

    def __call__(
        self, args: list[str], cwd: Optional[str], timeout_seconds: float,
    ) -> tuple[int, str, str]:
        self.calls.append(list(args))
        args = self._strip_prefix(args)
        if args[:3] == ["git", "fetch", "origin"]:
            return 0, "", ""
        if "rev-parse" in args and any("--abbrev-ref" in a for a in args):
            return 0, f"{self.branch}\n", ""
        if "rev-parse" in args and any("short" in a for a in args):
            ref = args[-1] if args else ""
            if ref.startswith("origin/"):
                return 0, f"{self.remote_sha}\n", ""
            return 0, f"{self.sha}\n", ""
        if "rev-list" in args and "--count" in args:
            return 1, "", "rev-list not allowed"
        if "log" in args and "--oneline" in args:
            spec = args[-1]
            if spec.startswith("HEAD.."):
                return 0, ("ab\n" * self.behind), ""
            if spec.startswith("origin/") and spec.endswith("..HEAD"):
                return 0, ("cd\n" * self.ahead), ""
        return 1, "", "err"


class TestMatchChannelForBranch(unittest.TestCase):
    def test_main_maps_to_stable(self) -> None:
        info = match_channel_for_branch(ReleaseChannelRegistry(), "main")
        self.assertEqual(info["active_channel_id"], "stable")

    def test_retired_upstream_rc_branch_maps_to_custom(self) -> None:
        # Upstream sprint branches are not in this fork's catalog.
        info = match_channel_for_branch(ReleaseChannelRegistry(), "feat/v0.7.7")
        self.assertEqual(info["active_channel_id"], "custom")

    def test_retired_wismesh_branch_maps_to_custom(self) -> None:
        info = match_channel_for_branch(ReleaseChannelRegistry(), "feat/wismesh-hat")
        self.assertEqual(info["active_channel_id"], "custom")
        self.assertEqual(info["channel_tier"], "custom")

    def test_main_stays_stable_without_rc_channel(self) -> None:
        # Fork catalog has no RC tier, so the picker never auto-advances.
        info = suggest_active_channel_for_install(
            ReleaseChannelRegistry(), "main", local_version="0.7.5",
        )
        self.assertEqual(info["active_channel_id"], "stable")

    def test_unknown_branch_maps_to_custom(self) -> None:
        info = match_channel_for_branch(ReleaseChannelRegistry(), "feat/other")
        self.assertEqual(info["active_channel_id"], "custom")
        self.assertIn("feat/other", info["active_channel_label"])


class TestReadInstallGitRef(unittest.TestCase):
    def test_reads_branch_and_sha(self) -> None:
        runner = _FakeGitRunner(branch="feat/v0.7.4", sha="deadbeef")
        branch, sha = read_install_git_ref(
            "/opt/meshpoint", runner=runner, use_sudo=False,
        )
        self.assertEqual(branch, "feat/v0.7.4")
        self.assertEqual(sha, "deadbeef")


class TestBuildInstallStatusPayload(unittest.TestCase):
    def test_null_branch_does_not_default_to_stable(self) -> None:
        runner = _FakeGitRunner(branch="", sha="")
        runner.__call__ = lambda args, cwd, timeout: (1, "", "denied")  # noqa: E731
        with mock.patch(
            "src.api.update.install_status.fetch_remote_version_sync",
            return_value=None,
        ):
            payload = build_install_status_payload(
                registry=ReleaseChannelRegistry(),
                repo_path="/opt/meshpoint",
                runner=runner,
                use_sudo=False,
            )
        self.assertIsNone(payload["install_branch"])
        self.assertIsNone(payload["active_channel_id"])

    def test_payload_includes_branch_and_channel(self) -> None:
        runner = _FakeGitRunner(branch="feat/v0.7.8")
        with mock.patch(
            "src.api.update.install_status.fetch_remote_version_sync",
            return_value="0.7.3.1",
        ):
            with mock.patch(
                "src.api.update.install_status.__version__",
                "0.7.3.1",
            ):
                payload = build_install_status_payload(
                    registry=ReleaseChannelRegistry(),
                    repo_path="/opt/meshpoint",
                    runner=runner,
                    use_sudo=False,
                )
        self.assertEqual(payload["install_branch"], "feat/v0.7.8")
        self.assertEqual(payload["active_channel_id"], "custom")
        self.assertEqual(payload["remote_branch"], "feat/v0.7.8")
        self.assertFalse(payload["update_available"])

    def test_main_on_075_payload_keeps_picker_on_stable(self) -> None:
        runner = _FakeGitRunner(branch="main", sha="56d4f7c")
        with mock.patch(
            "src.api.update.install_status.fetch_remote_version_sync",
            return_value="0.7.5",
        ):
            with mock.patch(
                "src.api.update.install_status.__version__",
                "0.7.5",
            ):
                payload = build_install_status_payload(
                    registry=ReleaseChannelRegistry(),
                    repo_path="/opt/meshpoint",
                    runner=runner,
                    use_sudo=False,
                )
        self.assertEqual(payload["install_branch"], "main")
        self.assertEqual(payload["active_channel_id"], "stable")

    def test_sync_reports_commits_behind(self) -> None:
        runner = _FakeGitRunner(behind=12)
        with mock.patch(
            "src.api.update.install_status.fetch_remote_version_sync",
            return_value="0.7.4.0",
        ):
            with mock.patch(
                "src.api.update.install_status.__version__",
                "0.7.3.1",
            ):
                payload = build_install_status_payload(
                    registry=ReleaseChannelRegistry(),
                    repo_path="/opt/meshpoint",
                    runner=runner,
                    use_sudo=False,
                    sync_remote=True,
                    channel_id="rc-077",  # retired id, aliases to stable
                )
        self.assertEqual(payload["commits_behind"], 12)
        self.assertEqual(payload["commits_ahead"], 0)
        self.assertEqual(payload["compare_branch"], "main")
        self.assertTrue(payload["update_available"])
        self.assertIsNotNone(payload["checked_at"])
        self.assertTrue(
            any(
                _FakeGitRunner._strip_prefix(c)[:3] == ["git", "fetch", "origin"]
                for c in runner.calls
            ),
        )


class TestListBranchCommits(unittest.TestCase):
    """Latest-commits list shown on the Updates page (git log origin/<branch>)."""

    @staticmethod
    def _runner_returning(out: str, rc: int = 0):
        calls: list[list[str]] = []

        def runner(args, cwd, timeout):
            calls.append(list(args))
            return rc, out, ""

        runner.calls = calls
        return runner

    def test_parses_sha_date_and_subject(self) -> None:
        out = (
            "fee568e\t1751972400\tdocs: default yaml header\n"
            "50eed38\t1751968800\tfeat: updates page history\n"
        )
        runner = self._runner_returning(out)
        commits = list_branch_commits(
            "/opt/meshpoint", "origin/main", runner=runner, use_sudo=False,
        )
        self.assertEqual(len(commits), 2)
        self.assertEqual(commits[0]["sha"], "fee568e")
        self.assertEqual(commits[0]["subject"], "docs: default yaml header")
        self.assertEqual(commits[0]["committed_at"], "2025-07-08T11:00:00+00:00")
        self.assertIn("origin/main", runner.calls[0])

    def test_bad_timestamp_yields_none_date(self) -> None:
        runner = self._runner_returning("abc1234\tnot-a-ts\tfix: something\n")
        commits = list_branch_commits(
            "/opt/meshpoint", "origin/main", runner=runner, use_sudo=False,
        )
        self.assertEqual(commits[0]["sha"], "abc1234")
        self.assertIsNone(commits[0]["committed_at"])

    def test_limit_is_enforced(self) -> None:
        out = "".join(f"sha{i}\t1751972400\tsubject {i}\n" for i in range(9))
        runner = self._runner_returning(out)
        commits = list_branch_commits(
            "/opt/meshpoint", "origin/main",
            runner=runner, use_sudo=False, limit=5,
        )
        self.assertEqual(len(commits), 5)

    def test_git_failure_returns_empty(self) -> None:
        runner = self._runner_returning("", rc=128)
        self.assertEqual(
            list_branch_commits(
                "/opt/meshpoint", "origin/main", runner=runner, use_sudo=False,
            ),
            [],
        )

    def test_payload_includes_remote_commits(self) -> None:
        runner = _FakeGitRunner(branch="main")
        with mock.patch(
            "src.api.update.install_status.fetch_remote_version_sync",
            return_value=None,
        ):
            payload = build_install_status_payload(
                registry=ReleaseChannelRegistry(),
                repo_path="/opt/meshpoint",
                runner=runner,
                use_sudo=False,
            )
        # _FakeGitRunner answers no --format log call → empty but present.
        self.assertIn("remote_commits", payload)
        self.assertEqual(payload["remote_commits"], [])
        self.assertTrue(
            any(
                "origin/main" in c and "log" in c
                for c in (_FakeGitRunner._strip_prefix(c) for c in runner.calls)
            ),
        )


class TestRevisionCountFallback(unittest.TestCase):
    def test_rev_list_denied_uses_git_log(self) -> None:
        runner = _FakeGitRunner(behind=3, ahead=1)
        behind, ahead, _ = count_commits_behind_ahead(
            "/opt/meshpoint",
            "feat/v0.7.4",
            runner=runner,
            use_sudo=False,
        )
        self.assertEqual(behind, 3)
        self.assertEqual(ahead, 1)
        self.assertTrue(any("log" in c and "--oneline" in c for c in runner.calls))


class TestRollbackInInstallStatus(unittest.TestCase):
    def test_install_status_includes_persisted_rollback_sha(self) -> None:
        with mock.patch(
            "src.api.update.install_status.read_rollback_state",
            return_value={"pre_update_sha": "deadbeefcafebabe", "target_branch": "main"},
        ):
            with mock.patch(
                "src.api.update.install_status.fetch_remote_version_sync",
                return_value=None,
            ):
                payload = build_install_status_payload(
                    registry=ReleaseChannelRegistry(),
                    repo_path="/opt/meshpoint",
                    runner=_FakeGitRunner(),
                    use_sudo=False,
                )
        self.assertEqual(payload["rollback_pre_sha"], "deadbeefcafebabe")


class TestResolveCompareBranch(unittest.TestCase):
    def test_picker_overrides_install_branch(self) -> None:
        reg = ReleaseChannelRegistry()
        branch = resolve_compare_branch(
            reg,
            channel_id="stable",
            custom_branch=None,
            install_branch="feat/v0.7.4",
        )
        self.assertEqual(branch, "main")


if __name__ == "__main__":
    unittest.main()
