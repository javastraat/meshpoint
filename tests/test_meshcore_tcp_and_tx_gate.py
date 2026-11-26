"""MeshCore over TCP, the live Transmit switch, and channel readback.

Ported from upstream KMX415/meshpoint 6ea8de00, adapted to our multi-companion
config (a list in local.yaml) and our own sync_channels.
"""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.capture.meshcore_usb_source import MeshcoreUsbCaptureSource
from src.config import _coerce_meshcore_usb
from src.transmit.meshcore_tx_client import MeshCoreTxClient

OK = SimpleNamespace(type=SimpleNamespace(value="ok"), payload={})


class TcpTransportTests(unittest.IsolatedAsyncioTestCase):
    def test_config_list_keeps_tcp_fields(self):
        [c] = _coerce_meshcore_usb([{"label": "pi", "connection_type": "tcp",
                                     "tcp_host": "10.0.0.5", "tcp_port": 5001}])
        self.assertEqual((c.connection_type, c.tcp_host, c.tcp_port), ("tcp", "10.0.0.5", 5001))
        [d] = _coerce_meshcore_usb([{"label": "usb"}])
        self.assertEqual(d.connection_type, "serial")

    def test_invalid_endpoint_is_refused(self):
        for kwargs in ({"connection_type": "bluetooth"},
                       {"connection_type": "tcp", "tcp_host": ""},
                       {"connection_type": "tcp", "tcp_port": 70000}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    MeshcoreUsbCaptureSource(**kwargs)

    async def test_tcp_opens_tcp_and_needs_no_port_probe(self):
        s = MeshcoreUsbCaptureSource(connection_type="tcp", tcp_host="10.0.0.5", tcp_port=5001)
        self.assertEqual(await s._resolve_port(), "tcp://10.0.0.5:5001")
        fake = SimpleNamespace(create_tcp=AsyncMock(return_value="mc"), create_serial=AsyncMock())
        with patch.dict("sys.modules", {"meshcore": SimpleNamespace(MeshCore=fake)}):
            self.assertEqual(await s._open_meshcore(5.0, "ignored"), "mc")
        fake.create_tcp.assert_awaited_once_with("10.0.0.5", 5001, default_timeout=5.0)
        fake.create_serial.assert_not_called()

    async def test_serial_still_opens_serial(self):
        s = MeshcoreUsbCaptureSource(serial_port="/dev/ttyACM0", baud_rate=115200)
        fake = SimpleNamespace(create_tcp=AsyncMock(), create_serial=AsyncMock(return_value="mc"))
        with patch.dict("sys.modules", {"meshcore": SimpleNamespace(MeshCore=fake)}):
            await s._open_meshcore(5.0, "/dev/ttyACM0")
        fake.create_serial.assert_awaited_once_with("/dev/ttyACM0", 115200, default_timeout=5.0)
        fake.create_tcp.assert_not_called()


class TxSwitchTests(unittest.IsolatedAsyncioTestCase):
    async def test_client_refuses_all_sends_while_tx_is_off(self):
        client = MeshCoreTxClient()
        mc = SimpleNamespace(commands=SimpleNamespace(
            send_chan_msg=AsyncMock(return_value=OK), send_msg=AsyncMock(return_value=OK),
            send_advert=AsyncMock(return_value=OK)))
        client.set_connection(mc)
        client.tx_enabled_provider = lambda: False
        for result in (await client.send_channel_message(0, "x"),
                       await client.send_direct_message("aabb", "x"),
                       await client.send_advert()):
            self.assertEqual((result.success, result.error), (False, "MeshCore TX disabled"))
        mc.commands.send_chan_msg.assert_not_called()
        mc.commands.send_msg.assert_not_called()

    async def test_companion_refuses_its_own_sends_while_tx_is_off(self):
        s = MeshcoreUsbCaptureSource()
        s._connected = True
        s.tx_enabled_provider = lambda: False
        for result in (await s.send_channel_message(0, "x"),
                       await s.send_direct_message("aabb", "x"),
                       await s.send_advert()):
            self.assertEqual(result.error, "MeshCore TX disabled")

    def test_tx_service_follows_the_live_switch(self):
        from src.transmit.tx_service import TxService

        cfg = SimpleNamespace(enabled=True)
        svc = TxService.__new__(TxService)
        svc._config = cfg
        svc._meshcore_tx = SimpleNamespace(connected=True)
        self.assertTrue(svc.meshcore_enabled)
        cfg.enabled = False  # Configuration -> Transmit switched off, no restart
        self.assertFalse(svc.meshcore_enabled)


class ChannelReadbackTests(unittest.IsolatedAsyncioTestCase):
    def client(self, slots):
        """A companion whose get_channel answers from `slots` and set_channel
        writes there unless the slot is in `stuck`."""
        from meshcore import EventType

        self.stuck = set()

        async def get_channel(i):
            if i not in slots:
                return SimpleNamespace(type=EventType.ERROR, payload={})
            name, secret = slots[i]
            return SimpleNamespace(type=EventType.CHANNEL_INFO,
                                   payload={"channel_name": name, "channel_secret": secret})

        async def set_channel(i, name, secret):
            if i not in self.stuck:
                slots[i] = (name, secret)
            return OK

        c = MeshCoreTxClient()
        c.set_connection(SimpleNamespace(commands=SimpleNamespace(
            get_channel=AsyncMock(side_effect=get_channel),
            set_channel=AsyncMock(side_effect=set_channel))))
        return c

    def slots(self, n=4):
        return {i: ("Public" if i == 0 else "", b"\0" * 16) for i in range(n)}

    async def test_verified_save(self):
        key = "11" * 16
        c = self.client(self.slots())
        await c.sync_channels({"Ops": key}, verify=True)  # no exception

    async def test_write_that_did_not_stick_is_reported(self):
        c = self.client(self.slots())
        self.stuck = {1}
        with self.assertRaisesRegex(RuntimeError, "did not stick in slot 1"):
            await c.sync_channels({"Ops": "11" * 16}, verify=True)

    async def test_removal_that_did_not_stick_is_reported(self):
        slots = self.slots()
        slots[2] = ("Old", b"\x22" * 16)
        c = self.client(slots)
        self.stuck = {2}
        with self.assertRaisesRegex(RuntimeError, "was not removed"):
            await c.sync_channels({"Ops": "11" * 16}, verify=True)

    async def test_not_connected_is_an_error_only_when_verifying(self):
        c = MeshCoreTxClient()
        await c.sync_channels({})  # silent, as before
        with self.assertRaisesRegex(RuntimeError, "not connected"):
            await c.sync_channels({}, verify=True)


if __name__ == "__main__":
    unittest.main()
