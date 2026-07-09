"""Tests for the multi-stick Meshtastic USB wiring in main.py.

``_add_serial_source`` must add exactly one SerialCaptureSource per
configured device: the legacy single scalar pair (serial_port/serial_baud)
when ``capture.serial`` is empty, or one per entry in that list when set
(T5 -- multiple Meshtastic USB sticks). See test_multi_serial_pipeline_server.py
for the equivalent server.py coverage (needs fastapi, CI-only).

NOTE: src.main pulls in PipelineCoordinator -> ... -> pycryptodome/aiosqlite,
so like test_meshcore_usb.py and test_update_routes.py this module runs in
CI (full Pi-equivalent deps) but not on a bare Mac dev checkout.
"""

from __future__ import annotations

import unittest

from src.capture.serial_source import SerialCaptureSource
from src.config import AppConfig, SerialDeviceConfig
from src.main import _add_serial_source


class _FakeCaptureCoordinator:
    def __init__(self) -> None:
        self.added: list[SerialCaptureSource] = []

    def add_source(self, source) -> None:
        self.added.append(source)


class _FakeCoordinator:
    def __init__(self) -> None:
        self.capture_coordinator = _FakeCaptureCoordinator()


class MainAddSerialSourceTest(unittest.TestCase):
    def test_legacy_scalar_config_adds_one_unlabelled_source(self):
        config = AppConfig()
        config.capture.serial_port = "/dev/ttyUSB0"
        config.capture.serial_baud = 115200
        coordinator = _FakeCoordinator()

        _add_serial_source(coordinator, config)

        added = coordinator.capture_coordinator.added
        self.assertEqual(len(added), 1)
        self.assertEqual(added[0]._port, "/dev/ttyUSB0")
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
        self.assertEqual(added[0]._port, "/dev/ttyUSB0")
        self.assertEqual(added[1]._port, "/dev/ttyUSB1")


if __name__ == "__main__":
    unittest.main()
