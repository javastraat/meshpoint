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

from meshtastic.protobuf import config_pb2, portnums_pb2  # noqa: F401 -- import-time dependency probe

from src.capture.serial_source import SerialCaptureSource, _default_frequency_mhz


class ReadRadioInfoLongFastPresetTest(unittest.TestCase):
    """The common case: a node running a named modem preset."""

    def test_eu433_longfast_preset(self):
        iface = MagicMock()
        iface.localNode.localConfig.lora.channel_num = 0
        iface.localNode.localConfig.lora.region = 2  # EU_433
        iface.localNode.localConfig.lora.use_preset = True
        iface.localNode.localConfig.lora.modem_preset = 0  # LONG_FAST
        iface.getShortName.return_value = "EMC3"
        iface.getLongName.return_value = "Meshpoint433"

        info = SerialCaptureSource._read_radio_info(iface)

        self.assertEqual(info["region"], "EU_433")
        self.assertEqual(info["channel_num"], 0)
        self.assertEqual(info["modem_preset"], "LONG_FAST")
        self.assertEqual(info["spreading_factor"], 11)
        self.assertEqual(info["bandwidth_khz"], 250)
        self.assertEqual(info["coding_rate"], "4/5")
        self.assertEqual(info["short_name"], "EMC3")
        self.assertEqual(info["long_name"], "Meshpoint433")

    def test_default_frequency_matches_eu433_preset_default_channel(self):
        # channel_num=0 is the firmware's hash-derived default channel;
        # 433.875 MHz is the documented EU_433 LongFast default.
        self.assertEqual(_default_frequency_mhz("EU_433", 0), 433.875)

    def test_default_frequency_matches_eu868_preset_default_channel(self):
        self.assertEqual(_default_frequency_mhz("EU_868", 0), 869.525)


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
        iface.getShortName.return_value = "CUST"
        iface.getLongName.return_value = "CustomNode"

        info = SerialCaptureSource._read_radio_info(iface)

        self.assertEqual(info["modem_preset"], "CUSTOM")
        self.assertEqual(info["spreading_factor"], 9)
        self.assertEqual(info["bandwidth_khz"], 125.0)
        self.assertEqual(info["coding_rate"], "4/6")

    def test_non_default_channel_num_yields_unknown_frequency(self):
        # A non-zero channel_num means the true frequency depends on
        # the firmware's channel-name hash, not replicated here --
        # 0.0 (this codebase's "unknown" sentinel), not a guess.
        self.assertEqual(_default_frequency_mhz("EU_868", 3), 0.0)


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

    def test_known_portnum_resolves_and_decodes_payload(self):
        payload = base64.b64encode(b"\x01\x02\x03").decode()
        pre = SerialCaptureSource._build_pre_decoded({
            "decoded": {"portnum": "TELEMETRY_APP", "payload": payload, "requestId": 7},
        })
        self.assertIsNotNone(pre)
        self.assertEqual(pre["portnum"], portnums_pb2.PortNum.TELEMETRY_APP)
        self.assertEqual(pre["payload"], b"\x01\x02\x03")
        self.assertEqual(pre["request_id"], 7)

    def test_unrecognized_portnum_name_returns_none(self):
        pre = SerialCaptureSource._build_pre_decoded({
            "decoded": {"portnum": "NOT_A_REAL_PORTNUM_XYZ", "payload": ""},
        })
        self.assertIsNone(pre)

    def test_missing_payload_yields_empty_bytes_not_error(self):
        pre = SerialCaptureSource._build_pre_decoded({
            "decoded": {"portnum": "NODEINFO_APP"},
        })
        self.assertIsNotNone(pre)
        self.assertEqual(pre["payload"], b"")
        self.assertEqual(pre["request_id"], 0)


if __name__ == "__main__":
    unittest.main()
