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

Sideband's structured PROCESSOR / RAM / NVM sensors pack as a nested
``[[label, value], ...]`` list whose exact shape we haven't verified
against a real client, so for now that content goes into the INFORMATION
string instead. Location is intentionally omitted from v1 (opt-in privacy
surface + its own struct layout) -- add it when the collector/map lands.

FastAPI-free, stdlib only.
"""

from __future__ import annotations

import time

# Sideband sensor IDs (sbapp/sideband/sense.py :: Sensor.SID_*)
SID_TIME = 0x01
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


def build_telemetry(host: dict, node_name: str = "") -> dict[int, object]:
    """The ``{ sensor_id: packed_value }`` dict for one telemetry frame.
    The caller msgpacks it. ``host`` is ``host_stats.read_host()``'s
    output (any field may be ``None``)."""
    frame: dict[int, object] = {SID_TIME: int(time.time())}
    temp = host.get("cpu_temp_c")
    if isinstance(temp, (int, float)):
        frame[SID_TEMPERATURE] = float(temp)
    frame[SID_INFORMATION] = _info_line(host, node_name)
    return frame
