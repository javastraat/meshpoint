"""src/plugins/sources.py -- GitHub URL parsing + repo.json catalog
validation. Pure, no network (fetch_catalog's HTTP is not exercised here)."""

from __future__ import annotations

import json
import unittest

from unittest import mock

from src.plugins import sources as _sources_mod
from src.plugins.sources import (
    PluginSourceError,
    catalog_raw_url,
    commits_api_url,
    normalise_ref,
    parse_catalog,
    parse_github_url,
    resolve_commit,
    tarball_url,
)


class TestUrlParsing(unittest.TestCase):
    def test_https_forms(self) -> None:
        for url in (
            "https://github.com/javastraat/meshpoint-plugins",
            "https://github.com/javastraat/meshpoint-plugins.git",
            "https://github.com/javastraat/meshpoint-plugins/",
            "http://github.com/javastraat/meshpoint-plugins",
        ):
            self.assertEqual(parse_github_url(url), ("javastraat", "meshpoint-plugins"))

    def test_ssh_form(self) -> None:
        self.assertEqual(
            parse_github_url("git@github.com:javastraat/meshpoint-plugins.git"),
            ("javastraat", "meshpoint-plugins"),
        )

    def test_rejects_non_github(self) -> None:
        for bad in (
            "https://gitlab.com/x/y", "not a url", "",
            "https://github.com/onlyowner",
            "https://github.com/a/b/c",
        ):
            with self.assertRaises(PluginSourceError):
                parse_github_url(bad)

    def test_ref_normalisation(self) -> None:
        self.assertEqual(normalise_ref(""), "main")
        self.assertEqual(normalise_ref(None), "main")
        self.assertEqual(normalise_ref("v1.2.0"), "v1.2.0")
        self.assertEqual(normalise_ref("a1b2c3d"), "a1b2c3d")
        self.assertEqual(normalise_ref("feature/thing"), "feature/thing")  # slash ok
        for bad in (
            "bad ref with spaces",
            "/etc/passwd",
            "trailing/",
            "../../other-repo/main",   # would repoint the raw.githubusercontent fetch
            "main/../..",
            "..",
        ):
            with self.assertRaises(PluginSourceError):
                normalise_ref(bad)

    def test_url_builders(self) -> None:
        self.assertEqual(
            catalog_raw_url("o", "r", "main"),
            "https://raw.githubusercontent.com/o/r/main/repo.json",
        )
        self.assertEqual(
            tarball_url("o", "r", "v1"),
            "https://api.github.com/repos/o/r/tarball/v1",
        )


class TestResolveCommit(unittest.TestCase):
    # The *list*-commits endpoint's shape (an array), not the single-commit
    # endpoint's -- see commits_api_url()'s docstring for why: the
    # single-commit endpoint embeds a full diff per file and blows past
    # the fetch size cap on anything but a tiny commit.
    _COMMIT_JSON = json.dumps([{
        "sha": "9abcdef012345678901234567890123456789abc",
        "html_url": "https://github.com/o/r/commit/9abcdef",
        "commit": {
            "message": "fix: the thing\n\nlonger body",
            "author": {"date": "2026-09-09T12:00:00Z"},
        },
    }]).encode()

    def test_parses_github_commit_json(self) -> None:
        with mock.patch.object(_sources_mod, "_http_get", return_value=self._COMMIT_JSON):
            out = resolve_commit("https://github.com/o/r", "main")
        self.assertEqual(out["sha"], "9abcdef012345678901234567890123456789abc")
        self.assertEqual(out["short_sha"], "9abcdef")
        self.assertEqual(out["message"], "fix: the thing")   # first line only
        self.assertEqual(out["committed_at"], "2026-09-09T12:00:00Z")

    def test_no_commit_is_an_error(self) -> None:
        with mock.patch.object(_sources_mod, "_http_get", return_value=b'{"message":"Not Found"}'):
            with self.assertRaises(PluginSourceError):
                resolve_commit("https://github.com/o/r", "nope")

    def test_empty_list_is_an_error(self) -> None:
        # A ref GitHub genuinely knows nothing about, e.g. a typo'd branch.
        with mock.patch.object(_sources_mod, "_http_get", return_value=b"[]"):
            with self.assertRaises(PluginSourceError):
                resolve_commit("https://github.com/o/r", "nope")

    def test_rejects_non_github(self) -> None:
        with self.assertRaises(PluginSourceError):
            resolve_commit("https://gitlab.com/o/r", "main")

    def test_uses_the_list_endpoint_not_the_single_commit_one(self) -> None:
        # Regression guard for the real bug: /commits/<ref> (singular)
        # embeds a full diff per changed file and blew past the fetch size
        # cap on an ordinary multi-file commit. Must stay the list form
        # (?sha=<ref>&per_page=1), which returns the same fields without it.
        url = commits_api_url("javastraat", "meshpoint-plugins", "main")
        self.assertEqual(
            url,
            "https://api.github.com/repos/javastraat/meshpoint-plugins/commits?sha=main&per_page=1",
        )
        self.assertNotIn("/commits/main", url)


_GOOD = {
    "meshpoint_repo": 1,
    "name": "test repo",
    "plugins": [
        {
            "id": "hello-world-github", "kind": "app",
            "path": "apps/hello-world-github", "version": "0.1.0",
            "meshpoint_api": 1, "provides": ["sidebar"],
            "description": "d", "author": "a",
        },
    ],
    "themes": [
        {"id": "midnight", "kind": "theme", "path": "themes/midnight",
         "version": "1.0.0"},
    ],
}


class TestCatalog(unittest.TestCase):
    def _parse(self, doc) -> dict:
        return parse_catalog(json.dumps(doc).encode("utf-8"))

    def test_valid(self) -> None:
        cat = self._parse(_GOOD)
        self.assertEqual(cat["name"], "test repo")
        self.assertEqual(cat["plugins"][0]["id"], "hello-world-github")
        self.assertTrue(cat["plugins"][0]["compatible"])
        self.assertEqual(cat["themes"][0]["id"], "midnight")

    def test_hook_host_and_requires_survive_parsing(self) -> None:
        # Both are optional catalog-display hints; _entry() must not
        # silently drop either one (requires was dropped for a while --
        # present in repo.json, stripped on the way to the browser, so the
        # UI never had the data it needed to show a "Requires: x" note or
        # nest the row under its host).
        doc = json.loads(json.dumps(_GOOD))
        doc["plugins"][0]["hook_host"] = "some-host"
        doc["plugins"][0]["requires"] = "some-other-plugin"
        cat = self._parse(doc)
        self.assertEqual(cat["plugins"][0]["hook_host"], "some-host")
        self.assertEqual(cat["plugins"][0]["requires"], "some-other-plugin")

    def test_hook_host_and_requires_absent_when_not_given(self) -> None:
        cat = self._parse(_GOOD)
        self.assertNotIn("hook_host", cat["plugins"][0])
        self.assertNotIn("requires", cat["plugins"][0])

    def test_invalid_requires_is_dropped_not_rejected(self) -> None:
        # Same tolerance as hook_host: a malformed value just means no
        # grouping hint, not a rejected catalog.
        doc = json.loads(json.dumps(_GOOD))
        doc["plugins"][0]["requires"] = "Not A Slug"
        cat = self._parse(doc)
        self.assertNotIn("requires", cat["plugins"][0])

    def test_wrong_repo_version(self) -> None:
        with self.assertRaises(PluginSourceError):
            self._parse({**_GOOD, "meshpoint_repo": 2})

    def test_not_json(self) -> None:
        with self.assertRaises(PluginSourceError):
            parse_catalog(b"{ not json")

    def test_bad_path_rejected(self) -> None:
        for bad_path in ("apps/other", "../apps/x", "apps/hello/deep", "themes/x"):
            doc = json.loads(json.dumps(_GOOD))
            doc["plugins"][0]["path"] = bad_path
            with self.assertRaises(PluginSourceError):
                self._parse(doc)

    def test_bad_id_rejected(self) -> None:
        doc = json.loads(json.dumps(_GOOD))
        doc["plugins"][0]["id"] = "Not A Slug"
        with self.assertRaises(PluginSourceError):
            self._parse(doc)

    def test_incompatible_api_flagged_not_rejected(self) -> None:
        doc = json.loads(json.dumps(_GOOD))
        doc["plugins"][0]["meshpoint_api"] = 99
        cat = self._parse(doc)
        self.assertFalse(cat["plugins"][0]["compatible"])

    def test_duplicate_id_across_plugins_and_themes(self) -> None:
        doc = json.loads(json.dumps(_GOOD))
        doc["themes"][0]["id"] = "hello-world-github"
        doc["themes"][0]["path"] = "themes/hello-world-github"
        with self.assertRaises(PluginSourceError):
            self._parse(doc)

    def test_empty_lists_ok(self) -> None:
        cat = self._parse({"meshpoint_repo": 1, "name": "x"})
        self.assertEqual(cat["plugins"], [])
        self.assertEqual(cat["themes"], [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
