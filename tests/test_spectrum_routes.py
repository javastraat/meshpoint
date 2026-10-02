"""Tests for GET /api/device/spectrum.

Only the unauthenticated GET path is covered here (mirrors
test_rf_routes.py's own scope) -- confirms RfEnvCompanionScanService
duck-types into this route exactly like the real SpectralScanService
does, via the same is_companion-style structural typing rf_routes.py
already relies on. POST /sweep requires admin auth and isn't touched by
the companion wiring itself, so it's left to whatever coverage already
exists for that route.
"""
from __future__ import annotations

import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routes import spectrum_routes


class TestSpectrumRoutes(unittest.TestCase):
    def _client(self, service) -> TestClient:
        spectrum_routes.init_routes(service)
        app = FastAPI()
        app.include_router(spectrum_routes.router)
        return TestClient(app)

    def test_no_service_reports_unavailable(self) -> None:
        client = self._client(None)
        body = client.get("/api/device/spectrum").json()
        self.assertEqual(body, {"available": False, "sweep": None})

    def test_service_without_sweep_support_reports_unavailable(self) -> None:
        class _NoSweep:
            sweep_supported = False
            latest_sweep = None

        client = self._client(_NoSweep())
        body = client.get("/api/device/spectrum").json()
        self.assertEqual(body, {"available": False, "sweep": None})

    def test_companion_service_sweep_surfaces_same_shape_as_real_hal(self) -> None:
        # RfEnvCompanionScanService duck-types the exact same
        # sweep_supported/latest_sweep surface SpectralScanService
        # exposes -- this route neither knows nor cares which backs it.
        envelope = {
            "generated_at": "2026-08-06T10:00:00+00:00",
            "duration_seconds": 2.4,
            "point_count": 2,
            "points": [
                {"frequency_mhz": 863.0, "floor_dbm": -110.0, "median_dbm": -95.0, "p95_dbm": -80.0},
                {"frequency_mhz": 863.1, "floor_dbm": -108.0, "median_dbm": -94.0, "p95_dbm": -79.0},
            ],
        }

        class _FakeCompanionService:
            sweep_supported = True
            latest_sweep = envelope

        client = self._client(_FakeCompanionService())
        body = client.get("/api/device/spectrum").json()
        self.assertTrue(body["available"])
        self.assertEqual(body["sweep"], envelope)
        self.assertNotIn("calibration", body)

    def test_capture_ram_service_reports_calibration(self) -> None:
        class _FakeCaptureRam:
            sweep_supported = True
            latest_sweep = None

            def calibration_status(self):
                return {"supported": True, "calibrated": False,
                        "calibrating": False, "created_at": None}

        body = self._client(_FakeCaptureRam()).get("/api/device/spectrum").json()
        self.assertFalse(body["calibration"]["calibrated"])


if __name__ == "__main__":
    unittest.main()
