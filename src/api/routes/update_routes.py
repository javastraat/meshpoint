"""HTTP surface for the dashboard update + watchdog flow.

Three endpoints, all admin-only, all audited:

* ``GET  /api/update/channels`` -- enumerate available release tracks
  for the picker.
* ``POST /api/update/apply``    -- run the apply chain on the
  selected channel; returns the structured ``ApplyResult``.
* ``POST /api/update/rollback`` -- restore a prior SHA + restart
  service.

The route layer never spawns subprocesses directly: it asks the
injected :class:`UpdateApplier` to do the work. Tests provide a fake
applier so the suite never shells out.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.api.audit import AuditLogWriter
from src.api.audit.dependencies import get_audit_writer
from src.api.auth.dependencies import require_admin
from src.api.auth.jwt_session import SessionClaims
from src.api.update.apply import ApplyResult, UpdateApplier
from src.api.update.channels import ReleaseChannelRegistry
from src.api.update.streaming import stream_update
from src.api.update.install_status import build_install_status_payload
from src.api.update.rollback_state import clear_rollback_state, write_rollback_state
from src.api.update.release_notes import (
    ChangelogParser,
    format_section_for_preview,
    format_section_full,
    select_preview_section,
)
from src.config import AppConfig, save_section_to_yaml
from src.version import __version__ as INSTALLED_VERSION

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/update", tags=["update"])

_applier: UpdateApplier | None = None
_registry: ReleaseChannelRegistry | None = None
_changelog_path: Path | None = None
_rollback_state_path: Path = Path("/opt/meshpoint/data/update_rollback.json")
_config: AppConfig | None = None
_last_periodic_check: dict | None = None

# Each check is a real `git fetch`, not a cheap request -- floor the
# interval so a bad config value (or a hand-edited yaml) can't turn
# this into a tight loop hammering GitHub.
MIN_CHECK_INTERVAL_MINUTES = 5


def init_routes(
    applier: UpdateApplier,
    registry: ReleaseChannelRegistry,
    changelog_path: Path | None = None,
    rollback_state_path: Path | None = None,
    config: AppConfig | None = None,
) -> None:
    global _applier, _registry, _changelog_path, _rollback_state_path, _config
    _applier = applier
    _registry = registry
    _changelog_path = changelog_path
    if rollback_state_path is not None:
        _rollback_state_path = rollback_state_path
    _config = config


def reset_routes() -> None:
    global _applier, _registry, _changelog_path, _rollback_state_path, _config, _last_periodic_check
    _applier = None
    _registry = None
    _changelog_path = None
    _rollback_state_path = Path("/opt/meshpoint/data/update_rollback.json")
    _config = None
    _last_periodic_check = None


async def periodic_update_check_loop(interval_minutes: float) -> None:
    """Background task: re-run the same check the "Check for updates"
    button does, on a timer, caching the result for the sidebar badge.

    Runs an initial check immediately (so the badge isn't blank for a
    full interval after boot), then repeats every ``interval_minutes``.
    Same lifecycle pattern as the fan/LED/button controllers -- started
    via create_task in server.py's lifespan, cancelled on shutdown.
    """
    global _last_periodic_check
    interval_s = max(MIN_CHECK_INTERVAL_MINUTES, interval_minutes) * 60
    loop = asyncio.get_running_loop()
    try:
        while True:
            if _registry is not None:
                try:
                    _last_periodic_check = await loop.run_in_executor(
                        None,
                        lambda: build_install_status_payload(
                            registry=_registry,
                            sync_remote=True,
                            rollback_state_path=_rollback_state_path,
                        ),
                    )
                    logger.info(
                        "Periodic update check: commits_behind=%s",
                        _last_periodic_check.get("commits_behind"),
                    )
                except Exception:
                    logger.exception("Periodic update check failed")
            await asyncio.sleep(interval_s)
    except asyncio.CancelledError:
        pass


class UpdateCheckSettingsUpdate(BaseModel):
    enabled: bool = True
    interval_minutes: int = Field(60, ge=MIN_CHECK_INTERVAL_MINUTES)


@router.get("/badge")
async def update_badge(
    _claims: SessionClaims = Depends(require_admin),
) -> dict:
    """Cached result of the periodic check, for the sidebar badge.

    Never triggers a git fetch itself -- just reads whatever the
    background loop last found, so polling this is cheap.
    """
    if _last_periodic_check is None:
        return {"update_available": False, "commits_behind": None, "checked_at": None}
    return {
        "update_available": bool(_last_periodic_check.get("commits_behind")),
        "commits_behind": _last_periodic_check.get("commits_behind"),
        "checked_at": _last_periodic_check.get("checked_at"),
    }


@router.put("/check-settings")
async def update_check_settings(
    req: UpdateCheckSettingsUpdate,
    _claims: SessionClaims = Depends(require_admin),
    audit: AuditLogWriter = Depends(get_audit_writer),
):
    if _config is None:
        raise HTTPException(503, "Config not loaded")

    updates = req.model_dump()
    with audit.timed_action(
        user=_claims.subject, action="config.update_check_settings", params=updates
    ):
        _config.update_check.enabled = req.enabled
        _config.update_check.interval_minutes = req.interval_minutes
        try:
            save_section_to_yaml("update_check", updates)
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc

    logger.info(
        "Update-check settings changed: enabled=%s interval_minutes=%s",
        req.enabled, req.interval_minutes,
    )
    return {"saved": True, "restart_required": True, "updates": updates}


def _require_initialized() -> tuple[UpdateApplier, ReleaseChannelRegistry]:
    if _applier is None or _registry is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="update subsystem not initialized",
        )
    return _applier, _registry


class ApplyRequest(BaseModel):
    channel_id: str = Field(..., min_length=1, max_length=64)
    custom_branch: str | None = Field(default=None, max_length=200)


class RollbackRequest(BaseModel):
    sha: str = Field(..., min_length=4, max_length=80)


class CheckUpdatesRequest(BaseModel):
    """Optional channel picker values; defaults to the live install branch."""

    channel_id: str | None = Field(default=None, max_length=64)
    custom_branch: str | None = Field(default=None, max_length=200)


@router.get("/channels")
async def list_channels(
    _claims: SessionClaims = Depends(require_admin),
) -> dict:
    _applier_instance, registry = _require_initialized()
    return {"channels": registry.to_payload()}


@router.get("/install_status")
async def install_status(
    _claims: SessionClaims = Depends(require_admin),
) -> dict:
    """Live install branch, matched channel, and upstream version on that branch."""
    _applier_instance, registry = _require_initialized()
    return build_install_status_payload(
        registry=registry,
        rollback_state_path=_rollback_state_path,
    )


@router.post("/check")
async def check_for_updates(
    req: CheckUpdatesRequest,
    _claims: SessionClaims = Depends(require_admin),
) -> dict:
    """Fetch origin and report how many commits HEAD is behind the target branch."""
    global _last_periodic_check
    _applier_instance, registry = _require_initialized()
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        lambda: build_install_status_payload(
            registry=registry,
            sync_remote=True,
            channel_id=req.channel_id,
            custom_branch=req.custom_branch,
            rollback_state_path=_rollback_state_path,
        ),
    )
    # Only refresh the sidebar badge's cache when this checked the same
    # thing the periodic background loop would (the current install's
    # own tracked channel) -- a manual check against a genuinely
    # different picker channel/custom branch shouldn't make the badge
    # reflect THAT branch's status instead of the actually-installed
    # one. NOTE: the dashboard's Check button always sends a concrete
    # channel_id (never null -- it's whatever's selected in the
    # picker), so comparing against None here would never match in
    # practice; compare against the channel actually resolved for this
    # install instead (channel_info is derived from the real installed
    # branch regardless of what channel_id was requested).
    is_own_channel = req.channel_id is None or req.channel_id == result.get("active_channel_id")
    if is_own_channel and req.custom_branch is None:
        _last_periodic_check = result
    return result


@router.get("/release_notes")
async def release_notes(
    channel_id: str = Query(..., min_length=1, max_length=64),
    _claims: SessionClaims = Depends(require_admin),
) -> dict:
    _applier_instance, registry = _require_initialized()
    channel = registry.find(channel_id)
    if channel is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid_channel",
        )
    sections = _load_changelog_sections()
    preview = select_preview_section(
        sections,
        tier=channel.tier,
        channel_id=channel.id,
        installed_version=INSTALLED_VERSION,
    )
    return {
        "channel_id": channel.id,
        "channel_label": channel.label,
        "channel_tier": channel.tier,
        "current_installed_version": INSTALLED_VERSION,
        "preview_section": (
            format_section_for_preview(preview) if preview is not None else None
        ),
        "full_section": (
            format_section_full(preview) if preview is not None else None
        ),
    }


def _load_changelog_sections() -> list:
    if _changelog_path is None or not _changelog_path.exists():
        return []
    try:
        return ChangelogParser.parse_file(_changelog_path)
    except OSError as exc:
        logger.warning("release_notes: could not read changelog: %s", exc)
        return []


def _audit_apply_result(ctx, result: ApplyResult) -> None:
    ctx.params["success"] = result.success
    ctx.params["target_branch"] = result.target_branch
    if result.pre_update_sha:
        ctx.params["pre_update_sha"] = result.pre_update_sha
    if not result.success:
        ctx.params["failed_step"] = result.failed_step
        ctx.set_result("error")


def _persist_rollback_after_apply(result: ApplyResult) -> None:
    """Keep rollback SHA across dashboard reload after service restart."""
    if (
        result.success
        and result.pre_update_sha
        and result.target_branch != "rollback"
    ):
        write_rollback_state(
            result.pre_update_sha,
            target_branch=result.target_branch,
            path=_rollback_state_path,
        )


def _clear_rollback_after_success(result: ApplyResult) -> None:
    if result.success:
        clear_rollback_state(path=_rollback_state_path)


@router.post("/apply")
async def apply_update(
    payload: ApplyRequest,
    claims: SessionClaims = Depends(require_admin),
    audit: AuditLogWriter = Depends(get_audit_writer),
) -> dict:
    applier, registry = _require_initialized()
    branch = registry.resolve_branch(
        payload.channel_id, custom_branch=payload.custom_branch,
    )
    if not branch:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid_channel_or_branch",
        )
    with audit.timed_action(
        user=claims.subject,
        action="update.apply",
        params={"channel_id": payload.channel_id, "branch": branch},
    ) as ctx:
        result = applier.apply(branch=branch)
        _audit_apply_result(ctx, result)
        _persist_rollback_after_apply(result)
    return asdict(result)


@router.post("/apply/stream")
async def apply_update_stream(
    payload: ApplyRequest,
    claims: SessionClaims = Depends(require_admin),
    audit: AuditLogWriter = Depends(get_audit_writer),
) -> StreamingResponse:
    """Run apply and stream per-step progress as NDJSON (one object per line)."""
    applier, registry = _require_initialized()
    branch = registry.resolve_branch(
        payload.channel_id, custom_branch=payload.custom_branch,
    )
    if not branch:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid_channel_or_branch",
        )

    async def body() -> AsyncIterator[bytes]:
        result: ApplyResult | None = None
        with audit.timed_action(
            user=claims.subject,
            action="update.apply.stream",
            params={"channel_id": payload.channel_id, "branch": branch},
        ) as ctx:
            async for chunk in stream_update(
                applier, mode="apply", branch=branch,
            ):
                yield chunk
                line = chunk.decode("utf-8").strip()
                if not line:
                    continue
                event = json.loads(line)
                if event.get("type") == "result":
                    result_dict = event.get("result")
                    if result_dict:
                        result = ApplyResult(**result_dict)
                        _audit_apply_result(ctx, result)
                        _persist_rollback_after_apply(result)
            if result is None:
                ctx.set_result("error")

    return StreamingResponse(
        body(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.post("/rollback")
async def rollback_update(
    payload: RollbackRequest,
    claims: SessionClaims = Depends(require_admin),
    audit: AuditLogWriter = Depends(get_audit_writer),
) -> dict:
    applier, _registry_instance = _require_initialized()
    with audit.timed_action(
        user=claims.subject,
        action="update.rollback",
        params={"sha": payload.sha},
    ) as ctx:
        result = applier.rollback(sha=payload.sha)
        ctx.params["success"] = result.success
        if not result.success:
            ctx.params["failed_step"] = result.failed_step
            ctx.set_result("error")
        _clear_rollback_after_success(result)
    return asdict(result)


@router.post("/rollback/stream")
async def rollback_update_stream(
    payload: RollbackRequest,
    claims: SessionClaims = Depends(require_admin),
    audit: AuditLogWriter = Depends(get_audit_writer),
) -> StreamingResponse:
    """Roll back and stream per-step progress as NDJSON."""
    applier, _registry_instance = _require_initialized()

    async def body() -> AsyncIterator[bytes]:
        result: ApplyResult | None = None
        with audit.timed_action(
            user=claims.subject,
            action="update.rollback.stream",
            params={"sha": payload.sha},
        ) as ctx:
            async for chunk in stream_update(
                applier, mode="rollback", sha=payload.sha,
            ):
                yield chunk
                line = chunk.decode("utf-8").strip()
                if not line:
                    continue
                event = json.loads(line)
                if event.get("type") == "result":
                    result_dict = event.get("result")
                    if result_dict:
                        result = ApplyResult(**result_dict)
                        ctx.params["success"] = result.success
                        if not result.success:
                            ctx.params["failed_step"] = result.failed_step
                            ctx.set_result("error")
                        _clear_rollback_after_success(result)
            if result is None:
                ctx.set_result("error")

    return StreamingResponse(
        body(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )
