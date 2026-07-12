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


class EnrichConfigPayloadHardwareTest(unittest.TestCase):
    def test_defaults_are_enriched(self):
        cfg = AppConfig()
        enriched = enrich_config_payload(cfg, {})
        self.assertEqual(enriched["hardware"]["fan"], {
            "enabled": False, "gpio_pin": 13, "min_temp_c": 45.0,
            "max_temp_c": 65.0, "min_duty": 0.35, "hysteresis_c": 5.0,
            "poll_interval_s": 10.0,
        })
        self.assertEqual(enriched["hardware"]["led"], {
            "enabled": False, "gpio_pin": 22, "activity_blink": True,
        })
        self.assertEqual(enriched["hardware"]["button"], {
            "enabled": False, "gpio_pin": 27, "hold_time_s": 3.0,
            "advert_cooldown_s": 30.0,
        })

    def test_custom_values_are_enriched(self):
        cfg = AppConfig()
        cfg.fan.enabled = True
        cfg.fan.min_temp_c = 50.0
        cfg.led.activity_blink = False
        cfg.button.hold_time_s = 5.0
        enriched = enrich_config_payload(cfg, {})
        self.assertTrue(enriched["hardware"]["fan"]["enabled"])
        self.assertEqual(enriched["hardware"]["fan"]["min_temp_c"], 50.0)
        self.assertFalse(enriched["hardware"]["led"]["activity_blink"])
        self.assertEqual(enriched["hardware"]["button"]["hold_time_s"], 5.0)


if __name__ == "__main__":
    unittest.main()
