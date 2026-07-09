"""Tests for PUT /api/config/capture/serial-devices.

Calls the route handler directly (bypassing FastAPI's TestClient/auth
layer, for which there's no existing harness for this router) since
the handler is a plain async function taking a validated pydantic
request plus injected claims/audit. Needs fastapi (system_config_routes
imports it, and SerialDevicesUpdate is a pydantic model), so CI-only
like the other api/*-adjacent tests in this suite.
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import FastAPI  # noqa: F401 -- import-time dependency probe

from src.api.audit import AuditLogWriter
from src.api.auth.jwt_session import SessionClaims
from src.api.routes import system_config_routes as routes
from src.config import AppConfig, SerialDeviceConfig


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class UpdateSerialDevicesTest(unittest.TestCase):
    def setUp(self):
        self.config = AppConfig()
        routes.init_routes(self.config)
        self.addCleanup(routes.reset_routes)

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.audit = AuditLogWriter(log_path=Path(self.tmp.name) / "audit.jsonl")
        self.claims = SessionClaims("test-admin", "admin", 1)

    def _put(self, devices, enable_source=None):
        req = routes.SerialDevicesUpdate(
            devices=[routes.SerialDeviceEntry(**d) for d in devices],
            enable_source=enable_source,
        )
        with mock.patch.object(routes, "save_section_to_yaml") as mock_save:
            result = _run(routes.update_serial_devices(
                req, _claims=self.claims, audit=self.audit,
            ))
        return result, mock_save

    def test_replaces_config_capture_serial_list(self):
        result, mock_save = self._put([
            {"label": "433", "serial_port": "/dev/ttyUSB0", "serial_baud": 115200},
            {"label": "868", "serial_port": "/dev/ttyUSB1", "serial_baud": 57600},
        ])

        self.assertEqual(result["saved"], True)
        self.assertEqual(len(self.config.capture.serial), 2)
        self.assertEqual(self.config.capture.serial[0].label, "433")
        self.assertEqual(self.config.capture.serial[1].serial_baud, 57600)

        mock_save.assert_called_once()
        section, values = mock_save.call_args[0]
        self.assertEqual(section, "capture")
        self.assertEqual(len(values["serial"]), 2)
        self.assertEqual(values["serial"][0]["label"], "433")

    def test_strips_whitespace_from_serial_port(self):
        self._put([{"label": "", "serial_port": "  /dev/ttyUSB0  ", "serial_baud": 115200}])
        self.assertEqual(self.config.capture.serial[0].serial_port, "/dev/ttyUSB0")

    def test_blank_serial_port_becomes_none_for_auto_detect(self):
        self._put([{"label": "", "serial_port": "", "serial_baud": 115200}])
        self.assertIsNone(self.config.capture.serial[0].serial_port)

    def test_enable_source_true_adds_serial_to_sources(self):
        self.config.capture.sources = ["concentrator"]
        self._put([{"label": "433", "serial_port": None}], enable_source=True)
        self.assertIn("serial", self.config.capture.sources)

    def test_enable_source_false_removes_serial_from_sources(self):
        self.config.capture.sources = ["concentrator", "serial"]
        self._put([{"label": "433", "serial_port": None}], enable_source=False)
        self.assertNotIn("serial", self.config.capture.sources)

    def test_enable_source_none_leaves_sources_untouched(self):
        self.config.capture.sources = ["concentrator", "serial"]
        self._put([{"label": "433", "serial_port": None}], enable_source=None)
        self.assertEqual(self.config.capture.sources, ["concentrator", "serial"])

    def test_empty_device_list_clears_capture_serial(self):
        self.config.capture.serial = [SerialDeviceConfig(label="868")]
        self._put([])
        self.assertEqual(self.config.capture.serial, [])

    def test_raises_503_when_config_not_loaded(self):
        routes.reset_routes()
        from fastapi import HTTPException
        req = routes.SerialDevicesUpdate(devices=[])
        with self.assertRaises(HTTPException) as ctx:
            _run(routes.update_serial_devices(
                req, _claims=self.claims, audit=self.audit,
            ))
        self.assertEqual(ctx.exception.status_code, 503)
        # Re-init for the shared addCleanup(reset_routes) to be a no-op-safe redo.
        routes.init_routes(self.config)


if __name__ == "__main__":
    unittest.main()
