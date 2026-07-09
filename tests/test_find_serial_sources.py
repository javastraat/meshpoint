"""Tests for _find_serial_sources in api/server.py.

Unlike MeshCore's single TX-bound "primary" companion, every Meshtastic
USB serial device is a passive capture-only source, so the topbar
needs the full list, in configured order -- not just the first match.
Needs fastapi (server.py imports it at module level), so CI-only like
test_multi_serial_pipeline_server.py / test_find_meshcore_source.py.
"""

from __future__ import annotations

import unittest

from fastapi import FastAPI  # noqa: F401 -- import-time dependency probe

from src.api.server import _find_serial_sources


class _FakeSource:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeCaptureCoordinator:
    def __init__(self, sources) -> None:
        self._sources = sources


class _FakeCoordinator:
    def __init__(self, sources) -> None:
        self.capture_coordinator = _FakeCaptureCoordinator(sources)


class FindSerialSourcesTest(unittest.TestCase):
    def test_finds_unlabelled_source(self):
        coord = _FakeCoordinator([_FakeSource("concentrator"), _FakeSource("serial")])
        found = _find_serial_sources(coord)
        self.assertEqual([s.name for s in found], ["serial"])

    def test_finds_all_labelled_devices_in_order(self):
        coord = _FakeCoordinator([
            _FakeSource("concentrator"),
            _FakeSource("meshcore_usb_868"),
            _FakeSource("serial_433"),
            _FakeSource("serial_868"),
        ])
        found = _find_serial_sources(coord)
        self.assertEqual([s.name for s in found], ["serial_433", "serial_868"])

    def test_returns_empty_list_when_absent(self):
        coord = _FakeCoordinator([_FakeSource("concentrator"), _FakeSource("meshcore_usb")])
        self.assertEqual(_find_serial_sources(coord), [])


if __name__ == "__main__":
    unittest.main()
