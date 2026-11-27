"""Received channel messages keep their channel number (upstream 121c2d3a).

Before, every received channel message was stored with channel 0, even though
the conversation id (broadcast:<protocol>:<index>) knew the right index.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from src.config import AppConfig
from src.models.packet import Packet, PacketType, Protocol


class ReceivedChannelTests(unittest.IsolatedAsyncioTestCase):
    async def deliver(self, packet, resolver_index=None):
        from src.api.server import _setup_message_interception

        coord = MagicMock()
        coord.node_repo._db = AsyncMock()
        coord.node_repo._db.fetch_one.return_value = None
        repo = SimpleNamespace(save_received=AsyncMock(return_value=(1, False)))
        coroutines = []
        with patch("src.api.message_name_resolver.MessageNameResolver",
                   return_value=SimpleNamespace(resolve=AsyncMock(return_value="Peer"))), \
             patch("src.api.server.ws_manager.broadcast", new=AsyncMock()), \
             patch("src.api.channel_hash_resolver.ChannelHashResolver") as hash_resolver:
            hash_resolver.return_value.lookup.return_value = resolver_index
            _setup_message_interception(coord, repo, AppConfig())
            callback = coord.on_packet.call_args.args[0]
            with patch("asyncio.get_running_loop") as loop:
                loop.return_value.create_task.side_effect = coroutines.append
                callback(packet)
            for coroutine in coroutines:
                await coroutine
        return repo.save_received.await_args.kwargs

    async def test_meshcore_channel_index_is_stored(self):
        for channel in (0, 3):
            with self.subTest(channel=channel):
                packet = Packet("42", "123456789012", f"channel:{channel}", Protocol.MESHCORE,
                                PacketType.TEXT, channel_hash=channel, decoded_payload={"text": "hi"})
                kwargs = await self.deliver(packet)
                self.assertEqual(kwargs["node_id"], f"broadcast:meshcore:{channel}")
                self.assertEqual(kwargs["channel"], channel)

    async def test_meshtastic_channel_from_hash_is_stored(self):
        packet = Packet("43", "a1b2c3d4", "ffffffff", Protocol.MESHTASTIC,
                        PacketType.TEXT, channel_hash=0x71, decoded_payload={"text": "hi"})
        kwargs = await self.deliver(packet, resolver_index=1)
        self.assertEqual(kwargs["node_id"], "broadcast:meshtastic:1")
        self.assertEqual(kwargs["channel"], 1)

    async def test_direct_message_stays_channel_0(self):
        packet = Packet("44", "a1b2c3d4", "deadbeef", Protocol.MESHTASTIC,
                        PacketType.TEXT, channel_hash=0, decoded_payload={"text": "hi"})
        kwargs = await self.deliver(packet)
        self.assertEqual(kwargs["channel"], 0)


if __name__ == "__main__":
    unittest.main()
