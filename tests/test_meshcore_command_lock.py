"""MeshCore companion commands never overlap on the serial line (TODO 50a).

Upstream KMX415/meshpoint runs every TX-client command under one
``asyncio.Lock`` and shares it with the capture source (``set_command_lock``)
so the health probe waits too (b91d994b, 6ea8de00). Without it a send, a
contacts refresh, a repeater poll and the health probe could interleave, the
library could pick up the other command's response or time out, and a timeout
triggers a reconnect. Ours also locks the capture source's own commands
(per-companion sends, rename, radio change).
"""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace

from src.capture.meshcore_usb_source import MeshcoreUsbCaptureSource
from src.transmit.meshcore_tx_client import MeshCoreTxClient

try:
    from meshcore import EventType
    ERROR = EventType.ERROR
except Exception:  # library missing: anything that isn't ERROR counts as OK
    ERROR = "error"


class OverlapMeter:
    """Fake companion: every command takes a moment and records overlap."""

    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0
        self.calls: list[str] = []

    def command(self, name, result):
        async def run(*_args, **_kwargs):
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.calls.append(name)
            try:
                await asyncio.sleep(0.02)
            finally:
                self.active -= 1
            return result
        return run

    def mc(self):
        ok = SimpleNamespace(type=SimpleNamespace(value="ok"), payload={})
        error = SimpleNamespace(type=ERROR, payload={})
        contact = {"public_key": "aa" * 32, "adv_name": "Rep"}
        commands = SimpleNamespace(
            send_chan_msg=self.command("send_chan_msg", ok),
            send_msg=self.command("send_msg", ok),
            send_advert=self.command("send_advert", ok),
            get_contacts=self.command("get_contacts", SimpleNamespace(type="contacts", payload={})),
            get_channel=self.command("get_channel", error),
            send_device_query=self.command("send_device_query", SimpleNamespace(type="device", payload={})),
            set_name=self.command("set_name", ok),
            req_status_sync=self.command("req_status_sync", {"uptime": 1}),
            req_telemetry_sync=self.command("req_telemetry_sync", None),
            fetch_all_neighbours=self.command("fetch_all_neighbours", None),
            add_contact=self.command("add_contact", ok),
        )
        return SimpleNamespace(
            commands=commands, self_info={"name": "PD2EMC"},
            get_contact_by_key_prefix=lambda key: dict(contact),
            stop_auto_message_fetching=self.command("stop_auto", None),
            start_auto_message_fetching=self.command("start_auto", None),
        )


def bound_pair(meter: OverlapMeter):
    """A TX client bound to a connected capture source, like the server wires them."""
    source = MeshcoreUsbCaptureSource(serial_port="/dev/ttyACM0")
    source._meshcore = meter.mc()
    source._connected = True
    source._running = True
    client = MeshCoreTxClient()
    client.set_source(source)
    return client, source


class TxClientCommandLockTests(unittest.IsolatedAsyncioTestCase):
    async def test_client_commands_wait_for_each_other(self):
        meter = OverlapMeter()
        client, _ = bound_pair(meter)
        await asyncio.gather(
            client.send_channel_message(0, "hi"),
            client.send_direct_message(b"\xaa" * 6, "hi"),
            client.send_advert(),
            client.get_contacts(),
            client.get_device_info(),
            client.set_companion_name("PD2EMC"),
            client.poll_repeater("aaaaaaaaaaaa"),
            client.add_contact({"public_key": "aa" * 32}),
            client.sync_channels({}),
        )
        self.assertEqual(meter.max_active, 1, meter.calls)
        self.assertIn("req_status_sync", meter.calls)

    async def test_health_probe_waits_for_a_client_command(self):
        meter = OverlapMeter()
        client, source = bound_pair(meter)
        results = await asyncio.gather(client.poll_repeater("aaaaaaaaaaaa"), source._check_health())
        self.assertEqual(meter.max_active, 1, meter.calls)
        self.assertTrue(results[1])

    async def test_source_commands_share_the_client_lock(self):
        meter = OverlapMeter()
        client, source = bound_pair(meter)
        await asyncio.gather(
            client.send_channel_message(0, "a"),
            source.send_channel_message(0, "b"),
            source.send_direct_message(b"\xaa" * 6, "c"),
            source.send_advert(),
            source.set_companion_name("PD2EMC"),
            source.get_device_info(),
            source._check_health(),
        )
        self.assertEqual(meter.max_active, 1, meter.calls)

    async def test_no_deadlock_when_a_command_finishes_with_auto_fetch_restart(self):
        # A send ends with restart_auto_fetching() (its own lock, and it
        # sends stop/start to the companion); that must not wait on the
        # command lock the send is holding.
        meter = OverlapMeter()
        client, source = bound_pair(meter)
        client.set_post_command_callback(source.restart_auto_fetching)
        results = await asyncio.wait_for(asyncio.gather(
            client.send_channel_message(0, "a"),
            client.send_advert(),
            source.send_advert(),
        ), timeout=2.0)
        self.assertTrue(all(r.success for r in results))
        self.assertIn("start_auto", meter.calls)

    async def test_lock_is_released_after_a_failing_command(self):
        meter = OverlapMeter()
        client, _ = bound_pair(meter)

        async def boom(*_a, **_k):
            raise RuntimeError("serial gone")
        client._mc.commands.send_advert = boom
        self.assertFalse((await client.send_advert()).success)
        self.assertTrue((await asyncio.wait_for(client.send_channel_message(0, "x"), 1.0)).success)

    async def test_unbound_client_still_serializes_its_own_commands(self):
        meter = OverlapMeter()
        client = MeshCoreTxClient()
        client.set_connection(meter.mc())
        await asyncio.gather(client.send_advert(), client.get_contacts(), client.send_channel_message(0, "x"))
        self.assertEqual(meter.max_active, 1, meter.calls)


if __name__ == "__main__":
    unittest.main()
