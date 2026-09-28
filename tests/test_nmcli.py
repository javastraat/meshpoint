"""src.api.nmcli shells out to `sudo nmcli <args>` for WiFi scan/connect/
status (the raspberry-network plugin).

Pure Python, no FastAPI. The subprocess call is patched -- checks argv
construction, the (returncode, text) shape, and the terse-output parser,
not that sudo/nmcli actually run.
"""

from __future__ import annotations

import asyncio
import unittest
from unittest import mock

from src.api import nmcli


class _FakeProc:
    def __init__(self, out: bytes, rc: int) -> None:
        self.stdout = mock.AsyncMock()
        self.stdout.read.return_value = out
        self._rc = rc

    async def wait(self) -> int:
        return self._rc


def _patched(out: bytes, rc: int = 0):
    return mock.patch.object(
        nmcli.asyncio, "create_subprocess_exec",
        new=mock.AsyncMock(return_value=_FakeProc(out, rc)),
    )


class TestRunNmcli(unittest.TestCase):
    def test_builds_sudo_nmcli_argv_and_returns_rc_and_text(self) -> None:
        with _patched(b"  connected\n", 0) as spawn:
            rc, out = asyncio.run(nmcli._run_nmcli("device", "status"))
        self.assertEqual((rc, out), (0, "connected"))
        args, _kwargs = spawn.call_args
        self.assertEqual(args[:4], ("sudo", "nmcli", "device", "status"))

    def test_nonzero_exit_is_passed_through(self) -> None:
        with _patched(b"Error: Connection activation failed.", 4):
            rc, out = asyncio.run(nmcli._run_nmcli("device", "wifi", "connect", "x"))
        self.assertEqual(rc, 4)
        self.assertIn("activation failed", out)


class TestSplitTerseLine(unittest.TestCase):
    def test_plain_fields(self) -> None:
        self.assertEqual(
            nmcli._split_terse_line("MyWifi:80:WPA2:*", 4),
            ["MyWifi", "80", "WPA2", "*"],
        )

    def test_escaped_colon_within_a_field_is_not_a_split_point(self) -> None:
        # A real SSID can contain a literal ":" -- nmcli's own terse mode
        # escapes it as "\:" specifically so this doesn't happen; a naive
        # str.split(':') would corrupt this into 5 fields instead of 4.
        self.assertEqual(
            nmcli._split_terse_line(r"Cafe\:Downtown:60:WPA2:", 4),
            ["Cafe:Downtown", "60", "WPA2", ""],
        )

    def test_escaped_backslash_within_a_field(self) -> None:
        self.assertEqual(
            nmcli._split_terse_line(r"back\\slash:40::", 4),
            ["back\\slash", "40", "", ""],
        )

    def test_short_line_is_padded_not_rejected(self) -> None:
        # One malformed row from a flaky scan shouldn't take down the
        # whole list -- pad with "" for whatever's missing.
        self.assertEqual(
            nmcli._split_terse_line("OnlySsid", 4),
            ["OnlySsid", "", "", ""],
        )


class TestWifiScan(unittest.TestCase):
    def test_parses_networks_and_flags_the_in_use_one(self) -> None:
        out = "HomeNet:70:WPA2:*\nGuestNet:40::\n"
        with _patched(out.encode()):
            networks = asyncio.run(nmcli.wifi_scan())
        self.assertEqual(networks, [
            {"ssid": "HomeNet", "signal": 70, "security": "WPA2", "in_use": True},
            {"ssid": "GuestNet", "signal": 40, "security": None, "in_use": False},
        ])

    def test_skips_hidden_networks_with_no_ssid(self) -> None:
        out = ":55:WPA2:\nRealNet:65::\n"
        with _patched(out.encode()):
            networks = asyncio.run(nmcli.wifi_scan())
        self.assertEqual([n["ssid"] for n in networks], ["RealNet"])

    def test_empty_scan_result(self) -> None:
        with _patched(b""):
            networks = asyncio.run(nmcli.wifi_scan())
        self.assertEqual(networks, [])

    def test_scan_uses_the_real_field_list_and_rescan_flag(self) -> None:
        with _patched(b"") as spawn:
            asyncio.run(nmcli.wifi_scan())
        args, _kwargs = spawn.call_args
        self.assertEqual(
            args,
            ("sudo", "nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY,IN-USE",
             "device", "wifi", "list", "--rescan", "yes"),
        )


class TestWifiStatus(unittest.TestCase):
    def test_finds_the_wifi_device_among_others(self) -> None:
        out = "eth0:ethernet:connected:Wired\nwlan0:wifi:connected:HomeNet\n"
        with _patched(out.encode()):
            status = asyncio.run(nmcli.wifi_status())
        self.assertEqual(
            status, {"device": "wlan0", "state": "connected", "connection": "HomeNet"},
        )

    def test_disconnected_wifi_has_no_connection_name(self) -> None:
        out = "wlan0:wifi:disconnected:\n"
        with _patched(out.encode()):
            status = asyncio.run(nmcli.wifi_status())
        self.assertEqual(
            status, {"device": "wlan0", "state": "disconnected", "connection": None},
        )

    def test_no_wifi_device_at_all_returns_none(self) -> None:
        out = "eth0:ethernet:connected:Wired\n"
        with _patched(out.encode()):
            status = asyncio.run(nmcli.wifi_status())
        self.assertIsNone(status)


class TestWifiConnect(unittest.TestCase):
    def _patched_sequence(self, *results: tuple[bytes, int]):
        """Like _patched(), but each successive create_subprocess_exec
        call gets the next (out, rc) pair -- for asserting the delete
        and connect calls' results are handled independently."""
        procs = [_FakeProc(out, rc) for out, rc in results]
        return mock.patch.object(
            nmcli.asyncio, "create_subprocess_exec",
            new=mock.AsyncMock(side_effect=procs),
        )

    def test_builds_the_real_connect_argv_after_deleting_any_stale_profile(self) -> None:
        with self._patched_sequence(
            (b"", 0),  # connection delete
            (b"Device 'wlan0' successfully activated", 0),  # device wifi connect
        ) as spawn:
            rc, out = asyncio.run(nmcli.wifi_connect("HomeNet", "hunter2"))
        self.assertEqual(rc, 0)
        self.assertIn("successfully activated", out)
        calls = [c.args for c in spawn.call_args_list]
        self.assertEqual(calls, [
            ("sudo", "nmcli", "connection", "delete", "HomeNet"),
            ("sudo", "nmcli", "device", "wifi", "connect", "HomeNet", "password", "hunter2"),
        ])

    def test_delete_failing_does_not_block_the_connect_attempt(self) -> None:
        # "unknown connection" (nothing to delete -- first-ever attempt
        # at this SSID) is the common case, not an error to propagate.
        with self._patched_sequence(
            (b"Error: unknown connection 'HomeNet'.", 1),
            (b"Device 'wlan0' successfully activated", 0),
        ):
            rc, out = asyncio.run(nmcli.wifi_connect("HomeNet", "hunter2"))
        # The returned (rc, out) reflects the connect call, not the delete.
        self.assertEqual(rc, 0)
        self.assertIn("successfully activated", out)

    def test_failure_is_passed_through_not_raised(self) -> None:
        with self._patched_sequence(
            (b"", 0),
            (b"Error: Secrets were required, but not provided.", 4),
        ):
            rc, out = asyncio.run(nmcli.wifi_connect("HomeNet", "wrong"))
        self.assertEqual(rc, 4)
        self.assertIn("Secrets were required", out)

    def test_empty_password_omits_the_password_argument_and_skips_delete(self) -> None:
        # Regression guard for a real bug: passing an *empty* password
        # ("password", "") made nmcli build a malformed security block
        # ("802-11-wireless-security.key-mgmt: property is missing")
        # instead of reusing an already-saved network's real stored
        # credentials or connecting outright to a genuinely open one --
        # confirmed live, reconnecting to an already-known secured
        # network with no new password typed. Must also NOT delete the
        # existing profile first -- that's the one this path explicitly
        # wants to keep and reuse, unlike the real-password path above.
        with _patched(b"Device 'wlan0' successfully activated", 0) as spawn:
            asyncio.run(nmcli.wifi_connect("KnownNet", ""))
        self.assertEqual(spawn.call_count, 1)
        args, _kwargs = spawn.call_args
        self.assertEqual(args, ("sudo", "nmcli", "device", "wifi", "connect", "KnownNet"))
        self.assertNotIn("password", args)

    def test_password_defaults_to_empty_when_omitted(self) -> None:
        with _patched(b"", 0) as spawn:
            asyncio.run(nmcli.wifi_connect("KnownNet"))
        self.assertEqual(spawn.call_count, 1)
        args, _kwargs = spawn.call_args
        self.assertEqual(args, ("sudo", "nmcli", "device", "wifi", "connect", "KnownNet"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
