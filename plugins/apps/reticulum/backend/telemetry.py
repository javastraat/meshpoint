"""Build a Sideband-compatible LXMF telemetry payload from host stats.

Sideband -- and any LXMF client that reads ``FIELD_TELEMETRY`` (0x02) --
expects a msgpacked ``dict`` of ``{ sensor_id: packed_value }``. This
module builds that dict from ``backend/host_stats.py``'s readings; the
caller (``lxmf_service``) msgpacks it with RNS's bundled ``umsgpack`` and
hangs it off an outbound ``LXMessage.fields``.

Deliberately a **small, safe subset** of Sideband's sensor set -- only
the sensors whose ``pack()`` format is a single unambiguous scalar/string
(verified against Sideband's ``sbapp/sideband/sense.py``):

    SID_TIME        0x01  int    unix seconds (always sent)
    SID_TEMPERATURE 0x07  float  celsius -- the CPU/SoC temperature
    SID_INFORMATION 0x0F  str    a one-line human-readable status

    SID_LOCATION    0x02  [7-element struct-packed list] -- only when the
                          operator opts in (Configuration -> GPS pin)

Sideband's structured PROCESSOR / RAM / NVM sensors pack as a nested
``[[label, value], ...]`` list whose exact shape we haven't verified
against a real client, so for now that content goes into the INFORMATION
string instead.

FastAPI-free, stdlib only.
"""

from __future__ import annotations

import struct
import time

# Sideband sensor IDs (sbapp/sideband/sense.py :: Sensor.SID_*)
SID_TIME = 0x01
SID_LOCATION = 0x02
SID_TEMPERATURE = 0x07
SID_INFORMATION = 0x0F


def _info_line(host: dict, node_name: str) -> str:
    """A compact, human-readable status string for the INFORMATION sensor
    -- what shows on a subscriber's telemetry screen as free text."""
    parts: list[str] = []
    if node_name:
        parts.append(node_name)
    load = host.get("load_1m")
    if load is not None:
        parts.append(f"load {load}")
    used, total = host.get("mem_used_mb"), host.get("mem_total_mb")
    if used is not None and total:
        parts.append(f"RAM {round(100 * used / total)}%")
    free_gb = host.get("disk_free_gb")
    if free_gb is not None:
        parts.append(f"disk {free_gb} GB free")
    temp = host.get("cpu_temp_c")
    if temp is not None:
        parts.append(f"{temp}°C")
    return " · ".join(parts) or "meshpoint"


def _pack_location(lat: float, lon: float, alt: float = 0.0) -> list:
    """Sideband's ``Location.pack()`` layout (sense.py) for a fixed pin --
    speed / bearing / accuracy are all 0. Coordinates are big-endian ints
    scaled by 1e6 (deg) / 1e2 (m)."""
    return [
        struct.pack("!i", int(round(lat, 6) * 1e6)),
        struct.pack("!i", int(round(lon, 6) * 1e6)),
        struct.pack("!i", int(round(alt, 2) * 1e2)),
        struct.pack("!I", 0),                       # speed
        struct.pack("!i", 0),                       # bearing
        struct.pack("!H", 0),                       # accuracy
        int(time.time()),                           # last_update
    ]


def build_telemetry(
    host: dict, node_name: str = "",
    location: tuple[float, float, float] | None = None,
) -> dict[int, object]:
    """The ``{ sensor_id: packed_value }`` dict for one telemetry frame.
    The caller msgpacks it. ``host`` is ``host_stats.read_host()``'s
    output (any field may be ``None``). ``location`` is
    ``(lat, lon, alt)`` -- included as ``SID_LOCATION`` only when both
    lat and lon are real numbers."""
    frame: dict[int, object] = {SID_TIME: int(time.time())}
    if location and isinstance(location[0], (int, float)) and isinstance(location[1], (int, float)):
        alt = location[2] if len(location) > 2 and isinstance(location[2], (int, float)) else 0.0
        frame[SID_LOCATION] = _pack_location(location[0], location[1], alt)
    temp = host.get("cpu_temp_c")
    if isinstance(temp, (int, float)):
        frame[SID_TEMPERATURE] = float(temp)
    frame[SID_INFORMATION] = _info_line(host, node_name)
    return frame
