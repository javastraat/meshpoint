"""Meshtastic RX preamble for the SX1302 LoRa service modem (ch8).

Ported from upstream KMX415/meshpoint fcacc92b (#179). lgw_start() sets the
service modem's RX preamble to the HAL default of 8 symbols; Meshtastic
transmits 16. This sets 16 after every lgw_start() and reads it back.

Only the LoRa service modem's RX preamble registers are touched: not the
multi-SF channels (ch0-7, LoRaWAN), not the FSK channel (ch9 has its own
FSK_CFG registers), and not TX (each TX packet carries its own preamble).
"""

from __future__ import annotations

import ctypes
import logging

logger = logging.getLogger(__name__)

# Semtech sx1302_hal V2.1.0 loragw_reg.h:
# SX1302_REG_RX_TOP_LORA_SERVICE_FSK_TXRX_CFG6/7_PREAMBLE_SYMB_NB.
# Register-table IDs for lgw_reg_w/lgw_reg_r, not bus addresses.
SERVICE_PREAMBLE_LOW = 916
SERVICE_PREAMBLE_HIGH = 917
MESHTASTIC_PREAMBLE = 16


def configure_service_preamble(lib) -> None:
    """Set the service modem RX preamble to 16 and verify it.

    Call after every lgw_start(), which resets these registers.
    Raises RuntimeError when the HAL lacks register access or the
    write/read-back fails; the caller decides what that means.
    """
    try:
        write = lib.lgw_reg_w
        read = lib.lgw_reg_r
    except AttributeError as exc:
        raise RuntimeError("HAL lacks service-modem preamble register access") from exc
    write.argtypes = [ctypes.c_uint16, ctypes.c_int32]
    write.restype = ctypes.c_int
    read.argtypes = [ctypes.c_uint16, ctypes.POINTER(ctypes.c_int32)]
    read.restype = ctypes.c_int
    for register, value in ((SERVICE_PREAMBLE_LOW, MESHTASTIC_PREAMBLE),
                            (SERVICE_PREAMBLE_HIGH, 0)):
        if write(register, value) != 0:
            raise RuntimeError("Cannot set LoRa service modem RX preamble")
    values = []
    for register in (SERVICE_PREAMBLE_LOW, SERVICE_PREAMBLE_HIGH):
        value = ctypes.c_int32()
        if read(register, ctypes.byref(value)) != 0:
            raise RuntimeError("Cannot read LoRa service modem RX preamble")
        values.append(value.value)
    if values != [MESHTASTIC_PREAMBLE, 0]:
        raise RuntimeError(
            f"LoRa service modem RX preamble verification failed (read {values})"
        )
    logger.info("LoRa service modem RX preamble verified: %d symbols", MESHTASTIC_PREAMBLE)
