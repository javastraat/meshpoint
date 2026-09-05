"""Tests for DapnetSerialSource's pure logic (naming, status cache,
JSON-line parsing) -- not its threaded serial I/O, which needs a real
serial.Serial object and isn't exercised here.

Pure Python, no FastAPI.
"""

from __future__ import annotations

import unittest

from plugins.apps.dapnet.backend.listener import DapnetSerialSource, _parse_json_line


class TestName(unittest.TestCase):
    def test_bare_name_with_no_label(self) -> None:
        source = DapnetSerialSource(serial_port="/dev/ttyUSB0")
        self.assertEqual(source.name, "dapnet")

    def test_labeled_name(self) -> None:
        source = DapnetSerialSource(serial_port="/dev/ttyUSB0", label="ttgo")
        self.assertEqual(source.name, "dapnet_ttgo")


class TestStatusAndCallsign(unittest.TestCase):
    def test_status_starts_empty(self) -> None:
        source = DapnetSerialSource()
        self.assertEqual(source.status, {})

    def test_note_new_callsign_updates_status_without_clobbering_other_fields(self) -> None:
        source = DapnetSerialSource()
        source._status = {"board": "heltec_v3", "callsign": "OLD"}
        source.note_new_callsign("PD2EMC")
        self.assertEqual(source.status["callsign"], "PD2EMC")
        self.assertEqual(source.status["board"], "heltec_v3")

    def test_not_connected_or_running_before_start(self) -> None:
        source = DapnetSerialSource()
        self.assertFalse(source.connected)
        self.assertFalse(source.is_running)


class TestParseJsonLine(unittest.TestCase):
    def test_valid_json_object(self) -> None:
        self.assertEqual(_parse_json_line(b'{"capcode": 1}\n'), {"capcode": 1})

    def test_plain_text_boot_banner_returns_none(self) -> None:
        self.assertIsNone(_parse_json_line(b"WiFi connected\n"))

    def test_blank_line_returns_none(self) -> None:
        self.assertIsNone(_parse_json_line(b"\n"))

    def test_json_array_is_not_a_dict_returns_none(self) -> None:
        self.assertIsNone(_parse_json_line(b"[1, 2, 3]\n"))

    def test_malformed_json_returns_none(self) -> None:
        self.assertIsNone(_parse_json_line(b'{"capcode": \n'))

    def test_cheap_first_byte_check_skips_json_loads_for_non_brace_lines(self) -> None:
        # Not directly observable from the return value, but confirms a
        # plain-text line doesn't crash even if it happens to contain
        # JSON-special characters elsewhere in the line.
        self.assertIsNone(_parse_json_line(b'SEND BLOCKED: no callsign {set}\n'))


class TestStartWithoutPort(unittest.IsolatedAsyncioTestCase):
    async def test_start_without_serial_port_configured_does_not_raise(self) -> None:
        source = DapnetSerialSource(serial_port=None)
        await source.start()
        self.assertFalse(source.is_running)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
