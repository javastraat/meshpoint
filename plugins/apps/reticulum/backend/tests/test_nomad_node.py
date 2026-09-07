"""Tests for the NomadNet-node host that don't need a real RNS stack.

Without ``rns`` installed (the dev Mac), ``nomad_node.RNS`` is ``None`` and
``start()`` is a no-op -- construction, ``status()`` and the Micron
generators are what's covered here.
"""

from __future__ import annotations

import asyncio
import unittest

from plugins.apps.reticulum.backend import nomad_node as nomad_node_module
from plugins.apps.reticulum.backend.nomad_node import NomadNode, _esc


class TestMicronEscape(unittest.TestCase):
    def test_escapes_backtick_and_backslash(self) -> None:
        self.assertEqual(_esc("a`b\\c"), "a\\`b\\\\c")

    def test_plain_text_untouched(self) -> None:
        self.assertEqual(_esc("Rhein-Main RNS"), "Rhein-Main RNS")


class TestNomadNode(unittest.TestCase):
    def _node(self, **kw):
        kw.setdefault("hardware_description", "a SenseCap M1")
        return NomadNode(
            identity=object(), name="PD2EMC Meshpoint",
            pages_dir="/tmp/does-not-exist/pages", announce_interval_s=21600, **kw,
        )

    def test_announce_interval_floored(self) -> None:
        n = NomadNode(identity=object(), name="x", pages_dir="/tmp/x", announce_interval_s=1)
        self.assertGreaterEqual(n._announce_interval_s, 600)

    @unittest.skipIf(
        nomad_node_module.RNS is not None,
        "rns installed -- this covers only the not-available path",
    )
    def test_start_is_a_no_op_without_rns(self) -> None:
        n = self._node()
        asyncio.run(n.start())  # must not raise
        self.assertIsNone(n._destination)
        asyncio.run(n.stop())

    def test_status_shape(self) -> None:
        st = self._node().status()
        self.assertEqual(st["hosting"], False)
        self.assertEqual(st["name"], "PD2EMC Meshpoint")
        self.assertIn("requests_served", st)

    def test_reload_pages_is_a_no_op_when_not_hosting(self) -> None:
        n = self._node()
        self.assertIsNone(n._destination)
        n.reload_pages()  # must not raise (Pages tab calls this after every save)
        self.assertIsNone(n._destination)

    def test_serve_index_returns_branding_page(self) -> None:
        n = self._node()
        out = n._serve_index("/page/index.mu", None, 1, 1, None, 0)
        self.assertIsInstance(out, bytes)
        text = out.decode("utf-8")
        self.assertIn("PD2EMC Meshpoint", text)
        self.assertIn("MESHPOINT", text)
        self.assertIn("SenseCap", text)
        self.assertIn("nomadnetwork.node", text)
        self.assertIn(":/page/info.mu", text)
        self.assertEqual(n._requests_served, 1)

    def test_serve_index_without_hardware_description(self) -> None:
        n = self._node(hardware_description="")
        text = n._serve_index("/page/index.mu", None, 1, 1, None, 0).decode("utf-8")
        self.assertIn("runs `!Meshpoint`! -- it captures", text)

    def test_serve_info_returns_micron_bytes(self) -> None:
        n = self._node()
        n._stats = {"version": "0.8.1", "uptime": "3h 12m", "reticulum_peers": 11270}
        out = n._serve_info("/page/info.mu", None, 1, 1, None, 0)
        self.assertIsInstance(out, bytes)
        text = out.decode("utf-8")
        self.assertIn("PD2EMC Meshpoint", text)
        self.assertIn("11270", text)
        self.assertIn(":/page/index.mu", text)
        self.assertEqual(n._requests_served, 1)
        # No host/mesh keys -> those sections are simply absent.
        self.assertNotIn(">Host", text)
        self.assertNotIn(">Mesh activity", text)

    def test_serve_info_host_and_mesh_sections(self) -> None:
        n = self._node()
        n._stats = {
            "version": "0.8.1",
            "host": {
                "pi_model": "Raspberry Pi 4 Model B", "cpu_temp_c": 47.2,
                "load_1m": 0.31, "mem_used_mb": 900, "mem_total_mb": 3800,
                "disk_free_gb": 21.4, "disk_total_gb": 29.0,
            },
            "mesh": {
                "packets_total": 1234567, "packets_24h": 8912,
                "by_protocol": {"meshtastic": 900000, "meshcore": 300000, "lorawan": 34567},
            },
        }
        text = n._serve_info("/page/info.mu", None, 1, 1, None, 0).decode("utf-8")
        self.assertIn(">Host", text)
        self.assertIn("Raspberry Pi 4 Model B", text)
        self.assertIn("47.2 C", text)
        self.assertIn("900 / 3800 MB", text)
        self.assertIn(">Mesh activity", text)
        self.assertIn("1,234,567", text)     # thousands-separated
        self.assertIn("meshtastic", text)
        # per-protocol is ordered by count desc
        self.assertLess(text.index("meshtastic"), text.index("lorawan"))
        # deliberately nothing node-level
        self.assertNotIn("source_id", text)

    def test_serve_info_and_index_use_the_project_url(self) -> None:
        n = self._node(project_url="https://github.com/someforker/meshpoint")
        for handler in (n._serve_index, n._serve_info):
            text = handler("/page/x.mu", None, 1, 1, None, 0).decode("utf-8")
            self.assertIn("https://github.com/someforker/meshpoint", text)
            self.assertIn("github.com/someforker/meshpoint]", text)  # link label

    def test_project_url_defaults_to_kmx415(self) -> None:
        text = self._node()._serve_info("/page/info.mu", None, 1, 1, None, 0).decode("utf-8")
        self.assertIn("https://github.com/KMX415/meshpoint", text)

    def test_serve_nodes_lists_recent(self) -> None:
        n = self._node()
        n._stats = {"recent_nodes": [
            {"display_name": "libstalin.so", "destination_hash": "abcd"},
        ]}
        text = n._serve_nodes("/page/nodes.mu", None, 1, 1, None, 0).decode("utf-8")
        self.assertIn("libstalin.so", text)
        self.assertIn("abcd:/page/index.mu", text)

    def test_announce_is_a_no_op_before_start(self) -> None:
        n = self._node()
        n.announce()  # _destination is None -> must not raise
        self.assertIsNone(n._last_announce)

    def test_serve_nodes_empty(self) -> None:
        n = self._node()
        text = n._serve_nodes("/page/nodes.mu", None, 1, 1, None, 0).decode("utf-8")
        self.assertIn("none yet", text)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
