"""Tests for adapt_event() -- turning one companion serial JSON line into
a decoded Packet.

Pure Python, no FastAPI. This function was never directly unit-tested
before this plugin existed (src/decode/dapnet_event_adapter.py had no
matching test file in core) -- new coverage, not a straight port.
"""

from __future__ import annotations

import json
import unittest

from plugins.apps.dapnet.backend.decode import adapt_event
from src.models.packet import OpenPacketType, OpenProtocol


class TestAdaptEvent(unittest.TestCase):
    def test_alpha_page_decodes(self) -> None:
        line = json.dumps({
            "capcode": 2081296, "function": 3, "type": "alpha",
            "text": "Surveillance temperature relais DAPNET F6Z",
        }).encode()
        packet = adapt_event(line)
        self.assertIsNotNone(packet)
        self.assertEqual(packet.protocol, OpenProtocol("dapnet"))
        self.assertIsInstance(packet.protocol, OpenProtocol)
        self.assertEqual(packet.packet_type, OpenPacketType("dapnet_alpha"))
        self.assertEqual(packet.source_id, "broadcast")
        self.assertEqual(packet.destination_id, "2081296")
        self.assertTrue(packet.decrypted)
        self.assertEqual(packet.decoded_payload["capcode"], 2081296)
        self.assertEqual(packet.decoded_payload["function"], 3)
        self.assertEqual(
            packet.decoded_payload["text"], "Surveillance temperature relais DAPNET F6Z",
        )

    def test_every_known_type_maps_to_its_own_packet_type(self) -> None:
        for wire_type, expected in [
            ("alpha", "dapnet_alpha"),
            ("numeric", "dapnet_numeric"),
            ("tone", "dapnet_tone"),
            ("activation", "dapnet_activation"),
        ]:
            with self.subTest(wire_type=wire_type):
                line = json.dumps({"capcode": 1, "type": wire_type}).encode()
                packet = adapt_event(line)
                self.assertEqual(packet.packet_type, OpenPacketType(expected))

    def test_unknown_type_string_falls_back_to_unknown(self) -> None:
        line = json.dumps({"capcode": 1, "type": "something_new"}).encode()
        packet = adapt_event(line)
        self.assertEqual(packet.packet_type, "unknown")

    def test_missing_text_defaults_to_empty_string(self) -> None:
        line = json.dumps({"capcode": 1, "type": "tone"}).encode()
        packet = adapt_event(line)
        self.assertEqual(packet.decoded_payload["text"], "")

    def test_non_json_line_returns_none(self) -> None:
        self.assertIsNone(adapt_event(b"not json at all"))

    def test_valid_json_non_dict_returns_none(self) -> None:
        self.assertIsNone(adapt_event(json.dumps([1, 2, 3]).encode()))

    def test_missing_capcode_returns_none(self) -> None:
        self.assertIsNone(adapt_event(json.dumps({"type": "alpha"}).encode()))

    def test_missing_type_returns_none(self) -> None:
        self.assertIsNone(adapt_event(json.dumps({"capcode": 1}).encode()))

    def test_non_integer_capcode_returns_none(self) -> None:
        self.assertIsNone(adapt_event(json.dumps({"capcode": "not-a-number", "type": "alpha"}).encode()))

    def test_capcode_as_numeric_string_is_coerced(self) -> None:
        packet = adapt_event(json.dumps({"capcode": "1234", "type": "alpha"}).encode())
        self.assertEqual(packet.destination_id, "1234")

    def test_signal_argument_is_accepted_but_ignored(self) -> None:
        # Interface parity with the other capture adapters -- the
        # companion reports no RF signal metrics, so a real SignalMetrics
        # passed in must not end up on the resulting Packet.
        from src.models.signal import SignalMetrics
        line = json.dumps({"capcode": 1, "type": "alpha"}).encode()
        packet = adapt_event(line, signal=SignalMetrics(
            rssi=-50.0, snr=10.0, frequency_mhz=439.9875, spreading_factor=0, bandwidth_khz=0.0,
        ))
        self.assertIsNone(packet.signal)

    def test_generates_a_unique_packet_id_per_call(self) -> None:
        line = json.dumps({"capcode": 1, "type": "alpha"}).encode()
        first = adapt_event(line)
        second = adapt_event(line)
        self.assertNotEqual(first.packet_id, second.packet_id)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
