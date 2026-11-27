"""MeshCore USB robustness (upstream b91d994b; TODO.md item 42).

1. restart_auto_fetching() stops before it starts (the library's start is
   not idempotent: each call adds a subscription).
2. DTR is released on CP210x USB bridges only; no answer -> one retry with
   DTR inverted (the library's own create_serial() behaviour, kept).
3. An unplugged USB companion or a DISCONNECTED event reconnects now.
4. A failed connect cleans up the instance; an OSError logs one line.
"""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.capture import meshcore_serial
from src.capture.meshcore_usb_source import MeshcoreUsbCaptureSource


class FakeMeshCore:
    """Records start/stop of auto fetching like meshcore's MeshCore does."""

    def __init__(self, cx=None, default_timeout=None, answer=True, raise_exc=None):
        self.cx, self.answer, self.raise_exc = cx, answer, raise_exc
        self.subscriptions, self.disconnected = 0, False

    async def connect(self):
        if self.raise_exc:
            raise self.raise_exc
        return {"ok": True} if self.answer else None

    async def disconnect(self):
        self.disconnected = True

    async def start_auto_message_fetching(self):
        self.subscriptions += 1  # the library never removes the old one itself

    async def stop_auto_message_fetching(self):
        self.subscriptions = 0


class AutoFetchTests(unittest.IsolatedAsyncioTestCase):
    async def test_restart_does_not_pile_up_subscriptions(self):
        s = MeshcoreUsbCaptureSource()
        s._meshcore, s._connected = FakeMeshCore(), True
        for _ in range(5):  # e.g. five sends
            await s.restart_auto_fetching()
        self.assertEqual(s._meshcore.subscriptions, 1)

    async def test_concurrent_restarts_end_with_one(self):
        s = MeshcoreUsbCaptureSource()
        s._meshcore, s._connected = FakeMeshCore(), True
        await asyncio.gather(*(s.restart_auto_fetching() for _ in range(4)))
        self.assertEqual(s._meshcore.subscriptions, 1)


class DtrTests(unittest.TestCase):
    def test_cp210x_is_recognised_through_aliases(self):
        port = SimpleNamespace(vid=0x10C4, pid=0xEA60, device="/dev/ttyUSB0")
        with patch("serial.tools.list_ports.comports", return_value=[port]), \
             patch("os.path.realpath", side_effect=lambda p: "/dev/ttyUSB0" if "by-path" in p else p):
            self.assertTrue(meshcore_serial.is_cp210x("/dev/serial/by-path/usb-0:1.2"))
        native = SimpleNamespace(vid=0x303A, pid=0x1001, device="/dev/ttyACM0")
        with patch("serial.tools.list_ports.comports", return_value=[native]):
            self.assertFalse(meshcore_serial.is_cp210x("/dev/ttyACM0"))

    def test_released_connection_drops_dtr_after_opening(self):
        cx = meshcore_serial.create_serial_connection("/dev/ttyUSB0", 115200, release_dtr=True)
        port = SimpleNamespace(dtr=True, rts=True)
        transport = SimpleNamespace(serial=port)
        protocol = cx.MCSerialClientProtocol(cx)
        protocol.connection_made(transport)
        self.assertFalse(port.dtr)

    def test_native_usb_keeps_the_library_default(self):
        from meshcore.serial_cx import SerialConnection

        cx = meshcore_serial.create_serial_connection("/dev/ttyACM0", 115200, release_dtr=False)
        self.assertIs(type(cx), SerialConnection)


class OpenTests(unittest.IsolatedAsyncioTestCase):
    def patched(self, answers, cp210x=False):
        made, releases = [], []

        def make(cx, default_timeout=None):
            mc = FakeMeshCore(cx, answer=answers[len(made)])
            made.append(mc)
            return mc

        fake_module = SimpleNamespace(MeshCore=make)
        return made, releases, [
            patch.dict("sys.modules", {"meshcore": fake_module}),
            patch("src.capture.meshcore_serial.is_cp210x", return_value=cp210x),
            patch("src.capture.meshcore_serial.create_serial_connection",
                  side_effect=lambda p, b, release_dtr=None: releases.append(release_dtr) or "cx"),
        ]

    async def run_open(self, answers, cp210x=False):
        made, releases, patches = self.patched(answers, cp210x)
        for p in patches:
            p.start()
        try:
            s = MeshcoreUsbCaptureSource(serial_port="/dev/ttyUSB0")
            kept = []
            mc = await s._open_meshcore(5.0, "/dev/ttyUSB0", keep=kept.append)
        finally:
            for p in patches:
                p.stop()
        return mc, made, releases, kept

    async def test_cp210x_starts_with_dtr_released(self):
        mc, made, releases, _ = await self.run_open([True], cp210x=True)
        self.assertEqual(releases, [True])
        self.assertIs(mc, made[0])

    async def test_no_answer_retries_once_with_dtr_inverted_and_cleans_up(self):
        mc, made, releases, kept = await self.run_open([False, True])
        self.assertEqual(releases, [False, True])
        self.assertTrue(made[0].disconnected)
        self.assertIs(mc, made[1])
        self.assertEqual(kept, made)  # every instance handed over before connect()

    async def test_no_answer_at_all_returns_none(self):
        mc, made, _, _ = await self.run_open([False, False])
        self.assertIsNone(mc)
        self.assertTrue(all(m.disconnected for m in made))


class ConnectFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_oserror_cleans_up_and_logs_one_line(self):
        s = MeshcoreUsbCaptureSource(serial_port="/dev/ttyUSB9")
        broken = FakeMeshCore(raise_exc=OSError(2, "No such file or directory"))

        async def open_meshcore(timeout, port=None, keep=None):
            keep(broken)
            raise broken.raise_exc

        with patch.object(s, "_open_meshcore", side_effect=open_meshcore), \
             self.assertLogs("src.capture.meshcore_usb_source", level="WARNING") as logs:
            await s._connect("/dev/ttyUSB9")
        self.assertFalse(s._connected)
        self.assertIsNone(s._meshcore)
        self.assertTrue(broken.disconnected)
        self.assertEqual(len(logs.output), 1)
        self.assertIn("waiting for reconnect", logs.output[0])
        self.assertNotIn("Traceback", logs.output[0])


class UnplugTests(unittest.IsolatedAsyncioTestCase):
    def source(self):
        s = MeshcoreUsbCaptureSource(serial_port="/dev/ttyACM0")
        s._connected, s._running = True, True
        s._resolved_port = "/dev/serial/by-path/usb-0:1.2"
        s._trigger_reconnect = MagicMock()
        return s

    def test_vanished_port_triggers_reconnect(self):
        s = self.source()
        with patch("os.path.exists", return_value=False):
            s._check_usb_presence()
        s._trigger_reconnect.assert_called_once_with("USB device removed")

    def test_present_port_or_tcp_does_nothing(self):
        s = self.source()
        with patch("os.path.exists", return_value=True):
            s._check_usb_presence()
        tcp = MeshcoreUsbCaptureSource(connection_type="tcp")
        tcp._connected, tcp._resolved_port = True, "tcp://127.0.0.1:5000"
        tcp._trigger_reconnect = MagicMock()
        tcp._check_usb_presence()
        s._trigger_reconnect.assert_not_called()
        tcp._trigger_reconnect.assert_not_called()

    async def test_disconnected_event_reconnects_and_is_not_queued(self):
        s = self.source()
        await s._on_event(SimpleNamespace(type=SimpleNamespace(name="DISCONNECTED", value="disconnected"),
                                          payload={}))
        s._trigger_reconnect.assert_called_once_with("transport disconnected")
        self.assertTrue(s._queue.empty())


if __name__ == "__main__":
    unittest.main()
