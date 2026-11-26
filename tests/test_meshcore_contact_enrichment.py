from __future__ import annotations

import asyncio
import unittest

from src.api.meshcore_contacts import sync_meshcore_contacts_to_nodes
from src.models.node import Node
from src.storage.database import DatabaseManager
from src.storage.node_repository import NodeRepository


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _Coord:
    def __init__(self, repo: NodeRepository):
        from src.analytics.stats_reporter import StatsReporter

        self.node_repo = repo
        self.stats_reporter = StatsReporter()


class _MeshCoreTx:
    connected = True

    def __init__(self, contacts):
        self._contacts = contacts

    async def get_contacts(self):
        return self._contacts


class TestMeshCoreContactEnrichment(unittest.TestCase):
    def setUp(self) -> None:
        self.db = DatabaseManager(":memory:")
        _run(self.db.connect())
        self.repo = NodeRepository(self.db)
        self.coord = _Coord(self.repo)

    def tearDown(self) -> None:
        _run(self.db.disconnect())

    def test_contact_name_updates_matching_meshcore_node(self):
        _run(self.repo.upsert(Node(
            node_id="e34ef4172778",
            protocol="meshcore",
        )))

        updated = _run(sync_meshcore_contacts_to_nodes(
            self.coord,
            _MeshCoreTx([{
                "public_key": "e34ef4172778aaaabbbbcccc",
                "name": "Ridge Repeater",
            }]),
        ))

        node = _run(self.repo.get_by_id("e34ef4172778"))
        self.assertEqual(updated, 1)
        self.assertEqual(node.long_name, "Ridge Repeater")
        self.assertEqual(node.short_name, "Ridg")
        self.assertEqual(node.display_name, "Ridge Repeater")

    def test_sync_applies_all_contacts_not_only_triggering_packet(self):
        _run(self.repo.upsert(Node(
            node_id="e34ef4172778",
            protocol="meshcore",
        )))
        _run(self.repo.upsert(Node(
            node_id="c1871770ebc1",
            protocol="meshcore",
        )))

        updated = _run(sync_meshcore_contacts_to_nodes(
            self.coord,
            _MeshCoreTx([
                {
                    "public_key": "e34ef4172778aaaabbbbcccc",
                    "name": "Ridge Repeater",
                },
                {
                    "public_key": "c1871770ebc1deadbeef",
                    "name": "Valley Node",
                },
            ]),
        ))

        self.assertEqual(updated, 2)
        ridge = _run(self.repo.get_by_id("e34ef4172778"))
        valley = _run(self.repo.get_by_id("c1871770ebc1"))
        self.assertEqual(ridge.long_name, "Ridge Repeater")
        self.assertEqual(valley.long_name, "Valley Node")



class TestMeshCoreContactPositions(unittest.TestCase):
    """Positions from the companion's contact roster (upstream 4439c2a8)."""

    def setUp(self) -> None:
        self.db = DatabaseManager(":memory:")
        _run(self.db.connect())
        self.repo = NodeRepository(self.db)
        self.coord = _Coord(self.repo)

    def tearDown(self) -> None:
        _run(self.db.disconnect())

    def sync(self, contacts):
        return _run(sync_meshcore_contacts_to_nodes(self.coord, _MeshCoreTx(contacts)))

    def test_key_only_advert_gets_the_roster_position(self):
        import json
        from src.config import AppConfig
        from src.coordinator import PipelineCoordinator
        from src.decode.meshcore_event_adapter import adapt_event

        public_key = "aabb00112233" + "44" * 26
        packet = adapt_event(json.dumps({
            "event_type": "advertisement", "payload": {"public_key": public_key},
        }).encode())
        self.assertNotIn("latitude", packet.decoded_payload)
        pipeline = PipelineCoordinator(AppConfig())
        pipeline._node_repo = self.repo
        pipeline._stats_reporter = self.coord.stats_reporter
        _run(pipeline._update_node(packet))
        before = _run(self.repo.get_by_id(public_key[:12]))

        self.assertEqual(self.sync([{"public_key": public_key, "name": "Ridge Repeater",
                                     "adv_lat": 52.37, "adv_lon": 4.85}]), 1)
        node = _run(self.repo.get_by_id(public_key[:12]))
        self.assertEqual((node.latitude, node.longitude), (52.37, 4.85))
        self.assertEqual(node.long_name, "Ridge Repeater")
        self.assertEqual(node.last_heard, before.last_heard)     # no fake reception
        self.assertEqual(node.packet_count, before.packet_count)

        _run(pipeline._update_node(packet))  # another key-only advert keeps it
        node = _run(self.repo.get_by_id(public_key[:12]))
        self.assertEqual((node.latitude, node.longitude), (52.37, 4.85))

    def test_unchanged_contacts_are_not_counted_again(self):
        _run(self.repo.upsert(Node(node_id="aabb00112233", protocol="meshcore")))
        contact = {"public_key": "aabb001122334455", "name": "Ridge", "adv_lat": 10, "adv_lon": 20}
        self.assertEqual(self.sync([contact]), 1)
        self.coord.stats_reporter.reset()
        self.assertEqual(self.sync([contact]), 0)
        self.assertEqual(self.coord.stats_reporter.build_node_roster(), [])

    def test_position_without_a_friendly_name_keeps_the_names(self):
        for name, lat, lon in [("", 0, 20), ("aabb00112233", 10, 0)]:
            with self.subTest(name=name):
                _run(self.repo.upsert(Node(node_id="aabb00112233", protocol="meshcore",
                                           long_name="Keep Name", short_name="Mine")))
                self.assertEqual(self.sync([{"public_key": "aabb001122334455", "name": name,
                                             "adv_lat": lat, "adv_lon": lon}]), 1)
                node = _run(self.repo.get_by_id("aabb00112233"))
                self.assertEqual((node.latitude, node.longitude), (lat, lon))
                self.assertEqual((node.long_name, node.short_name), ("Keep Name", "Mine"))

    def test_invalid_position_keeps_the_known_one(self):
        for lat, lon in [(None, 20), (10, None), (0, 0), (91, 20), (10, float("nan"))]:
            with self.subTest(lat=lat, lon=lon):
                _run(self.repo.upsert(Node(node_id="aabb00112233", protocol="meshcore",
                                           latitude=30, longitude=40)))
                self.sync([{"public_key": "aabb001122334455", "name": "Ridge",
                            "adv_lat": lat, "adv_lon": lon}])
                node = _run(self.repo.get_by_id("aabb00112233"))
                self.assertEqual((node.latitude, node.longitude), (30, 40))
                self.assertEqual(node.long_name, "Ridge")

    def test_only_the_exact_heard_meshcore_node_is_touched(self):
        for node_id, protocol in [("aabb00112233", "meshcore"), ("aabb00119999", "meshcore"),
                                  ("ccdd00112233", "meshtastic")]:
            _run(self.repo.upsert(Node(node_id=node_id, protocol=protocol)))
        contacts = [{"public_key": pk, "name": "Ridge", "adv_lat": 10, "adv_lon": 20}
                    for pk in ("AABB001122334455", "ccdd001122334455", "eeee001122334455")]
        self.assertEqual(self.sync(contacts), 1)
        self.assertEqual(_run(self.repo.get_count()), 3)  # nothing new invented
        self.assertIsNone(_run(self.repo.get_by_id("aabb00119999")).latitude)
        self.assertIsNone(_run(self.repo.get_by_id("ccdd00112233")).latitude)


class TestContactParserPositions(unittest.TestCase):
    def test_get_contacts_carries_valid_positions_only(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        from src.transmit.meshcore_tx_client import MeshCoreTxClient

        payload = {
            "aa" * 32: {"public_key": "aa" * 32, "adv_name": "Roof", "adv_lat": 52.37, "adv_lon": 4.85},
            "bb" * 32: {"public_key": "bb" * 32, "adv_name": "Unset", "adv_lat": 0, "adv_lon": 0},
        }
        client = MeshCoreTxClient()
        client.set_connection(SimpleNamespace(commands=SimpleNamespace(
            get_contacts=AsyncMock(return_value=SimpleNamespace(type=SimpleNamespace(value="contacts"),
                                                                payload=payload)))))
        contacts = {c["name"]: c for c in _run(client.get_contacts())}
        self.assertEqual((contacts["Roof"]["adv_lat"], contacts["Roof"]["adv_lon"]), (52.37, 4.85))
        self.assertEqual((contacts["Unset"]["adv_lat"], contacts["Unset"]["adv_lon"]), (None, None))


if __name__ == "__main__":
    unittest.main()
