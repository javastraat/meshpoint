"""Storage, capture, relay, and radio advanced settings."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.api.audit import AuditLogWriter
from src.api.audit.dependencies import get_audit_writer
from src.api.auth.dependencies import require_admin, require_auth
from src.api.auth.jwt_session import SessionClaims
from src.config import AppConfig, save_section_to_yaml

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/config", tags=["config"])

_config: AppConfig | None = None


def init_routes(config: AppConfig) -> None:
    global _config
    _config = config


def reset_routes() -> None:
    global _config
    _config = None


class StorageUpdate(BaseModel):
    max_packets_retained: Optional[int] = Field(None, ge=1000, le=10_000_000)
    max_telemetry_retained: Optional[int] = Field(None, ge=1000, le=10_000_000)
    cleanup_interval_seconds: Optional[int] = Field(None, ge=60, le=86400)


class MeshcoreUsbUpdate(BaseModel):
    serial_port: Optional[str] = None
    baud_rate: Optional[int] = Field(None, ge=9600, le=921600)
    auto_detect: Optional[bool] = None
    enable_source: Optional[bool] = None


class CompanionEntry(BaseModel):
    label: str = ""
    serial_port: Optional[str] = None
    baud_rate: int = Field(115200, ge=9600, le=921600)
    auto_detect: bool = True


class MeshcoreCompanionsUpdate(BaseModel):
    companions: list[CompanionEntry] = Field(..., min_length=0, max_length=4)
    enable_source: Optional[bool] = None


class SerialDeviceEntry(BaseModel):
    label: str = ""
    serial_port: Optional[str] = None
    serial_baud: int = Field(115200, ge=9600, le=921600)


class SerialDevicesUpdate(BaseModel):
    devices: list[SerialDeviceEntry] = Field(..., min_length=0, max_length=4)
    enable_source: Optional[bool] = None


class RelayUpdate(BaseModel):
    enabled: Optional[bool] = None
    serial_port: Optional[str] = None
    serial_baud: Optional[int] = Field(None, ge=9600, le=921600)
    max_relay_per_minute: Optional[int] = Field(None, ge=0, le=600)
    burst_size: Optional[int] = Field(None, ge=1, le=50)
    min_relay_rssi: Optional[float] = Field(None, ge=-150, le=0)
    max_relay_rssi: Optional[float] = Field(None, ge=-150, le=0)


class RadioAdvancedUpdate(BaseModel):
    spectral_scan_interval_seconds: Optional[float] = Field(None, ge=0, le=3600)
    sx1261_spi_path: Optional[str] = None


# Generous but safety-bounding: comfortably covers the whole ETSI sub-band
# P window (only +-125 kHz from RF1's 869.525 MHz anchor in the EU868
# plan) while still catching a frequency meant for a different RF chain
# or region -- the SX1302's real per-chain IF range is on this order
# (the existing ch0-7 multi-SF plan already spans +-400 kHz from RF0's
# anchor without issue).
_PAGER_MAX_IF_OFFSET_HZ = 1_000_000


class RadioPagerUpdate(BaseModel):
    """Deliberately does NOT expose pager_rf_chain. The bounded frequency
    range below only makes physical sense on RF1 in this deployment (RF0
    is anchored at 868.3 MHz, nowhere near 869.4-869.65 MHz) -- letting a
    user pick RF0 here would just produce a huge, likely-rejected IF
    offset with no valid reason to ever do it. Still adjustable directly
    in local.yaml for a genuine re-plan, just not surfaced as a UI trap.
    """
    pager_enabled: Optional[bool] = None
    # ETSI EU868 "sub-band P" high-power window -- the whole reason this
    # channel can use 10% duty / 500mW instead of the standard 1%/25mW.
    # Bounded here so a typo can't silently move the pager outside the
    # regulatory window it was specifically chosen to sit in.
    pager_frequency_mhz: Optional[float] = Field(None, ge=869.40, le=869.65)
    pager_sync_word: Optional[int] = Field(None, ge=0, le=0xFFFFFFFFFFFFFFFF)
    pager_sync_word_size: Optional[int] = Field(None, ge=1, le=8)
    # This device's own POCSAG-style capcode -- pure software (read fresh
    # on every send/receive, no HAL reconfiguration involved), unlike the
    # four fields above which all need a restart to reach the hardware.
    pager_capcode: Optional[int] = Field(None, ge=0, le=0xFFFFFFFF)


@router.get("/serial-ports")
async def get_serial_ports(_claims: SessionClaims = Depends(require_auth)) -> dict:
    """Enumerate connected USB-serial devices for the dashboard's port
    picker (Configuration -> Serial / MeshCore's "Pinned serial port"
    fields).

    Read-only/no side effects, so unlike the save routes below this
    doesn't require admin -- any logged-in session can list.

    ``stable_path`` is the recommended value to pin: prefers
    ``/dev/serial/by-path/...`` over the raw ``/dev/ttyUSBn`` (or
    ``by-id`` when by-path is unavailable) since it stays unique per
    physical USB port even when two boards share an identical
    (often unprogrammed) vendor serial number -- confirmed on cheap
    CP210x clone boards, where ``/dev/serial/by-id/`` can only keep one
    symlink per unique name and silently drops the other device.

    Filters to devices with a real USB VID/PID -- this card is
    specifically for USB capture sources, and pyserial's enumeration
    also returns the Pi's own onboard UARTs (``/dev/ttyAMA0``,
    ``/dev/ttyS0``), which never carry a VID/PID and are never a
    MeshCore/Meshtastic USB stick.
    """
    from src.hal.usb_classifier import (
        list_serial_ports_with_stable_paths,
        serial_port_held_hint,
    )
    ports = [p for p in list_serial_ports_with_stable_paths() if p.vid is not None]
    return {
        "ports": [
            {
                "device": p.device,
                "stable_path": p.stable_path,
                "by_id": p.by_id,
                "by_path": p.by_path,
                "description": p.description,
                "vid": f"{p.vid:04x}" if p.vid is not None else None,
                "pid": f"{p.pid:04x}" if p.pid is not None else None,
                "port_class": p.port_class.value,
                "held_hint": serial_port_held_hint(p.port_class),
            }
            for p in ports
        ],
    }


@router.put("/storage")
async def update_storage(
    req: StorageUpdate,
    _claims: SessionClaims = Depends(require_admin),
    audit: AuditLogWriter = Depends(get_audit_writer),
):
    if _config is None:
        raise HTTPException(503, "Config not loaded")

    updates: dict = {}
    storage = _config.storage
    restart_needed = False

    if req.max_packets_retained is not None:
        storage.max_packets_retained = req.max_packets_retained
        updates["max_packets_retained"] = req.max_packets_retained
    if req.max_telemetry_retained is not None:
        storage.max_telemetry_retained = req.max_telemetry_retained
        updates["max_telemetry_retained"] = req.max_telemetry_retained
    if req.cleanup_interval_seconds is not None:
        storage.cleanup_interval_seconds = req.cleanup_interval_seconds
        updates["cleanup_interval_seconds"] = req.cleanup_interval_seconds

    if not updates:
        return {"saved": False, "restart_required": False}

    with audit.timed_action(
        user=_claims.subject, action="config.storage_update", params=updates
    ):
        try:
            save_section_to_yaml("storage", updates)
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc

    return {"saved": True, "restart_required": restart_needed, "updates": updates}


@router.put("/capture/meshcore-usb")
async def update_meshcore_usb(
    req: MeshcoreUsbUpdate,
    _claims: SessionClaims = Depends(require_admin),
    audit: AuditLogWriter = Depends(get_audit_writer),
):
    if _config is None:
        raise HTTPException(503, "Config not loaded")

    # The UI manages the primary (first) companion; extras are edited via local.yaml.
    companions = _config.capture.meshcore_usb
    mc_usb = companions[0] if companions else None
    if mc_usb is None:
        raise HTTPException(500, "No MeshCore USB companion configured")

    usb_updates: dict = {}
    capture_updates: dict = {}
    restart_needed = False

    if req.serial_port is not None:
        port = req.serial_port.strip() or None
        mc_usb.serial_port = port
        usb_updates["serial_port"] = port
        restart_needed = True
    if req.baud_rate is not None:
        mc_usb.baud_rate = req.baud_rate
        usb_updates["baud_rate"] = req.baud_rate
        restart_needed = True
    if req.auto_detect is not None:
        mc_usb.auto_detect = req.auto_detect
        usb_updates["auto_detect"] = req.auto_detect
        restart_needed = True

    sources = list(_config.capture.sources or [])
    if req.enable_source is not None:
        has_usb = "meshcore_usb" in sources
        if req.enable_source and not has_usb:
            sources.append("meshcore_usb")
            capture_updates["sources"] = sources
            _config.capture.sources = sources
            restart_needed = True
        elif not req.enable_source and has_usb:
            sources = [s for s in sources if s != "meshcore_usb"]
            capture_updates["sources"] = sources
            _config.capture.sources = sources
            restart_needed = True

    if not usb_updates and not capture_updates:
        return {"saved": False, "restart_required": False}

    with audit.timed_action(
        user=_claims.subject,
        action="config.meshcore_usb_update",
        params={"usb": usb_updates, "capture": capture_updates},
    ):
        try:
            if usb_updates:
                # Persist the full list so extra companions are not lost.
                all_companions = [
                    {**_meshcore_usb_dict(c), **(usb_updates if c is mc_usb else {})}
                    for c in companions
                ]
                save_section_to_yaml("capture", {"meshcore_usb": all_companions})
            if capture_updates:
                save_section_to_yaml("capture", capture_updates)
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc

    return {"saved": True, "restart_required": restart_needed}


@router.put("/capture/meshcore-companions")
async def update_meshcore_companions(
    req: MeshcoreCompanionsUpdate,
    _claims: SessionClaims = Depends(require_admin),
    audit: AuditLogWriter = Depends(get_audit_writer),
):
    """Replace the full MeshCore USB companion list (up to 4 entries)."""
    from src.config import MeshcoreUsbConfig
    if _config is None:
        raise HTTPException(503, "Config not loaded")

    # This form doesn't edit companion_name (that's the per-companion
    # rename card's job) -- preserve each existing companion's own name by
    # label match so replacing the list here doesn't silently wipe it.
    old_names = {c.label: c.companion_name for c in _config.capture.meshcore_usb}

    new_companions = [
        MeshcoreUsbConfig(
            label=c.label,
            serial_port=c.serial_port.strip() if c.serial_port else None,
            baud_rate=c.baud_rate,
            auto_detect=c.auto_detect,
            companion_name=old_names.get(c.label),
        )
        for c in req.companions
    ]
    _config.capture.meshcore_usb = new_companions

    yaml_updates: dict = {}
    capture_updates: dict = {}

    companions_list = [_meshcore_usb_dict(c) for c in new_companions]
    yaml_updates["meshcore_usb"] = companions_list

    sources = list(_config.capture.sources or [])
    if req.enable_source is not None:
        has_usb = "meshcore_usb" in sources
        if req.enable_source and not has_usb:
            sources.append("meshcore_usb")
            capture_updates["sources"] = sources
            _config.capture.sources = sources
        elif not req.enable_source and has_usb:
            sources = [s for s in sources if s != "meshcore_usb"]
            capture_updates["sources"] = sources
            _config.capture.sources = sources

    with audit.timed_action(
        user=_claims.subject,
        action="config.meshcore_companions_update",
        params={"companions": companions_list},
    ):
        try:
            save_section_to_yaml("capture", {**yaml_updates, **capture_updates})
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc

    return {"saved": True, "restart_required": True}


@router.put("/capture/serial-devices")
async def update_serial_devices(
    req: SerialDevicesUpdate,
    _claims: SessionClaims = Depends(require_admin),
    audit: AuditLogWriter = Depends(get_audit_writer),
):
    """Replace the full Meshtastic USB serial device list (up to 4 entries).

    Mirrors ``update_meshcore_companions`` -- same shape, minus
    ``auto_detect`` (SerialDeviceConfig has no such field: an empty
    serial_port already means "let meshtastic-python auto-detect").
    """
    from src.config import SerialDeviceConfig
    if _config is None:
        raise HTTPException(503, "Config not loaded")

    # This form doesn't edit long_name/short_name (that's the per-device
    # identity card's job) -- preserve each existing device's own
    # configured identity by label match so replacing the list here
    # doesn't silently wipe it (mirrors update_meshcore_companions'
    # identical companion_name preservation fix).
    old_identity = {
        d.label: (d.long_name, d.short_name) for d in _config.capture.serial
    }

    # A blank serial_port means "auto-detect" -- fine for a single device,
    # but among 2+ devices an ambiguous auto-detect row can re-open
    # whatever port another row already has claimed and crash on the
    # exclusive lock. Drop blank rows once there's more than one.
    devices_in = req.devices
    if len(devices_in) > 1:
        devices_in = [d for d in devices_in if (d.serial_port or "").strip()]

    new_devices = [
        SerialDeviceConfig(
            label=d.label,
            serial_port=d.serial_port.strip() if d.serial_port else None,
            serial_baud=d.serial_baud,
            long_name=old_identity.get(d.label, (None, None))[0],
            short_name=old_identity.get(d.label, (None, None))[1],
        )
        for d in devices_in
    ]
    _config.capture.serial = new_devices

    yaml_updates: dict = {}
    capture_updates: dict = {}

    devices_list = [_serial_device_dict(d) for d in new_devices]
    yaml_updates["serial"] = devices_list

    sources = list(_config.capture.sources or [])
    if req.enable_source is not None:
        has_serial = "serial" in sources
        if req.enable_source and not has_serial:
            sources.append("serial")
            capture_updates["sources"] = sources
            _config.capture.sources = sources
        elif not req.enable_source and has_serial:
            sources = [s for s in sources if s != "serial"]
            capture_updates["sources"] = sources
            _config.capture.sources = sources

    with audit.timed_action(
        user=_claims.subject,
        action="config.serial_devices_update",
        params={"devices": devices_list},
    ):
        try:
            save_section_to_yaml("capture", {**yaml_updates, **capture_updates})
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc

    return {"saved": True, "restart_required": True}


@router.put("/relay")
async def update_relay(
    req: RelayUpdate,
    _claims: SessionClaims = Depends(require_admin),
    audit: AuditLogWriter = Depends(get_audit_writer),
):
    if _config is None:
        raise HTTPException(503, "Config not loaded")

    updates: dict = {}
    relay = _config.relay
    restart_needed = False

    if req.enabled is not None:
        relay.enabled = req.enabled
        updates["enabled"] = req.enabled
        restart_needed = True
    if req.serial_port is not None:
        relay.serial_port = req.serial_port.strip() or None
        updates["serial_port"] = relay.serial_port
        restart_needed = True
    if req.serial_baud is not None:
        relay.serial_baud = req.serial_baud
        updates["serial_baud"] = req.serial_baud
    if req.max_relay_per_minute is not None:
        relay.max_relay_per_minute = req.max_relay_per_minute
        updates["max_relay_per_minute"] = req.max_relay_per_minute
    if req.burst_size is not None:
        relay.burst_size = req.burst_size
        updates["burst_size"] = req.burst_size
    if req.min_relay_rssi is not None:
        relay.min_relay_rssi = req.min_relay_rssi
        updates["min_relay_rssi"] = req.min_relay_rssi
    if req.max_relay_rssi is not None:
        if req.max_relay_rssi <= relay.min_relay_rssi:
            raise HTTPException(400, "max_relay_rssi must be greater than min_relay_rssi")
        relay.max_relay_rssi = req.max_relay_rssi
        updates["max_relay_rssi"] = req.max_relay_rssi

    if not updates:
        return {"saved": False, "restart_required": False}

    with audit.timed_action(
        user=_claims.subject, action="config.relay_update", params=updates
    ):
        try:
            save_section_to_yaml("relay", updates)
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc

    return {"saved": True, "restart_required": restart_needed, "updates": updates}


@router.put("/radio/pager")
async def update_radio_pager(
    req: RadioPagerUpdate,
    _claims: SessionClaims = Depends(require_admin),
    audit: AuditLogWriter = Depends(get_audit_writer),
):
    """Emergency pager project: concentrator ch9 (FSK) settings.

    Still internal/experimental -- no real pager protocol/firmware exists
    yet, this only lets the RX side be tuned without editing local.yaml
    by hand. Always requires a restart: none of this is hot-reloadable,
    same as radio/advanced's spectral_scan_interval_seconds/sx1261_spi_path.
    """
    if _config is None:
        raise HTTPException(503, "Config not loaded")

    radio = _config.radio
    sync_word = req.pager_sync_word if req.pager_sync_word is not None else radio.pager_sync_word
    sync_word_size = (
        req.pager_sync_word_size if req.pager_sync_word_size is not None
        else radio.pager_sync_word_size
    )
    if sync_word >= (1 << (8 * sync_word_size)):
        raise HTTPException(
            400,
            f"pager_sync_word 0x{sync_word:X} doesn't fit in "
            f"pager_sync_word_size={sync_word_size} byte(s)",
        )

    if req.pager_frequency_mhz is not None:
        from src.hal.concentrator_config import ConcentratorChannelPlan

        try:
            plan = ConcentratorChannelPlan.from_radio_config(
                region=radio.region,
                frequency_mhz=radio.frequency_mhz,
                spreading_factor=radio.spreading_factor,
                bandwidth_khz=radio.bandwidth_khz,
            )
        except (ValueError, TypeError) as exc:
            raise HTTPException(
                400, f"Cannot validate against the current channel plan: {exc}"
            ) from exc
        anchor_hz = (
            plan.radio_1_freq_hz if radio.pager_rf_chain == 1 else plan.radio_0_freq_hz
        )
        offset_hz = round(req.pager_frequency_mhz * 1_000_000) - anchor_hz
        if abs(offset_hz) > _PAGER_MAX_IF_OFFSET_HZ:
            raise HTTPException(
                400,
                f"pager_frequency_mhz {req.pager_frequency_mhz} is "
                f"{offset_hz / 1e6:+.4f} MHz from RF{radio.pager_rf_chain}'s anchor "
                f"({anchor_hz / 1e6} MHz) for the currently configured region "
                f"({radio.region}) -- outside the hardware's tunable IF range on "
                "this chain.",
            )

    updates: dict = {}
    if req.pager_enabled is not None:
        radio.pager_enabled = req.pager_enabled
        updates["pager_enabled"] = req.pager_enabled
    if req.pager_frequency_mhz is not None:
        radio.pager_frequency_mhz = req.pager_frequency_mhz
        updates["pager_frequency_mhz"] = req.pager_frequency_mhz
    if req.pager_sync_word is not None:
        radio.pager_sync_word = req.pager_sync_word
        updates["pager_sync_word"] = req.pager_sync_word
    if req.pager_sync_word_size is not None:
        radio.pager_sync_word_size = req.pager_sync_word_size
        updates["pager_sync_word_size"] = req.pager_sync_word_size
    if req.pager_capcode is not None:
        radio.pager_capcode = req.pager_capcode
        updates["pager_capcode"] = req.pager_capcode

    if not updates:
        return {"saved": False, "restart_required": False}

    # pager_capcode alone never needs a restart (see its own field
    # comment above) -- only these four actually reconfigure the HAL.
    restart_required = any(
        key in updates
        for key in (
            "pager_enabled", "pager_frequency_mhz",
            "pager_sync_word", "pager_sync_word_size",
        )
    )

    with audit.timed_action(
        user=_claims.subject, action="config.radio_pager_update", params=updates
    ):
        try:
            save_section_to_yaml("radio", updates)
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc

    return {"saved": True, "restart_required": restart_required, "updates": updates}


@router.put("/radio/advanced")
async def update_radio_advanced(
    req: RadioAdvancedUpdate,
    _claims: SessionClaims = Depends(require_admin),
    audit: AuditLogWriter = Depends(get_audit_writer),
):
    if _config is None:
        raise HTTPException(503, "Config not loaded")

    updates: dict = {}
    radio = _config.radio
    restart_needed = False

    if req.spectral_scan_interval_seconds is not None:
        radio.spectral_scan_interval_seconds = req.spectral_scan_interval_seconds
        updates["spectral_scan_interval_seconds"] = req.spectral_scan_interval_seconds
        restart_needed = True
    if req.sx1261_spi_path is not None:
        path = req.sx1261_spi_path.strip()
        radio.sx1261_spi_path = path
        updates["sx1261_spi_path"] = path
        restart_needed = True

    if not updates:
        return {"saved": False, "restart_required": False}

    with audit.timed_action(
        user=_claims.subject, action="config.radio_advanced_update", params=updates
    ):
        try:
            save_section_to_yaml("radio", updates)
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc

    return {"saved": True, "restart_required": restart_needed, "updates": updates}


def _meshcore_usb_dict(mc_usb) -> dict:
    return {
        "serial_port": mc_usb.serial_port,
        "baud_rate": mc_usb.baud_rate,
        "auto_detect": mc_usb.auto_detect,
        "label": mc_usb.label,
        "companion_name": mc_usb.companion_name,
    }


def _serial_device_dict(dev) -> dict:
    return {
        "serial_port": dev.serial_port,
        "serial_baud": dev.serial_baud,
        "label": dev.label,
        "long_name": dev.long_name,
        "short_name": dev.short_name,
    }
