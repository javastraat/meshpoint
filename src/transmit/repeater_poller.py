"""Periodic MeshCore repeater status/telemetry poller.

MeshCore nodes advertise identity only -- no battery/uptime like
Meshtastic broadcasts -- so the node stats have to be *asked for*. This
polls a configured short list of repeaters (ones you have the password
for) via the companion's ``req_status``/``req_telemetry`` (the same
meshcore-cli uses), fills the ``telemetry`` table for the drawer chart /
CSV, and keeps the full raw status for the Repeaters tab.

Active two-way RF on a schedule -- the most chatty thing Meshpoint does
-- so it's opt-in, sequential, conservatively paced, and backs off on
failure rather than hammering a wedged command channel.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.models.telemetry import Telemetry

logger = logging.getLogger(__name__)

# Gap between repeaters within one poll round (active TX, be polite).
PER_REPEATER_GAP_S = 5.0
STATE_FILENAME = "repeater_status.json"

# LPP (channel, type) -> Telemetry field. Channel 1 is the node's own
# board; higher channels are attached sensors. Battery voltage doubles
# as battery_level's source (we store the volts, not a fake %).
_LPP_MAP = {
    (1, "voltage"): "voltage",
    (1, "temperature"): "temperature",
    (3, "temperature"): "temperature",
    (3, "barometer"): "barometric_pressure",
    (4, "temperature"): "temperature",
    (4, "humidity"): "humidity",
}


class RepeaterPoller:
    """Polls configured repeaters and exposes their latest status.

    Lifecycle mirrors NodeInfoBroadcaster: ``start()`` spawns a loop,
    ``stop()`` cancels it. ``latest`` (keyed by repeater key) backs the
    ``GET /api/meshcore/repeaters`` endpoint and survives restarts via a
    small JSON file in the data dir.
    """

    def __init__(
        self,
        tx_client,
        repeaters: list,
        interval_minutes: int,
        telemetry_repo=None,
        data_dir: str = "data",
    ):
        self._tx = tx_client
        self._repeaters = repeaters
        self._interval_s = max(60, int(interval_minutes) * 60)
        self._telemetry_repo = telemetry_repo
        self._state_path = Path(data_dir) / STATE_FILENAME
        self._task: Optional[asyncio.Task] = None
        self.latest: dict[str, dict] = {}
        self._load_state()

    async def start(self) -> None:
        logger.info(
            "Repeater poller started: %d repeater(s), every %d min",
            len(self._repeaters), self._interval_s // 60,
        )
        self._task = asyncio.create_task(self._loop())

    async def stop(self, timeout: float = 5.0) -> None:
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        try:
            await asyncio.wait_for(task, timeout=timeout)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
        except Exception:
            logger.debug("Repeater poller stop raised", exc_info=True)

    async def _loop(self) -> None:
        # Small initial delay so the companion roster is loaded first.
        try:
            await asyncio.sleep(45)
            while True:
                await self._poll_round()
                await asyncio.sleep(self._interval_s)
        except asyncio.CancelledError:
            pass

    async def _poll_round(self) -> None:
        first = True
        for rep in self._repeaters:
            if not first:
                await asyncio.sleep(PER_REPEATER_GAP_S)
            first = False
            await self._poll_one(rep)

    async def _poll_one(self, rep) -> None:
        key = getattr(rep, "key", "")
        name = getattr(rep, "name", "") or key
        try:
            result = await self._tx.poll_repeater(
                key, getattr(rep, "password", ""),
            )
        except Exception:
            logger.exception("Repeater poll raised for %s", name)
            result = {"ok": False, "error": "exception"}

        entry = {
            "key": key,
            "name": name,
            "ok": bool(result.get("ok")),
            "error": result.get("error") or "",
            "status": result.get("status"),
            "telemetry": result.get("telemetry"),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        # Preserve last-good status when a poll fails, so the tab keeps
        # showing the most recent real data with a stale marker.
        if not entry["ok"] and key in self.latest:
            prev = self.latest[key]
            entry["status"] = entry["status"] or prev.get("status")
            entry["telemetry"] = entry["telemetry"] or prev.get("telemetry")
            entry["last_ok_at"] = prev.get("last_ok_at")
        elif entry["ok"]:
            entry["last_ok_at"] = entry["updated_at"]

        self.latest[key] = entry
        self._save_state()

        if entry["ok"]:
            logger.info("Repeater %s polled OK", name)
            await self._store_telemetry(key, result)
        else:
            logger.warning("Repeater %s poll failed: %s", name, entry["error"])

    async def _store_telemetry(self, key: str, result: dict) -> None:
        """Map status + LPP telemetry onto a Telemetry row (drawer/CSV)."""
        if self._telemetry_repo is None:
            return
        status = result.get("status") or {}
        telem = Telemetry(node_id=key)
        bat_mv = status.get("bat")
        if isinstance(bat_mv, (int, float)) and bat_mv > 0:
            telem.voltage = round(bat_mv / 1000.0, 3)
        uptime = status.get("uptime")
        if isinstance(uptime, (int, float)):
            telem.uptime_seconds = int(uptime)

        for reading in _iter_lpp(result.get("telemetry")):
            field = _LPP_MAP.get((reading.get("channel"), reading.get("type")))
            if field and getattr(telem, field, None) is None:
                setattr(telem, field, reading.get("value"))

        if telem.voltage is None and telem.temperature is None:
            return  # nothing worth storing
        try:
            await self._telemetry_repo.insert(telem)
        except Exception:
            logger.debug("Repeater telemetry insert failed", exc_info=True)

    def _load_state(self) -> None:
        try:
            if self._state_path.exists():
                self.latest = json.loads(self._state_path.read_text())
        except Exception:
            logger.debug("Repeater state load failed", exc_info=True)
            self.latest = {}

    def _save_state(self) -> None:
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            self._state_path.write_text(json.dumps(self.latest))
        except Exception:
            logger.debug("Repeater state save failed", exc_info=True)


def _iter_lpp(telemetry):
    """Yield LPP {channel,type,value} dicts from a telemetry payload."""
    if isinstance(telemetry, dict):
        lpp = telemetry.get("lpp")
        if isinstance(lpp, list):
            for r in lpp:
                if isinstance(r, dict):
                    yield r
