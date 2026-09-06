"""Tests for the NomadNet-node host that don't need a real RNS stack.

Without ``rns`` installed (the dev Mac), ``nomad_node.RNS`` is ``None`` and
``start()`` is a no-op -- construction, ``status()`` and the Micron
generators are what's covered here.
"""

from __future__ import annotations

import asyncio
import unittest

from plugins.apps.reticulum.backend.nomad_node import NomadNode, _esc


class TestMicronEscape(unittest.TestCase):
    def test_escapes_backtick_and_backslash(self) -> None:
        self.assertEqual(_esc("a`b\\c"), "a\\`b\\\\c")

    def test_plain_text_untouched(self) -> None:
        self.assertEqual(_esc("Rhein-Main RNS"), "Rhein-Main RNS")


class TestNomadNode(unittest.TestCase):
    def _node(self, **kw):
        return NomadNode(
            identity=object(), name="PD2EMC Meshpoint",
            pages_dir="/tmp/does-not-exist/pages", announce_interval_s=21600, **kw,
        )

    def test_announce_interval_floored(self) -> None:
        n = NomadNode(identity=object(), name="x", pages_dir="/tmp/x", announce_interval_s=1)
        self.assertGreaterEqual(n._announce_interval_s, 600)

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

    def test_serve_index_returns_micron_bytes(self) -> None:
        n = self._node()
        n._stats = {"version": "0.8.1", "uptime": "3h 12m", "reticulum_peers": 11270}
        out = n._serve_index("/page/index.mu", None, 1, 1, None, 0)
        self.assertIsInstance(out, bytes)
        text = out.decode("utf-8")
        self.assertIn("PD2EMC Meshpoint", text)
        self.assertIn("11270", text)
        self.assertIn("nomadnetwork.node", text)
        self.assertEqual(n._requests_served, 1)

    def test_serve_nodes_lists_recent(self) -> None:
        n = self._node()
        n._stats = {"recent_nodes": [
            {"display_name": "libstalin.so", "destination_hash": "abcd"},
        ]}
        text = n._serve_nodes("/page/nodes.mu", None, 1, 1, None, 0).decode("utf-8")
        self.assertIn("libstalin.so", text)
        self.assertIn("abcd:/page/index.mu", text)

    def test_serve_nodes_empty(self) -> None:
        n = self._node()
        text = n._serve_nodes("/page/nodes.mu", None, 1, 1, None, 0).decode("utf-8")
        self.assertIn("none yet", text)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
