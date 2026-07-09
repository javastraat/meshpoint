"""Fan duty fields on /api/device/metrics -- CI-only (needs fastapi),
same as its sibling test_system_metrics_load_avg.py.
"""

import asyncio
import unittest
from unittest.mock import patch

from src.api.routes import system_metrics


class FakeFanController:
    def __init__(self, current_duty: float, previous_duty: float):
        self.current_duty = current_duty
        self.previous_duty = previous_duty


class SystemMetricsFanFieldsTest(unittest.TestCase):
    def tearDown(self):
        system_metrics.reset_routes()

    def _call(self):
        with patch("psutil.cpu_percent", return_value=1.0), \
             patch("psutil.virtual_memory") as mem, \
             patch("shutil.disk_usage") as disk:
            mem.return_value.percent = 1.0
            mem.return_value.used = 1
            mem.return_value.total = 1
            disk.return_value.used = 1
            disk.return_value.total = 1
            return asyncio.run(system_metrics.system_metrics())

    def test_no_fan_controller_reports_none(self):
        system_metrics.init_routes(None)
        result = self._call()
        self.assertIsNone(result["fan_duty_percent"])
        self.assertIsNone(result["fan_previous_duty_percent"])

    def test_fan_controller_reports_percentages(self):
        system_metrics.init_routes(FakeFanController(current_duty=0.62, previous_duty=0.35))
        result = self._call()
        self.assertEqual(result["fan_duty_percent"], 62.0)
        self.assertEqual(result["fan_previous_duty_percent"], 35.0)


class SystemMetricsThermalsTest(unittest.TestCase):
    def tearDown(self):
        system_metrics.reset_routes()

    def test_no_fan_controller_reports_unavailable(self):
        system_metrics.init_routes(None)
        result = asyncio.run(system_metrics.thermals())
        self.assertEqual(result, {"available": False, "points": []})

    def test_history_serialized_as_points(self):
        fan = FakeFanController(current_duty=0.41, previous_duty=0.36)
        fan.poll_interval_s = 10.0
        fan.history = [(1000.9, 45.26, 0.36), (1010.9, 46.74, 0.41)]
        system_metrics.init_routes(fan)
        result = asyncio.run(system_metrics.thermals())
        self.assertTrue(result["available"])
        self.assertEqual(result["poll_interval_s"], 10.0)
        self.assertEqual(
            result["points"],
            [
                {"ts": 1000, "temp_c": 45.3, "duty": 0.36},
                {"ts": 1010, "temp_c": 46.7, "duty": 0.41},
            ],
        )


if __name__ == "__main__":
    unittest.main()
