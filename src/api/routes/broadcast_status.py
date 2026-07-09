"""Shared helpers for mesh broadcast configuration routes."""

from __future__ import annotations


def build_broadcast_status(broadcaster, cfg_section) -> dict:
    """Build a live status block for ``GET /api/config``."""
    last_sent = None
    next_due = None
    running = False
    if broadcaster is not None:
        running = broadcaster.is_running
        if broadcaster.last_sent_at is not None:
            last_sent = broadcaster.last_sent_at.isoformat()
        if broadcaster.next_due_at is not None:
            next_due = broadcaster.next_due_at.isoformat()
    return {
        "interval_minutes": cfg_section.interval_minutes,
        "startup_delay_seconds": cfg_section.startup_delay_seconds,
        "running": running,
        "last_sent_at": last_sent,
        "next_due_at": next_due,
    }
