"""Meshtastic RX preamble on the SX1302 LoRa service modem.

Ported from upstream KMX415/meshpoint fcacc92b (#179), as unittest (the Pi
venv has no pytest). One deliberate difference: a failed write/read-back
logs an error and keeps the concentrator running on the HAL default,
where upstream stops it.
"""

from __future__ import annotations

import ctypes
import unittest
from unittest.mock import MagicMock, patch

from src.hal.concentrator_config import ChannelConfig, ConcentratorChannelPlan
from src.hal.sx1302_wrapper import SX1302Wrapper


def make_wrapper(enabled=True):
    w = SX1302Wrapper()
    lib = MagicMock()
    registers = {}

    def start():
        registers.update({916: 8, 917: 0})  # lgw_start() resets to the HAL default
        return 0

    def write(reg, value):
        registers[reg] = value
        return 0

    def read(reg, ptr):
        ctypes.cast(ptr, ctypes.POINTER(ctypes.c_int32))[0] = registers[reg]
        return 0

    lib.lgw_start.side_effect = start
    lib.lgw_reg_w.side_effect = write
    lib.lgw_reg_r.side_effect = read
    w._lib = lib
    w._service_modem_enabled = enabled
    return w, lib, registers


def configure(w, channel):
    plan = ConcentratorChannelPlan()
    plan.single_sf_channel = channel
    with patch.object(w, "_configure_board"), patch.object(w, "_configure_rf_chains"), \
         patch.object(w, "_configure_if_channels"), \
         patch.object(w, "_configure_sx1261_for_spectral_scan"):
        w.configure(plan)


class TestServicePreamble(unittest.TestCase):
    def test_every_start_sets_16_again(self):
        w, lib, registers = make_wrapper()
        for _ in range(2):  # start, then a restart: lgw_start() resets it each time
            w.start()
            self.assertTrue(w._started)
            self.assertEqual(registers, {916: 16, 917: 0})
            w.stop()
        self.assertEqual(
            [c.args for c in lib.lgw_reg_w.call_args_list], [(916, 16), (917, 0)] * 2
        )
        self.assertEqual(lib.lgw_reg_w.argtypes, [ctypes.c_uint16, ctypes.c_int32])
        lib.lgw_send.assert_not_called()
        lib.lgw_txgain_setconf.assert_not_called()

    def test_without_service_channel_registers_are_untouched(self):
        for channel in (None, ChannelConfig(frequency_hz=869_525_000, enabled=False)):
            with self.subTest(channel=channel):
                w, lib, _ = make_wrapper()
                configure(w, channel)
                w.start()
                lib.lgw_reg_w.assert_not_called()
                lib.lgw_reg_r.assert_not_called()

    def test_enabled_service_channel_sets_it_after_lgw_start(self):
        w, lib, registers = make_wrapper(enabled=False)
        configure(w, ChannelConfig(frequency_hz=869_525_000))
        w.start()
        self.assertEqual(registers, {916: 16, 917: 0})
        calls = [c[0] for c in lib.mock_calls]
        self.assertLess(calls.index("lgw_start"), calls.index("lgw_reg_w"))
        self.assertLess(calls.index("lgw_reg_w"), calls.index("lgw_reg_r"))

    def test_failure_is_logged_and_receiving_continues(self):
        for failure in ("write", "read", "mismatch", "missing"):
            with self.subTest(failure=failure):
                w, lib, _ = make_wrapper()
                if failure == "write":
                    lib.lgw_reg_w.side_effect = None
                    lib.lgw_reg_w.return_value = -1
                elif failure == "read":
                    lib.lgw_reg_r.side_effect = None
                    lib.lgw_reg_r.return_value = -1
                elif failure == "mismatch":
                    lib.lgw_reg_r.side_effect = None
                    lib.lgw_reg_r.return_value = 0  # reads back 0, not 16
                else:
                    del lib.lgw_reg_w
                with self.assertLogs("src.hal.sx1302_wrapper", level="ERROR") as logs:
                    w.start()
                self.assertTrue(w._started)
                lib.lgw_stop.assert_not_called()
                self.assertIn("RX preamble", logs.output[0])

    def test_failed_hal_start_never_touches_registers(self):
        w, lib, _ = make_wrapper()
        lib.lgw_start.side_effect = None
        lib.lgw_start.return_value = -1
        with self.assertRaises(RuntimeError):
            w.start()
        lib.lgw_reg_w.assert_not_called()
        self.assertFalse(w._started)


if __name__ == "__main__":
    unittest.main()
