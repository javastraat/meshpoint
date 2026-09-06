"""PipelineCoordinator._setup_channel_keys handles LoRaWAN device config
gracefully: the shipped placeholder is skipped silently, a genuinely
malformed real device gets one warning line (not a traceback), and a
config with no usable devices says so plainly.

Regression for the "YOUR_DEVICE_EUI_HEX dumps a traceback every boot" report.
The coordinator import chain pulls Crypto / aiosqlite, so like
tests/test_coordinator_location.py this runs on CI / the Pi, not the dev Mac.
"""

from __future__ import annotations

import unittest

try:
    from src.config import AppConfig
    from src.coordinator import PipelineCoordinator, _is_lorawan_placeholder
    _HAS_DEPS = True
except ModuleNotFoundError:
    _HAS_DEPS = False


@unittest.skipUnless(_HAS_DEPS, "coordinator import chain (Crypto/aiosqlite) -- CI/Pi only")
class TestIsLoRaWANPlaceholder(unittest.TestCase):
    def test_shipped_placeholder_detected(self):
        self.assertTrue(_is_lorawan_placeholder(
            "YOUR_DEVICE_EUI_HEX",
            {"app_key": "YOUR_APP_KEY_HEX", "nwk_key": "YOUR_NWK_KEY_HEX"},
        ))

    def test_real_device_is_not_a_placeholder(self):
        self.assertFalse(_is_lorawan_placeholder(
            "70:B3:D5:7E:D0:07:8B:FD",
            {"app_key": "10" * 16, "nwk_key": "20" * 16},
        ))

    def test_partial_placeholder_still_detected(self):
        # a user replaced the EUI but not the keys
        self.assertTrue(_is_lorawan_placeholder(
            "70:B3:D5:7E:D0:07:8B:FD",
            {"app_key": "YOUR_APP_KEY_HEX", "nwk_key": "20" * 16},
        ))


@unittest.skipUnless(_HAS_DEPS, "coordinator import chain (Crypto/aiosqlite) -- CI/Pi only")
class TestSetupChannelKeysLoRaWAN(unittest.TestCase):
    def _coord(self, devices: dict) -> "PipelineCoordinator":
        cfg = AppConfig()
        cfg.lorawan.devices = devices
        return PipelineCoordinator(cfg)

    def test_placeholder_device_skipped_silently_with_a_no_keys_note(self):
        coord = self._coord({
            "YOUR_DEVICE_EUI_HEX": {
                "app_key": "YOUR_APP_KEY_HEX", "nwk_key": "YOUR_NWK_KEY_HEX",
            },
        })
        with self.assertLogs("src.coordinator", level="INFO") as cm:
            coord._setup_channel_keys()
        joined = "\n".join(cm.output)
        self.assertNotIn("WARNING", joined)
        self.assertNotIn("ERROR", joined)
        self.assertNotIn("Traceback", joined)
        self.assertIn("no device keys configured", joined)

    def test_malformed_real_device_logs_one_warning_not_a_traceback(self):
        coord = self._coord({
            "70:B3:D5:7E:D0:07:8B:FD": {"app_key": "nothex!!", "nwk_key": "20" * 16},
        })
        with self.assertLogs("src.coordinator", level="WARNING") as cm:
            coord._setup_channel_keys()
        joined = "\n".join(cm.output)
        self.assertIn("skipping device 70:B3:D5:7E:D0:07:8B:FD", joined)
        self.assertNotIn("Traceback", joined)

    def test_valid_device_loads(self):
        coord = self._coord({
            "70:B3:D5:7E:D0:07:8B:FD": {"app_key": "10" * 16, "nwk_key": "20" * 16},
        })
        coord._setup_channel_keys()
        self.assertTrue(
            coord._lorawan_keystore.has_device("70:B3:D5:7E:D0:07:8B:FD")
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
