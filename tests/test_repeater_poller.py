"""Repeater poller telemetry mapping + config coercion (Mac-runnable)."""

import asyncio
import tempfile
import unittest

from src.config import RepeaterConfig, _coerce_repeaters
from src.transmit import repeater_poller as rp_mod
from src.transmit.repeater_poller import RepeaterPoller

# Don't sleep between retries in tests.
rp_mod.RETRY_DELAY_S = 0


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
        self.calls = 0

    async def poll_repeater(self, key, password=""):
        self.calls += 1
        return self._result


class _FlakyTx:
    """Fails ``fail_times`` polls, then succeeds."""

    def __init__(self, fail_times, success):
        self._fail_times = fail_times
        self._success = success
        self.calls = 0

    async def poll_repeater(self, key, password=""):
        self.calls += 1
        if self.calls <= self._fail_times:
            return {"ok": False, "error": "login failed or timed out"}
        return self._success


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

    def test_retries_then_succeeds(self):
        # Two transient failures, then a good poll -> ends OK, 3 calls.
        good = {"ok": True, "status": {"bat": 4119}, "telemetry": None, "error": ""}
        tx = _FlakyTx(fail_times=2, success=good)
        p = _poller(tx, _FakeTelemetryRepo(), self._tmp)
        asyncio.run(p._poll_one(p._repeaters[0]))
        self.assertEqual(tx.calls, 3)
        self.assertTrue(p.latest["da0b77f13bc7"]["ok"])

    def test_gives_up_after_max_attempts(self):
        tx = _FakeTx({"ok": False, "error": "login failed or timed out"})
        p = _poller(tx, _FakeTelemetryRepo(), self._tmp)
        asyncio.run(p._poll_one(p._repeaters[0]))
        self.assertEqual(tx.calls, rp_mod.POLL_ATTEMPTS)  # tried the max
        self.assertFalse(p.latest["da0b77f13bc7"]["ok"])


class PollRepeaterShapeTest(unittest.TestCase):
    """req_telemetry_sync returns the LPP list directly; poll_repeater
    must normalize it to {"lpp": [...]} so readers find the sensors."""

    def _client_with_fakes(self, telem_return):
        from src.transmit.meshcore_tx_client import MeshCoreTxClient

        class _Cmds:
            async def send_login_sync(self, contact, pwd, *a, **k):
                return object()  # login success

            async def req_status_sync(self, contact, *a, **k):
                return {"bat": 4119}

            async def req_telemetry_sync(self, contact, *a, **k):
                return telem_return

        class _Mc:
            commands = _Cmds()

            def get_contact_by_key_prefix(self, key):
                return {"public_key": key + "00", "adv_name": "R"}

        client = MeshCoreTxClient()
        client._owned_mc = _Mc()
        client._owned_connected = True
        return client

    def test_bare_lpp_list_is_wrapped(self):
        lpp = [{"channel": 1, "type": "voltage", "value": 4.11}]
        client = self._client_with_fakes(lpp)
        out = asyncio.run(client.poll_repeater("da0b77f13bc7", "pw"))
        self.assertTrue(out["ok"])
        self.assertEqual(out["telemetry"], {"lpp": lpp})  # wrapped

    def test_none_telemetry_stays_none(self):
        client = self._client_with_fakes(None)
        out = asyncio.run(client.poll_repeater("da0b77f13bc7", "pw"))
        self.assertTrue(out["ok"])                 # status still succeeded
        self.assertIsNone(out["telemetry"])


if __name__ == "__main__":
    unittest.main()
