"""Tests for SerialCaptureSource (Meshtastic USB capture).

Covers the T5 multi-stick support: per-device ``label`` -> ``name`` /
``capture_source`` tagging, and the pypubsub cross-talk guard needed
because meshtastic-python publishes every open SerialInterface's
packets on one process-wide topic ("meshtastic.receive"). Also covers
two pre-existing bugs caught live the first time a `serial` source ran
for real (2026-07-09): meshtastic-python always sets packet["raw"] to
the actual MeshPacket protobuf object, never bytes, so the old
truthiness check never triggered the reconstruction fallback -- and
that fallback itself read the wrong dict key/encoding for the
encrypted payload.
"""

from __future__ import annotations

import asyncio
import base64
import struct
import unittest

from src.capture.serial_source import SerialCaptureSource


class _FakeMeshPacket:
    """Stand-in for the real meshtastic.protobuf.mesh_pb2.MeshPacket.

    Not bytes, not str -- exactly what packet["raw"] always actually is
    (mesh_interface.py explicitly does asDict["raw"] = meshPacket), so
    the old `if not raw_bytes` check saw a truthy non-bytes object and
    let it flow downstream, crashing the pipeline decoder's len() call.
    """


class SerialCaptureSourceNamingTest(unittest.TestCase):
    def test_unlabelled_name_is_plain_serial(self):
        source = SerialCaptureSource(port="/dev/ttyUSB0")
        self.assertEqual(source.name, "serial")

    def test_labelled_name_includes_label(self):
        source = SerialCaptureSource(port="/dev/ttyUSB0", label="433")
        self.assertEqual(source.name, "serial_433")

    def test_packet_capture_source_matches_name(self):
        source = SerialCaptureSource(port="/dev/ttyUSB1", label="868")
        raw = source._packet_to_raw_capture({"raw": "aabbccddeeff"})
        self.assertIsNotNone(raw)
        self.assertEqual(raw.capture_source, "serial_868")


class SerialCaptureSourceProtobufRawFieldTest(unittest.TestCase):
    """packet["raw"] is always a MeshPacket protobuf object, never bytes."""

    def test_non_bytes_raw_falls_back_to_reconstruction_instead_of_crashing(self):
        source = SerialCaptureSource(port="/dev/ttyUSB1", label="433")
        payload = base64.b64encode(b"\x01\x02\x03").decode()
        packet = {
            "raw": _FakeMeshPacket(),
            "decoded": {"portnum": "TEXT_MESSAGE_APP"},
            "to": 0xFFFFFFFF,
            "from": 12345,
            "id": 999,
            "hopLimit": 3,
            "hopStart": 3,
            "channel": 0,
            "encrypted": payload,
            "rxRssi": -90,
            "rxSnr": 5.5,
        }

        raw = source._packet_to_raw_capture(packet)

        self.assertIsNotNone(raw)
        self.assertEqual(raw.payload[-3:], b"\x01\x02\x03")

    def test_encrypted_only_packet_without_decoded_key_is_still_captured(self):
        # "decoded" and "encrypted" share one protobuf oneof: a packet
        # the connected stick's OWN key couldn't decrypt (e.g. traffic
        # on a channel it isn't configured for) has "encrypted" set and
        # NO "decoded" key at all. Gating reconstruction on "decoded"
        # being present silently dropped exactly this case -- the one a
        # passive multi-channel sniffer most needs, since MeshPoint's
        # own channel_keys config may decrypt what the stick couldn't.
        source = SerialCaptureSource(port="/dev/ttyUSB1", label="433")
        payload = base64.b64encode(b"\xaa\xbb").decode()
        packet = {
            "raw": _FakeMeshPacket(),
            "to": 0xFFFFFFFF, "from": 1, "id": 2,
            "encrypted": payload,
        }

        raw = source._packet_to_raw_capture(packet)

        self.assertIsNotNone(raw)
        self.assertEqual(raw.payload[-2:], b"\xaa\xbb")

    def test_packet_with_no_recognizable_fields_still_yields_header_only_frame(self):
        # _reconstruct_raw defaults every field it reads, so it never
        # actually returns empty bytes -- even a near-empty packet dict
        # yields a minimal (all-default) header, never None.
        source = SerialCaptureSource(port="/dev/ttyUSB1")
        raw = source._packet_to_raw_capture({"raw": _FakeMeshPacket()})
        self.assertIsNotNone(raw)
        self.assertEqual(len(raw.payload), 16)


class ReconstructRawTest(unittest.TestCase):
    """_reconstruct_raw must read the real MessageToDict key/encoding.

    google.protobuf.json_format.MessageToDict base64-encodes bytes
    fields and names the payload field "encrypted" (verified against
    the installed meshtastic.protobuf.mesh_pb2.MeshPacket descriptor)
    -- not "encoded"/hex, which never matched any real key.
    """

    def test_encrypted_field_is_base64_decoded_into_payload_tail(self):
        payload_bytes = b"\xde\xad\xbe\xef"
        packet = {
            "to": 0xFFFFFFFF,
            "from": 42,
            "id": 7,
            "hopLimit": 3,
            "hopStart": 3,
            "channel": 1,
            "encrypted": base64.b64encode(payload_bytes).decode(),
        }

        frame = SerialCaptureSource._reconstruct_raw(packet)

        header = struct.unpack("<III", frame[:12])
        self.assertEqual(header, (0xFFFFFFFF, 42, 7))
        # flags = hop_limit(3) | hop_start(3) << 5 = 0x63; channel = 1.
        self.assertEqual(frame[12:16], bytes([0x63, 1, 0, 0]))
        self.assertEqual(frame[16:], payload_bytes)

    def test_missing_encrypted_key_yields_header_only_frame(self):
        # The locally-decrypted case: encrypted/decoded share one
        # protobuf oneof, so a packet the stick's own key already
        # decrypted has no ciphertext left -- header-only is expected,
        # not a bug (matches the method's own docstring).
        frame = SerialCaptureSource._reconstruct_raw({"to": 1, "from": 2, "id": 3})
        self.assertEqual(len(frame), 16)


class _FakeInterface:
    """Stand-in for meshtastic.serial_interface.SerialInterface."""


class SerialCaptureSourcePubsubGuardTest(unittest.IsolatedAsyncioTestCase):
    """Two SerialCaptureSource instances share one pypubsub topic.

    Without an identity check in ``_on_receive``, instance A's callback
    would also fire for instance B's packets (and vice versa), so a
    two-stick setup would duplicate and cross-attribute captures. This
    verifies the guard filters by interface identity.
    """

    async def test_ignores_packets_from_a_different_interface(self):
        source = SerialCaptureSource(port="/dev/ttyUSB0", label="433")
        source._running = True
        source._interface = _FakeInterface()
        other_interface = _FakeInterface()

        source._on_receive({"raw": "aabbcc"}, other_interface)

        self.assertTrue(source._queue.empty())

    async def test_accepts_packets_from_its_own_interface(self):
        source = SerialCaptureSource(port="/dev/ttyUSB0", label="433")
        source._running = True
        source._interface = _FakeInterface()

        source._on_receive({"raw": "aabbcc"}, source._interface)

        self.assertFalse(source._queue.empty())
        raw = await asyncio.wait_for(source._queue.get(), timeout=1.0)
        self.assertEqual(raw.capture_source, "serial_433")

    async def test_ignores_packets_when_not_running(self):
        source = SerialCaptureSource(port="/dev/ttyUSB0")
        source._interface = _FakeInterface()
        source._running = False

        source._on_receive({"raw": "aabbcc"}, source._interface)

        self.assertTrue(source._queue.empty())


class BuildPreDecodedEarlyExitTest(unittest.TestCase):
    """_build_pre_decoded's early-exit paths (no real meshtastic import
    reached, so these run without the package installed -- the
    portnum-resolution success path needs the real
    meshtastic.protobuf.portnums_pb2 enum and lives in
    test_serial_radio_handshake.py instead, alongside this module's
    other real-library-dependent tests."""

    def test_no_decoded_key_returns_none(self):
        self.assertIsNone(SerialCaptureSource._build_pre_decoded({"raw": "aa"}))

    def test_decoded_not_a_dict_returns_none(self):
        self.assertIsNone(
            SerialCaptureSource._build_pre_decoded({"decoded": "not-a-dict"})
        )

    def test_decoded_missing_portnum_returns_none(self):
        self.assertIsNone(
            SerialCaptureSource._build_pre_decoded({"decoded": {"payload": "AQI="}})
        )


class DropSelfOriginatedPacketTest(unittest.TestCase):
    """A stick's own self-telemetry/nodeinfo passes through the same
    "meshtastic.receive" stream as genuinely received packets --
    meshtastic-python doesn't distinguish them, and firmware's own
    rx_rssi==rx_snr==0 convention confirms there's no real signal for
    a node reporting on itself. These must be dropped before any other
    processing (decode/storage/packet feed/node counters), not just
    hidden cosmetically.
    """

    def test_packet_from_own_node_is_dropped(self):
        source = SerialCaptureSource(port="/dev/ttyUSB1", label="433")
        source._radio_info = {"own_node_num": 0x09D406F4}

        result = source._packet_to_raw_capture({
            "from": 0x09D406F4, "to": 0xFFFFFFFF,
            "decoded": {"portnum": "TELEMETRY_APP", "payload": ""},
        })

        self.assertIsNone(result)

    def test_self_originated_text_message_is_not_dropped(self):
        # A message typed via a BLE/WiFi-connected app on this same
        # physical stick is genuine chat content, not a beacon -- it
        # must still reach decode/storage/Messages even though this
        # stick is also the packet's "from" node.
        source = SerialCaptureSource(port="/dev/ttyUSB1", label="433")
        source._radio_info = {"own_node_num": 0x09D406F4}

        result = source._packet_to_raw_capture({
            "from": 0x09D406F4, "to": 0xFFFFFFFF, "raw": "aabbccddeeff",
            "decoded": {"portnum": "TEXT_MESSAGE_APP", "payload": ""},
        })

        self.assertIsNotNone(result)

    def test_packet_from_a_remote_node_is_not_dropped(self):
        source = SerialCaptureSource(port="/dev/ttyUSB1", label="433")
        source._radio_info = {"own_node_num": 0x09D406F4}

        result = source._packet_to_raw_capture({
            "from": 0xAABBCCDD, "to": 0xFFFFFFFF, "raw": "aabbccddeeff",
        })

        self.assertIsNotNone(result)

    def test_unknown_own_node_num_does_not_drop_anything(self):
        # Handshake hasn't populated own_node_num yet -- must not
        # accidentally treat every packet (or none) as self-originated.
        source = SerialCaptureSource(port="/dev/ttyUSB1", label="433")
        source._radio_info = {"own_node_num": None}

        result = source._packet_to_raw_capture({
            "from": 0x09D406F4, "to": 0xFFFFFFFF, "raw": "aabbccddeeff",
        })

        self.assertIsNotNone(result)

    def test_missing_from_field_does_not_crash(self):
        source = SerialCaptureSource(port="/dev/ttyUSB1", label="433")
        source._radio_info = {"own_node_num": 0x09D406F4}

        result = source._packet_to_raw_capture({"raw": "aabbccddeeff"})

        self.assertIsNotNone(result)


if __name__ == "__main__":
    unittest.main()
