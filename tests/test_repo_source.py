"""Tests for deriving the self-update GitHub repo from the origin remote."""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from src.remote import repo_source


def _write_origin(tmpdir: str, url: str | None) -> None:
    os.makedirs(os.path.join(tmpdir, ".git"), exist_ok=True)
    with open(os.path.join(tmpdir, ".git", "config"), "w") as f:
        f.write('[core]\n\trepositoryformatversion = 0\n')
        if url is not None:
            f.write(f'[remote "origin"]\n\turl = {url}\n')


class ResolveOwnerRepoTest(unittest.TestCase):
    def setUp(self) -> None:
        repo_source._cache = None
        self._tmpdir = tempfile.mkdtemp()
        self._env_patch = mock.patch.dict(
            os.environ, {"MESHPOINT_DIR": self._tmpdir}
        )
        self._env_patch.start()
        self.addCleanup(self._env_patch.stop)
        self.addCleanup(self._reset_cache)

    def _reset_cache(self) -> None:
        repo_source._cache = None

    def test_https_origin_resolves_fork(self) -> None:
        _write_origin(self._tmpdir, "https://github.com/javastraat/meshpoint.git")
        self.assertEqual(repo_source.resolve_owner_repo(), "javastraat/meshpoint")

    def test_https_origin_without_dot_git_suffix(self) -> None:
        _write_origin(self._tmpdir, "https://github.com/javastraat/meshpoint")
        self.assertEqual(repo_source.resolve_owner_repo(), "javastraat/meshpoint")

    def test_ssh_origin_resolves_fork(self) -> None:
        _write_origin(self._tmpdir, "git@github.com:javastraat/meshpoint.git")
        self.assertEqual(repo_source.resolve_owner_repo(), "javastraat/meshpoint")

    def test_non_github_host_falls_back_to_upstream(self) -> None:
        _write_origin(self._tmpdir, "https://gitlab.com/someone/meshpoint.git")
        self.assertEqual(repo_source.resolve_owner_repo(), repo_source.UPSTREAM_OWNER_REPO)

    def test_missing_origin_falls_back_to_upstream(self) -> None:
        _write_origin(self._tmpdir, None)
        self.assertEqual(repo_source.resolve_owner_repo(), repo_source.UPSTREAM_OWNER_REPO)

    def test_missing_git_dir_falls_back_to_upstream(self) -> None:
        # tmpdir exists but has no .git subdirectory at all.
        self.assertEqual(repo_source.resolve_owner_repo(), repo_source.UPSTREAM_OWNER_REPO)

    def test_result_is_cached(self) -> None:
        _write_origin(self._tmpdir, "https://github.com/javastraat/meshpoint.git")
        first = repo_source.resolve_owner_repo()
        _write_origin(self._tmpdir, "https://github.com/someone-else/meshpoint.git")
        second = repo_source.resolve_owner_repo()
        self.assertEqual(first, second)


class GithubRawUrlTest(unittest.TestCase):
    def setUp(self) -> None:
        repo_source._cache = None
        self.addCleanup(self._reset_cache)

    def _reset_cache(self) -> None:
        repo_source._cache = None

    def test_builds_raw_url_from_resolved_owner_repo(self) -> None:
        with mock.patch.object(
            repo_source, "resolve_owner_repo", return_value="acme/fork"
        ):
            url = repo_source.github_raw_url("main", "src/version.py")
        self.assertEqual(
            url, "https://raw.githubusercontent.com/acme/fork/main/src/version.py"
        )


if __name__ == "__main__":
    unittest.main()
