"""Periodic Meshtastic NodeInfo broadcaster.

Announces the Meshpoint's identity (node_id, long_name, short_name) on
the mesh so receiving Meshtastic clients can build a stable contact
entry. Without this, recipients have no friendly name to attach to
direct messages from the Meshpoint and DMs may show as 'Sent' in the
dashboard but never arrive.

Identity is captured at construction time. Changes to long_name /
short_name in the dashboard radio tab take effect on the next service
restart, matching the existing UX contract for ``transmit.node_id``.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Optional

from src.transmit.broadcast_interval import (
    INTERVAL_DISABLED,
    INTERVAL_MAX_MINUTES,
    INTERVAL_MIN_MINUTES,
    BroadcastIntervalController,
    clamp_interval_minutes,
)
from src.transmit.tx_service import HW_MODEL_PORTDUINO, TxService

logger = logging.getLogger(__name__)

DEFAULT_STARTUP_DELAY_SECONDS = 60
DEFAULT_INTERVAL_SECONDS = 180 * 60

__all__ = [
    "DEFAULT_INTERVAL_SECONDS",
    "DEFAULT_STARTUP_DELAY_SECONDS",
    "INTERVAL_DISABLED",
    "INTERVAL_MAX_MINUTES",
    "INTERVAL_MIN_MINUTES",
    "NodeInfoBroadcaster",
    "clamp_interval_minutes",
]


class NodeInfoBroadcaster:
    """Schedules periodic NodeInfo broadcasts via :class:`TxService`."""

    def __init__(
        self,
        tx_service: TxService,
        long_name: str,
        short_name: str,
        *,
        startup_delay_seconds: int = DEFAULT_STARTUP_DELAY_SECONDS,
        interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
        hw_model: int = HW_MODEL_PORTDUINO,
    ):
        self._tx = tx_service
        self._long_name = long_name
        self._short_name = short_name
        self._hw_model = hw_model
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._schedule = BroadcastIntervalController(
            startup_delay_seconds=startup_delay_seconds,
            interval_seconds=interval_seconds,
            field_name="transmit.nodeinfo.interval_minutes",
        )

    @property
    def is_running(self) -> bool:
        return self._running and self._task is not None and not self._task.done()

    @property
    def interval_seconds(self) -> int:
        return self._schedule.interval_seconds

    @property
    def startup_delay_seconds(self) -> int:
        return self._schedule.startup_delay_seconds

    @property
    def last_sent_at(self) -> Optional[datetime]:
        return self._schedule.last_sent_at

    @property
    def next_due_at(self) -> Optional[datetime]:
        return self._schedule.next_due_at(running=self._running)

    async def start(self) -> None:
        """Schedule the broadcast loop. No-op if already running."""
        if self.is_running:
            logger.debug("NodeInfoBroadcaster already running")
            return
        self._running = True
        self._schedule.begin()
        self._task = asyncio.create_task(
            self._loop(), name="nodeinfo-broadcaster"
        )
        logger.info(
            "NodeInfo broadcaster scheduled: first TX in %ds, "
            "interval %ds, long=%r short=%r",
            self._schedule.startup_delay_seconds,
            self._schedule.interval_seconds,
            self._long_name,
            self._short_name,
        )

    async def stop(self, timeout: float = 5.0) -> None:
        """Cancel the broadcast loop and wait for it to finish."""
        self._running = False
        task = self._task
        if task is None:
            return
        task.cancel()
        try:
            await asyncio.wait_for(task, timeout=timeout)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
        finally:
            self._task = None

    def set_interval(self, minutes: int) -> int:
        """Hot-reload the broadcast interval. Returns the clamped value."""
        return self._schedule.set_interval(minutes)

    async def _loop(self) -> None:
        try:
            await self._schedule.run_loop(
                is_running=lambda: self._running,
                on_due=self._broadcast_once,
                loop_name="NodeInfo broadcaster",
            )
        except Exception:
            logger.exception("NodeInfo broadcaster loop crashed")

    async def _broadcast_once(self):
        return await self.broadcast_now()

    async def broadcast_now(self):
        """Send a single NodeInfo broadcast right now."""
        try:
            result = await self._tx.send_nodeinfo(
                long_name=self._long_name,
                short_name=self._short_name,
                hw_model=self._hw_model,
            )
        except Exception as exc:
            logger.exception("NodeInfo send raised")
            from src.transmit.tx_service import SendResult
            return SendResult(
                success=False, protocol="meshtastic", error=str(exc),
            )

        if result.success:
            self._schedule.mark_sent()
            logger.info(
                "NodeInfo broadcast OK: id=%s airtime=%dms",
                result.packet_id, result.airtime_ms,
            )
        else:
            logger.warning(
                "NodeInfo broadcast skipped: %s", result.error or "unknown"
            )
        return result
