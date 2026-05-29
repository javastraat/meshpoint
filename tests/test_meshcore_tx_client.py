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

    async def test_excess_channels_truncated_to_seven(self):
        keys = {f"ch{i}": "aa" * 16 for i in range(MESHCORE_MAX_USER_CHANNELS + 3)}
        await self._run_sync(keys)
        named_writes = [n for _, n, _ in self.set_calls if n]
        self.assertEqual(len(named_writes), MESHCORE_MAX_USER_CHANNELS)


if __name__ == "__main__":
    unittest.main()
