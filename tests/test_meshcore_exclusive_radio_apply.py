"""set_radio_params() now applies over a temporary EXCLUSIVE connection
(detach the source's own live connection, cold-connect, set+reboot,
cold-reconnect, verify, reattach) instead of the source's shared/live
one -- real-hardware testing found the shared-handle approach could
still fail with no_event_received on a cross-band change even with a
verify-and-retry-once path, matching upstream KMX415/meshpoint's own
independently-confirmed finding on the same bug (a49ef60).

The real ``meshcore`` package isn't installed on this Mac (per this
repo's standing no-venv-here convention) -- ``_apply_radio_params_exclusive``
does ``from meshcore import MeshCore`` internally, so a minimal fake
module is installed into ``sys.modules`` before import, same idea as
stubbing ``aiosqlite`` elsewhere in this test suite."""

from __future__ import annotations

import asyncio
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch

try:  # the real package where installed (the Pi); a stub only where it isn't,
    import meshcore  # noqa: F401  # so it can't shadow it for later test files
except ImportError:
    _fake_meshcore = types.ModuleType("meshcore")

    class _FakeMeshCore:
        pass

    _fake_meshcore.MeshCore = _FakeMeshCore
    sys.modules["meshcore"] = _fake_meshcore

from src.capture import meshcore_usb_source as mus  # noqa: E402
from src.capture.meshcore_usb_source import MeshcoreUsbCaptureSource  # noqa: E402
from src.transmit.meshcore_tx_client import RadioStatus, SendResult  # noqa: E402


def _run(coro):
    """Reattach schedules a real background reconnect task -- with the
    mocked connect patches gone once the `with` block exits, and
    `_running` never set back to False (no source.stop() call here),
    that task would otherwise retry forever on real multi-second
    backoff sleeps. Cancel pending tasks instead of awaiting them to
    completion, same as test_serial_source_reconnect.py's own _run()."""
    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(coro)
        pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
        if pending:
            for t in pending:
                t.cancel()
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        return result
    finally:
        loop.close()


def _make_connected_source() -> MeshcoreUsbCaptureSource:
    source = MeshcoreUsbCaptureSource(serial_port="/dev/fake")
    source._running = True
    source._connected = True
    source._resolved_port = "/dev/fake"
    source._meshcore = AsyncMock()
    return source


class TestNotConnectedShortCircuits(unittest.TestCase):
    def test_not_connected_never_touches_the_port(self):
        source = MeshcoreUsbCaptureSource(serial_port="/dev/fake")
        source._connected = False
        result = _run(source.set_radio_params(868.1, 250.0, 11, 5))
        self.assertFalse(result.success)
        self.assertEqual(result.error, "Not connected")



def _via_open(fake_create_serial):
    """The exclusive apply opens through MeshcoreUsbCaptureSource._open_meshcore
    (own connection: CP210x DTR release, cleanup on failure; item 42). The
    tests fake that seam with the same (port, baud, timeout) fake as before."""
    async def open_meshcore(timeout, port=None, keep=None):
        return await fake_create_serial(port, 115200, default_timeout=timeout)
    return open_meshcore

class TestExclusiveApplySuccess(unittest.TestCase):
    def test_clean_success_detaches_verifies_and_reattaches(self):
        source = _make_connected_source()
        create_serial_calls = []

        async def fake_create_serial(port, baud, default_timeout=15.0):
            create_serial_calls.append(port)
            return AsyncMock()

        async def fake_send_set_radio_params(mc, freq, bw, sf, cr):
            return SendResult(success=True)

        async def fake_read_radio_status(mc):
            return RadioStatus(
                frequency_mhz=868.1, bandwidth_khz=250.0,
                spreading_factor=11, coding_rate=5,
            )

        with patch.object(mus.MeshcoreUsbCaptureSource, "_open_meshcore", side_effect=_via_open(fake_create_serial)), \
             patch.object(mus, "send_set_radio_params", fake_send_set_radio_params), \
             patch.object(mus, "read_radio_status", fake_read_radio_status), \
             patch("src.capture.meshcore_dtr.pulse_dtr_reset"), \
             patch.object(mus, "_RADIO_EXCLUSIVE_REBOOT_SETTLE_SECONDS", 0.0), \
             patch.object(mus, "_RADIO_EXCLUSIVE_DTR_SETTLE_SECONDS", 0.0):
            result = _run(source.set_radio_params(868.1, 250.0, 11, 5))

        self.assertTrue(result.success)
        self.assertEqual(len(create_serial_calls), 2, "one cold connect for apply, one for verify")
        self.assertIsNotNone(source._reconnect_task, "reattach must schedule a reconnect")

    def test_timeout_then_matching_verify_still_succeeds(self):
        source = _make_connected_source()

        async def fake_create_serial(port, baud, default_timeout=15.0):
            return AsyncMock()

        async def fake_send_set_radio_params(mc, freq, bw, sf, cr):
            return SendResult(success=False, error="set_radio timed out", timed_out=True)

        async def fake_read_radio_status(mc):
            return RadioStatus(
                frequency_mhz=868.1, bandwidth_khz=250.0,
                spreading_factor=11, coding_rate=5,
            )

        with patch.object(mus.MeshcoreUsbCaptureSource, "_open_meshcore", side_effect=_via_open(fake_create_serial)), \
             patch.object(mus, "send_set_radio_params", fake_send_set_radio_params), \
             patch.object(mus, "read_radio_status", fake_read_radio_status), \
             patch("src.capture.meshcore_dtr.pulse_dtr_reset"), \
             patch.object(mus, "_RADIO_EXCLUSIVE_REBOOT_SETTLE_SECONDS", 0.0), \
             patch.object(mus, "_RADIO_EXCLUSIVE_DTR_SETTLE_SECONDS", 0.0):
            result = _run(source.set_radio_params(868.1, 250.0, 11, 5))

        self.assertTrue(result.success, "ambiguous no-response still verifies as success if params match")

    def test_timeout_then_mismatched_verify_reports_failure(self):
        source = _make_connected_source()

        async def fake_create_serial(port, baud, default_timeout=15.0):
            return AsyncMock()

        async def fake_send_set_radio_params(mc, freq, bw, sf, cr):
            return SendResult(success=False, error="set_radio timed out", timed_out=True)

        async def fake_read_radio_status(mc):
            return RadioStatus(
                frequency_mhz=915.0, bandwidth_khz=250.0,
                spreading_factor=11, coding_rate=5,
            )

        with patch.object(mus.MeshcoreUsbCaptureSource, "_open_meshcore", side_effect=_via_open(fake_create_serial)), \
             patch.object(mus, "send_set_radio_params", fake_send_set_radio_params), \
             patch.object(mus, "read_radio_status", fake_read_radio_status), \
             patch("src.capture.meshcore_dtr.pulse_dtr_reset"), \
             patch.object(mus, "_RADIO_EXCLUSIVE_REBOOT_SETTLE_SECONDS", 0.0), \
             patch.object(mus, "_RADIO_EXCLUSIVE_DTR_SETTLE_SECONDS", 0.0):
            result = _run(source.set_radio_params(868.1, 250.0, 11, 5))

        self.assertFalse(result.success)
        self.assertTrue(result.timed_out)
        self.assertIn("915.000", result.error)


class TestExclusiveApplyRejectionAndFailures(unittest.TestCase):
    def test_clean_rejection_never_attempts_verify(self):
        source = _make_connected_source()
        verify_calls = []

        async def fake_create_serial(port, baud, default_timeout=15.0):
            return AsyncMock()

        async def fake_send_set_radio_params(mc, freq, bw, sf, cr):
            return SendResult(success=False, error="Frequency out of range")

        async def fake_read_radio_status(mc):
            verify_calls.append(True)
            return None

        with patch.object(mus.MeshcoreUsbCaptureSource, "_open_meshcore", side_effect=_via_open(fake_create_serial)), \
             patch.object(mus, "send_set_radio_params", fake_send_set_radio_params), \
             patch.object(mus, "read_radio_status", fake_read_radio_status), \
             patch("src.capture.meshcore_dtr.pulse_dtr_reset"), \
             patch.object(mus, "_RADIO_EXCLUSIVE_REBOOT_SETTLE_SECONDS", 0.0), \
             patch.object(mus, "_RADIO_EXCLUSIVE_DTR_SETTLE_SECONDS", 0.0):
            result = _run(source.set_radio_params(9999.0, 250.0, 11, 5))

        self.assertFalse(result.success)
        self.assertFalse(result.timed_out)
        self.assertEqual(result.error, "Frequency out of range")
        self.assertEqual(verify_calls, [], "a clean rejection never rebooted -- nothing to verify")

    def test_initial_handshake_failure_still_reattaches(self):
        source = _make_connected_source()

        async def fake_create_serial(port, baud, default_timeout=15.0):
            return None  # handshake failed

        with patch.object(mus.MeshcoreUsbCaptureSource, "_open_meshcore", side_effect=_via_open(fake_create_serial)), \
             patch("src.capture.meshcore_dtr.pulse_dtr_reset"), \
             patch.object(mus, "_RADIO_EXCLUSIVE_REBOOT_SETTLE_SECONDS", 0.0), \
             patch.object(mus, "_RADIO_EXCLUSIVE_DTR_SETTLE_SECONDS", 0.0):
            result = _run(source.set_radio_params(868.1, 250.0, 11, 5))

        self.assertFalse(result.success)
        self.assertIn("handshake failed", result.error)
        self.assertIsNotNone(source._reconnect_task, "must still reattach even on a cold-connect failure")

    def test_no_response_on_verify_reconnect_reports_timed_out(self):
        source = _make_connected_source()
        call_count = {"n": 0}

        async def fake_create_serial(port, baud, default_timeout=15.0):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return AsyncMock()
            return None  # verify reconnect never comes back

        async def fake_send_set_radio_params(mc, freq, bw, sf, cr):
            return SendResult(success=True)

        with patch.object(mus.MeshcoreUsbCaptureSource, "_open_meshcore", side_effect=_via_open(fake_create_serial)), \
             patch.object(mus, "send_set_radio_params", fake_send_set_radio_params), \
             patch("src.capture.meshcore_dtr.pulse_dtr_reset"), \
             patch.object(mus, "_RADIO_EXCLUSIVE_REBOOT_SETTLE_SECONDS", 0.0), \
             patch.object(mus, "_RADIO_EXCLUSIVE_DTR_SETTLE_SECONDS", 0.0):
            result = _run(source.set_radio_params(868.1, 250.0, 11, 5))

        self.assertFalse(result.success)
        self.assertTrue(result.timed_out)
        self.assertIn("did not come back for verify", result.error)


if __name__ == "__main__":
    unittest.main()
