"""Topology graph assembly (Mac-runnable: fastapi-free module)."""

import unittest

from src.api.topology_graph import assemble_graph


def _tr(source, route, ts="2026-07-10T10:00:00"):
    import json
    return {
        "source_id": source,
        "decoded_payload": json.dumps({"route": route}),
        "timestamp": ts,
    }


class AssembleGraphTest(unittest.TestCase):
    def test_traceroute_chain_becomes_hop_edges(self):
        graph = assemble_graph(
            [_tr("aa", ["bb", "cc"])], [], [], [],
            self_node_id=None, self_name="box", anchor_node_id=None,
        )
        kinds = [(e["a"], e["b"], e["kind"]) for e in graph["edges"]]
        self.assertIn(("aa", "bb", "route"), kinds)
        self.assertIn(("bb", "cc", "route"), kinds)
        self.assertEqual(graph["counts"]["route"], 2)
        self.assertEqual(graph["counts"]["nodes"], 3)

    def test_repeated_edge_merges_and_keeps_newest_timestamp(self):
        graph = assemble_graph(
            [
                _tr("aa", ["bb"], ts="2026-07-01T00:00:00"),
                _tr("bb", ["aa"], ts="2026-07-09T00:00:00"),
            ],
            [], [], [],
            self_node_id=None, self_name="box", anchor_node_id=None,
        )
        self.assertEqual(len(graph["edges"]), 1)
        edge = graph["edges"][0]
        self.assertEqual(edge["count"], 2)
        self.assertEqual(edge["last_seen"], "2026-07-09T00:00:00")

    def test_direct_rows_attach_to_self(self):
        direct = [{
            "source_id": "dd", "protocol": "meshtastic", "cnt": 5,
            "last_seen": "2026-07-11T09:00:00", "avg_rssi": -88.4, "avg_snr": 6.25,
        }]
        graph = assemble_graph(
            [], direct, [], [],
            self_node_id="c3ecf862", self_name="PD2EMC", anchor_node_id=None,
        )
        edge = graph["edges"][0]
        self.assertEqual(edge["kind"], "direct")
        self.assertEqual({edge["a"], edge["b"]}, {"c3ecf862", "dd"})
        self.assertEqual(edge["rssi"], -88.4)
        self_node = next(n for n in graph["nodes"] if n["is_self"])
        self.assertEqual(self_node["name"], "PD2EMC")

    def test_direct_rows_dropped_without_self_id(self):
        direct = [{
            "source_id": "dd", "protocol": "meshtastic", "cnt": 1,
            "last_seen": "2026-07-11T09:00:00", "avg_rssi": None, "avg_snr": None,
        }]
        graph = assemble_graph(
            [], direct, [], [],
            self_node_id=None, self_name="box", anchor_node_id=None,
        )
        self.assertEqual(graph["edges"], [])

    def test_neighbour_star_anchors_on_repeater(self):
        neigh = [
            {"source_id": "n1", "cnt": 3, "last_seen": "2026-07-10T20:00:00", "avg_snr": 8.0},
            {"source_id": "n2", "cnt": 1, "last_seen": "2026-07-08T20:00:00", "avg_snr": -2.5},
        ]
        graph = assemble_graph(
            [], [], neigh, [],
            self_node_id=None, self_name="box", anchor_node_id="da0b77f13bc7",
        )
        self.assertEqual(graph["counts"]["neighbour"], 2)
        anchor = next(n for n in graph["nodes"] if n["is_anchor"])
        self.assertEqual(anchor["id"], "da0b77f13bc7")
        self.assertEqual(anchor["protocol"], "meshcore")

    def test_roster_names_and_protocol_win_over_hints(self):
        roster = [{
            "node_id": "AA", "long_name": "Node Alpha", "short_name": None,
            "protocol": "meshtastic", "role": "ROUTER",
        }]
        graph = assemble_graph(
            [_tr("aa", ["bb"])], [], [], roster,
            self_node_id=None, self_name="box", anchor_node_id=None,
        )
        node = next(n for n in graph["nodes"] if n["id"] == "aa")
        self.assertEqual(node["name"], "Node Alpha")
        self.assertEqual(node["role"], "ROUTER")

    def test_positions_passed_through_and_null_island_dropped(self):
        roster = [
            {"node_id": "aa", "long_name": "Placed", "short_name": None,
             "protocol": "meshcore", "role": None,
             "latitude": 52.37, "longitude": 4.85},
            {"node_id": "bb", "long_name": "NullIsland", "short_name": None,
             "protocol": "meshcore", "role": None,
             "latitude": 0, "longitude": 0},
        ]
        graph = assemble_graph(
            [_tr("aa", ["bb"])], [], [], roster,
            self_node_id=None, self_name="box", anchor_node_id=None,
        )
        placed = next(n for n in graph["nodes"] if n["id"] == "aa")
        null_island = next(n for n in graph["nodes"] if n["id"] == "bb")
        self.assertEqual((placed["lat"], placed["lon"]), (52.37, 4.85))
        self.assertIsNone(null_island["lat"])
        self.assertIsNone(null_island["lon"])

    def test_self_loop_and_blank_ids_skipped(self):
        graph = assemble_graph(
            [_tr("aa", ["aa", "", "bb"])], [], [], [],
            self_node_id=None, self_name="box", anchor_node_id=None,
        )
        pairs = {(e["a"], e["b"]) for e in graph["edges"]}
        self.assertNotIn(("aa", "aa"), pairs)
        self.assertIn(("aa", "bb"), pairs)

    def test_unparseable_payload_ignored(self):
        rows = [{"source_id": "aa", "decoded_payload": "not json", "timestamp": "t"}]
        graph = assemble_graph(
            rows, [], [], [],
            self_node_id=None, self_name="box", anchor_node_id=None,
        )
        self.assertEqual(graph["edges"], [])


if __name__ == "__main__":
    unittest.main()
