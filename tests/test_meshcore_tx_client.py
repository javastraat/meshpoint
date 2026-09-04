"""Tests for MeshCoreTxClient static helpers."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from src.transmit.meshcore_tx_client import (
    MESHCORE_MAX_USER_CHANNELS,
    MeshCoreTxClient,
)


class TestNormalizeContactPayload(unittest.TestCase):

    def test_dict_keyed_by_pubkey(self):
        payload = {
            "aabb001122": {"adv_name": "Alice", "public_key": "aabb001122"},
            "ccdd334455": {"adv_name": "Bob", "public_key": "ccdd334455"},
        }
        result = MeshCoreTxClient._normalize_contact_payload(payload)
        self.assertEqual(len(result), 2)
        names = {e.get("adv_name") for e in result}
        self.assertIn("Alice", names)
        self.assertIn("Bob", names)

    def test_list_format(self):
        payload = [
            {"adv_name": "Carol", "public_key": "eeff"},
            {"adv_name": "Dave", "public_key": "1122"},
        ]
        result = MeshCoreTxClient._normalize_contact_payload(payload)
        self.assertEqual(len(result), 2)

    def test_list_filters_non_dict(self):
        payload = [
            {"adv_name": "Eve", "public_key": "3344"},
            "not-a-dict",
            42,
        ]
        result = MeshCoreTxClient._normalize_contact_payload(payload)
        self.assertEqual(len(result), 1)

    def test_dict_filters_non_dict_values(self):
        # Some firmware revisions return a dict with mixed value types
        # (count fields alongside contact dicts). The normaliser must
        # drop the int / string values so they cannot crash the
        # downstream entry.get() loop.
        payload = {
            "contact_count": 2,
            "ts": "2026-05-15T19:48:42Z",
            "aabb001122": {"adv_name": "Alice", "public_key": "aabb001122"},
            "ccdd334455": {"adv_name": "Bob", "public_key": "ccdd334455"},
        }
        result = MeshCoreTxClient._normalize_contact_payload(payload)
        self.assertEqual(len(result), 2)
        names = {e.get("adv_name") for e in result}
        self.assertEqual(names, {"Alice", "Bob"})

    def test_dict_all_int_values_returns_empty(self):
        payload = {"a": 1, "b": 2, "c": 3}
        result = MeshCoreTxClient._normalize_contact_payload(payload)
        self.assertEqual(result, [])

    def test_none_returns_empty(self):
        self.assertEqual(MeshCoreTxClient._normalize_contact_payload(None), [])

    def test_string_returns_empty(self):
        self.assertEqual(MeshCoreTxClient._normalize_contact_payload("nope"), [])

    def test_empty_dict(self):
        self.assertEqual(MeshCoreTxClient._normalize_contact_payload({}), [])

    def test_empty_list(self):
        self.assertEqual(MeshCoreTxClient._normalize_contact_payload([]), [])


class _FakeMcSource:
    """Test double mimicking the bits of MeshcoreUsbCaptureSource we need."""

    def __init__(self):
        self._meshcore = None
        self._connected = False


class _FakeMcInstance:
    """Test double for a meshcore.MeshCore instance."""

    def __init__(self):
        self.self_info = {
            "radio_freq": 910.525,
            "radio_bw": 62.5,
            "radio_sf": 7,
            "radio_cr": 5,
            "tx_power": 22,
            "name": "FakeNode",
        }


class TestLiveSourceBinding(unittest.TestCase):
    """Verify TX client tracks source's live MeshCore handle on reconnect."""

    def test_set_source_reads_live_state(self):
        client = MeshCoreTxClient()
        source = _FakeMcSource()
        client.set_source(source)

        # Source not yet connected: client must report disconnected
        self.assertFalse(client.connected)
        self.assertIsNone(client._mc)

        # Source connects with first instance
        first = _FakeMcInstance()
        source._meshcore = first
        source._connected = True
        self.assertTrue(client.connected)
        self.assertIs(client._mc, first)

        # Source reconnects with a brand new instance (the bug case)
        second = _FakeMcInstance()
        source._meshcore = second
        self.assertTrue(client.connected)
        self.assertIs(client._mc, second)

        # Source drops the connection again
        source._meshcore = None
        source._connected = False
        self.assertFalse(client.connected)
        self.assertIsNone(client._mc)

    def test_legacy_set_connection_still_works(self):
        client = MeshCoreTxClient()
        instance = _FakeMcInstance()
        client.set_connection(instance)
        self.assertTrue(client.connected)
        self.assertIs(client._mc, instance)

    def test_set_source_overrides_legacy_owned_handle(self):
        client = MeshCoreTxClient()
        legacy = _FakeMcInstance()
        client.set_connection(legacy)
        self.assertIs(client._mc, legacy)

        source = _FakeMcSource()
        client.set_source(source)
        self.assertIsNone(client._mc)
        self.assertFalse(client.connected)


class TestSyncChannelSlots(unittest.IsolatedAsyncioTestCase):
    """User channel keys must land in device slots 1..N (slot 0 = Public)."""

    async def asyncSetUp(self):
        self.client = MeshCoreTxClient()
        self.mc = MagicMock()
        self.client.set_connection(self.mc)
        self.set_calls: list[tuple[int, str, bytes]] = []

        async def get_channel(slot: int):
            result = MagicMock()
            result.type = "OK"
            result.payload = {
                "channel_name": "",
                "channel_secret": b"\x00" * 16,
            }
            return result

        async def set_channel(slot: int, name: str, secret: bytes):
            self.set_calls.append((slot, name, secret))
            return MagicMock()

        self.mc.commands.get_channel = get_channel
        self.mc.commands.set_channel = set_channel
        self.client._run_post_command = AsyncMock()

        self._event_type = MagicMock()
        self._event_type.ERROR = "ERROR"
        self._meshcore_mod = MagicMock(EventType=self._event_type)

    async def _run_sync(self, channel_keys: dict[str, str]) -> None:
        async def immediate_wait_for(coro, timeout):
            return await coro

        with patch.dict("sys.modules", {"meshcore": self._meshcore_mod}):
            with patch(
                "src.transmit.meshcore_tx_client.asyncio.wait_for",
                side_effect=immediate_wait_for,
            ):
                await self.client.sync_channels(channel_keys)

    async def test_first_user_channel_uses_slot_one(self):
        key_hex = "f708715569f4ee34c273f8f32d32e0e8"
        await self._run_sync({"orangecounty": key_hex})
        written = [(s, n) for s, n, _ in self.set_calls if n]
        self.assertEqual(written, [(1, "orangecounty")])

    async def test_slot_zero_never_written(self):
        key_hex = "f708715569f4ee34c273f8f32d32e0e8"
        await self._run_sync({"orangecounty": key_hex})
        slots = [slot for slot, _, _ in self.set_calls]
        self.assertNotIn(0, slots)

    async def test_excess_channels_truncated_to_max(self):
        keys = {f"ch{i}": "aa" * 16 for i in range(MESHCORE_MAX_USER_CHANNELS + 3)}
        await self._run_sync(keys)
        named_writes = [n for _, n, _ in self.set_calls if n]
        self.assertEqual(len(named_writes), MESHCORE_MAX_USER_CHANNELS)


class _FakeEventType:
    """Stand-in for meshcore.EventType so set_companion_name can compare
    result.type against EventType.ERROR without a real meshcore install."""

    OK = "OK"
    ERROR = "ERROR"


class TestSetCompanionName(unittest.IsolatedAsyncioTestCase):
    """Cover the rename path end-to-end: validation, timeout, ERROR, OK."""

    async def asyncSetUp(self):
        self.client = MeshCoreTxClient()
        self.mc = MagicMock()
        self.set_name_mock = AsyncMock()
        self.mc.commands.set_name = self.set_name_mock
        # self_info is a plain dict on the real meshcore client. Seed it
        # with a stale name so we can prove set_companion_name updates it.
        self.mc.self_info = {"name": "old-name", "adv_type": 1}
        self.client.set_connection(self.mc)
        self.client._run_post_command = AsyncMock()
        self._meshcore_mod = MagicMock(EventType=_FakeEventType)

    def _ok_result(self):
        result = MagicMock()
        result.type = _FakeEventType.OK
        return result

    def _error_result(self, payload=None):
        result = MagicMock()
        result.type = _FakeEventType.ERROR
        result.payload = payload
        return result

    async def _run(self, name: str):
        async def immediate_wait_for(coro, timeout):
            return await coro

        with patch.dict("sys.modules", {"meshcore": self._meshcore_mod}):
            with patch(
                "src.transmit.meshcore_tx_client.asyncio.wait_for",
                side_effect=immediate_wait_for,
            ):
                return await self.client.set_companion_name(name)

    async def test_not_connected_short_circuits(self):
        client = MeshCoreTxClient()
        result = await client.set_companion_name("Anything")
        self.assertFalse(result.success)
        self.assertEqual(result.error, "Not connected")

    async def test_empty_name_rejected_locally(self):
        result = await self._run("")
        self.assertFalse(result.success)
        self.assertIn("empty", result.error.lower())
        self.set_name_mock.assert_not_called()

    async def test_whitespace_only_rejected_locally(self):
        result = await self._run("   \t\n  ")
        self.assertFalse(result.success)
        self.assertIn("empty", result.error.lower())
        self.set_name_mock.assert_not_called()

    async def test_too_long_rejected_locally(self):
        result = await self._run("x" * 33)
        self.assertFalse(result.success)
        self.assertIn("33 bytes", result.error)
        self.assertIn("32", result.error)
        self.set_name_mock.assert_not_called()

    async def test_unicode_byte_count_enforced(self):
        # Each emoji here is 4 bytes UTF-8; 9 emojis = 36 bytes > 32.
        result = await self._run("🛰" * 9)
        self.assertFalse(result.success)
        self.assertIn("36 bytes", result.error)
        self.set_name_mock.assert_not_called()

    async def test_ok_path_updates_self_info_cache(self):
        self.set_name_mock.return_value = self._ok_result()
        result = await self._run("Mesh Lab East")
        self.assertTrue(result.success)
        self.set_name_mock.assert_awaited_once_with("Mesh Lab East")
        # The dashboard reads name from self_info; verify the rename
        # is reflected immediately so /api/config refresh shows the new
        # name without waiting for a USB reconnect.
        self.assertEqual(self.mc.self_info["name"], "Mesh Lab East")
        # Other self_info fields stay untouched.
        self.assertEqual(self.mc.self_info["adv_type"], 1)

    async def test_ok_path_strips_whitespace_before_sending(self):
        self.set_name_mock.return_value = self._ok_result()
        result = await self._run("   Mesh Lab East   ")
        self.assertTrue(result.success)
        self.set_name_mock.assert_awaited_once_with("Mesh Lab East")

    async def test_error_result_returns_failure_with_payload_detail(self):
        self.set_name_mock.return_value = self._error_result({"reason": "name in use"})
        result = await self._run("Mesh Lab East")
        self.assertFalse(result.success)
        self.assertIn("name in use", result.error)
        # A clean firmware rejection is NOT the same as a dead
        # connection -- timed_out must stay False so the caller doesn't
        # unnecessarily reconnect a perfectly healthy companion.
        self.assertFalse(result.timed_out)
        # Cache must NOT update if the rename was rejected -- otherwise
        # the dashboard would show a name the device doesn't actually
        # have.
        self.assertEqual(self.mc.self_info["name"], "old-name")

    async def test_error_with_string_payload(self):
        self.set_name_mock.return_value = self._error_result("rejected")
        result = await self._run("Mesh Lab East")
        self.assertFalse(result.success)
        self.assertIn("rejected", result.error)

    async def test_error_with_no_payload(self):
        self.set_name_mock.return_value = self._error_result(None)
        result = await self._run("Mesh Lab East")
        self.assertFalse(result.success)
        self.assertIn("rejected", result.error.lower())

    async def test_set_name_timeout_returns_error(self):
        import asyncio as _asyncio

        async def raise_timeout(coro, *_args, **_kwargs):
            # Close the coroutine the production code created so we don't
            # leak a "coroutine was never awaited" warning.
            if hasattr(coro, "close"):
                coro.close()
            raise _asyncio.TimeoutError()

        with patch.dict("sys.modules", {"meshcore": self._meshcore_mod}):
            with patch(
                "src.transmit.meshcore_tx_client.asyncio.wait_for",
                side_effect=raise_timeout,
            ):
                result = await self.client.set_companion_name("Mesh Lab East")

        self.assertFalse(result.success)
        self.assertIn("timed out", result.error)
        # timed_out=True is what tells MeshcoreUsbCaptureSource to treat
        # this as a dead connection and reconnect immediately, rather
        # than leaving it marked connected -- distinct from a clean
        # firmware ERROR response, which doesn't set this flag.
        self.assertTrue(result.timed_out)
        # On timeout we don't know whether the firmware accepted the
        # name; do not update the cache.
        self.assertEqual(self.mc.self_info["name"], "old-name")

    async def test_ok_path_tolerates_missing_self_info_dict(self):
        # If meshcore ever changes self_info to None or a non-dict,
        # the rename must still succeed -- the cache update is a best
        # effort, not a contract.
        self.set_name_mock.return_value = self._ok_result()
        self.mc.self_info = None
        result = await self._run("Mesh Lab East")
        self.assertTrue(result.success)


class TestAddContact(unittest.IsolatedAsyncioTestCase):
    """Re-injecting a cached contact record into the companion roster
    (repeater-reconnect fix: a companion reset wipes its roster, and a
    repeater's own re-advert can be hours away, so repeater_poller
    re-injects a previously-cached full record instead of waiting)."""

    async def asyncSetUp(self):
        self.client = MeshCoreTxClient()
        self.mc = MagicMock()
        self.add_contact_mock = AsyncMock()
        self.mc.commands.add_contact = self.add_contact_mock
        self.client.set_connection(self.mc)
        self.client._run_post_command = AsyncMock()
        self._meshcore_mod = MagicMock(EventType=_FakeEventType)
        self.contact = {
            "public_key": "aabbcc" + "00" * 29,
            "type": 2,
            "flags": 0,
            "out_path": "",
            "out_path_len": -1,
            "out_path_hash_mode": -1,
            "adv_name": "R",
            "last_advert": 1234,
            "adv_lat": 52.0,
            "adv_lon": 5.0,
        }

    def _ok_result(self):
        result = MagicMock()
        result.type = _FakeEventType.OK
        return result

    def _error_result(self):
        result = MagicMock()
        result.type = _FakeEventType.ERROR
        return result

    async def _run(self):
        async def immediate_wait_for(coro, timeout):
            return await coro

        with patch.dict("sys.modules", {"meshcore": self._meshcore_mod}):
            with patch(
                "src.transmit.meshcore_tx_client.asyncio.wait_for",
                side_effect=immediate_wait_for,
            ):
                return await self.client.add_contact(self.contact)

    async def test_not_connected_short_circuits(self):
        client = MeshCoreTxClient()
        result = await client.add_contact(self.contact)
        self.assertFalse(result)
        self.add_contact_mock.assert_not_called()

    async def test_ok_result_returns_true(self):
        self.add_contact_mock.return_value = self._ok_result()
        result = await self._run()
        self.assertTrue(result)
        self.add_contact_mock.assert_awaited_once_with(self.contact)

    async def test_error_result_returns_false(self):
        self.add_contact_mock.return_value = self._error_result()
        result = await self._run()
        self.assertFalse(result)

    async def test_exception_returns_false(self):
        self.add_contact_mock.side_effect = RuntimeError("boom")
        result = await self._run()
        self.assertFalse(result)

    async def test_runs_post_command_even_on_exception(self):
        self.add_contact_mock.side_effect = RuntimeError("boom")
        await self._run()
        self.client._run_post_command.assert_awaited_once()


class TestSendSetRadioParams(unittest.IsolatedAsyncioTestCase):
    """Cover send_set_radio_params(): local range validation, the
    set_radio()+reboot() sequence, ERROR/timeout handling. Standalone
    function (no MeshCoreTxClient wrapper, unlike set_companion_name --
    MeshcoreUsbCaptureSource.set_radio_params() calls it directly per
    companion), so tests call it directly too."""

    async def asyncSetUp(self):
        from src.transmit.meshcore_tx_client import send_set_radio_params
        self._send_set_radio_params = send_set_radio_params

        self.mc = MagicMock()
        self.set_radio_mock = AsyncMock()
        self.reboot_mock = AsyncMock()
        self.mc.commands.set_radio = self.set_radio_mock
        self.mc.commands.reboot = self.reboot_mock
        self._meshcore_mod = MagicMock(EventType=_FakeEventType)

    def _ok_result(self):
        result = MagicMock()
        result.type = _FakeEventType.OK
        return result

    def _error_result(self, payload=None):
        result = MagicMock()
        result.type = _FakeEventType.ERROR
        result.payload = payload
        return result

    async def _run(self, freq=433.650, bw=62.5, sf=8, cr=8):
        async def immediate_wait_for(coro, timeout):
            return await coro

        with patch.dict("sys.modules", {"meshcore": self._meshcore_mod}):
            with patch(
                "src.transmit.meshcore_tx_client.asyncio.wait_for",
                side_effect=immediate_wait_for,
            ):
                return await self._send_set_radio_params(self.mc, freq, bw, sf, cr)

    async def test_not_connected_short_circuits(self):
        result = await self._send_set_radio_params(None, 433.650, 62.5, 8, 8)
        self.assertFalse(result.success)
        self.assertEqual(result.error, "Not connected")
        self.set_radio_mock.assert_not_called()

    async def test_frequency_out_of_range_rejected_locally(self):
        result = await self._run(freq=100.0)
        self.assertFalse(result.success)
        self.assertIn("frequency", result.error.lower())
        self.set_radio_mock.assert_not_called()

    async def test_bandwidth_out_of_range_rejected_locally(self):
        result = await self._run(bw=1000.0)
        self.assertFalse(result.success)
        self.assertIn("bandwidth", result.error.lower())
        self.set_radio_mock.assert_not_called()

    async def test_spreading_factor_out_of_range_rejected_locally(self):
        result = await self._run(sf=20)
        self.assertFalse(result.success)
        self.assertIn("spreading factor", result.error.lower())
        self.set_radio_mock.assert_not_called()

    async def test_coding_rate_out_of_range_rejected_locally(self):
        result = await self._run(cr=1)
        self.assertFalse(result.success)
        self.assertIn("coding rate", result.error.lower())
        self.set_radio_mock.assert_not_called()

    async def test_ok_path_sets_radio_then_reboots(self):
        self.set_radio_mock.return_value = self._ok_result()
        self.reboot_mock.return_value = self._ok_result()
        result = await self._run(433.650, 62.5, 8, 8)
        self.assertTrue(result.success)
        self.set_radio_mock.assert_awaited_once_with(433.650, 62.5, 8, 8)
        self.reboot_mock.assert_awaited_once()

    async def test_error_result_skips_reboot(self):
        self.set_radio_mock.return_value = self._error_result({"reason": "bad params"})
        result = await self._run()
        self.assertFalse(result.success)
        self.assertIn("bad params", result.error)
        self.assertFalse(result.timed_out)
        self.reboot_mock.assert_not_called()

    async def test_error_with_no_payload(self):
        self.set_radio_mock.return_value = self._error_result(None)
        result = await self._run()
        self.assertFalse(result.success)
        self.assertIn("rejected", result.error.lower())
        self.reboot_mock.assert_not_called()

    async def test_reboot_failure_still_reports_success(self):
        # set_radio already succeeded -- the companion commonly drops
        # the connection immediately on reboot without a clean ack.
        # That's expected, not a failure of the params-set itself.
        self.set_radio_mock.return_value = self._ok_result()
        self.reboot_mock.side_effect = Exception("connection closed")
        result = await self._run()
        self.assertTrue(result.success)

    async def test_set_radio_timeout_returns_error(self):
        import asyncio as _asyncio

        async def raise_timeout(coro, *_args, **_kwargs):
            if hasattr(coro, "close"):
                coro.close()
            raise _asyncio.TimeoutError()

        with patch.dict("sys.modules", {"meshcore": self._meshcore_mod}):
            with patch(
                "src.transmit.meshcore_tx_client.asyncio.wait_for",
                side_effect=raise_timeout,
            ):
                result = await self._send_set_radio_params(self.mc, 433.650, 62.5, 8, 8)

        self.assertFalse(result.success)
        self.assertIn("timed out", result.error)
        self.assertTrue(result.timed_out)
        self.reboot_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
