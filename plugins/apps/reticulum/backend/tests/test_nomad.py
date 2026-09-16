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

    def test_identify_link_returns_an_error_result_not_an_exception(self) -> None:
        ok, result = asyncio.run(nomad.identify_link("abcd1234", object()))
        self.assertFalse(ok)
        self.assertIn("Reticulum is not running", result)

    def test_reset_clears_fingerprints_too(self) -> None:
        nomad._fingerprints["deadbeef"] = "some-hash"
        nomad.reset()
        self.assertEqual(nomad._fingerprints, {})


class TestFingerprintMergesIntoFieldData(unittest.TestCase):
    """The `dest` merge in fetch_page() is plain dict logic, checkable
    without RNS -- monkeypatch `_request` to capture what it was handed."""

    def tearDown(self) -> None:
        nomad.reset()

    def test_no_fingerprint_leaves_field_data_untouched(self) -> None:
        seen = {}

        async def fake_request(dest_hash_hex, path, field_data):
            seen["field_data"] = field_data
            return "err", "stub"

        original = nomad._request
        nomad._request = fake_request
        try:
            asyncio.run(nomad.fetch_page("deadbeef", "/page/index.mu", {"field_x": "1"}))
        finally:
            nomad._request = original
        self.assertEqual(seen["field_data"], {"field_x": "1"})

    def test_cached_fingerprint_merges_in_as_dest(self) -> None:
        nomad._fingerprints["deadbeef"] = "aabbcc"
        seen = {}

        async def fake_request(dest_hash_hex, path, field_data):
            seen["field_data"] = field_data
            return "err", "stub"

        original = nomad._request
        nomad._request = fake_request
        try:
            asyncio.run(nomad.fetch_page("deadbeef", "/page/index.mu", {"field_x": "1"}))
        finally:
            nomad._request = original
        self.assertEqual(seen["field_data"], {"field_x": "1", "dest": "aabbcc"})

    def test_cached_fingerprint_merges_in_even_with_no_other_field_data(self) -> None:
        nomad._fingerprints["deadbeef"] = "aabbcc"
        seen = {}

        async def fake_request(dest_hash_hex, path, field_data):
            seen["field_data"] = field_data
            return "err", "stub"

        original = nomad._request
        nomad._request = fake_request
        try:
            asyncio.run(nomad.fetch_page("deadbeef", "/page/index.mu"))
        finally:
            nomad._request = original
        self.assertEqual(seen["field_data"], {"dest": "aabbcc"})


class TestNomadResultShape(unittest.TestCase):
    def test_defaults(self) -> None:
        r = nomad.NomadResult(ok=True, content="`F222`b heading")
        self.assertTrue(r.ok)
        self.assertEqual(r.content, "`F222`b heading")
        self.assertIsNone(r.error)


class TestNomadTimeouts(unittest.TestCase):
    def tearDown(self) -> None:
        nomad.set_timeouts(None)

    def test_none_restores_defaults(self) -> None:
        nomad.set_timeouts(None)
        self.assertEqual(nomad._path_lookup_timeout_s, 20)
        self.assertEqual(nomad._request_timeout_s, 30)

    def test_scales_from_one_knob(self) -> None:
        nomad.set_timeouts(40)
        self.assertEqual(nomad._link_timeout_s, 40)
        self.assertEqual(nomad._request_timeout_s, 60)  # 1.5x

    def test_floor(self) -> None:
        nomad.set_timeouts(1)
        self.assertGreaterEqual(nomad._link_timeout_s, 5)


class TestExtractFile(unittest.TestCase):
    def test_bytes_plus_name_metadata_list(self) -> None:
        name, data = nomad._extract_file([b"payload", {"name": b"/x/report.pdf"}], None)
        self.assertEqual(name, "report.pdf")
        self.assertEqual(data, b"payload")

    def test_bare_bytes(self) -> None:
        name, data = nomad._extract_file(b"raw", None)
        self.assertEqual(data, b"raw")
        self.assertEqual(name, "downloaded_file")

    def test_unsupported_shape_raises(self) -> None:
        with self.assertRaises(ValueError):
            nomad._extract_file(42, None)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
