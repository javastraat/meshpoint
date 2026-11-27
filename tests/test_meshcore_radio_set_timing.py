"""Set Radio from the dashboard: give the port and the companion time (TODO 51).

Live on rakv21 (Heltec V4.3, native USB), the exclusive radio change always
failed with "MeshCore handshake failed during exclusive radio set": it pulsed
DTR the moment the live connection was closed, opened 2 s later and got no
answer to the library's fixed 2 s handshake, then retried with DTR inverted
straight away. The normal reconnect, which waits 5 s after closing before it
pulses, connects fine on the same board. So: wait after detaching before the
pulse, and pause before the DTR-inverted retry like the library's own
create_serial() does.

These tests only pin the order and the pauses; whether the board answers is
the Pi test.
"""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.capture import meshcore_usb_source as mus
from src.capture.meshcore_usb_source import MeshcoreUsbCaptureSource
from src.transmit.meshcore_tx_client import RadioStatus, SendResult

_real_sleep = asyncio.sleep


class Recorder:
    def __init__(self) -> None:
        self.events: list[tuple] = []

    async def sleep(self, seconds, *args, **kwargs):
        self.events.append(("sleep", seconds))
        await _real_sleep(0)

    def first(self, name, pred=lambda e: True) -> int:
        for i, e in enumerate(self.events):
            if e[0] == name and pred(e):
                return i
        raise AssertionError(f"no {name} in {self.events}")


class ExclusiveApplyOrderTests(unittest.IsolatedAsyncioTestCase):
    async def test_waits_after_detach_before_pulsing_and_before_opening(self):
        rec = Recorder()
        source = MeshcoreUsbCaptureSource(serial_port="/dev/fake")
        source._running = True
        source._connected = True
        source._resolved_port = "/dev/fake"
        source._meshcore = AsyncMock()

        async def disconnect():
            rec.events.append(("disconnect",))
            source._connected = False
            source._meshcore = None

        async def open_meshcore(timeout, port=None, keep=None):
            rec.events.append(("open", port))
            return AsyncMock()

        async def set_params(mc, freq, bw, sf, cr):
            return SendResult(success=True)

        async def radio_status(mc):
            return RadioStatus(frequency_mhz=869.618, bandwidth_khz=62.5, spreading_factor=8, coding_rate=8)

        with patch("asyncio.sleep", rec.sleep), \
             patch.object(source, "_disconnect", disconnect), \
             patch.object(source, "_open_meshcore", open_meshcore), \
             patch.object(source, "_reattach_after_exclusive_radio_apply", AsyncMock()), \
             patch.object(mus, "send_set_radio_params", set_params), \
             patch.object(mus, "read_radio_status", radio_status), \
             patch("src.capture.meshcore_dtr.pulse_dtr_reset",
                   side_effect=lambda port, baud: rec.events.append(("pulse", port))):
            result = await source.set_radio_params(869.618, 62.5, 8, 8)

        self.assertTrue(result.success, result)
        detach = rec.first("disconnect")
        settle = rec.first("sleep", lambda e: e[1] >= mus._RADIO_EXCLUSIVE_DETACH_SETTLE_SECONDS)
        pulse = rec.first("pulse")
        opened = rec.first("open")
        self.assertLess(detach, settle, rec.events)
        self.assertLess(settle, pulse, rec.events)
        self.assertLess(pulse, opened, rec.events)
        boot = [e for e in rec.events[pulse:opened] if e[0] == "sleep"]
        self.assertTrue(boot and boot[-1][1] >= mus._RADIO_EXCLUSIVE_DTR_SETTLE_SECONDS, rec.events)

    def test_pauses_are_long_enough(self):
        # The reconnect that works waits 5 s after closing; the companion
        # needs a few seconds to boot after a DTR reset.
        self.assertGreaterEqual(mus._RADIO_EXCLUSIVE_DETACH_SETTLE_SECONDS, 3.0)
        self.assertGreaterEqual(mus._RADIO_EXCLUSIVE_DTR_SETTLE_SECONDS, 3.0)


class OpenRetryPauseTests(unittest.IsolatedAsyncioTestCase):
    async def test_pause_before_the_dtr_inverted_retry(self):
        rec = Recorder()
        answers = [None, {"ok": True}]

        class FakeMeshCore:
            def __init__(self, cx, default_timeout=None):
                self.cx = cx

            async def connect(self):
                rec.events.append(("connect", self.cx[3]))
                return answers.pop(0)

            async def disconnect(self):
                rec.events.append(("disconnect",))

        source = MeshcoreUsbCaptureSource(serial_port="/dev/ttyACM0")
        with patch("asyncio.sleep", rec.sleep), \
             patch.dict("sys.modules", {"meshcore": SimpleNamespace(MeshCore=FakeMeshCore)}), \
             patch("src.capture.meshcore_serial.is_cp210x", return_value=False), \
             patch("src.capture.meshcore_serial.create_serial_connection",
                   side_effect=lambda port, baud, release_dtr=None: ("serial", port, baud, release_dtr)):
            mc = await source._open_meshcore(15.0, "/dev/ttyACM0")

        self.assertIsNotNone(mc)
        first, retry = rec.first("connect"), len(rec.events) - 1
        self.assertEqual(rec.events[retry], ("connect", True), rec.events)
        pauses = [e for e in rec.events[first:retry] if e[0] == "sleep"]
        self.assertTrue(pauses and pauses[-1][1] >= 1.0, rec.events)


if __name__ == "__main__":
    unittest.main()
