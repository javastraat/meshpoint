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
        # x6 867.9-869.5, not x5 867.9-868.7 -- v0.8.1 added ch5 (869.525
        # MHz multi-SF) for LoRaWAN Join-Accept/RX2 capture, see project
        # memory ("LoRaWAN key store + payload decrypt").
        desc = _describe_concentrator(_eu868_config())
        self.assertIn("LoRaWAN x6 867.9-869.5 MHz", desc)
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

    def test_dashboard_line_is_http_when_tls_disabled(self) -> None:
        cfg = _eu868_config()
        cfg.dashboard.tls_enabled = False
        buf = io.StringIO()
        with redirect_stdout(buf):
            print_banner(cfg)
        self.assertIn("Dashboard", buf.getvalue())
        self.assertIn("http://", buf.getvalue())
        self.assertNotIn("https://", buf.getvalue())

    def test_dashboard_line_is_https_when_tls_enabled(self) -> None:
        # Confirmed live 2026-09-08: with dashboard.tls_enabled on, uvicorn
        # itself logs "Running on https://..." but this banner line still
        # said "http://" -- it hardcoded the scheme instead of reading
        # dashboard.tls_enabled.
        cfg = _eu868_config()
        cfg.dashboard.tls_enabled = True
        buf = io.StringIO()
        with redirect_stdout(buf):
            print_banner(cfg)
        out = buf.getvalue()
        self.assertIn("Dashboard", out)
        self.assertIn("https://", out)

    def test_dashboard_line_shows_tls_port_not_plain_port_when_enabled(self) -> None:
        # dashboard.port becomes the redirect-only listener once TLS is
        # on (src/serve.py) -- the banner must point at tls_port, the
        # port the real dashboard is actually reachable on.
        cfg = _eu868_config()
        cfg.dashboard.tls_enabled = True
        cfg.dashboard.port = 8080
        cfg.dashboard.tls_port = 8443
        buf = io.StringIO()
        with redirect_stdout(buf):
            print_banner(cfg)
        out = buf.getvalue()
        dashboard_line = next(line for line in out.splitlines() if "Dashboard" in line)
        self.assertIn(":8443", dashboard_line)
        self.assertNotIn(":8080", dashboard_line)


if __name__ == "__main__":
    unittest.main()
