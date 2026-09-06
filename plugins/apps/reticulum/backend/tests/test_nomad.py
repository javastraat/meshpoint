"""Tests for the NomadNet fetcher's non-RNS paths.

On a machine without ``rns`` installed (the dev Mac), ``nomad.RNS`` is
``None`` and ``available()`` is ``False`` -- ``fetch_page`` returns an
error result instead of raising, which is what's covered here. The real
Link/Request round trip is integration-level (needs rnsd + a live
NomadNet node) and lives on the Pi.
"""

from __future__ import annotations

import asyncio
import unittest

from plugins.apps.reticulum.backend import nomad


@unittest.skipIf(nomad.RNS is not None, "rns installed -- covers only the not-available path")
class TestNomadWithoutRns(unittest.TestCase):
    def tearDown(self) -> None:
        nomad.reset()

    def test_available_is_false_without_rns(self) -> None:
        self.assertFalse(nomad.available())

    def test_fetch_page_returns_an_error_result_not_an_exception(self) -> None:
        result = asyncio.run(nomad.fetch_page("abcd1234", "/page/index.mu"))
        self.assertFalse(result.ok)
        self.assertIsNone(result.content)
        self.assertIn("Reticulum is not running", result.error)
        self.assertEqual(result.destination_hash, "abcd1234")
        self.assertEqual(result.path, "/page/index.mu")

    def test_reset_clears_the_link_cache(self) -> None:
        nomad._links["deadbeef"] = object()
        nomad.reset()
        self.assertEqual(nomad._links, {})


class TestNomadResultShape(unittest.TestCase):
    def test_defaults(self) -> None:
        r = nomad.NomadResult(ok=True, content="`F222`b heading")
        self.assertTrue(r.ok)
        self.assertEqual(r.content, "`F222`b heading")
        self.assertIsNone(r.error)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
