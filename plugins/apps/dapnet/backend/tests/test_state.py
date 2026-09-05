"""Tests for the DAPNET plugin's in-memory state (devices, capcode filters,
tier() classification).

Pure Python -- no FastAPI import. _persist()'s file I/O is patched out
(mock.patch.object) rather than exercised for real, same reasoning
test_dapnet_update_route.py used for save_section_to_yaml in core.
"""

from __future__ import annotations

import unittest
from unittest import mock

from plugins.apps.dapnet.backend import state


class _FakePacket:
    def __init__(self, capcode: int) -> None:
        self.decoded_payload = {"capcode": capcode}


class TestInit(unittest.TestCase):
    def tearDown(self) -> None:
        state.init({})  # reset to defaults for the next test

    def test_seeds_from_config_dict(self) -> None:
        state.init({
            "devices": [{"serial_port": "/dev/ttyUSB2", "label": "ttgo"}],
            "blacklist_capcodes": [1, 2],
            "ignore_capcodes": [3],
            "status_poll_interval_s": 30,
        })
        self.assertEqual(state.devices(), [{"serial_port": "/dev/ttyUSB2", "label": "ttgo"}])
        self.assertEqual(state.blacklist_capcodes(), [1, 2])
        self.assertEqual(state.ignore_capcodes(), [3])
        self.assertEqual(state.status_poll_interval_s(), 30)

    def test_empty_config_falls_back_to_defaults(self) -> None:
        state.init({})
        self.assertEqual(state.devices(), [])
        self.assertEqual(state.blacklist_capcodes(), [200, 208, 216, 224])
        self.assertEqual(state.ignore_capcodes(), [4512, 4520])
        self.assertEqual(state.status_poll_interval_s(), 60)

    def test_devices_returns_a_copy(self) -> None:
        state.init({"devices": [{"label": "x"}]})
        state.devices().clear()
        self.assertEqual(len(state.devices()), 1)


class TestTier(unittest.TestCase):
    def setUp(self) -> None:
        state.init({"blacklist_capcodes": [200, 208], "ignore_capcodes": [4512]})

    def tearDown(self) -> None:
        state.init({})

    def test_ignored_capcode_returns_ignore(self) -> None:
        self.assertEqual(state.tier(_FakePacket(4512)), "ignore")

    def test_blacklisted_capcode_returns_blacklist(self) -> None:
        self.assertEqual(state.tier(_FakePacket(200)), "blacklist")

    def test_unlisted_capcode_returns_none(self) -> None:
        self.assertIsNone(state.tier(_FakePacket(999)))

    def test_missing_decoded_payload_does_not_crash(self) -> None:
        packet = _FakePacket(0)
        packet.decoded_payload = None
        self.assertIsNone(state.tier(packet))

    def test_ignore_wins_over_blacklist_for_same_capcode(self) -> None:
        # A capcode in both lists (misconfiguration, but shouldn't crash --
        # ignore is checked first, matching the stricter tier).
        state.init({"blacklist_capcodes": [1], "ignore_capcodes": [1]})
        self.assertEqual(state.tier(_FakePacket(1)), "ignore")


class TestSetters(unittest.TestCase):
    def setUp(self) -> None:
        state.init({})
        self._persist_patcher = mock.patch.object(state, "_persist")
        self._persist_patcher.start()

    def tearDown(self) -> None:
        self._persist_patcher.stop()
        state.init({})

    def test_set_filters_updates_blacklist_only(self) -> None:
        state.set_filters(blacklist_capcodes=[1, 2])
        self.assertEqual(state.blacklist_capcodes(), [1, 2])
        self.assertEqual(state.ignore_capcodes(), [4512, 4520])  # unchanged

    def test_set_filters_updates_ignore_only(self) -> None:
        state.set_filters(ignore_capcodes=[9])
        self.assertEqual(state.ignore_capcodes(), [9])
        self.assertEqual(state.blacklist_capcodes(), [200, 208, 216, 224])  # unchanged

    def test_set_filters_calls_persist(self) -> None:
        state.set_filters(blacklist_capcodes=[1])
        state._persist.assert_called_once()

    def test_set_devices_replaces_the_list(self) -> None:
        state.set_devices([{"label": "a"}, {"label": "b"}])
        self.assertEqual(state.devices(), [{"label": "a"}, {"label": "b"}])

    def test_set_status_poll_interval_s(self) -> None:
        state.set_status_poll_interval_s(120)
        self.assertEqual(state.status_poll_interval_s(), 120)


class TestPersistMerge(unittest.TestCase):
    """_persist() must preserve fields it doesn't manage (like "enabled",
    owned by the core Settings -> Plugins toggle) rather than wiping them
    via save_section_to_yaml's shallow per-section dict.update()."""

    def tearDown(self) -> None:
        state.init({})

    def test_persist_merges_over_current_saved_config(self) -> None:
        state.init({"blacklist_capcodes": [1]})
        with mock.patch.object(
            state, "_current_saved_config", return_value={"enabled": True, "extra": "kept"},
        ):
            with mock.patch("src.config.save_section_to_yaml") as mock_save:
                state.set_filters(blacklist_capcodes=[2])
        mock_save.assert_called_once()
        (_section, values), _kwargs = mock_save.call_args
        self.assertEqual(values["dapnet"]["enabled"], True)
        self.assertEqual(values["dapnet"]["extra"], "kept")
        self.assertEqual(values["dapnet"]["blacklist_capcodes"], [2])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
