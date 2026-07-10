"""Startup banner per-source frequency lines (Mac-runnable)."""

import io
import types
import unittest
from contextlib import redirect_stdout

from src.config import AppConfig
from src.log_format import (
    _describe_concentrator,
    _describe_meshcore_source,
    _describe_serial_source,
    print_banner,
)


def _eu868_config():
    cfg = AppConfig()
    cfg.radio.region = "EU_868"
    cfg.radio.frequency_mhz = 869.525
    return cfg


class _Src:
    def __init__(self, name, **attrs):
        self.name = name
        for k, v in attrs.items():
            setattr(self, k, v)


class BannerSourceLinesTest(unittest.TestCase):
    def test_concentrator_summary_shows_both_protocols(self):
        desc = _describe_concentrator(_eu868_config())
        self.assertIn("LoRaWAN x5 867.9-868.7 MHz", desc)
        self.assertIn("Meshtastic 869.525 MHz SF11", desc)
        self.assertIn("(EU_868)", desc)

    def test_meshcore_summary_from_self_info(self):
        src = _Src("meshcore_usb_868", _meshcore=types.SimpleNamespace(
            self_info={"radio_freq": 869.618, "radio_sf": 8},
        ))
        self.assertEqual(
            _describe_meshcore_source(src), "MeshCore 869.618 MHz SF8",
        )

    def test_meshcore_pending_before_handshake(self):
        src = _Src("meshcore_usb_433", _meshcore=None)
        self.assertEqual(
            _describe_meshcore_source(src), "MeshCore (radio info pending)",
        )

    def test_serial_summary_resolves_eu433_frequency(self):
        src = _Src("serial_433", _radio_info={
            "region": "EU_433", "channel_num": 0, "bandwidth_khz": 250.0,
            "modem_preset": "LONG_FAST", "use_preset": True,
            "spreading_factor": 11,
        })
        self.assertEqual(
            _describe_serial_source(src),
            "Meshtastic 433.875 MHz SF11 (EU_433)",
        )

    def test_serial_pending_before_handshake(self):
        src = _Src("serial_433", _radio_info={})
        self.assertEqual(
            _describe_serial_source(src), "Meshtastic (radio info pending)",
        )

    def test_banner_prints_one_line_per_source(self):
        cfg = _eu868_config()
        sources = [
            _Src("concentrator"),
            _Src("meshcore_usb_868", _meshcore=types.SimpleNamespace(
                self_info={"radio_freq": 869.618, "radio_sf": 8},
            )),
        ]
        buf = io.StringIO()
        with redirect_stdout(buf):
            print_banner(cfg, sources=sources)
        out = buf.getvalue()
        self.assertIn("concentrator", out)
        self.assertIn("meshcore_usb_868  MeshCore 869.618 MHz SF8", out)
        self.assertNotIn("Frequency", out)  # combined line replaced

    def test_banner_without_sources_keeps_legacy_lines(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            print_banner(_eu868_config())
        out = buf.getvalue()
        self.assertIn("Frequency", out)
        self.assertIn("Source", out)


if __name__ == "__main__":
    unittest.main()
