"""Shared time-bucketing helper for downsampled history queries.

Used by TelemetryRepository.get_history() and
PacketRepository.get_signal_history() so a long-lived node's chart data
stays bounded to roughly `limit` points regardless of how long or dense
its history is, instead of a plain LIMIT silently dropping the newest
rows once history exceeds it.
"""

from __future__ import annotations

from datetime import datetime


def bucket_seconds(span_row: dict | None, limit: int, hours: float) -> int:
    """Bucket width in seconds for a downsampled history query.

    Derived from the ACTUAL span of matching data (``span_row``'s
    ``lo``/``hi`` timestamps) rather than the requested ``hours`` window --
    callers often over-request a huge window ("everything, however far
    back it goes") to avoid guessing a real history length, and sizing
    buckets off that requested window instead of the real span would
    crush a short real history into a handful of absurdly coarse buckets.
    Falls back to ``hours`` only when there's no data yet to measure a
    real span from. Floored at 60s so a short/sparse window doesn't
    produce a sub-minute bucket width.
    """
    limit = max(limit, 1)
    lo = span_row.get("lo") if span_row else None
    hi = span_row.get("hi") if span_row else None
    if lo and hi:
        span = (datetime.fromisoformat(hi) - datetime.fromisoformat(lo)).total_seconds()
        if span > 0:
            return max(60, int(span / limit))
    return max(60, int((hours * 3600) / limit))
