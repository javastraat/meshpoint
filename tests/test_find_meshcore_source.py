"""Tests for _find_meshcore_source in api/server.py.

Regression coverage for a real bug hit live (2026-07-09): the lookup
used exact ``src.name == "meshcore_usb"``, which broke the instant a
MeshCore companion got a label (name becomes "meshcore_usb_<label>"),
silently disabling MeshCore TX/advert/status with no crash and no log
error -- just a topbar stuck on "No companion". Needs fastapi
(server.py imports it at module level), so CI-only like
test_multi_serial_pipeline_server.py.
"""

from __future__ import annotations

import unittest

from fastapi import FastAPI  # noqa: F401 -- import-time dependency probe

from src.api.server import _find_meshcore_source


class _FakeSource:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeCaptureCoordinator:
    def __init__(self, sources) -> None:
        self._sources = sources


class _FakeCoordinator:
    def __init__(self, sources) -> None:
        self.capture_coordinator = _FakeCaptureCoordinator(sources)


class FindMeshcoreSourceTest(unittest.TestCase):
    def test_finds_unlabelled_source(self):
        coord = _FakeCoordinator([_FakeSource("concentrator"), _FakeSource("meshcore_usb")])
        found = _find_meshcore_source(coord)
        self.assertIsNotNone(found)
        self.assertEqual(found.name, "meshcore_usb")

    def test_finds_labelled_source(self):
        coord = _FakeCoordinator([
            _FakeSource("concentrator"),
            _FakeSource("meshcore_usb_868"),
            _FakeSource("serial_433"),
        ])
        found = _find_meshcore_source(coord)
        self.assertIsNotNone(found)
        self.assertEqual(found.name, "meshcore_usb_868")

    def test_picks_first_of_multiple_labelled_companions(self):
        coord = _FakeCoordinator([
            _FakeSource("meshcore_usb_868"),
            _FakeSource("meshcore_usb_433"),
        ])
        found = _find_meshcore_source(coord)
        self.assertEqual(found.name, "meshcore_usb_868")

    def test_returns_none_when_absent(self):
        coord = _FakeCoordinator([_FakeSource("concentrator"), _FakeSource("serial_433")])
        self.assertIsNone(_find_meshcore_source(coord))


if __name__ == "__main__":
    unittest.main()
