"""Tests for audio_call.py -- the RNS.Link byte-pipe wrapper, with a
fake RNS.Link/RNS module (rns isn't installed on this Mac, same story
as lxmf_service.py's own tests)."""

from __future__ import annotations

import asyncio
import unittest
from unittest import mock

from plugins.apps.reticulum.backend import audio_call
from plugins.apps.reticulum.backend.audio_call import (
    AudioCall,
    AudioCallManager,
    CallFailedException,
)


class _FakeLink:
    ACTIVE = "active"
    CLOSED = "closed"

    def __init__(self, link_hash: bytes = b"\xaa" * 16, remote_identity=None):
        self.status = _FakeLink.ACTIVE
        self.hash = link_hash
        self._remote_identity = remote_identity
        self._closed_cb = None
        self._packet_cb = None
        self.identify_called_with = None

    def set_link_closed_callback(self, cb):
        self._closed_cb = cb

    def set_packet_callback(self, cb):
        self._packet_cb = cb

    def get_remote_identity(self):
        return self._remote_identity

    def teardown(self):
        self.status = _FakeLink.CLOSED
        if self._closed_cb:
            self._closed_cb(self)

    def identify(self, identity):
        self.identify_called_with = identity

    def deliver_packet(self, data: bytes):
        if self._packet_cb:
            self._packet_cb(data, mock.Mock())


class TestAudioCall(unittest.TestCase):
    def setUp(self):
        self._rns_patch = mock.patch.object(audio_call, "RNS", mock.Mock())
        self.mock_rns = self._rns_patch.start()
        self.addCleanup(self._rns_patch.stop)
        self.mock_rns.Link.ACTIVE = _FakeLink.ACTIVE
        self.mock_rns.Link.MDU = 500
        self.mock_rns.hexrep.side_effect = lambda h, delimit=False: h.hex()

    def test_is_active_reflects_link_status(self):
        link = _FakeLink()
        call = AudioCall(link, is_outbound=True)
        self.assertTrue(call.is_active())
        link.status = _FakeLink.CLOSED
        self.assertFalse(call.is_active())

    def test_send_audio_packet_forwards_via_rns_packet(self):
        link = _FakeLink()
        call = AudioCall(link, is_outbound=True)
        sent = mock.Mock()
        self.mock_rns.Packet.return_value = sent

        call.send_audio_packet(b"abc")

        self.mock_rns.Packet.assert_called_once_with(link, b"abc")
        sent.send.assert_called_once()

    def test_send_audio_packet_drops_oversized_data(self):
        link = _FakeLink()
        call = AudioCall(link, is_outbound=True)
        call.send_audio_packet(b"x" * 501)  # MDU is 500
        self.mock_rns.Packet.assert_not_called()

    def test_send_audio_packet_noop_when_inactive(self):
        link = _FakeLink()
        link.status = _FakeLink.CLOSED
        call = AudioCall(link, is_outbound=True)
        call.send_audio_packet(b"abc")
        self.mock_rns.Packet.assert_not_called()

    def test_incoming_packet_reaches_registered_listeners(self):
        link = _FakeLink()
        call = AudioCall(link, is_outbound=False)
        received = []
        call.register_audio_packet_listener(received.append)
        link.deliver_packet(b"hello")
        self.assertEqual(received, [b"hello"])

    def test_a_raising_listener_does_not_block_others(self):
        link = _FakeLink()
        call = AudioCall(link, is_outbound=False)
        received = []

        def bad_listener(_data):
            raise RuntimeError("boom")

        call.register_audio_packet_listener(bad_listener)
        call.register_audio_packet_listener(received.append)
        link.deliver_packet(b"hello")
        self.assertEqual(received, [b"hello"])

    def test_unregister_stops_delivery(self):
        link = _FakeLink()
        call = AudioCall(link, is_outbound=False)
        received = []
        call.register_audio_packet_listener(received.append)
        call.unregister_audio_packet_listener(received.append)
        link.deliver_packet(b"hello")
        self.assertEqual(received, [])

    def test_hangup_tears_down_the_link_and_fires_hangup_listeners(self):
        link = _FakeLink()
        call = AudioCall(link, is_outbound=True)
        fired = []
        call.register_hangup_listener(lambda: fired.append(True))
        call.hangup()
        self.assertEqual(link.status, _FakeLink.CLOSED)
        self.assertEqual(fired, [True])

    def test_link_hash_hex(self):
        link = _FakeLink(link_hash=b"\xde\xad\xbe\xef")
        call = AudioCall(link, is_outbound=True)
        self.assertEqual(call.link_hash_hex, "deadbeef")


class TestAudioCallManager(unittest.TestCase):
    def setUp(self):
        self._rns_patch = mock.patch.object(audio_call, "RNS", mock.Mock())
        self.mock_rns = self._rns_patch.start()
        self.addCleanup(self._rns_patch.stop)
        self.mock_rns.Link.ACTIVE = _FakeLink.ACTIVE
        self.mock_rns.Link.MDU = 500
        self.mock_rns.hexrep.side_effect = lambda h, delimit=False: h.hex()
        self.mock_rns.Destination.IN = "in"
        self.mock_rns.Destination.OUT = "out"
        self.mock_rns.Destination.SINGLE = "single"
        self.mock_rns.Destination.return_value = mock.Mock(hash=b"\xcc" * 16)

    def test_incoming_call_is_tracked_and_callback_fires(self):
        identity = mock.Mock()
        manager = AudioCallManager(identity)
        seen = []
        manager.register_incoming_call_callback(seen.append)

        link = _FakeLink()
        manager.receiver._client_connected(link)

        self.assertEqual(len(manager.calls), 1)
        self.assertEqual(len(seen), 1)
        self.assertIs(seen[0], manager.calls[0])

    def test_find_by_link_hash_hex(self):
        identity = mock.Mock()
        manager = AudioCallManager(identity)
        link = _FakeLink(link_hash=b"\xbe\xef" * 8)
        manager.receiver._client_connected(link)

        found = manager.find_by_link_hash_hex(link.hash.hex())
        self.assertIsNotNone(found)
        self.assertIsNone(manager.find_by_link_hash_hex("not-hex"))
        self.assertIsNone(manager.find_by_link_hash_hex("aa" * 16))

    def test_hangup_all_tears_down_every_call(self):
        identity = mock.Mock()
        manager = AudioCallManager(identity)
        link1, link2 = _FakeLink(link_hash=b"\x01" * 16), _FakeLink(link_hash=b"\x02" * 16)
        manager.receiver._client_connected(link1)
        manager.receiver._client_connected(link2)

        manager.hangup_all()
        self.assertEqual(link1.status, _FakeLink.CLOSED)
        self.assertEqual(link2.status, _FakeLink.CLOSED)

    def test_initiate_raises_when_no_path_ever_found(self):
        identity = mock.Mock()
        manager = AudioCallManager(identity)
        self.mock_rns.Transport.has_path.return_value = False

        with self.assertRaises(CallFailedException):
            asyncio.run(manager.initiate("aa" * 16, timeout_seconds=-1))

    def test_initiate_raises_when_identity_never_resolves(self):
        identity = mock.Mock()
        manager = AudioCallManager(identity)
        self.mock_rns.Transport.has_path.return_value = True
        self.mock_rns.Identity.recall.return_value = None

        with self.assertRaises(CallFailedException):
            asyncio.run(manager.initiate("aa" * 16, timeout_seconds=-1))

    def test_initiate_success_appends_call_and_identifies_on_link(self):
        identity = mock.Mock()
        manager = AudioCallManager(identity)
        self.mock_rns.Transport.has_path.return_value = True
        self.mock_rns.Identity.recall.return_value = mock.Mock()
        fake_link = _FakeLink()
        self.mock_rns.Link.return_value = fake_link

        call = asyncio.run(manager.initiate("aa" * 16, timeout_seconds=5))

        self.assertIn(call, manager.calls)
        self.assertTrue(call.is_outbound)
        self.assertIs(fake_link.identify_called_with, identity)


if __name__ == "__main__":
    unittest.main()
