"""SX1302 capture RAM: raw I/Q snapshots of radio A/B, no SX1261 needed.

The SX1302 has a 16 KB debug buffer (4k x 32-bit words) that can record
raw samples from one of 32 internal points. Sources 2 and 3 are the raw
radio A / radio B streams (12-bit I/Q at 4 MHz, ~1 ms per snapshot),
which gives a ~4 MHz-wide spectrum around each RF chain's centre --
the Band Spectrum card's fallback on boards without an SX1261 (RAK2287).

Register sequence and sample decoding are copied from the proven probe
in ``extra/sniffer.c`` (``capture_snapshot``/``capture_decode``), itself
taken from Semtech's ``tst/test_loragw_capture_ram.c``. Hardware run
2026-09-30 on a RAK2287: captures complete reliably and RX keeps
decoding while they run.

Register IDs are indices into libloragw's register table
(``loragw_reg.h``), same convention as the wrapper's hardcoded
``_REG_SERVICE_PEAK1/2``. Callers must hold the wrapper's HAL lock:
reading the RAM flips the SX1302 register page to 1, and any other
register access in that window would land on the wrong page.
"""
from __future__ import annotations

import ctypes
import logging
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# loragw_reg.h
_REG_COMMON_PAGE_PAGE = 0
_REG_CAPTURE_CFG_ENABLE = 1030
_REG_CAPTURE_CFG_CAPTUREWRAP = 1031
_REG_CAPTURE_CFG_CAPTURESTART = 1033
_REG_CAPTURE_CFG_RAMCONFIG = 1034
_REG_CAPTURE_SOURCE_A_SOURCEMUX = 1035
_REG_CAPTURE_PERIOD_0 = 1037
_REG_CAPTURE_PERIOD_1 = 1038
_REG_CAPTURE_STATUS_CAPCOMPLETE = 1039

CAPTURE_RAM_SIZE = 0x4000
SOURCE_RADIO_A = 2
SOURCE_RADIO_B = 3
RAW_SAMPLE_RATE_HZ = 4_000_000

# 4096 samples at 4 MHz take ~1 ms; give up well after that.
_COMPLETE_POLL_S = 0.001
_COMPLETE_MAX_POLLS = 200


def apply_capture_ram_signatures(lib: ctypes.CDLL) -> bool:
    """Set ctypes signatures for the extra calls capture RAM needs.

    Returns False when the loaded libloragw doesn't export them (not
    expected on any real build, but keeps the feature optional rather
    than an import-time crash).
    """
    if not (hasattr(lib, "lgw_reg_r") and hasattr(lib, "lgw_mem_rb")):
        return False
    lib.lgw_reg_r.restype = ctypes.c_int
    lib.lgw_reg_r.argtypes = [ctypes.c_uint16, ctypes.POINTER(ctypes.c_int32)]
    lib.lgw_mem_rb.restype = ctypes.c_int
    lib.lgw_mem_rb.argtypes = [
        ctypes.c_uint16,
        ctypes.POINTER(ctypes.c_uint8),
        ctypes.c_uint16,
        ctypes.c_bool,
    ]
    return True


def read_capture_ram(
    lib: ctypes.CDLL,
    source: int,
    sleep: Callable[[float], None] = time.sleep,
) -> Optional[bytes]:
    """One-shot capture of ``source`` (a 4 MHz raw source); raw RAM bytes.

    Returns None if the capture never completes or the RAM read fails.
    """
    period = 32_000_000 // RAW_SAMPLE_RATE_HZ - 1
    lib.lgw_reg_w(_REG_CAPTURE_CFG_ENABLE, 1)
    lib.lgw_reg_w(_REG_CAPTURE_CFG_CAPTUREWRAP, 0)   # one shot
    lib.lgw_reg_w(_REG_CAPTURE_CFG_RAMCONFIG, 0)     # 4k x 32
    lib.lgw_reg_w(_REG_CAPTURE_SOURCE_A_SOURCEMUX, source)
    lib.lgw_reg_w(_REG_CAPTURE_PERIOD_0, period & 0xFF)
    lib.lgw_reg_w(_REG_CAPTURE_PERIOD_1, (period >> 8) & 0xFF)
    lib.lgw_reg_w(_REG_CAPTURE_CFG_CAPTURESTART, 1)

    done = ctypes.c_int32(0)
    for _ in range(_COMPLETE_MAX_POLLS):
        sleep(_COMPLETE_POLL_S)
        lib.lgw_reg_r(_REG_CAPTURE_STATUS_CAPCOMPLETE, ctypes.byref(done))
        if done.value == 1:
            break
    lib.lgw_reg_w(_REG_CAPTURE_CFG_CAPTURESTART, 0)
    if done.value != 1:
        logger.warning("Capture RAM: source %d did not complete", source)
        return None

    buf = (ctypes.c_uint8 * CAPTURE_RAM_SIZE)()
    lib.lgw_reg_w(_REG_COMMON_PAGE_PAGE, 1)
    try:
        err = lib.lgw_mem_rb(0, buf, CAPTURE_RAM_SIZE, False)
    finally:
        lib.lgw_reg_w(_REG_COMMON_PAGE_PAGE, 0)
    if err != 0:
        logger.warning("Capture RAM: lgw_mem_rb failed (%d)", err)
        return None
    return bytes(buf)


def decode_iq_12bit(raw: bytes) -> list[complex]:
    """Decode sources 2/3 (12-bit I/Q, one sample per 32-bit word).

    Word layout (little-endian bytes w0..w3): I = w3:w2 >> 4, Q = w1:w0 >> 4,
    both signed -- same as ``capture_decode`` in extra/sniffer.c.
    """
    out = []
    for k in range(0, len(raw) - 3, 4):
        i = int.from_bytes(raw[k + 2:k + 4], "little", signed=True) >> 4
        q = int.from_bytes(raw[k:k + 2], "little", signed=True) >> 4
        out.append(complex(i, q))
    return out
