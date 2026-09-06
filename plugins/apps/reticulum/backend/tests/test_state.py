"""Tests for the reticulum plugin's config state.

Pure Python -- backend.state has no FastAPI / RNS import.
"""

from __future__ import annotations

import unittest

from plugins.apps.reticulum.backend import state


class TestReticulumState(unittest.TestCase):
    def tearDown(self) -> None:
        state.init({})  # reset to defaults for the next test

    def test_defaults_match_core_reticulumconfig(self) -> None:
        state.init({})
        self.assertEqual(state.display_name(), "Meshpoint")
        self.assertEqual(state.reticulum_config_dir(), "data/reticulum/rns_config")
        self.assertEqual(state.identity_path(), "data/reticulum/identity")
        self.assertEqual(state.lxmf_storage_dir(), "data/reticulum/lxmf")
        d = state.to_dict()
        self.assertEqual(d["rnode_frequency_hz"], 869_463_000)
        self.assertEqual(d["backbone_host"], "node.reticulumnet.nl")
        self.assertEqual(d["backbone_port"], 4242)
        self.assertEqual(d["rnode_serial_port"], "")

    def test_user_values_override_defaults(self) -> None:
        state.init({
            "display_name": "PD2EMC Meshpoint",
            "reticulum_config_dir": "/opt/meshpoint/data/reticulum/rns_config",
            "rnode_serial_port": "/dev/serial/by-id/usb-RNode-x",
            "rnode_frequency_hz": 867_000_000,
            "backbone_port": 4243,
        })
        self.assertEqual(state.display_name(), "PD2EMC Meshpoint")
        self.assertEqual(
            state.reticulum_config_dir(), "/opt/meshpoint/data/reticulum/rns_config",
        )
        d = state.to_dict()
        self.assertEqual(d["rnode_serial_port"], "/dev/serial/by-id/usb-RNode-x")
        self.assertEqual(d["rnode_frequency_hz"], 867_000_000)
        self.assertEqual(d["backbone_port"], 4243)

    def test_empty_string_and_missing_keys_fall_back_to_defaults(self) -> None:
        # "" is what a cleared YAML field looks like -- treat it as unset.
        state.init({"display_name": "", "backbone_host": None})
        self.assertEqual(state.display_name(), "Meshpoint")
        self.assertEqual(state.to_dict()["backbone_host"], "node.reticulumnet.nl")

    def test_rnode_serial_port_empty_string_is_taken_verbatim(self) -> None:
        state.init({"rnode_serial_port": ""})
        self.assertEqual(state.to_dict()["rnode_serial_port"], "")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
