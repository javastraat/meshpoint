"""Tests for SerialCaptureSource's connect-time radio handshake.

Needs the real ``meshtastic`` package (protobuf enums for region and
modem preset) -- CI-only, same convention as
test_multi_serial_pipeline_server.py needing fastapi. ``meshtastic`` is
a declared dependency (requirements.txt), so CI has it; a bare Mac
python3 (no venv) does not -- verify locally with a venv/interpreter
that has it installed (e.g. `/opt/homebrew/bin/python3.11` if
meshtastic was pip-installed there).
"""

from __future__ import annotations

import base64
import unittest
from unittest.mock import MagicMock

from meshtastic.protobuf import channel_pb2, config_pb2, portnums_pb2  # noqa: F401 -- import-time dependency probe

from src.capture.serial_source import SerialCaptureSource
from src.radio.channel_frequency import resolve_frequency_mhz


def _mock_primary_channel(name: str):
    ch = MagicMock()
    ch.role = channel_pb2.Channel.Role.PRIMARY
    ch.settings.name = name
    return ch


class ReadRadioInfoLongFastPresetTest(unittest.TestCase):
    """The common case: a node running a named modem preset."""

    def test_eu433_longfast_preset(self):
        iface = MagicMock()
        iface.localNode.localConfig.lora.channel_num = 0
        iface.localNode.localConfig.lora.region = 2  # EU_433
        iface.localNode.localConfig.lora.use_preset = True
        iface.localNode.localConfig.lora.modem_preset = 0  # LONG_FAST
        iface.localNode.localConfig.lora.frequency_offset = 0.0
        iface.localNode.localConfig.lora.override_frequency = 0.0
        iface.localNode.channels = [_mock_primary_channel("")]
        iface.getShortName.return_value = "EMC3"
        iface.getLongName.return_value = "Meshpoint433"
        iface.myInfo.my_node_num = 0x09D406F4

        info = SerialCaptureSource._read_radio_info(iface)

        self.assertEqual(info["region"], "EU_433")
        self.assertEqual(info["channel_num"], 0)
        self.assertEqual(info["modem_preset"], "LONG_FAST")
        self.assertTrue(info["use_preset"])
        self.assertEqual(info["channel_name"], "")
        self.assertEqual(info["spreading_factor"], 11)
        self.assertEqual(info["bandwidth_khz"], 250)
        self.assertEqual(info["coding_rate"], "4/5")
        self.assertEqual(info["short_name"], "EMC3")
        self.assertEqual(info["long_name"], "Meshpoint433")
        self.assertEqual(info["own_node_num"], 0x09D406F4)

    def test_reads_primary_channel_name_when_set(self):
        iface = MagicMock()
        iface.localNode.channels = [
            _mock_primary_channel("MyCustomChannel"),
        ]
        name = SerialCaptureSource._read_primary_channel_name(iface)
        self.assertEqual(name, "MyCustomChannel")

    def test_default_frequency_matches_eu433_preset_default_channel(self):
        # channel_num=0 (default/hash-derived), blank channel name (the
        # common stock-setup case), LongFast preset -- reproduces the
        # exact value observed live on a real EU_433 device.
        freq = resolve_frequency_mhz(
            region="EU_433", channel_num=0, bandwidth_khz=250,
            channel_name="", modem_preset="LONG_FAST", use_preset=True,
        )
        self.assertEqual(freq, 433.875)

    def test_default_frequency_matches_eu868_preset_default_channel(self):
        # EU_868's band only fits one 250kHz slot, so this is
        # deterministic regardless of channel name.
        freq = resolve_frequency_mhz(
            region="EU_868", channel_num=0, bandwidth_khz=250,
            channel_name="AnythingAtAll", modem_preset="LONG_FAST",
        )
        self.assertEqual(freq, 869.525)


class ReadRadioInfoCustomConfigTest(unittest.TestCase):
    """use_preset=False: read the raw spread_factor/bandwidth/coding_rate."""

    def test_custom_config_reads_raw_fields(self):
        iface = MagicMock()
        iface.localNode.localConfig.lora.channel_num = 3
        iface.localNode.localConfig.lora.region = 3  # EU_868
        iface.localNode.localConfig.lora.use_preset = False
        iface.localNode.localConfig.lora.spread_factor = 9
        iface.localNode.localConfig.lora.bandwidth = 125
        iface.localNode.localConfig.lora.coding_rate = 6
        iface.localNode.localConfig.lora.frequency_offset = 0.0
        iface.localNode.localConfig.lora.override_frequency = 0.0
        iface.localNode.channels = [_mock_primary_channel("")]
        iface.getShortName.return_value = "CUST"
        iface.getLongName.return_value = "CustomNode"

        info = SerialCaptureSource._read_radio_info(iface)

        self.assertEqual(info["modem_preset"], "CUSTOM")
        self.assertFalse(info["use_preset"])
        self.assertEqual(info["spreading_factor"], 9)
        self.assertEqual(info["bandwidth_khz"], 125.0)
        self.assertEqual(info["coding_rate"], "4/6")

    def test_non_default_channel_num_uses_explicit_slot(self):
        # channel_num=3 (1-based, protobuf convention) -> zero-based
        # slot 2 -- an explicit slot no longer needs the channel-name
        # hash at all.
        freq = resolve_frequency_mhz(
            region="EU_433", channel_num=3, bandwidth_khz=250,
        )
        self.assertEqual(freq, 433.625)

    def test_unsupported_region_yields_unknown_frequency(self):
        # EU_866 uses nonzero spacing/padding (PROFILE_LITE), not
        # modelled here -- 0.0 (this codebase's "unknown" sentinel),
        # not a guess.
        freq = resolve_frequency_mhz(region="EU_866", channel_num=0, bandwidth_khz=250)
        self.assertEqual(freq, 0.0)


class ReadRadioInfoFailureIsolationTest(unittest.TestCase):
    def test_broken_interface_returns_none_filled_dict_not_raise(self):
        iface = MagicMock()
        del iface.localNode  # attribute access now raises AttributeError
        iface.getShortName.side_effect = Exception("boom")

        info = SerialCaptureSource._read_radio_info(iface)

        self.assertIsNone(info["region"])
        self.assertIsNone(info["channel_num"])
        self.assertIsNone(info["short_name"])


class BuildPreDecodedTest(unittest.TestCase):
    """Locally-decoded packets (meshtastic-python's own key succeeded)
    carry real portnum + payload in packet["decoded"] -- previously
    thrown away, showing as "Unknown" even though the content was
    right there. Verifies the real enum-name -> int resolution and
    base64 payload decode against the actual portnums_pb2 descriptor.
    """

    def setUp(self):
        self.source = SerialCaptureSource(port="/dev/ttyUSB1", label="433")

    def test_known_portnum_resolves_and_decodes_payload(self):
        payload = base64.b64encode(b"\x01\x02\x03").decode()
        pre = self.source._build_pre_decoded({
            "decoded": {"portnum": "TELEMETRY_APP", "payload": payload, "requestId": 7},
        })
        self.assertIsNotNone(pre)
        self.assertEqual(pre["portnum"], portnums_pb2.PortNum.TELEMETRY_APP)
        self.assertEqual(pre["payload"], b"\x01\x02\x03")
        self.assertEqual(pre["request_id"], 7)

    def test_unrecognized_portnum_name_returns_none(self):
        pre = self.source._build_pre_decoded({
            "decoded": {"portnum": "NOT_A_REAL_PORTNUM_XYZ", "payload": ""},
        })
        self.assertIsNone(pre)

    def test_missing_payload_yields_empty_bytes_not_error(self):
        pre = self.source._build_pre_decoded({
            "decoded": {"portnum": "NODEINFO_APP"},
        })
        self.assertIsNotNone(pre)
        self.assertEqual(pre["payload"], b"")
        self.assertEqual(pre["request_id"], 0)

    def test_resolves_channel_index_to_name_via_channel_table(self):
        # F1: packet["channel"] is THIS STICK's own local channel-table
        # index for a locally-decoded packet (mesh_interface.py sets
        # meshPacket.channel = channelIndex symmetrically on send) --
        # not the real on-air channel_hash. _build_pre_decoded must
        # resolve it to a NAME via the connect-time channel table
        # rather than let a caller mistake the bare index for a hash.
        self.source._radio_info["channel_table"] = {0: "LongFast", 2: "PD2EMC"}
        pre = self.source._build_pre_decoded({
            "decoded": {"portnum": "TEXT_MESSAGE_APP", "payload": ""},
            "channel": 2,
        })
        self.assertEqual(pre["channel_name"], "PD2EMC")

    def test_unresolvable_channel_index_omits_channel_name(self):
        # No channel_table entry for this index (e.g. handshake never
        # populated it, or the stick has fewer channels than this
        # index implies) -- must not fabricate a name, and must not
        # raise either.
        self.source._radio_info["channel_table"] = {0: "LongFast"}
        pre = self.source._build_pre_decoded({
            "decoded": {"portnum": "TEXT_MESSAGE_APP", "payload": ""},
            "channel": 5,
        })
        self.assertIsNotNone(pre)
        self.assertNotIn("channel_name", pre)


class ReadChannelTableTest(unittest.TestCase):
    """F1: index -> name mapping for a stick's own channel table, read
    at connect time so a locally-decoded packet's bare channel index
    can be resolved to something meaningful instead of being mistaken
    for a real over-the-air channel_hash."""

    @staticmethod
    def _channel(index, role, name):
        ch = MagicMock()
        ch.index = index
        ch.role = role
        ch.settings.name = name
        return ch

    def test_builds_index_to_name_map_skipping_disabled(self):
        R = channel_pb2.Channel.Role
        channels = [
            self._channel(0, R.PRIMARY, "Home"),
            self._channel(1, R.SECONDARY, "BayMesh"),
            self._channel(2, R.DISABLED, "Unused"),
        ]
        iface = MagicMock()
        iface.localNode.channels = channels

        table = SerialCaptureSource._read_channel_table(iface, modem_preset_name="LongFast")

        self.assertEqual(table, {0: "Home", 1: "BayMesh"})

    def test_blank_primary_name_falls_back_to_modem_preset(self):
        # Mirrors firmware's own Channels::getName() convention (same
        # fallback _read_primary_channel_name's docstring documents)
        # -- the common stock-setup case where the primary channel's
        # own name is left blank.
        R = channel_pb2.Channel.Role
        channels = [self._channel(0, R.PRIMARY, "")]
        iface = MagicMock()
        iface.localNode.channels = channels

        table = SerialCaptureSource._read_channel_table(iface, modem_preset_name="LongFast")

        self.assertEqual(table, {0: "LongFast"})

    def test_blank_secondary_name_is_skipped_not_guessed(self):
        R = channel_pb2.Channel.Role
        channels = [
            self._channel(0, R.PRIMARY, "Home"),
            self._channel(1, R.SECONDARY, ""),
        ]
        iface = MagicMock()
        iface.localNode.channels = channels

        table = SerialCaptureSource._read_channel_table(iface, modem_preset_name="LongFast")

        self.assertEqual(table, {0: "Home"})


class ResolveChannelIndexTest(unittest.TestCase):
    """F3: translating Meshpoint's own channel name to THIS stick's own
    channel-table index for an outbound reply, refusing rather than
    guessing when the stick has no channel by that name."""

    def test_finds_index_for_known_name(self):
        source = SerialCaptureSource(port="/dev/ttyUSB1", label="433")
        source._radio_info["channel_table"] = {0: "LongFast", 2: "PD2EMC"}

        self.assertEqual(source.resolve_channel_index("PD2EMC"), 2)

    def test_returns_none_for_unknown_name(self):
        source = SerialCaptureSource(port="/dev/ttyUSB1", label="433")
        source._radio_info["channel_table"] = {0: "LongFast"}

        self.assertIsNone(source.resolve_channel_index("SomeOtherChannel"))

    def test_returns_none_when_channel_table_never_populated(self):
        source = SerialCaptureSource(port="/dev/ttyUSB1", label="433")

        self.assertIsNone(source.resolve_channel_index("LongFast"))


if __name__ == "__main__":
    unittest.main()
