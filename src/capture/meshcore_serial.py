"""MeshCore serial transport that releases DTR on CP210x USB bridges.

Adapted from upstream KMX415/meshpoint `src/capture/meshcore_serial.py`
(b91d994b). On CP210x bridges (older ESP32 boards: Heltec V2, T-Beam, ...)
an asserted DTR line can act like a held BOOT button and drop the companion
into its firmware's rescue console shortly after the port opens: a brief
connection, then only query timeouts. Native USB CDC boards (ESP32-S3: Heltec
V3/V4) may need DTR asserted, so they keep the library's default.

The library's own ``MeshCore.create_serial()`` also retries once with DTR
inverted when the node doesn't answer; ``MeshcoreUsbCaptureSource`` keeps
that retry (``release_dtr`` flipped), which upstream's version dropped.
"""

from __future__ import annotations

import os
from typing import Optional

# Silicon Labs CP210x USB-UART bridges (VID 0x10C4).
_CP210X_PIDS = frozenset({0xEA60, 0xEA70, 0xEA71})


def is_cp210x(port: str) -> bool:
    """True when ``port`` (any alias, e.g. /dev/serial/by-path/...) is a CP210x."""
    try:
        from serial.tools import list_ports
    except ImportError:
        return False
    selected = os.path.normcase(os.path.realpath(port))
    try:
        ports = list_ports.comports()
    except Exception:
        return False
    return any(
        item.vid == 0x10C4 and item.pid in _CP210X_PIDS
        and os.path.normcase(os.path.realpath(item.device)) == selected
        for item in ports
    )


def create_serial_connection(port: str, baud_rate: int, release_dtr: Optional[bool] = None):
    """A meshcore ``SerialConnection`` for ``port``.

    ``release_dtr`` None = decide by hardware (released on CP210x only);
    True/False forces it (used for the one retry with DTR inverted).
    Imported lazily so installs without the meshcore package still load.
    """
    from meshcore.serial_cx import SerialConnection

    if release_dtr is None:
        release_dtr = is_cp210x(port)
    if not release_dtr:
        return SerialConnection(port, baud_rate, cx_dly=0.1)

    class ReleasedDtrConnection(SerialConnection):
        class MCSerialClientProtocol(SerialConnection.MCSerialClientProtocol):
            def connection_made(self, transport):
                super().connection_made(transport)
                # Works on library versions with and without a ``dtr`` argument.
                serial_port = getattr(transport, "serial", None)
                if serial_port is not None:
                    serial_port.dtr = False

    return ReleasedDtrConnection(port, baud_rate, cx_dly=0.1)
