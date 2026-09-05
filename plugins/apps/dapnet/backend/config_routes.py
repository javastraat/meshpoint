"""Per-device commands for the DAPNET/POCSAG companion (pocsag_companion).

Mounted under ``/api/config/dapnet/*``. Distinct from ``settings_routes.py``'s
``GET``/``PUT /api/dapnet/settings`` (that one saves the blacklist/ignore
capcode lists + device list) -- this module is for commands sent to a
specific connected companion over its live serial connection, same split
as core's ``serial_config_routes.py``/``meshcore_config_routes.py`` owning
their protocols' per-device actions.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.api.auth.dependencies import require_admin
from src.api.auth.jwt_session import SessionClaims

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/config/dapnet", tags=["config", "dapnet"])

_dapnet_sources: list = []


def init_routes(dapnet_sources=None) -> None:
    global _dapnet_sources
    _dapnet_sources = list(dapnet_sources) if dapnet_sources else []


def _resolve_dapnet_source(label: str):
    """Find the configured POCSAG companion source matching this label.

    Mirrors core's ``serial_config_routes.py``'s ``_resolve_serial_source``
    -- same ``dapnet_<label>``/bare ``dapnet`` naming convention.
    """
    name = f"dapnet_{label}" if label else "dapnet"
    for src in _dapnet_sources:
        if src.name == name:
            return src
    return None


class DapnetCallsignUpdate(BaseModel):
    label: str = ""
    callsign: str


@router.put("/callsign")
async def update_dapnet_callsign(
    req: DapnetCallsignUpdate,
    _claims: SessionClaims = Depends(require_admin),
) -> dict:
    """Set one POCSAG companion's operator callsign over its live serial
    connection.

    Unlike Serial/MeshCore identity renames, there is nothing to
    persist on the Meshpoint side afterward -- the callsign lives
    entirely in the companion's own NVS (set via the same validation
    cascade its web dashboard's /api/callsign already uses), not in
    local.yaml. A successful reply updates the source's cached status
    immediately so the config page / topbar chip reflect it without
    waiting for another status query (which only happens once, at
    connect).
    """
    source = _resolve_dapnet_source(req.label)
    if source is None or not source.connected:
        raise HTTPException(503, "POCSAG companion not connected")

    result = await source.send_command(
        {"cmd": "set_callsign", "callsign": req.callsign},
        expect_type="set_callsign_result",
        timeout=5.0,
    )
    if result is None:
        raise HTTPException(503, "No reply from companion (timed out)")
    if not result.get("ok"):
        raise HTTPException(400, result.get("error") or "Rejected by companion")

    saved_callsign = result.get("callsign", "")
    source.note_new_callsign(saved_callsign)
    return {"saved": True, "callsign": saved_callsign}


class DapnetWebPasswordUpdate(BaseModel):
    label: str = ""
    password: str


@router.put("/web-password")
async def update_dapnet_web_password(
    req: DapnetWebPasswordUpdate,
    _claims: SessionClaims = Depends(require_admin),
) -> dict:
    """Set one POCSAG companion's web dashboard login password over its
    live serial connection.

    Deliberately different from update_dapnet_callsign in one respect:
    the password itself is never cached, logged, or echoed back on this
    side (nor does the companion's own reply include it -- see
    handleSetWebPasswordCommand in the .ino) -- Meshpoint is a pure
    relay here, not a place this value should ever be visible again
    after the request completes. Nothing persists in local.yaml either;
    it lives entirely in the companion's own NVS, same as the callsign.
    """
    source = _resolve_dapnet_source(req.label)
    if source is None or not source.connected:
        raise HTTPException(503, "POCSAG companion not connected")

    result = await source.send_command(
        {"cmd": "set_web_password", "password": req.password},
        expect_type="set_web_password_result",
        timeout=5.0,
    )
    if result is None:
        raise HTTPException(503, "No reply from companion (timed out)")
    if not result.get("ok"):
        raise HTTPException(400, result.get("error") or "Rejected by companion")

    return {"saved": True}


class DapnetResetCredentialsRequest(BaseModel):
    label: str = ""


@router.post("/reset-credentials")
async def reset_dapnet_credentials(
    req: DapnetResetCredentialsRequest,
    _claims: SessionClaims = Depends(require_admin),
) -> dict:
    """Reset one POCSAG companion's callsign and web dashboard password
    back to their defaults (empty, and the secrets.h WEB_PASSWORD),
    without touching screen-timeout or anything else -- a Meshpoint-
    triggerable equivalent to a slice of the companion's own "Clear
    Settings" button. POST, not PUT: this is an action to trigger, not
    a value to set (no request body field beyond which device).

    A successful reply clears the cached callsign immediately (same
    reasoning as update_dapnet_callsign) so the readout tile doesn't
    keep showing the old value until the next status poll.
    """
    source = _resolve_dapnet_source(req.label)
    if source is None or not source.connected:
        raise HTTPException(503, "POCSAG companion not connected")

    result = await source.send_command(
        {"cmd": "reset_credentials"},
        expect_type="reset_credentials_result",
        timeout=5.0,
    )
    if result is None:
        raise HTTPException(503, "No reply from companion (timed out)")
    if not result.get("ok"):
        raise HTTPException(400, result.get("error") or "Rejected by companion")

    source.note_new_callsign("")
    return {"saved": True}


class DapnetWifiUpdate(BaseModel):
    label: str = ""
    ssid: str
    password: str = ""  # empty is valid -- open networks have no password


@router.put("/wifi")
async def update_dapnet_wifi(
    req: DapnetWifiUpdate,
    _claims: SessionClaims = Depends(require_admin),
) -> dict:
    """Set one POCSAG companion's WiFi SSID/password over its live
    serial connection.

    Deliberately a SEPARATE action from callsign/web-password/reset:
    this one takes the companion off its current network until it
    reboots with the new credentials, unlike the others which never
    touch connectivity. Handled as a secret the same way the web
    password is -- never cached, persisted, or logged on the Meshpoint
    side, and the companion's own reply never echoes the password back
    (only the SSID, which isn't sensitive).

    Saving alone does NOT reconnect -- setupWifiNtpOta() only runs once
    at boot. Call POST .../reboot afterward (or the companion's own web
    Reboot button, if still reachable) to actually apply it.
    """
    source = _resolve_dapnet_source(req.label)
    if source is None or not source.connected:
        raise HTTPException(503, "POCSAG companion not connected")

    result = await source.send_command(
        {"cmd": "set_wifi", "ssid": req.ssid, "password": req.password},
        expect_type="set_wifi_result",
        timeout=5.0,
    )
    if result is None:
        raise HTTPException(503, "No reply from companion (timed out)")
    if not result.get("ok"):
        raise HTTPException(400, result.get("error") or "Rejected by companion")

    return {"saved": True, "ssid": result.get("ssid", "")}


class DapnetRebootRequest(BaseModel):
    label: str = ""


@router.post("/reboot")
async def reboot_dapnet_companion(
    req: DapnetRebootRequest,
    _claims: SessionClaims = Depends(require_admin),
) -> dict:
    """Reboot one POCSAG companion over its live serial connection --
    e.g. right after saving new WiFi credentials, without needing the
    companion's own web dashboard (which the whole WiFi-set flow exists
    to route around in the first place, since bad credentials could
    make that dashboard unreachable too).

    NOTE: whether Meshpoint's own connection to this companion survives
    the reboot depends on the board's USB hardware -- a separate USB-
    UART bridge chip (common on these boards) keeps the OS-level serial
    device enumerated through an ESP32 reset; a board using the chip's
    own native USB instead would re-enumerate and could require a
    Meshpoint service restart to reconnect (DapnetSerialSource has no
    reconnect loop, matching SerialCaptureSource's own documented
    limitation). Not yet confirmed either way on real hardware.
    """
    source = _resolve_dapnet_source(req.label)
    if source is None or not source.connected:
        raise HTTPException(503, "POCSAG companion not connected")

    result = await source.send_command(
        {"cmd": "reboot"}, expect_type="reboot_result", timeout=5.0,
    )
    if result is None:
        raise HTTPException(503, "No reply from companion (timed out)")
    if not result.get("ok"):
        raise HTTPException(400, result.get("error") or "Rejected by companion")

    return {"saved": True}


class DapnetSendRequest(BaseModel):
    label: str = ""
    capcode: int | None = None
    text: str


@router.post("/send")
async def send_dapnet_page(
    req: DapnetSendRequest,
    _claims: SessionClaims = Depends(require_admin),
) -> dict:
    """Send a POCSAG alpha page through one connected companion's live
    serial connection.

    ``capcode`` omitted (or null) lets the companion use its own
    configured default (``SERIAL_DEFAULT_CAPCODE`` in the .ino) rather
    than Meshpoint guessing one. The companion prefixes every sent
    message with its operator callsign before transmitting (required by
    the licensing terms in the .ino's header) and echoes a successful
    send into the normal packet feed exactly like a received page (same
    reasoning as receiving your own transmission over the air), so it
    shows up in Recent Pages/Capcodes for free -- this route's own
    ``{"type":"send_result",...}`` reply (added specifically for this
    feature, distinct from that echo) is only for reporting success/
    failure back to the caller, not for storing anything itself.

    A longer timeout than the other commands here (10s, not 5s) --
    unlike a settings write, this one waits for an actual over-the-air
    POCSAG transmission (half-duplex RX/TX switch + real TX time) to
    complete before the companion replies.
    """
    text = req.text.strip()
    if not text:
        raise HTTPException(400, "Message text required")

    source = _resolve_dapnet_source(req.label)
    if source is None or not source.connected:
        raise HTTPException(503, "POCSAG companion not connected")

    command: dict = {"text": text}
    if req.capcode is not None:
        command["capcode"] = req.capcode

    result = await source.send_command(
        command, expect_type="send_result", timeout=10.0,
    )
    if result is None:
        raise HTTPException(503, "No reply from companion (timed out)")
    if not result.get("ok"):
        reason = result.get("reason", "failed")
        if reason == "blocked":
            raise HTTPException(
                400, "No callsign configured on the companion -- set one first",
            )
        raise HTTPException(502, "Companion failed to transmit the page")

    return {"sent": True}
