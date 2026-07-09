"""Tests for _serial_status_entry in api/routes/config_routes.py.

The topbar badge and the packet feed must never disagree about a
serial device's frequency, so this reuses the exact same
channel_frequency.resolve_frequency_mhz() call serial_source.py uses
to stamp captured packets. Needs fastapi (config_routes.py imports it
at module level), so CI-only like the other api/server.py-adjacent
tests.
"""

from __future__ import annotations

import unittest

from fastapi import FastAPI  # noqa: F401 -- import-time dependency probe

from src.api.routes.config_routes import _serial_status_entry


class _FakeSerialSource:
    def __init__(self, name, connected, radio_info):
        self.name = name
        self.connected = connected
        self._radio_info = radio_info

    def get_radio_info(self):
        return dict(self._radio_info)


class SerialStatusEntryTest(unittest.TestCase):
    def test_connected_device_with_default_channel_includes_frequency(self):
        src = _FakeSerialSource(
            "serial_433", True,
            {"region": "EU_433", "channel_num": 0, "short_name": "EMC3",
             "long_name": "Meshpoint433", "modem_preset": "LONG_FAST",
             "spreading_factor": 11, "bandwidth_khz": 250, "coding_rate": "4/5"},
        )

        entry = _serial_status_entry(src)

        self.assertEqual(entry["name"], "serial_433")
        self.assertTrue(entry["connected"])
        self.assertEqual(entry["frequency_mhz"], 433.875)
        self.assertEqual(entry["region"], "EU_433")
        self.assertEqual(entry["short_name"], "EMC3")

    def test_custom_channel_num_yields_unknown_frequency_not_a_guess(self):
        src = _FakeSerialSource(
            "serial_868", True,
            {"region": "EU_868", "channel_num": 5},
        )
        entry = _serial_status_entry(src)
        self.assertEqual(entry["frequency_mhz"], 0.0)

    def test_disconnected_source_with_no_radio_info_yet(self):
        src = _FakeSerialSource("serial", False, {})
        entry = _serial_status_entry(src)
        self.assertFalse(entry["connected"])
        self.assertEqual(entry["frequency_mhz"], 0.0)

    def test_source_without_get_radio_info_does_not_crash(self):
        class _Bare:
            name = "serial"
            connected = False

        entry = _serial_status_entry(_Bare())
        self.assertEqual(entry["name"], "serial")
        self.assertEqual(entry["frequency_mhz"], 0.0)


if __name__ == "__main__":
    unittest.main()
