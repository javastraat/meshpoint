"""Tests for the plugin protocol-registry seam.

Pure Python -- src/api/protocol_registry.py has no FastAPI import. Fake
RawCapture/Packet stand-ins (plain objects with just the attributes the
registry's callers care about) exercise adapt()/tier() wiring without
needing the real models.
"""

from __future__ import annotations

import unittest

from src.api import protocol_registry
from src.api.protocol_registry import ProtocolSpec


class _FakeRaw:
    def __init__(self, capture_source: str) -> None:
        self.capture_source = capture_source


class _FakePacket:
    def __init__(self, protocol: str) -> None:
        self.protocol = protocol


class TestProtocolRegistry(unittest.TestCase):
    def setUp(self) -> None:
        protocol_registry.reset()

    def tearDown(self) -> None:
        protocol_registry.reset()

    def test_for_capture_source_matches_by_prefix(self) -> None:
        spec = ProtocolSpec("dapnet", "dapnet", adapt=lambda raw: _FakePacket("dapnet"))
        protocol_registry.register_protocol(spec)
        self.assertIs(protocol_registry.for_capture_source("dapnet_ttgo"), spec)
        self.assertIs(protocol_registry.for_capture_source("dapnet"), spec)

    def test_for_capture_source_no_match_returns_none(self) -> None:
        protocol_registry.register_protocol(
            ProtocolSpec("dapnet", "dapnet", adapt=lambda raw: None),
        )
        self.assertIsNone(protocol_registry.for_capture_source("concentrator"))

    def test_for_capture_source_first_registered_prefix_wins(self) -> None:
        first = ProtocolSpec("a", "shared", adapt=lambda raw: None)
        second = ProtocolSpec("b", "shared", adapt=lambda raw: None)
        protocol_registry.register_protocol(first)
        protocol_registry.register_protocol(second)
        self.assertIs(protocol_registry.for_capture_source("shared_x"), first)

    def test_for_protocol_looks_up_by_protocol_name(self) -> None:
        spec = ProtocolSpec("dapnet", "dapnet", adapt=lambda raw: None)
        protocol_registry.register_protocol(spec)
        self.assertIs(protocol_registry.for_protocol("dapnet"), spec)
        self.assertIsNone(protocol_registry.for_protocol("meshtastic"))

    def test_adapt_is_the_registered_callable(self) -> None:
        protocol_registry.register_protocol(
            ProtocolSpec("dapnet", "dapnet", adapt=lambda raw: _FakePacket("dapnet")),
        )
        spec = protocol_registry.for_capture_source("dapnet_ttgo")
        packet = spec.adapt(_FakeRaw("dapnet_ttgo"))
        self.assertEqual(packet.protocol, "dapnet")

    def test_tier_defaults_to_none_when_not_given(self) -> None:
        protocol_registry.register_protocol(
            ProtocolSpec("dapnet", "dapnet", adapt=lambda raw: None),
        )
        spec = protocol_registry.for_protocol("dapnet")
        self.assertIsNone(spec.tier)

    def test_tier_classifies_ignore_and_blacklist(self) -> None:
        def tier(packet: _FakePacket) -> str | None:
            return {"ok": None, "noisy": "blacklist", "junk": "ignore"}[packet.protocol]

        protocol_registry.register_protocol(
            ProtocolSpec("dapnet", "dapnet", adapt=lambda raw: None, tier=tier),
        )
        spec = protocol_registry.for_protocol("dapnet")
        self.assertIsNone(spec.tier(_FakePacket("ok")))
        self.assertEqual(spec.tier(_FakePacket("noisy")), "blacklist")
        self.assertEqual(spec.tier(_FakePacket("junk")), "ignore")

    def test_reset_clears_specs_and_prefix_list(self) -> None:
        protocol_registry.register_protocol(
            ProtocolSpec("dapnet", "dapnet", adapt=lambda raw: None),
        )
        protocol_registry.reset()
        self.assertIsNone(protocol_registry.for_protocol("dapnet"))
        self.assertIsNone(protocol_registry.for_capture_source("dapnet_x"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
