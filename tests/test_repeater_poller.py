"""Repeater poller telemetry mapping + config coercion (Mac-runnable)."""

import asyncio
import tempfile
import unittest

from src.config import RepeaterConfig, _coerce_repeaters
from src.transmit.repeater_poller import RepeaterPoller


class CoerceRepeatersTest(unittest.TestCase):
    def test_parses_list_and_drops_keyless(self):
        out = _coerce_repeaters([
            {"key": "da0b77f13bc7", "password": "pw", "name": "PD2EMC"},
            {"password": "no-key"},          # dropped: no key
            {"key": "aabbccddeeff"},          # kept: key only
            "not-a-dict",
        ])
        self.assertEqual([r.key for r in out], ["da0b77f13bc7", "aabbccddeeff"])
        self.assertEqual(out[0].name, "PD2EMC")
        self.assertEqual(out[0].password, "pw")

    def test_non_list_yields_empty(self):
        self.assertEqual(_coerce_repeaters({"key": "x"}), [])
        self.assertEqual(_coerce_repeaters(None), [])


class _FakeTelemetryRepo:
    def __init__(self):
        self.inserted = []

    async def insert(self, telem):
        self.inserted.append(telem)


class _FakeTx:
    def __init__(self, result):
        self._result = result

    async def poll_repeater(self, key, password=""):
        return self._result


def _poller(tx, repo, tmpdir):
    return RepeaterPoller(
        tx_client=tx,
        repeaters=[RepeaterConfig(key="da0b77f13bc7", password="pw", name="R")],
        interval_minutes=30,
        telemetry_repo=repo,
        data_dir=tmpdir,
    )


class PollerTelemetryTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def test_status_and_lpp_map_to_telemetry_row(self):
        result = {
            "ok": True,
            "status": {"bat": 4119, "uptime": 3194952, "noise_floor": -105},
            "telemetry": {"lpp": [
                {"channel": 1, "type": "voltage", "value": 4.1},
                {"channel": 3, "type": "temperature", "value": 39.5},
                {"channel": 4, "type": "humidity", "value": 51.0},
                {"channel": 3, "type": "barometer", "value": 1016.3},
            ]},
            "error": "",
        }
        repo = _FakeTelemetryRepo()
        p = _poller(_FakeTx(result), repo, self._tmp)
        asyncio.run(p._poll_one(p._repeaters[0]))

        self.assertEqual(len(repo.inserted), 1)
        t = repo.inserted[0]
        self.assertEqual(t.node_id, "da0b77f13bc7")
        self.assertEqual(t.voltage, 4.119)           # bat mV -> V
        self.assertEqual(t.uptime_seconds, 3194952)
        self.assertEqual(t.temperature, 39.5)        # ambient sensor
        self.assertEqual(t.humidity, 51.0)
        self.assertEqual(t.barometric_pressure, 1016.3)

    def test_latest_and_persistence(self):
        result = {"ok": True, "status": {"bat": 4119}, "telemetry": None, "error": ""}
        p = _poller(_FakeTx(result), _FakeTelemetryRepo(), self._tmp)
        asyncio.run(p._poll_one(p._repeaters[0]))
        self.assertIn("da0b77f13bc7", p.latest)
        self.assertTrue(p.latest["da0b77f13bc7"]["ok"])
        # A fresh poller loads the persisted state on init.
        p2 = _poller(_FakeTx(result), _FakeTelemetryRepo(), self._tmp)
        self.assertIn("da0b77f13bc7", p2.latest)

    def test_failed_poll_keeps_last_good_status_and_marks_stale(self):
        good = {"ok": True, "status": {"bat": 4119}, "telemetry": None, "error": ""}
        p = _poller(_FakeTx(good), _FakeTelemetryRepo(), self._tmp)
        asyncio.run(p._poll_one(p._repeaters[0]))

        p._tx = _FakeTx({"ok": False, "status": None, "error": "timed out"})
        asyncio.run(p._poll_one(p._repeaters[0]))
        entry = p.latest["da0b77f13bc7"]
        self.assertFalse(entry["ok"])
        self.assertEqual(entry["status"], {"bat": 4119})  # preserved
        self.assertEqual(entry["error"], "timed out")

    def test_no_telemetry_worth_storing_skips_insert(self):
        result = {"ok": True, "status": {"noise_floor": -105}, "telemetry": None, "error": ""}
        repo = _FakeTelemetryRepo()
        p = _poller(_FakeTx(result), repo, self._tmp)
        asyncio.run(p._poll_one(p._repeaters[0]))
        self.assertEqual(repo.inserted, [])  # no voltage/temp -> nothing stored


if __name__ == "__main__":
    unittest.main()
