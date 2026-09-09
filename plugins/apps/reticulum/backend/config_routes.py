"""Reticulum RNode/backbone settings -- the plugin's own Settings tab.

Moved from ``src/api/routes/reticulum_config_routes.py``. Two shape changes
for the plugin:

* Reads/writes ``plugins.reticulum.*`` (via ``backend/state.py``) instead
  of the core ``AppConfig.reticulum`` dataclass + ``save_section_to_yaml``.
* No ``enabled`` field -- Settings -> Plugins' own toggle is the sole
  on/off switch now, same as every other shipped plugin.

Unchanged: a save here only updates ``local.yaml`` -- the RNode/backbone
fields are only ever read by ``scripts/write_rnsd_config.py``, which runs
as ``rnsd``'s own ``ExecStartPre``, so applying those needs an rnsd
restart too. ``restart_rnsd()`` gives the Settings tab a direct way to
trigger that, reusing the narrowly-scoped ``sudo systemctl ... rnsd``
helper (now ``src.api.systemctl``).

NOTE (until the reticulum-to-plugin cutover): ``scripts/write_rnsd_config.py``
still reads the core ``reticulum:`` section, not ``plugins.reticulum``, so
edits made here don't reach rnsd yet. Repointed in the Phase 5 cutover.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator

from src.api.audit import AuditLogWriter
from src.api.audit.dependencies import get_audit_writer
from src.api.auth.dependencies import require_admin
from src.api.auth.jwt_session import SessionClaims
from src.api.systemctl import run_systemctl

from . import state

router = APIRouter(prefix="/api/config", tags=["config", "reticulum"])

# SX127x/SX126x (every RNode board) only accept these LoRa bandwidths --
# anything else silently fails to key up, so reject early rather than let a
# typo reach rnsd only to be discovered on the next restart.
_VALID_BANDWIDTHS_HZ = frozenset(
    {7800, 10400, 15600, 20800, 31250, 41700, 62500, 125000, 250000, 500000}
)


class ReticulumUpdate(BaseModel):
    display_name: str = "Meshpoint"
    nomad_timeout_s: int = Field(20, ge=5, le=120)
    node_enabled: bool = False
    node_name: str = ""
    node_pages_dir: str = "data/reticulum/pages"
    node_announce_interval_s: int = Field(21600, ge=600, le=604800)
    node_spaceapi_url: str = ""
    node_events_ical_url: str = ""
    talkback_enabled: bool = False
    notify_url: str = ""
    propagation_enabled: bool = False
    propagation_storage_limit_mb: int = Field(250, ge=0, le=100_000)
    propagation_outbound_node: str = ""
    propagation_auto_sync_interval_s: int = Field(0, ge=0, le=86_400)
    telemetry_enabled: bool = False
    telemetry_collector: str = ""
    telemetry_interval_s: int = Field(900, ge=300, le=86_400)
    rnode_enabled: bool = True
    rnode_serial_port: str = ""
    rnode_frequency_hz: int = Field(..., ge=100_000_000, le=1_000_000_000)
    rnode_bandwidth_hz: int = 125_000
    rnode_tx_power: int = Field(20, ge=0, le=22)
    rnode_spreading_factor: int = Field(8, ge=5, le=12)
    rnode_coding_rate: int = Field(5, ge=5, le=8)
    backbone_enabled: bool = True
    backbone_host: str = "node.reticulumnet.nl"
    backbone_port: int = Field(4242, ge=1, le=65535)

    @field_validator("rnode_bandwidth_hz")
    @classmethod
    def _check_bandwidth(cls, value: int) -> int:
        if value not in _VALID_BANDWIDTHS_HZ:
            allowed = ", ".join(str(v) for v in sorted(_VALID_BANDWIDTHS_HZ))
            raise ValueError(f"rnode_bandwidth_hz must be one of: {allowed}")
        return value

    @field_validator("display_name", "backbone_host")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be empty")
        return stripped

    @field_validator("node_spaceapi_url", "node_events_ical_url", "notify_url")
    @classmethod
    def _feed_url_ok(cls, value: str) -> str:
        stripped = value.strip()
        if stripped and not stripped.startswith(("http://", "https://")):
            raise ValueError("must be an http(s) URL or blank")
        return stripped

    @field_validator("propagation_outbound_node", "telemetry_collector")
    @classmethod
    def _dest_hash_ok(cls, value: str) -> str:
        # Tolerate the shapes users actually paste: a bare hex hash from a
        # peer's Destination column, or RNS's own ``<hex>`` / ``aa:bb:..``
        # display forms (the startup banner + "You:" line use ``<hex>``).
        stripped = value.strip().lower().replace(":", "").strip("<>")
        if not stripped:
            return ""
        if (
            len(stripped) < 8 or len(stripped) > 64 or len(stripped) % 2
            or any(c not in "0123456789abcdef" for c in stripped)
        ):
            raise ValueError(
                "must be a Reticulum destination hash (hex, e.g. the 32-char "
                "hash from a peer's Destination column) or blank"
            )
        return stripped

    @model_validator(mode="after")
    def _at_least_one_interface(self) -> "ReticulumUpdate":
        if not self.rnode_enabled and not self.backbone_enabled:
            raise ValueError(
                "At least one of RNode radio or TCP backbone must stay enabled "
                "-- disable the whole plugin from Settings -> Plugins instead"
            )
        return self

    @model_validator(mode="after")
    def _auto_sync_needs_a_node(self) -> "ReticulumUpdate":
        if self.propagation_auto_sync_interval_s and not self.propagation_outbound_node:
            raise ValueError(
                "Auto-sync needs an outbound propagation node -- set one, or "
                "leave the interval at 0 for manual sync only"
            )
        if 0 < self.propagation_auto_sync_interval_s < 300:
            raise ValueError("propagation_auto_sync_interval_s must be 0 or at least 300")
        return self

    @model_validator(mode="after")
    def _telemetry_needs_a_collector(self) -> "ReticulumUpdate":
        if self.telemetry_enabled and not self.telemetry_collector:
            raise ValueError(
                "Telemetry publishing needs a collector address -- set one, or "
                "turn telemetry off"
            )
        return self

    @model_validator(mode="after")
    def _talkback_needs_node(self) -> "ReticulumUpdate":
        if self.talkback_enabled and not self.node_enabled:
            raise ValueError(
                "The talk-back bot answers from data the hosted NomadNet "
                "node caches -- enable \"Host a NomadNet node\" first"
            )
        return self


@router.get("/reticulum")
async def get_reticulum(_claims: SessionClaims = Depends(require_admin)):
    """Current ``plugins.reticulum.*`` values for the Settings tab to load.
    ``enabled`` is deliberately not here -- Settings -> Plugins owns it."""
    return state.to_dict()


@router.put("/reticulum")
async def update_reticulum(
    req: ReticulumUpdate,
    claims: SessionClaims = Depends(require_admin),
    audit: AuditLogWriter = Depends(get_audit_writer),
):
    updates = {
        "display_name": req.display_name,
        "nomad_timeout_s": req.nomad_timeout_s,
        "node_enabled": req.node_enabled,
        "node_name": req.node_name.strip(),
        "node_pages_dir": req.node_pages_dir.strip() or "data/reticulum/pages",
        "node_announce_interval_s": req.node_announce_interval_s,
        "node_spaceapi_url": req.node_spaceapi_url.strip(),
        "node_events_ical_url": req.node_events_ical_url.strip(),
        "talkback_enabled": req.talkback_enabled,
        "notify_url": req.notify_url.strip(),
        "propagation_enabled": req.propagation_enabled,
        "propagation_storage_limit_mb": req.propagation_storage_limit_mb,
        "propagation_outbound_node": req.propagation_outbound_node,
        "propagation_auto_sync_interval_s": req.propagation_auto_sync_interval_s,
        "telemetry_enabled": req.telemetry_enabled,
        "telemetry_collector": req.telemetry_collector,
        "telemetry_interval_s": req.telemetry_interval_s,
        "rnode_enabled": req.rnode_enabled,
        "rnode_serial_port": req.rnode_serial_port.strip(),
        "rnode_frequency_hz": req.rnode_frequency_hz,
        "rnode_bandwidth_hz": req.rnode_bandwidth_hz,
        "rnode_tx_power": req.rnode_tx_power,
        "rnode_spreading_factor": req.rnode_spreading_factor,
        "rnode_coding_rate": req.rnode_coding_rate,
        "backbone_enabled": req.backbone_enabled,
        "backbone_host": req.backbone_host,
        "backbone_port": req.backbone_port,
    }
    with audit.timed_action(
        user=claims.subject,
        action="config.reticulum_update",
        params={k: v for k, v in updates.items() if k != "rnode_serial_port"},
    ):
        try:
            state.set_config(updates)
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc

    # nomad_timeout_s takes effect immediately -- the rest need a restart.
    from . import nomad
    nomad.set_timeouts(req.nomad_timeout_s)
    return {"saved": True, "restart_required": True}


@router.post("/reticulum/restart-rnsd")
async def restart_rnsd(_claims: SessionClaims = Depends(require_admin)):
    """Restart the opt-in ``rnsd`` systemd unit so it re-runs
    ``write_rnsd_config.py`` and reconnects with the saved RNode/backbone
    settings. Errors clearly if rnsd isn't installed as a service."""
    rc, out = await run_systemctl("restart", "rnsd")
    if rc != 0:
        raise HTTPException(
            502,
            f"systemctl restart rnsd failed (exit {rc}): {out or 'no output'}",
        )
    return {"success": True, "output": out}
