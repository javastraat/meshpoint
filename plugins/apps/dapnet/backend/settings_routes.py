"""DAPNET plugin settings: device list, capcode filters, live status.

Replaces three things that used to live in core: ``PUT /api/config/capture/
pocsag-serial-devices`` and ``PUT /api/config/dapnet`` (both in
``system_config_routes.py``), and the ``dapnet_status`` key ``GET
/api/config`` used to enrich (``config_routes.py``'s ``_dapnet_status_entry``)
-- all three now live on this plugin's own Settings tab and status card
instead of the core Configuration page / ``GET /api/config`` blob.

``blacklist_capcodes``/``ignore_capcodes`` take effect immediately (
``state.tier()`` is consulted fresh on every packet by
``src.api.protocol_registry``, no capture-source restart needed) -- a page
for a capcode newly added to either list, already sitting in the packets
table from before this save, would otherwise keep showing up in history
forever (Recent Pages reads straight from storage), so both lists are
purged here via ``PacketRepository.delete_dapnet_capcodes`` to make "never
stored" hold immediately, not just going forward. ``devices`` and
``status_poll_interval_s`` are different: a ``DapnetSerialSource`` reads
its serial port / poll interval once at construction, so changing either
only takes effect on the next service restart, same as any other plugin's
config change.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.api.audit import AuditLogWriter
from src.api.audit.dependencies import get_audit_writer
from src.api.auth.dependencies import require_admin
from src.api.auth.jwt_session import SessionClaims
from src.storage.packet_repository import PacketRepository

from . import state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dapnet", tags=["config", "dapnet"])

_dapnet_sources: list = []
_packet_repo: PacketRepository | None = None


def init_routes(dapnet_sources=None, packet_repo: PacketRepository | None = None) -> None:
    global _dapnet_sources, _packet_repo
    _dapnet_sources = list(dapnet_sources) if dapnet_sources else []
    _packet_repo = packet_repo


def _status_entry(src) -> dict:
    """Topbar/status-card readout for one DAPNET/POCSAG companion.

    Board/callsign/freq/hostname/wifi_ip/tx_count/last_tx_ok/uptime_ms
    all come from the source's cached reply to its {"cmd":"status"}
    query (see DapnetSerialSource.status) -- {} until the first reply
    arrives (or if the companion's firmware predates the "cmd" handler).
    tx_count/last_tx_ok/uptime_ms only stay current because this query
    repeats periodically (status_poll_interval_s) rather than firing
    once at connect -- board/callsign/freq/hostname/wifi_ip would
    already be safe as a one-shot value, these wouldn't.
    """
    status = getattr(src, "status", {}) or {}
    return {
        "name": src.name,
        "connected": bool(getattr(src, "connected", False)),
        "board": status.get("board"),
        "callsign": status.get("callsign"),
        "frequency_mhz": status.get("freq"),
        "hostname": status.get("hostname"),
        "wifi_ssid": status.get("wifi_ssid"),
        "wifi_ip": status.get("wifi_ip"),
        "tx_count": status.get("tx_count"),
        "last_tx_ok": status.get("last_tx_ok"),
        "uptime_ms": status.get("uptime_ms"),
    }


@router.get("/status")
async def dapnet_status() -> list[dict]:
    """Live per-device connection status -- polled by the plugin's own
    status card (dapnet_status_card.js) in place of the old topbar chip
    this plugin doesn't have (see plugins/apps/dapnet/README.md)."""
    return [_status_entry(src) for src in _dapnet_sources]


@router.get("/settings")
async def get_dapnet_settings() -> dict:
    """Current device list + capcode filters + poll interval, for the
    Settings tab to render."""
    return state.to_dict()


class DeviceEntry(BaseModel):
    serial_port: str | None = None
    serial_baud: int = 115200
    label: str = ""
    name: str = ""


class DapnetSettingsUpdate(BaseModel):
    devices: list[DeviceEntry] | None = None
    blacklist_capcodes: list[int] | None = None
    ignore_capcodes: list[int] | None = None
    status_poll_interval_s: int | None = None


@router.put("/settings")
async def update_dapnet_settings(
    req: DapnetSettingsUpdate,
    _claims: SessionClaims = Depends(require_admin),
    audit: AuditLogWriter = Depends(get_audit_writer),
) -> dict:
    if req.status_poll_interval_s is not None and not (10 <= req.status_poll_interval_s <= 3600):
        raise HTTPException(400, "status_poll_interval_s must be between 10 and 3600")

    restart_required = False
    updates: dict = {}

    with audit.timed_action(
        user=_claims.subject, action="dapnet.settings_update", params={},
    ):
        if req.devices is not None:
            state.set_devices([d.model_dump() for d in req.devices])
            updates["devices"] = state.devices()
            restart_required = True

        if req.status_poll_interval_s is not None:
            state.set_status_poll_interval_s(req.status_poll_interval_s)
            updates["status_poll_interval_s"] = req.status_poll_interval_s
            restart_required = True

        if req.blacklist_capcodes is not None or req.ignore_capcodes is not None:
            state.set_filters(
                blacklist_capcodes=req.blacklist_capcodes,
                ignore_capcodes=req.ignore_capcodes,
            )
            updates["blacklist_capcodes"] = state.blacklist_capcodes()
            updates["ignore_capcodes"] = state.ignore_capcodes()

    purged = 0
    to_purge = sorted(set(state.blacklist_capcodes()) | set(state.ignore_capcodes()))
    if _packet_repo is not None and to_purge and (
        req.blacklist_capcodes is not None or req.ignore_capcodes is not None
    ):
        purged = await _packet_repo.delete_dapnet_capcodes(to_purge)

    return {"saved": True, "restart_required": restart_required, "purged": purged, **updates}
