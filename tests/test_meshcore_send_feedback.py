"""MeshCore send feedback: repeats heard back for channel sends, ACKs for DMs.

Ported from upstream KMX415/meshpoint e8c4c6e1 (#151) tests, adapted to our
multi-companion tracker (copies of one send share a packet_id and add up).
Real AES/HMAC channel frames, as the companion's RX log reports them.
"""

from __future__ import annotations

import hashlib
import hmac
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from Crypto.Cipher import AES

from src.storage.database import DatabaseManager
from src.storage.message_repository import MessageRepository
from src.transmit.meshcore_repeats import MeshcoreSendFeedback, new_packet_id
from src.transmit.meshcore_tx_client import send_mc_channel_message, send_mc_direct_message

SECRET = bytes(range(16))
CHANNEL = {"channel_secret": SECRET, "channel_name": "test"}


def frame(text="Bench: hello", timestamp=100, hops=1, width=1, scoped=False, secret=SECRET):
    plain = timestamp.to_bytes(4, "little") + b"\0" + text.encode()
    encrypted = AES.new(secret, AES.MODE_ECB).encrypt(plain + bytes((-len(plain)) % 16))
    body = hashlib.sha256(secret).digest()[:1] + hmac.digest(secret, encrypted, "sha256")[:2] + encrypted
    header = bytes([20 if scoped else 21]) + (bytes(4) if scoped else b"")
    return {"payload": (header + bytes([(width - 1) * 64 + hops]) + b"\xaa" * (hops * width) + body).hex()}


class FeedbackTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = DatabaseManager(":memory:")
        await self.db.connect()
        self.repo = MessageRepository(self.db)
        self.broadcast = AsyncMock()
        self.fb = MeshcoreSendFeedback(self.repo, self.broadcast)

    async def asyncTearDown(self):
        await self.db.disconnect()

    async def bind(self, packet_id, node="broadcast:meshcore"):
        row = await self.repo.save_sent("hello", node, "Bench", "meshcore", packet_id=packet_id)
        return row, await self.fb.bind(packet_id, row, node)

    def channel(self, packet_id=None, sender="Bench", timestamp=100):
        packet_id = packet_id or new_packet_id()
        return packet_id, self.fb.begin_channel(packet_id, CHANNEL, sender, "hello", timestamp)

    async def test_early_echoes_are_kept_and_later_ones_go_live(self):
        pid, item = self.channel()
        await self.fb.observe(frame())
        await self.fb.observe(frame(hops=2, width=3, scoped=True))
        self.broadcast.assert_not_called()  # no row yet
        row, feedback = await self.bind(pid)
        self.assertEqual(feedback["heard_repeats"], 2)
        await self.fb.observe(frame())
        message = (await self.repo.get_conversation("broadcast:meshcore"))[0]
        self.assertEqual((message.heard_repeats, message.status, message.rx_count), (3, "sent", 1))
        event, data = self.broadcast.call_args.args
        self.assertEqual((event, data["id"], data["heard_repeats"]), ("message_repeats", row, 3))

    async def test_unrelated_invalid_and_unrepeated_frames_do_not_count(self):
        _, item = self.channel()
        for payload in [frame(hops=0), frame(timestamp=101), frame(text="Other: hello"),
                        frame(secret=b"x" * 16), {"payload": "zz"}, {"payload": "15"},
                        {"payload": frame()["payload"][:-2]}, {"payload": "00" * 600}]:
            await self.fb.observe(payload)
        bad_mac = bytearray.fromhex(frame()["payload"])
        bad_mac[4] ^= 1
        await self.fb.observe({"payload": bad_mac.hex()})
        self.assertEqual(item.count, 0)

    async def test_two_companions_copies_add_up_on_one_row(self):
        pid = new_packet_id()
        self.fb.begin_channel(pid, CHANNEL, "Bench", "hello", 100)
        self.fb.begin_channel(pid, CHANNEL, "Roof", "hello", 100)
        await self.fb.observe(frame("Bench: hello"))
        await self.fb.observe(frame("Roof: hello"))
        await self.fb.observe(frame("Roof: hello"))
        _, feedback = await self.bind(pid)
        self.assertEqual(feedback["heard_repeats"], 3)

    async def test_same_text_in_another_second_is_another_send(self):
        _, first = self.channel(timestamp=100)
        _, second = self.channel(timestamp=101)
        await self.fb.observe(frame(timestamp=101))
        self.assertEqual((first.count, second.count), (0, 1))

    async def test_dm_ack_before_the_send_response(self):
        pid = new_packet_id()
        item = self.fb.begin_direct(pid)
        await self.fb.acknowledge({"code": "12345678"})
        self.fb.expect_ack(item, {"expected_ack": bytes.fromhex("12345678")})
        _, feedback = await self.bind(pid, "aabbccddeeff")
        self.assertEqual(feedback, {"heard_repeats": None, "status": "delivered"})
        message = (await self.repo.get_conversation("aabbccddeeff"))[0]
        self.assertEqual((message.status, message.heard_repeats), ("delivered", None))

    async def test_dm_ack_later_matches_only_its_own_token(self):
        pid = new_packet_id()
        item = self.fb.begin_direct(pid)
        self.fb.expect_ack(item, {"expected_ack": bytes.fromhex("12345678")})
        await self.bind(pid, "aabbccddeeff")
        await self.fb.acknowledge({"code": "87654321"})
        await self.fb.observe(frame())
        self.assertEqual((item.status, item.count), ("sent", None))
        await self.fb.acknowledge({"code": "12345678"})
        self.assertEqual((await self.repo.get_conversation("aabbccddeeff"))[0].status, "delivered")

    async def test_old_ack_and_expired_or_excess_sends(self):
        await self.fb.acknowledge({"code": "12345678"})
        item = self.fb.begin_direct(new_packet_id())
        self.fb.expect_ack(item, {"expected_ack": bytes.fromhex("12345678")})
        self.assertEqual(item.status, "sent")  # that ACK was for an earlier send
        item.created -= 901
        await self.fb.acknowledge({"code": "12345678"})
        self.assertNotIn(item, self.fb._pending.values())
        for _ in range(140):
            self.fb.begin_direct(new_packet_id())
        self.assertEqual(len(self.fb._pending), 128)

    async def test_counts_never_go_down_and_deleted_rows_stay_deleted(self):
        pid, _ = self.channel()
        row, _ = await self.bind(pid)
        await self.repo.update_meshcore_feedback(row, 9, "sent")
        await self.repo.update_meshcore_feedback(row, 2, "sent")
        self.assertEqual((await self.repo.get_conversation("broadcast:meshcore"))[0].heard_repeats, 9)
        await self.repo.delete_conversation("broadcast:meshcore")
        self.broadcast.reset_mock()
        await self.fb.observe(frame())
        self.broadcast.assert_not_called()

    async def test_received_messages_are_never_touched(self):
        row, _ = await self.repo.save_received(
            text="hi", node_id="aabbccddeeff", node_name="X", protocol="meshcore",
        )
        self.assertFalse(await self.repo.update_meshcore_feedback(row, 5, "delivered"))


class HeardPathTests(unittest.IsolatedAsyncioTestCase):
    """Repeater paths behind "Heard N repeats" (upstream a451d1e2)."""

    async def asyncSetUp(self):
        self.db = DatabaseManager(":memory:")
        await self.db.connect()
        self.repo = MessageRepository(self.db)
        self.fb = MeshcoreSendFeedback(self.repo, AsyncMock())

    async def asyncTearDown(self):
        await self.db.disconnect()

    async def test_paths_signal_and_names_are_saved_and_resolved(self):
        await self.db.execute(
            "INSERT INTO nodes (node_id, long_name, protocol, public_key, last_heard, first_seen) "
            "VALUES (?, ?, 'meshcore', ?, 'x', 'x')",
            ("aabbccddeeff", "Roof repeater", "aa" + "bb" * 31),
        )
        await self.db.commit()
        pid = new_packet_id()
        self.fb.begin_channel(pid, CHANNEL, "Bench", "hello", 100)
        row = await self.repo.save_sent("hello", "broadcast:meshcore", "Bench", "meshcore", packet_id=pid)
        await self.fb.bind(pid, row, "broadcast:meshcore")
        echo = frame()  # path byte 0xaa
        echo.update(rssi=-71.5, snr=4.25)
        await self.fb.observe(echo)
        paths = await self.repo.get_heard_paths(row)
        self.assertEqual((paths["count"], paths["recorded"]), (1, True))
        observation = paths["observations"][0]
        self.assertEqual((observation["rssi"], observation["snr"]), (-71.5, 4.25))
        self.assertEqual(observation["hops"], [{"id": "aa", "name": "Roof repeater", "ambiguous": False}])

    async def test_two_matches_are_ambiguous_and_unknown_stays_unnamed(self):
        for i, key in enumerate(("aa11", "aa22")):
            await self.db.execute(
                "INSERT INTO nodes (node_id, long_name, protocol, public_key, last_heard, first_seen) "
                "VALUES (?, ?, 'meshcore', ?, 'x', 'x')", (f"n{i}", f"R{i}", key + "00" * 30),
            )
        await self.db.commit()
        pid = new_packet_id()
        self.fb.begin_channel(pid, CHANNEL, "Bench", "hello", 100)
        row = await self.repo.save_sent("hello", "broadcast:meshcore", "Bench", "meshcore", packet_id=pid)
        await self.fb.bind(pid, row, "broadcast:meshcore")
        await self.fb.observe(frame(hops=2))  # path aa, aa
        await self.fb.observe(frame(hops=1, width=2))  # path aaaa: nobody
        hops = [o["hops"] for o in (await self.repo.get_heard_paths(row))["observations"]]
        self.assertTrue(hops[0][0]["ambiguous"])
        self.assertEqual(hops[1], [{"id": "aaaa", "name": None, "ambiguous": False}])

    async def test_dm_and_unknown_rows(self):
        pid = new_packet_id()
        self.fb.begin_direct(pid)
        row = await self.repo.save_sent("hi", "aabbccddeeff", "X", "meshcore", packet_id=pid)
        await self.fb.bind(pid, row, "aabbccddeeff")
        self.assertEqual(await self.repo.get_heard_paths(row),
                         {"count": None, "observations": [], "recorded": False})
        self.assertIsNone(await self.repo.get_heard_paths(9999))
        other = await self.repo.save_sent("x", "broadcast:0", "X", "meshtastic")
        self.assertIsNone(await self.repo.get_heard_paths(other))

    async def test_at_most_32_paths_are_kept(self):
        pid = new_packet_id()
        self.fb.begin_channel(pid, CHANNEL, "Bench", "hello", 100)
        row = await self.repo.save_sent("hello", "broadcast:meshcore", "Bench", "meshcore", packet_id=pid)
        await self.fb.bind(pid, row, "broadcast:meshcore")
        for _ in range(40):
            await self.fb.observe(frame())
        paths = await self.repo.get_heard_paths(row)
        self.assertEqual((paths["count"], len(paths["observations"])), (40, 32))


class SendHelperTests(unittest.IsolatedAsyncioTestCase):
    async def test_channel_send_uses_an_explicit_timestamp_and_tracks(self):
        fb = MeshcoreSendFeedback(AsyncMock(), AsyncMock())
        mc = SimpleNamespace(
            self_info={"name": "Bench"},
            commands=SimpleNamespace(
                get_channel=AsyncMock(return_value=SimpleNamespace(payload=CHANNEL)),
                send_chan_msg=AsyncMock(return_value=SimpleNamespace(type=SimpleNamespace(value="ok"))),
            ),
        )
        pid = new_packet_id()
        result = await send_mc_channel_message(mc, 1, "hello", fb, pid)
        self.assertTrue(result.success)
        self.assertEqual(result.heard_repeats, 0)
        ts = mc.commands.send_chan_msg.call_args.kwargs["timestamp"]
        self.assertEqual(fb._copies(pid)[0].timestamp, ts)
        again = await send_mc_channel_message(mc, 1, "hello", fb, new_packet_id())
        self.assertTrue(again.success)
        self.assertGreater(mc.commands.send_chan_msg.call_args.kwargs["timestamp"], ts)

    async def test_untracked_send_is_unchanged(self):
        mc = SimpleNamespace(commands=SimpleNamespace(
            send_chan_msg=AsyncMock(return_value=SimpleNamespace(type=SimpleNamespace(value="ok")))))
        result = await send_mc_channel_message(mc, 1, "hello")
        self.assertTrue(result.success)
        self.assertIsNone(result.heard_repeats)
        mc.commands.send_chan_msg.assert_awaited_once_with(1, "hello")

    async def test_failed_send_is_not_tracked(self):
        fb = MeshcoreSendFeedback(AsyncMock(), AsyncMock())
        mc = SimpleNamespace(commands=SimpleNamespace(send_msg=AsyncMock(side_effect=RuntimeError("boom"))))
        pid = new_packet_id()
        result = await send_mc_direct_message(mc, "aabb", "hello", fb, pid)
        self.assertFalse(result.success)
        self.assertEqual(fb._copies(pid), [])

    async def test_dm_ack_during_send_marks_delivered(self):
        fb = MeshcoreSendFeedback(AsyncMock(), AsyncMock())

        async def send(*args, **kwargs):
            await fb.acknowledge({"code": "12345678"})
            return SimpleNamespace(type=SimpleNamespace(value="msg_sent"),
                                   payload={"expected_ack": bytes.fromhex("12345678")})

        mc = SimpleNamespace(commands=SimpleNamespace(send_msg=AsyncMock(side_effect=send)))
        result = await send_mc_direct_message(mc, "aabb", "hello", fb, new_packet_id())
        self.assertEqual((result.success, result.status), (True, "delivered"))


if __name__ == "__main__":
    unittest.main()
