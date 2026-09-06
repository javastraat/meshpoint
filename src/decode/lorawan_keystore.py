"""In-memory LoRaWAN key store.

Holds each device's OTAA root keys (AppKey/NwkKey, from config -- see
LoRaWANConfig in src/config.py) keyed by DevEUI, plus derived per-session
AppSKeys keyed by DevAddr, populated live as real Join-Accepts get
captured and decrypted. Same shape/precedent as CryptoService's channel
keys, kept separate since the key material and wire format are unrelated.

DevAddr is the only thing _decode_data_up() has to key off of (that's
all a Data Up frame carries), and it's only known once a device's own
Join-Accept has actually been seen and decrypted -- so unlike
Meshtastic/Meshcore's channel keys (configured once, valid immediately),
a LoRaWAN device configured here won't actually decrypt anything until
its next real OTAA join happens over the air and gets captured.
"""
from __future__ import annotations

import logging
from typing import Optional

from src.decode.lorawan_payload_formats import PayloadField

logger = logging.getLogger(__name__)


class LoRaWANKeyStore:

    def __init__(self) -> None:
        self._root_keys: dict[str, tuple[bytes, bytes]] = {}  # dev_eui -> (app_key, nwk_key)
        self._payload_fields: dict[str, list[PayloadField]] = {}  # dev_eui -> field list, see lorawan_payload_formats.py
        self._session_keys: dict[int, bytes] = {}  # dev_addr -> app_skey
        self._dev_addr_eui: dict[int, str] = {}  # dev_addr -> dev_eui, so payload_fields_for_addr() can look one up

    def add_device(
        self,
        dev_eui: str,
        app_key_hex: str,
        nwk_key_hex: str,
        payload_fields: Optional[list[PayloadField]] = None,
    ) -> None:
        """dev_eui: colon-formatted, matching lorawan_decoder.py's _eui_str()
        output (e.g. "70:B3:D5:7E:D0:07:8B:FD"). app_key_hex/nwk_key_hex:
        32 hex chars (16 bytes) each, as shown on TTN Console's device page.
        payload_fields: optional, this device's own declarative FRMPayload
        field list (see lorawan_payload_formats.py) -- opt-in per device,
        never a blanket assumption applied to any device using a given
        FPort, since FPort is just an app-chosen channel number with no
        fixed meaning across devices.
        """
        try:
            app_key = bytes.fromhex(app_key_hex)
            nwk_key = bytes.fromhex(nwk_key_hex)
        except (ValueError, TypeError) as exc:
            raise ValueError(
                f"LoRaWAN keys for {dev_eui} must be hex strings "
                f"(32 hex chars = 16 bytes each): {exc}"
            ) from exc
        if len(app_key) != 16 or len(nwk_key) != 16:
            raise ValueError(
                f"LoRaWAN keys must be 16 bytes (32 hex chars): "
                f"app_key={len(app_key)}B nwk_key={len(nwk_key)}B"
            )
        dev_eui = dev_eui.upper()
        self._root_keys[dev_eui] = (app_key, nwk_key)
        if payload_fields:
            self._payload_fields[dev_eui] = payload_fields

    def root_keys_for(self, dev_eui: str) -> Optional[tuple[bytes, bytes]]:
        """Returns (app_key, nwk_key) or None if this DevEUI isn't configured."""
        return self._root_keys.get(dev_eui.upper())

    def has_device(self, dev_eui: str) -> bool:
        return dev_eui.upper() in self._root_keys

    def set_session_key(self, dev_addr: int, app_skey: bytes, dev_eui: str) -> None:
        """Called once a Join-Accept for this device has been decrypted
        and AppSKey derived -- see lorawan_decoder.py's _decode_join_accept().
        Overwrites any previous session for the same DevAddr (a rejoin
        legitimately changes it). dev_eui is recorded too so
        payload_fields_for_addr() has something to look the fields up by
        -- Data Up frames only ever carry DevAddr, never DevEUI."""
        self._session_keys[dev_addr] = app_skey
        self._dev_addr_eui[dev_addr] = dev_eui.upper()
        logger.info("LoRaWAN: session AppSKey installed for DevAddr=%08X", dev_addr)

    def session_key_for(self, dev_addr: int) -> Optional[bytes]:
        return self._session_keys.get(dev_addr)

    def payload_fields_for_addr(self, dev_addr: int) -> Optional[list[PayloadField]]:
        dev_eui = self._dev_addr_eui.get(dev_addr)
        if dev_eui is None:
            return None
        return self._payload_fields.get(dev_eui)
