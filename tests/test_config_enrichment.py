"""Tests for enrich_config_payload's capture.serial enrichment.

No fastapi dependency here (config_enrichment.py only imports
src.config), so this runs on a bare Mac python3 unlike most of the
other api/routes-adjacent tests in this suite.
"""

from __future__ import annotations

import unittest

from src.api.routes.config_enrichment import enrich_config_payload
from src.config import AppConfig, SerialDeviceConfig


class EnrichConfigPayloadSerialTest(unittest.TestCase):
    def test_empty_serial_list_by_default(self):
        cfg = AppConfig()
        enriched = enrich_config_payload(cfg, {})
        self.assertEqual(enriched["capture"]["serial"], [])

    def test_serial_devices_are_enriched(self):
        cfg = AppConfig()
        cfg.capture.serial = [
            SerialDeviceConfig(serial_port="/dev/ttyUSB0", serial_baud=115200, label="433"),
            SerialDeviceConfig(serial_port="/dev/ttyUSB1", serial_baud=57600, label="868"),
        ]
        enriched = enrich_config_payload(cfg, {})
        serial = enriched["capture"]["serial"]
        self.assertEqual(len(serial), 2)
        self.assertEqual(serial[0], {
            "serial_port": "/dev/ttyUSB0", "serial_baud": 115200, "label": "433",
        })
        self.assertEqual(serial[1]["label"], "868")

    def test_does_not_collide_with_meshcore_usb_enrichment(self):
        cfg = AppConfig()
        cfg.capture.serial = [SerialDeviceConfig(label="433")]
        enriched = enrich_config_payload(cfg, {})
        self.assertIn("meshcore_usb", enriched["capture"])
        self.assertIn("serial", enriched["capture"])
        self.assertIsInstance(enriched["capture"]["meshcore_usb"], list)


if __name__ == "__main__":
    unittest.main()
