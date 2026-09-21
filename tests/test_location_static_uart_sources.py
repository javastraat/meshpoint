"""Tests for ``StaticSource`` and ``UartSource``."""

from __future__ import annotations

import asyncio
import sys
import types
import unittest

from src.config import DeviceConfig
from src.hal.location.static_source import StaticSource
from src.hal.location.uart_source import UartSource, _nmea_to_decimal


class TestStaticSource(unittest.IsolatedAsyncioTestCase):
    """``StaticSource`` reports configured device coords as a fixed 3D fix."""

    async def test_valid_coordinates_yield_3d_fix(self) -> None:
        device = DeviceConfig(latitude=40.7128, longitude=-74.0060, altitude=12.0)
        source = StaticSource(device)
        await source.start()
        try:
            status = source.get_status()
            self.assertEqual(status.source, "static")
            self.assertTrue(status.available)
            self.assertEqual(status.fix.mode, 3)
            self.assertEqual(status.fix.mode_label, "3D")
            self.assertEqual(status.fix.latitude, 40.7128)
            self.assertEqual(status.fix.longitude, -74.0060)
            self.assertEqual(status.fix.altitude_m, 12.0)
            self.assertIsNone(status.satellites)
            self.assertIsNone(status.device)
        finally:
            await source.stop()

    async def test_missing_coordinates_yield_unavailable(self) -> None:
        device = DeviceConfig(latitude=None, longitude=None, altitude=None)
        source = StaticSource(device)
        await source.start()
        status = source.get_status()
        self.assertFalse(status.available)
        self.assertIsNone(status.fix)
        self.assertEqual(status.error, "No coordinates configured")

    async def test_partial_coordinates_yield_unavailable(self) -> None:
        # Lat without lon -- uncommon but possible mid-edit. Don't drop
        # a pin at (40, 0) silently.
        device = DeviceConfig(latitude=40.0, longitude=None)
        source = StaticSource(device)
        await source.start()
        status = source.get_status()
        self.assertFalse(status.available)

    async def test_out_of_range_coordinates_treated_as_invalid(self) -> None:
        device = DeviceConfig(latitude=200.0, longitude=400.0)
        source = StaticSource(device)
        await source.start()
        status = source.get_status()
        self.assertFalse(status.available)

    async def test_start_is_idempotent(self) -> None:
        device = DeviceConfig(latitude=40.0, longitude=-74.0)
        source = StaticSource(device)
        await source.start()
        await source.start()  # must not raise

    async def test_stop_is_idempotent(self) -> None:
        device = DeviceConfig(latitude=40.0, longitude=-74.0)
        source = StaticSource(device)
        await source.stop()  # without prior start
        await source.start()
        await source.stop()
        await source.stop()  # second stop is a no-op

    async def test_source_name_is_stable(self) -> None:
        source = StaticSource(DeviceConfig())
        self.assertEqual(source.source_name, "static")


class TestUartSource(unittest.IsolatedAsyncioTestCase):
    """``UartSource`` reads NMEA GGA/GSA off a real serial device.

    These tests exercise the sentence parser directly (no serial I/O
    involved) plus the connect-failure path against a device path that
    cannot exist, which is the only server-independent way to test the
    reader loop's error handling without real UART hardware.
    """

    async def test_status_is_unavailable_with_explanatory_error(self) -> None:
        source = UartSource(device="/dev/does-not-exist-in-ci")
        await source.start()
        try:
            # Give the reader task a chance to actually attempt (and
            # fail) opening the port -- start() only schedules it.
            await asyncio.sleep(0.2)
            status = source.get_status()
            self.assertEqual(status.source, "uart")
            self.assertFalse(status.available)
            self.assertIsNotNone(status.error)
            # Error must point users to the working alternatives.
            self.assertIn("static", status.error.lower())
            self.assertIn("gpsd", status.error.lower())
        finally:
            await source.stop()

    async def test_source_name_is_stable(self) -> None:
        source = UartSource()
        self.assertEqual(source.source_name, "uart")

    async def test_stop_before_start_is_a_noop(self) -> None:
        source = UartSource()
        await source.stop()  # must not raise

    def test_gga_and_gsa_sentences_combine_into_one_fix(self) -> None:
        """The textbook Wikipedia GGA/GSA example sentences, decoded."""
        source = UartSource()

        source._handle_gga("$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47")
        fix = source._latest_fix
        self.assertIsNotNone(fix)
        self.assertAlmostEqual(fix.latitude, 48.1173, places=3)
        self.assertAlmostEqual(fix.longitude, 11.516667, places=3)
        self.assertAlmostEqual(fix.altitude_m, 545.4)
        # No GSA seen yet -- a valid GGA fix implies at least 2D.
        self.assertEqual(fix.mode, 2)
        self.assertIsNone(fix.hdop)

        source._handle_gsa("$GPGSA,A,3,04,05,,09,12,,,24,,,,,2.5,1.3,2.1*39")
        fix = source._latest_fix
        self.assertEqual(fix.mode, 3)
        self.assertAlmostEqual(fix.pdop, 2.5)
        self.assertAlmostEqual(fix.hdop, 1.3)
        self.assertAlmostEqual(fix.vdop, 2.1)
        # Position from the earlier GGA must survive the GSA merge.
        self.assertAlmostEqual(fix.latitude, 48.1173, places=3)

    def test_real_p100_no_fix_capture_surfaces_diagnostics(self) -> None:
        """Real sentences captured off the Pisces P100's onboard receiver
        (GPS+GLONASS, no fix, antenna disconnected) -- exercises the
        multi-constellation GSA's extra NMEA 4.10 system-ID field (19
        comma fields instead of the textbook 18) and the $TXT
        diagnostic surfacing through get_status()."""
        source = UartSource()
        source._connected = True

        for sentence in (
            "$GNGGA,,,,,,0,00,25.5,,,,,,*64",
            "$GNGLL,,,,,,V,N*7A",
            "$GNGSA,A,1,,,,,,,,,,,,,25.5,25.5,25.5,1*01",
            "$GNGSA,A,1,,,,,,,,,,,,,25.5,25.5,25.5,2*02",
            "$GPGSV,1,1,00,0*65",
            "$GLGSV,1,1,00,0*79",
            "$GNRMC,,V,,,,,,,,,,N,V*37",
            "$GNVTG,,,,,,,,,N*2E",
            "$GNZDA,,,,,,*56",
            "$GPTXT,01,01,01,ANTENNA OPEN*25",
        ):
            source._handle_sentence(sentence)

        self.assertIsNone(source._latest_fix)  # genuinely no fix
        self.assertEqual(source._sats_used, 0)
        self.assertEqual(source._last_txt, "ANTENNA OPEN")

        status = source.get_status()
        self.assertTrue(status.available)
        self.assertIsNone(status.fix)
        self.assertIn("0 satellites", status.error)
        self.assertIn("ANTENNA OPEN", status.error)

    def test_no_fix_gga_does_not_clear_an_existing_fix(self) -> None:
        source = UartSource()
        source._handle_gga("$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47")
        self.assertIsNotNone(source._latest_fix)

        source._handle_gga("$GPGGA,123521,,,,,0,00,,,,,,,*66")
        self.assertIsNotNone(source._latest_fix)
        self.assertAlmostEqual(source._latest_fix.latitude, 48.1173, places=3)

    def test_nmea_to_decimal_handles_hemisphere_and_blank_input(self) -> None:
        self.assertAlmostEqual(_nmea_to_decimal("4807.038", "N"), 48.1173, places=4)
        self.assertLess(_nmea_to_decimal("4807.038", "S"), 0)
        self.assertIsNone(_nmea_to_decimal("", "N"))
        self.assertIsNone(_nmea_to_decimal("4807.038", ""))

    async def test_enable_gpios_driven_high_in_order(self) -> None:
        """Confirmed-real-hardware need: the Pisces P100 power-gates its
        onboard GPS behind GPIO 12/20/16 (piscesminer/Firmware-script-p100's
        own boot init.sh). gpiozero isn't installed in this test
        environment (Pi-only hardware lib), so it's stubbed via
        sys.modules the same way this repo already stubs aiosqlite for
        Mac-side testing."""
        calls = []

        class _FakeOutputDevice:
            def __init__(self, pin: int) -> None:
                self.pin = pin

            def on(self) -> None:
                calls.append(self.pin)

        fake_gpiozero = types.ModuleType("gpiozero")
        fake_gpiozero.OutputDevice = _FakeOutputDevice
        sys.modules["gpiozero"] = fake_gpiozero
        try:
            source = UartSource(enable_gpios=[12, 20, 16])
            await source._drive_enable_gpios()
        finally:
            del sys.modules["gpiozero"]

        self.assertEqual(calls, [12, 20, 16])
        self.assertEqual(len(source._enable_gpio_devices), 3)

    async def test_no_enable_gpios_is_a_noop(self) -> None:
        # Default -- boards like the RAK Pi HAT that don't need this.
        source = UartSource()
        self.assertEqual(source._enable_gpios, [])
        # Must not attempt to import gpiozero at all when the list is empty.
        await source._maybe_drive_enable_gpios_once()

    async def test_enable_gpios_only_attempted_once(self) -> None:
        source = UartSource(enable_gpios=[12])
        source._enable_gpios_attempted = True  # simulate "already tried"
        # No gpiozero stub installed -- if the guard were wrong, this
        # would raise ModuleNotFoundError instead of skipping cleanly.
        await source._maybe_drive_enable_gpios_once()

    async def test_enable_gpio_failure_is_captured_not_raised(self) -> None:
        # gpiozero deliberately left unstubbed -- ModuleNotFoundError
        # inside _drive_enable_gpios must be caught, not propagated,
        # so one broken enable sequence doesn't crash the reader loop.
        source = UartSource(enable_gpios=[12])
        await source._maybe_drive_enable_gpios_once()
        self.assertIn("Enable GPIO sequence failed", source._last_error)
        self.assertTrue(source._enable_gpios_attempted)


if __name__ == "__main__":
    unittest.main()
