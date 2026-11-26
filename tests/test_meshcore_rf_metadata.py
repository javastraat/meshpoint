"""MeshCore packets carry the receiver's settings and an advert's own RF data.

Ported from upstream KMX415/meshpoint fc15bc36 (#27 in TODO.md), adapted to
our model: hops go in hop_start (as for MeshCore messages), not a separate
meshcore_hops field.
"""

from __future__ import annotations

import json
import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.modules.setdefault("aiosqlite", types.ModuleType("aiosqlite"))  # Mac dev box

from src.capture.meshcore_usb_source import (  # noqa: E402
    MeshcoreUsbCaptureSource,
    _raw_advertisement,
    _receiver_settings,
)
from src.decode.meshcore_event_adapter import adapt_event  # noqa: E402

KEY = "11" * 32


def source():
    s = MeshcoreUsbCaptureSource()
    s._meshcore = SimpleNamespace(
        self_info={"radio_freq": 869.618, "radio_bw": 62.5, "radio_sf": 8, "radio_cr": 5}
    )
    return s


def event(kind, payload):
    return SimpleNamespace(type=SimpleNamespace(value=kind), payload=payload)


def raw_advert(key=KEY, count=2, rssi=-55, snr=8, route=1):
    """A flood (route 1) ADVERT frame as the RX log reports it."""
    body = bytes.fromhex(key) + bytes(4 + 64) + b"\0"
    header = (4 << 2) | route
    return {"payload": (bytes([header, count]) + bytes(count) + body).hex(),
            "adv_key": key, "recv_time": 1700000000, "rssi": rssi, "snr": snr}


class ReceiverSettingsTests(unittest.TestCase):
    def test_channel_message_gets_receiver_settings_and_coding_rate(self):
        s = source()
        raw = s._wrap_event(event("channel_message", {"text": "hi", "rssi": -70, "snr": 0, "path_len": 0}))
        packet = adapt_event(raw.payload, raw.signal)
        self.assertEqual(packet.signal.frequency_mhz, 869.618)
        self.assertEqual(packet.signal.spreading_factor, 8)
        self.assertEqual(packet.signal.bandwidth_khz, 62.5)
        self.assertEqual(packet.signal.coding_rate, "4/5")  # was "N/A"
        self.assertEqual(packet.signal.snr, 0)
        self.assertEqual(packet.decoded_payload["meshcore_receiver"]["coding_rate"], "4/5")

    def test_settings_are_taken_when_the_event_arrives(self):
        import asyncio

        async def run():
            s = source()
            s._running = True
            await s._on_event(event("channel_message", {"text": "hi"}))
            s._meshcore.self_info["radio_freq"] = 915.0  # changed while queued
            return s._wrap_event(await s._queue.get())

        self.assertEqual(asyncio.run(run()).signal.frequency_mhz, 869.618)

    def test_unknown_settings_at_capture_are_not_filled_in_later(self):
        import asyncio

        async def run():
            s = source()
            info = s._meshcore.self_info
            s._meshcore.self_info = {}
            s._running = True
            await s._on_event(event("channel_message", {"text": "hi"}))
            s._meshcore.self_info = info
            return s._wrap_event(await s._queue.get())

        raw = asyncio.run(run())
        self.assertNotIn("meshcore_receiver", adapt_event(raw.payload, raw.signal).decoded_payload)

    def test_invalid_settings_are_ignored(self):
        self.assertIsNone(_receiver_settings({}))
        self.assertIsNone(_receiver_settings({"radio_freq": 869.6, "radio_bw": 62.5, "radio_sf": 4, "radio_cr": 5}))
        self.assertIsNone(_receiver_settings({"radio_freq": "x", "radio_bw": 62.5, "radio_sf": 8, "radio_cr": 5}))


class AdvertRfTests(unittest.TestCase):
    def test_matched_advert_gets_its_own_rssi_snr_and_hops(self):
        s = source()
        # An unrelated, stronger frame heard in between used to be attached to the advert.
        s._wrap_event(event("rx_log_data", {"payload": "00", "rssi": -30, "snr": 12}))
        s._wrap_event(event("rx_log_data", raw_advert()))
        s._wrap_event(event("rx_log_data", {"payload": "00", "rssi": -30, "snr": 12}))
        raw = s._wrap_event(event("advertisement", {"public_key": KEY}))
        packet = adapt_event(raw.payload, raw.signal)
        self.assertEqual(packet.signal.rssi, -55)
        self.assertEqual(packet.signal.snr, 8)
        self.assertEqual(packet.hop_start, 2)
        self.assertEqual(packet.signal.coding_rate, "4/5")

    def test_ambiguous_unrelated_or_expired_frames_give_no_hops(self):
        cases = ("two copies", "other key", "expired")
        for case in cases:
            with self.subTest(case=case):
                s = source()
                with patch("src.capture.meshcore_usb_source.time.monotonic", return_value=100):
                    s._wrap_event(event("rx_log_data", raw_advert()))
                    if case == "two copies":
                        s._wrap_event(event("rx_log_data", raw_advert(count=3)))
                key = "22" * 32 if case == "other key" else KEY
                now = 103 if case == "expired" else 100
                with patch("src.capture.meshcore_usb_source.time.monotonic", return_value=now):
                    raw = s._wrap_event(event("advertisement", {"public_key": key}))
                self.assertEqual(adapt_event(raw.payload, raw.signal).hop_start, 0)

    def test_direct_route_path_is_not_a_hop_count(self):
        self.assertNotIn("path_len", _raw_advertisement(raw_advert(route=2)))

    def test_malformed_frames(self):
        self.assertIsNone(_raw_advertisement({"payload": "11"}))
        self.assertIsNone(_raw_advertisement({"payload": "gg"}))
        bad_key = raw_advert()
        bad_key["adv_key"] = "22" * 32  # library key must match the frame's own
        self.assertIsNone(_raw_advertisement(bad_key))

    def test_saved_outgoing_route_is_not_received_hops(self):
        raw = source()._wrap_event(event("advertisement", {"public_key": KEY, "out_path_len": 4}))
        self.assertEqual(adapt_event(raw.payload, raw.signal).hop_start, 0)


class StorageTests(unittest.TestCase):
    def test_coding_rate_and_settings_survive_the_database(self):
        from src.storage.packet_repository import PacketRepository

        s = source()
        s._wrap_event(event("rx_log_data", raw_advert()))
        raw = s._wrap_event(event("advertisement", {"public_key": KEY}))
        packet = adapt_event(raw.payload, raw.signal)
        row = {**packet.to_dict(), **packet.signal.to_dict(),
               "decoded_payload": json.dumps(packet.decoded_payload)}
        restored = PacketRepository._row_to_packet(row)
        self.assertEqual(restored.signal.coding_rate, "4/5")
        self.assertEqual(restored.decoded_payload["meshcore_receiver"]["frequency_mhz"], 869.618)


if __name__ == "__main__":
    unittest.main()
