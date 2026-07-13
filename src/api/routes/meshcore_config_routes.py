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

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.api.auth.dependencies import require_admin
from src.api.auth.jwt_session import SessionClaims
from src.config import AppConfig, save_section_to_yaml

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/config/meshcore", tags=["config", "meshcore"])

_config: AppConfig | None = None
_tx_service = None

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
_firmware_check_cache: dict[str, object] = {"result": None, "expires": 0}


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


async def _check_firmware_update(current_version: str) -> dict:
    now = time.time()
    cached = _firmware_check_cache["result"]
    if cached and now < _firmware_check_cache["expires"]:
        return cached

    loop = asyncio.get_running_loop()
    release = await loop.run_in_executor(None, _fetch_latest_firmware_release_sync)

    if release is None:
        result = {
            "checked": True,
            "update_available": False,
            "current_version": current_version,
            "latest_version": None,
            "release_url": None,
            "error": "Could not reach GitHub",
        }
    else:
        latest_version = _latest_release_version_string(release)
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

        result = {
            "checked": True,
            "update_available": update_available,
            "current_version": current_version,
            "latest_version": latest_version,
            "release_url": release.get("html_url"),
        }

    _firmware_check_cache["result"] = result
    _firmware_check_cache["expires"] = now + _FIRMWARE_CHECK_CACHE_TTL_SECONDS
    return result


def init_routes(config: AppConfig, tx_service=None) -> None:
    """Wire module-level state at app startup.

    ``tx_service`` is the same TxService instance used by the
    Meshtastic-side config routes; we reach through its ``_meshcore_tx``
    attribute so we share one companion handle across the whole API
    rather than opening a second connection.
    """
    global _config, _tx_service
    _config = config
    _tx_service = tx_service


def _resolve_meshcore_tx():
    """Return the live :class:`MeshCoreTxClient` or ``None`` if absent.

    ``getattr`` is intentional: in test fixtures or when MeshCore TX is
    disabled in config, ``_meshcore_tx`` may not exist on the
    TxService.
    """
    if _tx_service is None:
        return None
    return getattr(_tx_service, "_meshcore_tx", None)


class CompanionNameUpdate(BaseModel):
    name: str


@router.put("/companion-name")
async def update_companion_name(
    req: CompanionNameUpdate,
    _claims: SessionClaims = Depends(require_admin),
) -> dict:
    """Rename the USB companion (CMD_SET_ADVERT_NAME).

    Validation lives in :meth:`MeshCoreTxClient.set_companion_name`
    (single source of truth shared with future CLI / yaml-on-connect
    paths). Errors map to HTTP status codes as follows:

    - 503 if the companion is not connected (so the dashboard can show
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

    mc_tx = _resolve_meshcore_tx()
    if mc_tx is None or not mc_tx.connected:
        raise HTTPException(503, "MeshCore companion not connected")

    result = await mc_tx.set_companion_name(req.name)
    if not result.success:
        logger.warning(
            "Dashboard set_companion_name failed: %s", result.error
        )
        raise HTTPException(400, result.error or "Companion rejected name")

    cleaned = (req.name or "").strip()
    logger.info("MeshCore companion renamed to %r via dashboard", cleaned)

    # Persist the desired name so the USB capture source re-applies it
    # on the next connect (mirrors how channel_keys are re-synced).
    # Failure here is a soft error: the rename already stuck on the
    # companion's flash for the current session; only the on-reconnect
    # re-apply path is degraded until the user retries the save (or
    # edits local.yaml directly). Don't turn a successful rename into
    # an error response just because we couldn't write yaml.
    _config.meshcore.companion_name = cleaned
    try:
        save_section_to_yaml("meshcore", {"companion_name": cleaned})
    except PermissionError as exc:
        logger.warning(
            "Renamed companion to %r but failed to persist to "
            "local.yaml: %s. Reconnects will revert until saved.",
            cleaned,
            exc,
        )
    except Exception:
        logger.exception(
            "Renamed companion to %r but yaml persistence failed; "
            "reconnects will revert until saved.",
            cleaned,
        )

    event_type: Optional[str] = getattr(result, "event_type", None)
    return {
        "saved": True,
        "name": cleaned,
        "event_type": event_type,
    }


@router.get("/firmware-check")
async def check_companion_firmware() -> dict:
    """On-demand check of the companion's firmware against the latest
    MeshCore GitHub release. Never runs automatically -- only when this
    endpoint is actually called (i.e. the dashboard's Check button).

    Read-only and side-effect-free, so unlike /companion-name this
    doesn't require admin -- any logged-in session can check.
    """
    if _config is None:
        raise HTTPException(503, "Config not loaded")

    mc_tx = _resolve_meshcore_tx()
    if mc_tx is None or not mc_tx.connected:
        raise HTTPException(503, "MeshCore companion not connected")

    device_info = await mc_tx.get_device_info()
    if not device_info or not device_info.firmware_version:
        raise HTTPException(
            503, "Companion firmware version not available"
        )

    return await _check_firmware_update(device_info.firmware_version)
