"""A Meshtastic USB link that drops while running must reconnect.

Ported idea from upstream KMX415/meshpoint 93866842. Before, our reconnect
loop only ran when the *first* connect failed: after Set Preset / Set Region /
Bluetooth (the node reboots) or a meshtastic "connection.lost", the source
stayed connected=True with a dead interface and received nothing until a
service restart.
"""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import MagicMock, patch

from src.capture import serial_source as ss
from src.capture.serial_source import SerialCaptureSource


class FakeIface:
    def __init__(self):
        self.closed = False
        self.localNode = MagicMock()

    def close(self):
        self.closed = True


class LinkDropTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.ifaces = []

        def connect():
            iface = FakeIface()
            self.ifaces.append(iface)
            return iface, {"region": "EU_868"}

        self.patches = [
            patch.object(ss, "_RECONNECT_BASE_DELAY_SECONDS", 0),
            patch.object(SerialCaptureSource, "_blocking_connect", side_effect=connect),
        ]
        for p in self.patches:
            p.start()
        self.source = SerialCaptureSource(port="/dev/fake")
        await self.source.start()
        self.assertTrue(self.source.connected)

    async def asyncTearDown(self):
        await self.source.stop()
        for p in self.patches:
            p.stop()

    async def settle(self):
        for _ in range(20):
            await asyncio.sleep(0)
            task = self.source._reconnect_task
            if task is not None and task.done():
                break
        task = self.source._reconnect_task
        if task is not None:
            await asyncio.wait_for(task, 1)

    async def test_connection_lost_closes_dead_interface_and_reconnects(self):
        first = self.ifaces[0]
        self.source._on_connection_lost(interface=first)
        await asyncio.sleep(0)  # call_soon_threadsafe hop
        self.assertFalse(self.source.connected)
        await self.settle()
        self.assertTrue(first.closed)
        self.assertEqual(len(self.ifaces), 2)
        self.assertIs(self.source._interface, self.ifaces[1])
        self.assertTrue(self.source.connected)

    async def test_real_pubsub_topic_reaches_the_source(self):
        from pubsub import pub

        first = self.ifaces[0]
        pub.sendMessage("meshtastic.connection.lost", interface=first)
        await asyncio.sleep(0)
        await self.settle()
        self.assertTrue(first.closed)
        self.assertTrue(self.source.connected)
        self.assertIs(self.source._interface, self.ifaces[1])

    async def test_other_sticks_interface_is_ignored(self):
        self.source._on_connection_lost(interface=FakeIface())
        await asyncio.sleep(0)
        self.assertTrue(self.source.connected)
        self.assertIsNone(self.source._reconnect_task)
        self.assertEqual(len(self.ifaces), 1)

    async def test_config_writes_that_reboot_the_node_reconnect(self):
        for call in (
            lambda s: s.set_modem_preset("LONG_FAST"),
            lambda s: s.set_region("EU_868"),
            lambda s: s.set_bluetooth(True),
        ):
            with self.subTest(call=call):
                before = len(self.ifaces)
                result = call(self.source)
                self.assertTrue(result["success"], result)
                await asyncio.sleep(0)
                await self.settle()
                self.assertTrue(self.ifaces[before - 1].closed)
                self.assertEqual(len(self.ifaces), before + 1)
                self.assertTrue(self.source.connected)

    async def test_drop_during_or_after_stop_does_nothing(self):
        first = self.ifaces[0]
        await self.source.stop()
        self.source._on_connection_lost(interface=first)
        await asyncio.sleep(0)
        self.assertIsNone(self.source._reconnect_task)
        self.assertEqual(len(self.ifaces), 1)

    async def test_two_drop_events_start_one_reconnect(self):
        first = self.ifaces[0]
        self.source.handle_link_drop("lora config write")
        self.source._on_connection_lost(interface=first)  # native USB also reports it
        await asyncio.sleep(0)
        await self.settle()
        self.assertEqual(len(self.ifaces), 2)


if __name__ == "__main__":
    unittest.main()
