"""REST endpoints for MeshCore companion configuration.

Mounted under ``/api/config/meshcore/*``. Today this module owns the
companion-name save path (renames the USB companion via
``MeshCoreTxClient.set_companion_name``); future MeshCore-only config
surfaces (``set_coords``, ``set_tx_power``) will land here too rather
than bloating ``config_routes.py`` further.

Split out of ``config_routes.py`` because that file is already at the
500-line cap, and because companion-only operations don't share state
with the Meshtastic-side radio / channel / identity routes.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import urllib.request
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from src.api.auth.dependencies import require_admin
from src.api.auth.jwt_session import SessionClaims
from src.config import AppConfig, save_section_to_yaml

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/config/meshcore", tags=["config", "meshcore"])

_config: AppConfig | None = None
_tx_service = None
_meshcore_sources: list = []

# Manual/on-demand only -- no periodic background polling. Companion firmware
# only changes when the device is physically reflashed, so there's no live
# state worth watching automatically; this keeps GitHub API usage to exactly
# what a user actually asks for (same reasoning as update_check.py's own
# GitHub call for Meshpoint's own software, just not on an automatic timer).
_FIRMWARE_RELEASES_URL = (
    "https://api.github.com/repos/meshcore-dev/MeshCore/releases/latest"
)
_SEMVER_RE = re.compile(r"v?(\d+)\.(\d+)\.(\d+)")
# Confirmed against a real release: the git build hash only appears in asset
# filenames (e.g. 'Heltec_v3_room_server-v1.16.0-07a3ca9.bin'), never in the
# release tag/name itself -- matches the same '-<hash>' suffix the companion
# itself reports (e.g. 'v1.16.0-07a3ca9' from get_device_info()).
_ASSET_HASH_RE = re.compile(r"-([a-f0-9]{7})(?:-merged)?\.bin$")
_FIRMWARE_CHECK_CACHE_TTL_SECONDS = 300
# Caches only the shared GitHub fetch (latest_version/release_url), not a
# full comparison result -- up to 4 companions can each be on different
# firmware (mirrors serial_config_routes.py's identical reasoning), so the
# per-companion update_available comparison is always computed fresh
# against whichever current_version the caller passes.
_release_cache: dict[str, object] = {
    "latest_version": None, "release_url": None, "error": None, "expires": 0,
}


def _semver_and_hash(version_str: str) -> tuple[Optional[tuple[int, int, int]], Optional[str]]:
    semver_match = _SEMVER_RE.search(version_str or "")
    semver = tuple(int(g) for g in semver_match.groups()) if semver_match else None
    hash_match = re.search(r"-([a-f0-9]{7})\b", version_str or "")
    build_hash = hash_match.group(1) if hash_match else None
    return semver, build_hash


def _fetch_latest_firmware_release_sync() -> Optional[dict]:
    try:
        req = urllib.request.Request(
            _FIRMWARE_RELEASES_URL,
            headers={"Accept": "application/vnd.github+json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        logger.debug(
            "Failed to fetch latest MeshCore firmware release", exc_info=True,
        )
        return None


def _latest_release_version_string(release: dict) -> Optional[str]:
    """Build a 'vX.Y.Z-hash' string matching the companion's own version format.

    All assets in one release share the same build hash, so the first
    asset filename that matches is sufficient -- no need to find a
    device-specific one.
    """
    tag = release.get("tag_name") or release.get("name") or ""
    semver_match = _SEMVER_RE.search(tag)
    if not semver_match:
        return None
    semver = ".".join(semver_match.groups())

    for asset in release.get("assets") or []:
        hash_match = _ASSET_HASH_RE.search(asset.get("name", ""))
        if hash_match:
            return f"v{semver}-{hash_match.group(1)}"
    return f"v{semver}"


async def _get_latest_release_cached() -> dict:
    now = time.time()
    if _release_cache["expires"] > now and (
        _release_cache["latest_version"] or _release_cache["error"]
    ):
        return _release_cache

    loop = asyncio.get_running_loop()
    release = await loop.run_in_executor(None, _fetch_latest_firmware_release_sync)
    if release is None:
        _release_cache.update({
            "latest_version": None, "release_url": None,
            "error": "Could not reach GitHub", "expires": now + _FIRMWARE_CHECK_CACHE_TTL_SECONDS,
        })
    else:
        _release_cache.update({
            "latest_version": _latest_release_version_string(release),
            "release_url": release.get("html_url"),
            "error": None,
            "expires": now + _FIRMWARE_CHECK_CACHE_TTL_SECONDS,
        })
    return _release_cache


async def _check_firmware_update(current_version: str) -> dict:
    cache = await _get_latest_release_cached()
    if cache.get("error"):
        return {
            "checked": True,
            "update_available": False,
            "current_version": current_version,
            "latest_version": None,
            "release_url": None,
            "error": cache["error"],
        }

    latest_version = cache.get("latest_version")
    current_semver, current_hash = _semver_and_hash(current_version)
    latest_semver, latest_hash = _semver_and_hash(latest_version or "")

    update_available = False
    if latest_semver is not None and current_semver is not None:
        if latest_semver > current_semver:
            update_available = True
        elif (
            latest_semver == current_semver
            and current_hash and latest_hash
            and current_hash != latest_hash
        ):
            update_available = True

    return {
        "checked": True,
        "update_available": update_available,
        "current_version": current_version,
        "latest_version": latest_version,
        "release_url": cache.get("release_url"),
    }


def init_routes(config: AppConfig, tx_service=None, meshcore_sources=None) -> None:
    """Wire module-level state at app startup.

    ``tx_service`` is kept for back-compat with any future TX-wide
    (not per-companion) MeshCore config surface this module grows.
    ``meshcore_sources`` is every configured companion's own capture
    source (mirrors config_routes.py's identical list) -- rename and
    advert both target a specific companion's own connection now,
    rather than only the one "primary" companion the TX client is
    bound to.
    """
    global _config, _tx_service, _meshcore_sources
    _config = config
    _tx_service = tx_service
    _meshcore_sources = meshcore_sources or []


def _resolve_companion_source(label: str):
    """Find the configured companion source matching this label.

    Mirrors ``meshcore_card.js``'s own name reconstruction
    (``meshcore_usb_<label>``, bare ``meshcore_usb`` when unlabeled).
    """
    name = f"meshcore_usb_{label}" if label else "meshcore_usb"
    for src in _meshcore_sources:
        if src.name == name:
            return src
    return None


def _persist_companion_name(label: str, name: str) -> None:
    """Save one companion's renamed identity to its own config entry.

    Persists the FULL ``capture.meshcore_usb`` list (not just this
    entry) since ``save_section_to_yaml`` replaces the whole section
    value -- matching ``system_config_routes.py``'s identical
    "persist the full list so other companions aren't lost" pattern.
    Failure here is a soft error: the rename already stuck on the
    companion's flash for the current session; only the on-reconnect
    re-apply path is degraded until the user retries the save.
    """
    matched = False
    for entry in _config.capture.meshcore_usb:
        if (entry.label or "") == (label or ""):
            entry.companion_name = name
            matched = True
            break
    if not matched:
        logger.warning(
            "No meshcore_usb config entry matched label %r; "
            "rename won't survive a reconnect until saved",
            label,
        )
        return
    try:
        save_section_to_yaml("capture", {
            "meshcore_usb": [
                {
                    "serial_port": e.serial_port,
                    "baud_rate": e.baud_rate,
                    "auto_detect": e.auto_detect,
                    "label": e.label,
                    "companion_name": e.companion_name,
                }
                for e in _config.capture.meshcore_usb
            ],
        })
    except PermissionError as exc:
        logger.warning(
            "Renamed companion (label=%r) to %r but failed to persist to "
            "local.yaml: %s. Reconnects will revert until saved.",
            label, name, exc,
        )
    except Exception:
        logger.exception(
            "Renamed companion (label=%r) to %r but yaml persistence "
            "failed; reconnects will revert until saved.",
            label, name,
        )


class CompanionNameUpdate(BaseModel):
    name: str
    label: str = ""


@router.put("/companion-name")
async def update_companion_name(
    req: CompanionNameUpdate,
    _claims: SessionClaims = Depends(require_admin),
) -> dict:
    """Rename one USB companion (CMD_SET_ADVERT_NAME).

    Takes ``label`` to target a specific companion (empty string for
    the bare/unlabeled one) -- up to 4 companions can be configured,
    each with its own independent identity, mirroring the firmware-check
    endpoint's identical "target a specific device by its own known
    state" shape. Validation lives in the shared
    ``send_set_companion_name()`` helper. Errors map to HTTP status
    codes as follows:

    - 503 if that companion is not connected (so the dashboard can show
      a "plug in your companion" hint instead of a generic 400).
    - 400 for everything else: empty / whitespace name, oversize name,
      companion ERROR payload, set_name timeout, library missing.

    The companion's flash holds the rename across reboots; the
    Meshpoint's ``self_info`` cache refreshes on the OK path so the
    Configuration card readout updates after a single dashboard
    refresh.
    """
    if _config is None:
        raise HTTPException(503, "Config not loaded")

    source = _resolve_companion_source(req.label)
    if source is None or not source.connected:
        raise HTTPException(503, "MeshCore companion not connected")

    result = await source.set_companion_name(req.name)
    if not result.success:
        logger.warning(
            "Dashboard set_companion_name failed for %s: %s", source.name, result.error
        )
        raise HTTPException(400, result.error or "Companion rejected name")

    cleaned = (req.name or "").strip()
    logger.info("MeshCore companion %r renamed to %r via dashboard", source.name, cleaned)
    _persist_companion_name(req.label, cleaned)

    event_type: Optional[str] = getattr(result, "event_type", None)
    return {
        "saved": True,
        "name": cleaned,
        "event_type": event_type,
    }


class CompanionAdvertRequest(BaseModel):
    label: str = ""
    flood: bool = False


@router.post("/companion-advert")
async def send_companion_advert_route(
    req: CompanionAdvertRequest,
    _claims: SessionClaims = Depends(require_admin),
) -> dict:
    """Send an advert from one specific USB companion.

    Separate from the general ``POST /api/messages/advert`` (which
    always targets whichever companion the TX client is bound to,
    i.e. company[0]) -- this lets the per-companion rename card's
    "send advert after save" actually target the companion that was
    just renamed, not always the primary one.
    """
    if _config is None:
        raise HTTPException(503, "Config not loaded")

    source = _resolve_companion_source(req.label)
    if source is None or not source.connected:
        raise HTTPException(503, "MeshCore companion not connected")

    result = await source.send_advert(flood=req.flood)
    return {
        "success": result.success,
        "error": result.error or None,
        "event_type": result.event_type or None,
    }


@router.get("/firmware-check")
async def check_companion_firmware(
    current_version: str = Query(..., min_length=1),
) -> dict:
    """On-demand check of one companion's firmware against the latest
    MeshCore GitHub release. Never runs automatically -- only when this
    endpoint is actually called (the dashboard's Check button).

    Takes ``current_version`` as a query param rather than resolving the
    primary companion server-side (mirrors serial_config_routes.py's
    identical reasoning): up to 4 companions can be configured, each
    potentially on different firmware, and the frontend already has each
    companion's own firmware_version rendered on the page.

    Read-only and side-effect-free, so unlike /companion-name this
    doesn't require admin -- any logged-in session can check.
    """
    if _config is None:
        raise HTTPException(503, "Config not loaded")
    return await _check_firmware_update(current_version.strip())
