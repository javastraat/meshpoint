"""Tests for PUT /api/config/hardware/{fan,led,button}.

Calls the route handlers directly (same approach as
test_serial_devices_route.py -- no existing TestClient harness for this
router). Needs fastapi (hardware_config_routes imports it, and the
Update models are pydantic), so CI-only like the other api/*-adjacent
tests in this suite.
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import FastAPI  # noqa: F401 -- import-time dependency probe
from pydantic import ValidationError

from src.api.audit import AuditLogWriter
from src.api.auth.jwt_session import SessionClaims
from src.api.routes import hardware_config_routes as routes
from src.config import AppConfig


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class HardwareConfigRoutesTestBase(unittest.TestCase):
    def setUp(self):
        self.config = AppConfig()
        routes.init_routes(self.config)
        self.addCleanup(routes.reset_routes)

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.audit = AuditLogWriter(log_path=Path(self.tmp.name) / "audit.jsonl")
        self.claims = SessionClaims("test-admin", "admin", 1)


class UpdateFanTest(HardwareConfigRoutesTestBase):
    def _put(self, **overrides):
        req = routes.FanHardwareUpdate(**overrides)
        with mock.patch.object(routes, "save_section_to_yaml") as mock_save:
            result = _run(routes.update_fan(req, _claims=self.claims, audit=self.audit))
        return result, mock_save

    def test_saves_and_requires_restart(self):
        result, mock_save = self._put(
            enabled=True, gpio_pin=13, min_temp_c=40.0, max_temp_c=60.0,
            min_duty=0.3, hysteresis_c=4.0, poll_interval_s=5.0,
        )
        self.assertTrue(result["saved"])
        self.assertTrue(result["restart_required"])
        self.assertTrue(self.config.fan.enabled)
        self.assertEqual(self.config.fan.min_temp_c, 40.0)
        mock_save.assert_called_once()
        section, updates = mock_save.call_args[0]
        self.assertEqual(section, "fan")
        self.assertEqual(updates["min_temp_c"], 40.0)

    def test_max_temp_must_exceed_min_temp(self):
        with self.assertRaises(ValidationError):
            routes.FanHardwareUpdate(min_temp_c=60.0, max_temp_c=60.0)

    def test_gpio_pin_out_of_range_rejected(self):
        with self.assertRaises(ValidationError):
            routes.FanHardwareUpdate(gpio_pin=99)

    def test_raises_503_when_config_not_loaded(self):
        routes.reset_routes()
        req = routes.FanHardwareUpdate()
        with self.assertRaises(Exception):
            _run(routes.update_fan(req, _claims=self.claims, audit=self.audit))
        routes.init_routes(self.config)


class UpdateLedTest(HardwareConfigRoutesTestBase):
    def _put(self, **overrides):
        req = routes.LedHardwareUpdate(**overrides)
        with mock.patch.object(routes, "save_section_to_yaml") as mock_save:
            result = _run(routes.update_led(req, _claims=self.claims, audit=self.audit))
        return result, mock_save

    def test_saves_and_requires_restart(self):
        result, mock_save = self._put(enabled=True, gpio_pin=22, activity_blink=False)
        self.assertTrue(result["saved"])
        self.assertTrue(result["restart_required"])
        self.assertTrue(self.config.led.enabled)
        self.assertFalse(self.config.led.activity_blink)
        mock_save.assert_called_once()


class UpdateButtonTest(HardwareConfigRoutesTestBase):
    def _put(self, **overrides):
        req = routes.ButtonHardwareUpdate(**overrides)
        with mock.patch.object(routes, "save_section_to_yaml") as mock_save:
            result = _run(routes.update_button(req, _claims=self.claims, audit=self.audit))
        return result, mock_save

    def test_saves_and_requires_restart(self):
        result, mock_save = self._put(
            enabled=True, gpio_pin=27, hold_time_s=5.0, advert_cooldown_s=60.0,
        )
        self.assertTrue(result["saved"])
        self.assertTrue(result["restart_required"])
        self.assertTrue(self.config.button.enabled)
        self.assertEqual(self.config.button.hold_time_s, 5.0)
        mock_save.assert_called_once()

    def test_hold_time_must_be_positive(self):
        with self.assertRaises(ValidationError):
            routes.ButtonHardwareUpdate(hold_time_s=0.0)


if __name__ == "__main__":
    unittest.main()
