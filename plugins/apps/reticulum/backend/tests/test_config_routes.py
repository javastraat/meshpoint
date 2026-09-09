"""Tests for the ReticulumUpdate pydantic model's validators
(config_routes.py). No FastAPI route/DB involved -- pure model validation,
importable on the Mac (no aiosqlite pulled in)."""

from __future__ import annotations

import unittest

from pydantic import ValidationError

from plugins.apps.reticulum.backend.config_routes import ReticulumUpdate

_REQUIRED = {"rnode_frequency_hz": 869_463_000}


class TestTalkbackNeedsNode(unittest.TestCase):
    def test_talkback_without_node_hosting_is_rejected(self) -> None:
        with self.assertRaises(ValidationError) as cm:
            ReticulumUpdate(**_REQUIRED, talkback_enabled=True, node_enabled=False)
        self.assertIn("talk-back bot", str(cm.exception))

    def test_talkback_with_node_hosting_is_accepted(self) -> None:
        model = ReticulumUpdate(**_REQUIRED, talkback_enabled=True, node_enabled=True)
        self.assertTrue(model.talkback_enabled)

    def test_talkback_off_needs_no_node_hosting(self) -> None:
        model = ReticulumUpdate(**_REQUIRED, talkback_enabled=False, node_enabled=False)
        self.assertFalse(model.talkback_enabled)

    def test_defaults_to_off(self) -> None:
        model = ReticulumUpdate(**_REQUIRED)
        self.assertFalse(model.talkback_enabled)


class TestPropagationOutboundNode(unittest.TestCase):
    def test_blank_is_fine(self) -> None:
        m = ReticulumUpdate(**_REQUIRED, propagation_outbound_node="")
        self.assertEqual(m.propagation_outbound_node, "")

    def test_valid_hash_is_normalised(self) -> None:
        m = ReticulumUpdate(**_REQUIRED, propagation_outbound_node="AB:CD" + "EF" * 14)
        self.assertEqual(m.propagation_outbound_node, "abcd" + "ef" * 14)

    def test_angle_bracket_form_is_accepted(self) -> None:
        # RNS's own <hex> display form (startup banner / "You:" line)
        m = ReticulumUpdate(**_REQUIRED, telemetry_collector="<" + "ab" * 16 + ">")
        self.assertEqual(m.telemetry_collector, "ab" * 16)

    def test_non_hex_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            ReticulumUpdate(**_REQUIRED, propagation_outbound_node="not-a-hash")

    def test_auto_sync_needs_a_node(self) -> None:
        with self.assertRaises(ValidationError) as cm:
            ReticulumUpdate(**_REQUIRED, propagation_auto_sync_interval_s=600)
        self.assertIn("outbound propagation node", str(cm.exception))

    def test_auto_sync_floor(self) -> None:
        with self.assertRaises(ValidationError):
            ReticulumUpdate(
                **_REQUIRED,
                propagation_outbound_node="ab" * 16,
                propagation_auto_sync_interval_s=120,
            )

    def test_auto_sync_with_node_and_valid_interval(self) -> None:
        m = ReticulumUpdate(
            **_REQUIRED,
            propagation_outbound_node="ab" * 16,
            propagation_auto_sync_interval_s=900,
        )
        self.assertEqual(m.propagation_auto_sync_interval_s, 900)


class TestTelemetryConfig(unittest.TestCase):
    def test_defaults_off(self) -> None:
        m = ReticulumUpdate(**_REQUIRED)
        self.assertFalse(m.telemetry_enabled)
        self.assertEqual(m.telemetry_interval_s, 900)

    def test_enabled_needs_a_collector(self) -> None:
        with self.assertRaises(ValidationError) as cm:
            ReticulumUpdate(**_REQUIRED, telemetry_enabled=True)
        self.assertIn("collector", str(cm.exception))

    def test_enabled_with_collector_ok_and_hash_normalised(self) -> None:
        m = ReticulumUpdate(
            **_REQUIRED, telemetry_enabled=True,
            telemetry_collector="AB:CD" + "EF" * 14,
        )
        self.assertTrue(m.telemetry_enabled)
        self.assertEqual(m.telemetry_collector, "abcd" + "ef" * 14)

    def test_bad_collector_hash_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            ReticulumUpdate(**_REQUIRED, telemetry_collector="xyz")

    def test_interval_floor(self) -> None:
        with self.assertRaises(ValidationError):
            ReticulumUpdate(**_REQUIRED, telemetry_interval_s=60)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
