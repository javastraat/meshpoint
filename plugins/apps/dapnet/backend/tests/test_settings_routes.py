"""Tests for GET/PUT /api/dapnet/settings and GET /api/dapnet/status.

Same harness style as (now-removed) core test_dapnet_update_route.py --
calls the route handler directly with a fake PacketRepository (an async
mock, not a real DB) so this stays runnable without aiosqlite. Focus is
the same purge behavior that test used to cover: adding a capcode to the
ignore/blacklist list should also delete any already-stored dapnet pages
for that capcode, not just block future ones (see
PacketRepository.delete_dapnet_capcodes's own docstring for why), plus
the new device-list / status-poll-interval paths this plugin's version
adds on top.
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import HTTPException

from plugins.apps.dapnet.backend import settings_routes as routes
from plugins.apps.dapnet.backend import state
from src.api.audit import AuditLogWriter
from src.api.auth.jwt_session import SessionClaims


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _FakePacketRepo:
    def __init__(self):
        self.calls: list[list[int]] = []
        self.next_result = 0

    async def delete_dapnet_capcodes(self, capcodes):
        self.calls.append(list(capcodes))
        return self.next_result


class _FakeSource:
    def __init__(self, name: str, status: dict, connected: bool = True):
        self.name = name
        self._status = status
        self.connected = connected

    @property
    def status(self):
        return self._status


class _RouteTestBase(unittest.TestCase):
    def setUp(self) -> None:
        state.init({"blacklist_capcodes": [], "ignore_capcodes": []})
        self.packet_repo = _FakePacketRepo()
        routes.init_routes(dapnet_sources=[], packet_repo=self.packet_repo)

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.audit = AuditLogWriter(log_path=Path(self.tmp.name) / "audit.jsonl")
        self.claims = SessionClaims("test-admin", "admin", 1)
        # _persist()'s file I/O is out of scope for these tests -- covered
        # separately by test_state.py's TestPersistMerge.
        self._persist_patcher = mock.patch.object(state, "_persist")
        self._persist_patcher.start()
        self.addCleanup(self._persist_patcher.stop)

    def tearDown(self) -> None:
        state.init({})


class TestUpdateSettingsCapcodeFilters(_RouteTestBase):
    def _put(self, blacklist=None, ignore=None):
        req = routes.DapnetSettingsUpdate(
            blacklist_capcodes=blacklist, ignore_capcodes=ignore,
        )
        return _run(routes.update_dapnet_settings(req, _claims=self.claims, audit=self.audit))

    def test_saves_both_lists(self) -> None:
        self._put([200, 208], [4512, 4520])
        self.assertEqual(state.blacklist_capcodes(), [200, 208])
        self.assertEqual(state.ignore_capcodes(), [4512, 4520])

    def test_purges_stored_packets_for_newly_ignored_capcodes(self) -> None:
        self.packet_repo.next_result = 7
        result = self._put([], [4512, 4520])
        self.assertEqual(self.packet_repo.calls, [[4512, 4520]])
        self.assertEqual(result["purged"], 7)

    def test_purges_stored_packets_for_newly_blacklisted_capcodes_too(self) -> None:
        self.packet_repo.next_result = 3
        result = self._put([200], [])
        self.assertEqual(self.packet_repo.calls, [[200]])
        self.assertEqual(result["purged"], 3)

    def test_purges_the_union_of_both_lists_deduped(self) -> None:
        self._put([200, 4512], [4512, 4520])
        self.assertEqual(self.packet_repo.calls, [[200, 4512, 4520]])

    def test_both_lists_empty_does_not_call_purge(self) -> None:
        result = self._put([], [])
        self.assertEqual(self.packet_repo.calls, [])
        self.assertEqual(result["purged"], 0)

    def test_no_packet_repo_wired_skips_purge_without_error(self) -> None:
        routes.init_routes(dapnet_sources=[], packet_repo=None)
        result = self._put([], [4512])
        self.assertEqual(result["saved"], True)
        self.assertEqual(result["purged"], 0)

    def test_filter_change_does_not_require_restart(self) -> None:
        result = self._put([200], [])
        self.assertFalse(result["restart_required"])

    def test_omitting_both_lists_leaves_them_unchanged(self) -> None:
        state.set_filters(blacklist_capcodes=[1], ignore_capcodes=[2])
        req = routes.DapnetSettingsUpdate()
        _run(routes.update_dapnet_settings(req, _claims=self.claims, audit=self.audit))
        self.assertEqual(state.blacklist_capcodes(), [1])
        self.assertEqual(state.ignore_capcodes(), [2])


class TestUpdateSettingsDevicesAndPollInterval(_RouteTestBase):
    def test_updating_devices_requires_restart(self) -> None:
        req = routes.DapnetSettingsUpdate(
            devices=[routes.DeviceEntry(serial_port="/dev/ttyUSB2", label="ttgo")],
        )
        result = _run(routes.update_dapnet_settings(req, _claims=self.claims, audit=self.audit))
        self.assertTrue(result["restart_required"])
        self.assertEqual(state.devices(), [
            {"serial_port": "/dev/ttyUSB2", "serial_baud": 115200, "label": "ttgo", "name": ""},
        ])

    def test_updating_poll_interval_requires_restart(self) -> None:
        req = routes.DapnetSettingsUpdate(status_poll_interval_s=120)
        result = _run(routes.update_dapnet_settings(req, _claims=self.claims, audit=self.audit))
        self.assertTrue(result["restart_required"])
        self.assertEqual(state.status_poll_interval_s(), 120)

    def test_poll_interval_out_of_range_is_rejected(self) -> None:
        req = routes.DapnetSettingsUpdate(status_poll_interval_s=5)
        with self.assertRaises(HTTPException) as ctx:
            _run(routes.update_dapnet_settings(req, _claims=self.claims, audit=self.audit))
        self.assertEqual(ctx.exception.status_code, 400)

    def test_poll_interval_upper_bound(self) -> None:
        req = routes.DapnetSettingsUpdate(status_poll_interval_s=9999)
        with self.assertRaises(HTTPException):
            _run(routes.update_dapnet_settings(req, _claims=self.claims, audit=self.audit))


class TestGetSettings(_RouteTestBase):
    def test_returns_current_state(self) -> None:
        state.init({"devices": [{"label": "x"}], "blacklist_capcodes": [1]})
        result = _run(routes.get_dapnet_settings())
        self.assertEqual(result["devices"], [{"label": "x"}])
        self.assertEqual(result["blacklist_capcodes"], [1])


class TestStatus(_RouteTestBase):
    def test_returns_one_entry_per_source(self) -> None:
        routes.init_routes(dapnet_sources=[
            _FakeSource("dapnet", {"board": "heltec_v3", "callsign": "PD2EMC", "freq": 439.9875}),
        ])
        result = _run(routes.dapnet_status())
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "dapnet")
        self.assertTrue(result[0]["connected"])
        self.assertEqual(result[0]["board"], "heltec_v3")
        self.assertEqual(result[0]["callsign"], "PD2EMC")
        self.assertEqual(result[0]["frequency_mhz"], 439.9875)

    def test_disconnected_source_reports_connected_false(self) -> None:
        routes.init_routes(dapnet_sources=[_FakeSource("dapnet", {}, connected=False)])
        result = _run(routes.dapnet_status())
        self.assertFalse(result[0]["connected"])

    def test_no_sources_returns_empty_list(self) -> None:
        routes.init_routes(dapnet_sources=[])
        self.assertEqual(_run(routes.dapnet_status()), [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
