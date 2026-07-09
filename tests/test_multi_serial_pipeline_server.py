"""Tests for the multi-stick Meshtastic USB wiring in api/server.py.

Same coverage as test_multi_serial_pipeline.py's main.py tests, but for
the dashboard's ``_add_serial_source``. Needs fastapi (server.py imports
it at module level), so this module only runs in CI, not on the Mac dev
checkout -- same convention as test_update_routes.py.
"""

from __future__ import annotations

import unittest

from fastapi import FastAPI  # noqa: F401 -- import-time dependency probe

from src.api.server import _add_serial_source
from src.config import AppConfig, SerialDeviceConfig


class _FakeCaptureCoordinator:
    def __init__(self) -> None:
        self.added = []

    def add_source(self, source) -> None:
        self.added.append(source)


class _FakeCoordinator:
    def __init__(self) -> None:
        self.capture_coordinator = _FakeCaptureCoordinator()


class ServerAddSerialSourceTest(unittest.TestCase):
    def test_legacy_scalar_config_adds_one_unlabelled_source(self):
        config = AppConfig()
        config.capture.serial_port = "/dev/ttyACM2"
        coordinator = _FakeCoordinator()

        _add_serial_source(coordinator, config)

        added = coordinator.capture_coordinator.added
        self.assertEqual(len(added), 1)
        self.assertEqual(added[0]._port, "/dev/ttyACM2")
        self.assertEqual(added[0].name, "serial")

    def test_multi_device_list_adds_one_source_per_device(self):
        config = AppConfig()
        config.capture.serial = [
            SerialDeviceConfig(serial_port="/dev/ttyUSB0", label="433"),
            SerialDeviceConfig(serial_port="/dev/ttyUSB1", label="868"),
        ]
        coordinator = _FakeCoordinator()

        _add_serial_source(coordinator, config)

        added = coordinator.capture_coordinator.added
        self.assertEqual(len(added), 2)
        self.assertEqual([s.name for s in added], ["serial_433", "serial_868"])


if __name__ == "__main__":
    unittest.main()
