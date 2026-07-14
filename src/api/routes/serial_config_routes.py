"""REST endpoints for Meshtastic USB serial device configuration.

Mounted under ``/api/config/serial/*``. Today this module owns the
on-demand firmware-update check against the meshtastic/firmware GitHub
releases, mirroring meshcore_config_routes.py's companion firmware
check -- split into its own file for the same reason that one was: a
single shared config_routes.py grows unwieldy fast.
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

router = APIRouter(prefix="/api/config/serial", tags=["config", "serial"])

_config: AppConfig | None = None
_serial_sources: list = []

# Manual/on-demand only -- same reasoning as meshcore_config_routes.py's
# identical comment: firmware only changes when a stick is physically
# reflashed, so there's no live state worth polling automatically.
_FIRMWARE_RELEASES_URL = (
    "https://api.github.com/repos/meshtastic/firmware/releases/latest"
)
_SEMVER_RE = re.compile(r"v?(\d+)\.(\d+)\.(\d+)")
# Confirmed against a real release: unlike MeshCore (hash only in asset
# filenames), meshtastic/firmware's own tag_name IS already the full
# 'vX.Y.Z.hash' string (e.g. 'v2.7.26.54e0d8d') -- no need to dig through
# release assets at all here.
_TAG_VERSION_RE = re.compile(r"v?(\d+\.\d+\.\d+\.[a-f0-9]{7})")
_HASH_RE = re.compile(r"\.([a-f0-9]{7})\b")

_FIRMWARE_CHECK_CACHE_TTL_SECONDS = 300
# Caches only the shared GitHub fetch (latest_version/release_url), not a
# full comparison result -- unlike MeshCore's single companion, up to 4
# serial devices can each be on different firmware, so the per-device
# update_available comparison is always computed fresh against whichever
# current_version the caller passes.
_release_cache: dict[str, object] = {
    "latest_version": None, "release_url": None, "error": None, "expires": 0,
}


def _semver_and_hash(version_str: str) -> tuple[Optional[tuple[int, int, int]], Optional[str]]:
    semver_match = _SEMVER_RE.search(version_str or "")
    semver = tuple(int(g) for g in semver_match.groups()) if semver_match else None
    hash_match = _HASH_RE.search(version_str or "")
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
            "Failed to fetch latest Meshtastic firmware release", exc_info=True,
        )
        return None


def _latest_release_version_string(release: dict) -> Optional[str]:
    """The release tag is already 'vX.Y.Z.hash' -- strip the leading 'v'
    so it matches the device's own reported format exactly (e.g. device
    reports '2.7.26.54e0d8d', tag is 'v2.7.26.54e0d8d')."""
    tag = release.get("tag_name") or release.get("name") or ""
    match = _TAG_VERSION_RE.search(tag)
    return match.group(1) if match else None


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


def init_routes(config: AppConfig, serial_sources=None) -> None:
    global _config, _serial_sources
    _config = config
    _serial_sources = serial_sources or []


def _resolve_serial_source(label: str):
    """Find the configured serial device source matching this label.

    Mirrors ``serial_card.js``'s own name reconstruction
    (``serial_<label>``, bare ``serial`` when unlabeled) -- same
    pattern as meshcore_config_routes.py's ``_resolve_companion_source``.
    """
    name = f"serial_{label}" if label else "serial"
    for src in _serial_sources:
        if src.name == name:
            return src
    return None


def _persist_serial_identity(label: str, long_name: Optional[str], short_name: Optional[str]) -> None:
    """Save one device's renamed identity to its own config entry.

    Persists the FULL ``capture.serial`` list (mirrors
    meshcore_config_routes.py's ``_persist_companion_name`` -- same
    "save_section_to_yaml replaces the whole section" reasoning).
    Failure here is a soft error: the rename already stuck on the
    stick's own flash for the current session; only the
    apply-on-next-restart path is degraded until the user retries.
    """
    matched = False
    for entry in _config.capture.serial:
        if (entry.label or "") == (label or ""):
            if long_name is not None:
                entry.long_name = long_name
            if short_name is not None:
                entry.short_name = short_name
            matched = True
            break
    if not matched:
        logger.warning(
            "No serial config entry matched label %r; "
            "rename won't be re-applied on the next restart until saved",
            label,
        )
        return
    try:
        save_section_to_yaml("capture", {
            "serial": [
                {
                    "serial_port": e.serial_port,
                    "serial_baud": e.serial_baud,
                    "label": e.label,
                    "long_name": e.long_name,
                    "short_name": e.short_name,
                }
                for e in _config.capture.serial
            ],
        })
    except PermissionError as exc:
        logger.warning(
            "Renamed serial device (label=%r) but failed to persist to "
            "local.yaml: %s. Won't be re-applied on the next restart "
            "until saved.",
            label, exc,
        )
    except Exception:
        logger.exception(
            "Renamed serial device (label=%r) but yaml persistence "
            "failed; won't be re-applied on the next restart until saved.",
            label,
        )


class SerialIdentityUpdate(BaseModel):
    label: str = ""
    long_name: Optional[str] = None
    short_name: Optional[str] = None


@router.put("/identity")
async def update_serial_identity(
    req: SerialIdentityUpdate,
    _claims: SessionClaims = Depends(require_admin),
) -> dict:
    """Rename one Meshtastic USB stick's own long/short name.

    Takes ``label`` to target a specific device (empty string for the
    bare/unlabeled one) -- up to 4 devices can be configured, each with
    its own independent identity. Mirrors meshcore_config_routes.py's
    ``/companion-name`` shape exactly.

    Unlike MeshCore's companion rename, there's no live reconnect-callback
    to re-apply this if the stick is later swapped for a blank
    replacement -- the persisted value is only re-applied at the next
    service start (``SerialCaptureSource`` has no auto-reconnect loop to
    hook into). The live rename itself still takes effect immediately on
    the currently connected stick.
    """
    if _config is None:
        raise HTTPException(503, "Config not loaded")

    source = _resolve_serial_source(req.label)
    if source is None or not source.connected:
        raise HTTPException(503, "Serial device not connected")

    result = source.set_owner(req.long_name, req.short_name)
    if not result["success"]:
        logger.warning(
            "Dashboard set_owner failed for %s: %s", source.name, result["error"],
        )
        raise HTTPException(400, result["error"] or "Device rejected identity change")

    _persist_serial_identity(req.label, result.get("long_name"), result.get("short_name"))

    return {
        "saved": True,
        "long_name": result.get("long_name"),
        "short_name": result.get("short_name"),
    }


class SerialAdvertRequest(BaseModel):
    label: str = ""


@router.post("/advert")
async def send_serial_advert_route(
    req: SerialAdvertRequest,
    _claims: SessionClaims = Depends(require_admin),
) -> dict:
    """Send a NodeInfo broadcast from one specific Meshtastic USB stick.

    Mirrors meshcore_config_routes.py's ``/companion-advert`` -- lets the
    per-device rename card's "send advert after save" target the exact
    stick that was just renamed.
    """
    if _config is None:
        raise HTTPException(503, "Config not loaded")

    source = _resolve_serial_source(req.label)
    if source is None or not source.connected:
        raise HTTPException(503, "Serial device not connected")

    success = source.send_nodeinfo()
    return {"success": success, "error": None if success else "NodeInfo broadcast failed"}


@router.get("/firmware-check")
async def check_serial_firmware(
    current_version: str = Query(..., min_length=1),
) -> dict:
    """On-demand check of one Meshtastic USB stick's firmware against the
    latest meshtastic/firmware GitHub release. Never runs automatically --
    only when this endpoint is actually called (the dashboard's Check
    button).

    Takes ``current_version`` as a query param rather than resolving a
    specific connected device server-side: up to 4 serial devices can be
    configured, each potentially on different firmware, and the frontend
    already has each device's own firmware_version rendered on the page.

    Read-only and side-effect-free, so this doesn't require admin -- any
    logged-in session can check (same as MeshCore's equivalent).
    """
    if _config is None:
        raise HTTPException(503, "Config not loaded")
    return await _check_firmware_update(current_version.strip())
