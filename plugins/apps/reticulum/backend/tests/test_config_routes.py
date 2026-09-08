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


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
