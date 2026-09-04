"""Shared RTL-SDR dongle-ownership status, independent of any one plugin.

Single read-only route: ``GET /api/sdr/status``. Every RTL-SDR listener
(Radio, DAB+, P2000, Pagers, POCSAG, RTL433, ACARS, ADS-B -- all opt-in
plugins now, see ``src/audio/sdr_registry.py``) claims the one physical
dongle through the same shared registry, so this endpoint works
regardless of which of those plugins happen to be installed or enabled.
Powers the RTL-SDR sidebar item's "in use by" badge
(``frontend/sidebar/sdr_status_badge.js``) without hardcoding it to poll
any one plugin's own status route, which might not even exist.
"""

from __future__ import annotations

from fastapi import APIRouter

from src.audio import sdr_registry

router = APIRouter(prefix="/api/sdr", tags=["sdr"])


@router.get("/status")
async def sdr_status() -> dict:
    return {"dongle_owner": sdr_registry.current_owner()}
