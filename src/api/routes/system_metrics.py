"""System-level hardware metrics for the Meshpoint host."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from fastapi import APIRouter, Depends

from src.system_metrics import cpu_sampler

from src.api.auth.dependencies import require_auth
from src.api.auth.metrics_api_key import require_session_or_metrics_key

if TYPE_CHECKING:
    from src.hardware.fan_control import CpuTempSampler, FanController

router = APIRouter(prefix="/api/device", tags=["device"])

_fan_controller: Optional["FanController"] = None
# Whatever is actually sampling CPU temperature history right now --
# the real FanController when fan.enabled, otherwise a plain
# CpuTempSampler (temp reading isn't tied to whether a fan is wired
# up). None only if somehow neither was started.
_temp_sampler: Optional["CpuTempSampler"] = None


def init_routes(
    fan_controller: Optional["FanController"] = None,
    temp_sampler: Optional["CpuTempSampler"] = None,
) -> None:
    global _fan_controller, _temp_sampler
    _fan_controller = fan_controller
    _temp_sampler = temp_sampler or fan_controller


def reset_routes() -> None:
    global _fan_controller, _temp_sampler
    _fan_controller = None
    _temp_sampler = None


def _read_cpu_temp() -> float | None:
    """Read CPU temperature from the thermal zone (Linux/RPi)."""
    thermal = Path("/sys/class/thermal/thermal_zone0/temp")
    try:
        return int(thermal.read_text().strip()) / 1000.0
    except (FileNotFoundError, ValueError, OSError):
        return None


def _read_load_avg() -> tuple[float, float, float] | None:
    """Read the 1/5/15-minute load averages from /proc/loadavg (Linux)."""
    try:
        fields = Path("/proc/loadavg").read_text().split()
        return float(fields[0]), float(fields[1]), float(fields[2])
    except (FileNotFoundError, ValueError, OSError, IndexError):
        return None


def _read_uptime_seconds() -> float:
    """Read system uptime from /proc/uptime (Linux)."""
    try:
        return float(Path("/proc/uptime").read_text().split()[0])
    except (FileNotFoundError, ValueError, OSError, IndexError):
        return 0.0


@router.get("/metrics", dependencies=[Depends(require_session_or_metrics_key)])
async def system_metrics():
    import psutil

    mem = psutil.virtual_memory()
    disk = shutil.disk_usage("/")
    cpu_temp = _read_cpu_temp()
    load_avg = _read_load_avg()

    return {
        "cpu_percent": cpu_sampler.value,  # None while warming up
        "memory_percent": mem.percent,
        "memory_used_mb": round(mem.used / (1024 * 1024)),
        "memory_total_mb": round(mem.total / (1024 * 1024)),
        "disk_percent": round(disk.used / disk.total * 100, 1),
        "disk_used_gb": round(disk.used / (1024 ** 3), 1),
        "disk_total_gb": round(disk.total / (1024 ** 3), 1),
        "cpu_temp_c": round(cpu_temp, 1) if cpu_temp is not None else None,
        "load_avg": [round(v, 2) for v in load_avg] if load_avg is not None else None,
        "system_uptime_seconds": int(_read_uptime_seconds()),
        "fan_duty_percent": (
            round(_fan_controller.current_duty * 100, 1)
            if _fan_controller is not None else None
        ),
        "fan_previous_duty_percent": (
            round(_fan_controller.previous_duty * 100, 1)
            if _fan_controller is not None else None
        ),
    }


@router.get("/thermals", dependencies=[Depends(require_auth)])
async def thermals():
    """CPU temperature (+ fan duty, when a fan is actually configured)
    history for the Hardware Thermals chart.

    Temperature is always sampled (``CpuTempSampler``, or the fuller
    ``FanController`` when ``fan.enabled``) -- reading the SoC's own
    thermal zone has nothing to do with whether a PWM fan happens to be
    wired up, so boards with no fan (e.g. RAK V2) still get a
    temperature history. ``fan_available`` tells the frontend whether
    to also render the fan-duty panel; each point's ``duty`` key is
    only present when it does. ``available: false`` only when
    literally nothing is sampling temperature at all. In-memory ring
    buffer -- cleared on restart, no database involvement.
    """
    if _temp_sampler is None:
        return {"available": False, "fan_available": False, "points": []}

    has_fan = _fan_controller is not None
    if has_fan:
        points = [
            {"ts": int(ts), "temp_c": round(temp, 1), "duty": duty}
            for ts, temp, duty in _fan_controller.history
        ]
    else:
        points = [
            {"ts": int(ts), "temp_c": round(temp, 1)}
            for ts, temp in _temp_sampler.history
        ]
    return {
        "available": True,
        "fan_available": has_fan,
        "poll_interval_s": _temp_sampler.poll_interval_s,
        "points": points,
    }
