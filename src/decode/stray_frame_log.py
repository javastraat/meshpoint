"""In-memory ring buffer of RF frames that failed every protocol decoder.

Diagnostic-only, not persisted to the database: the SX1302 concentrator's
broadband capture can plausibly see far more junk/partial RF than genuine
decodable traffic, and there's no way to know that real-world volume ahead
of testing on live hardware. A ring buffer means production never risks an
unbounded (or wrongly-sized) table of noise -- see the RF Environment
page's "Stray Frames" card. If this proves useful once tested live, it can
graduate to a persisted table with a real retention cap later.
"""
from __future__ import annotations

from collections import deque

from src.models.packet import RawCapture

_MAX_ENTRIES = 500
# Defensive cap on stored hex -- genuine LoRaWAN/Meshtastic/MeshCore frames
# are far smaller than this; a huge payload here would itself be a red flag,
# not something worth storing in full.
_MAX_RAW_BYTES = 512


class StrayFrameLog:
    """Ring buffer of frames the PacketRouter (or meshcore_usb adapter) could not decode."""

    def __init__(self, maxlen: int = _MAX_ENTRIES):
        self._entries: "deque[dict]" = deque(maxlen=maxlen)

    def record(self, raw: RawCapture) -> None:
        self._entries.append({
            "received_at": raw.timestamp.timestamp(),
            "capture_source": raw.capture_source,
            "protocol_hint": raw.protocol_hint.value if raw.protocol_hint else None,
            "byte_length": len(raw.payload),
            "rssi": raw.signal.rssi if raw.signal else None,
            "snr": raw.signal.snr if raw.signal else None,
            "raw_hex": raw.payload[:_MAX_RAW_BYTES].hex(),
        })

    def snapshot(self) -> list[dict]:
        """Newest-last, matching deque append order (frontend reverses for display)."""
        return list(self._entries)

    @property
    def count(self) -> int:
        return len(self._entries)
