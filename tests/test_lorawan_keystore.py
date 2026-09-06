"""Tests for LoRaWANKeyStore."""

from __future__ import annotations

import unittest

from src.decode.lorawan_keystore import LoRaWANKeyStore


class TestLoRaWANKeyStore(unittest.TestCase):

    def test_add_and_lookup_root_keys(self):
        store = LoRaWANKeyStore()
        dev_eui = "70:B3:D5:7E:D0:07:8B:FD"
        app_key_hex = "10" * 16
        nwk_key_hex = "20" * 16

        store.add_device(dev_eui, app_key_hex, nwk_key_hex)

        self.assertTrue(store.has_device(dev_eui))
        app_key, nwk_key = store.root_keys_for(dev_eui)
        self.assertEqual(app_key, bytes.fromhex(app_key_hex))
        self.assertEqual(nwk_key, bytes.fromhex(nwk_key_hex))

    def test_lookup_is_case_insensitive(self):
        store = LoRaWANKeyStore()
        store.add_device("70:b3:d5:7e:d0:07:8b:fd", "10" * 16, "20" * 16)

        self.assertTrue(store.has_device("70:B3:D5:7E:D0:07:8B:FD"))

    def test_unconfigured_device_returns_none(self):
        store = LoRaWANKeyStore()
        self.assertIsNone(store.root_keys_for("00:00:00:00:00:00:00:00"))
        self.assertFalse(store.has_device("00:00:00:00:00:00:00:00"))

    def test_wrong_key_length_rejected(self):
        store = LoRaWANKeyStore()
        with self.assertRaises(ValueError):
            store.add_device("70:B3:D5:7E:D0:07:8B:FD", "1234", "20" * 16)

    def test_non_hex_key_rejected_with_a_clear_message(self):
        store = LoRaWANKeyStore()
        with self.assertRaises(ValueError) as ctx:
            store.add_device("70:B3:D5:7E:D0:07:8B:FD", "YOUR_APP_KEY_HEX", "20" * 16)
        msg = str(ctx.exception)
        self.assertIn("70:B3:D5:7E:D0:07:8B:FD", msg)
        self.assertIn("hex", msg.lower())
        # not the bare "non-hexadecimal number found in fromhex()" surprise
        self.assertNotEqual(msg, "non-hexadecimal number found in fromhex() arg at position 0")

    def test_session_key_round_trip(self):
        store = LoRaWANKeyStore()
        self.assertIsNone(store.session_key_for(0x260BA627))

        app_skey = bytes(range(16))
        store.set_session_key(0x260BA627, app_skey, "70:B3:D5:7E:D0:07:8B:FD")

        self.assertEqual(store.session_key_for(0x260BA627), app_skey)

    def test_rejoin_overwrites_previous_session_key(self):
        store = LoRaWANKeyStore()
        store.set_session_key(1, bytes(16), "70:B3:D5:7E:D0:07:8B:FD")
        store.set_session_key(1, bytes(range(16)), "70:B3:D5:7E:D0:07:8B:FD")

        self.assertEqual(store.session_key_for(1), bytes(range(16)))

    def test_payload_fields_looked_up_via_dev_addr(self):
        store = LoRaWANKeyStore()
        dev_eui = "70:B3:D5:7E:D0:07:8B:FD"
        fields = [{"name": "temperature_c", "type": "int16_be", "scale": 0.01}]
        store.add_device(dev_eui, "10" * 16, "20" * 16, payload_fields=fields)

        self.assertIsNone(store.payload_fields_for_addr(0x260BA627))  # not joined yet

        store.set_session_key(0x260BA627, bytes(16), dev_eui)

        self.assertEqual(store.payload_fields_for_addr(0x260BA627), fields)

    def test_no_payload_fields_configured_returns_none(self):
        store = LoRaWANKeyStore()
        dev_eui = "70:B3:D5:7E:D0:07:8B:FD"
        store.add_device(dev_eui, "10" * 16, "20" * 16)  # no payload_fields
        store.set_session_key(0x260BA627, bytes(16), dev_eui)

        self.assertIsNone(store.payload_fields_for_addr(0x260BA627))


if __name__ == "__main__":
    unittest.main()
