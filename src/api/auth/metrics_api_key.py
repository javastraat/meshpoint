"""Shared /metrics-scoped API key matching.

Used by every route this key is allowed to reach: the Prometheus
``/metrics`` endpoint itself, plus the small, fixed set of additional
read-only status routes explicitly opened to it (``/api/device/metrics``,
``/api/stats/summary``) -- see docs/CONFIGURATION.md. Deliberately not
"any read-only route": each route that accepts this key does so via an
explicit ``Depends(require_session_or_metrics_key)``, not a blanket rule.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone
from typing import Optional

from fastapi import Header, Request

from src.api.auth.dependencies import require_auth
from src.config import MetricsApiKey, MetricsConfig

_config: MetricsConfig | None = None


def init_metrics_api_key(config: MetricsConfig) -> None:
    global _config
    _config = config


def reset_metrics_api_key() -> None:
    global _config
    _config = None


def match_metrics_api_key(authorization: Optional[str]) -> Optional[MetricsApiKey]:
    """Check ``Authorization: Bearer <key>`` against configured metrics
    API keys. Returns the matched key (so the caller can stamp
    ``last_used_at``), or ``None``.
    """
    if _config is None or not authorization or not authorization.startswith("Bearer "):
        return None
    presented = authorization[len("Bearer "):].strip()
    if not presented:
        return None
    presented_hash = hashlib.sha256(presented.encode()).hexdigest()
    for key in _config.api_keys:
        if hmac.compare_digest(presented_hash, key.key_hash):
            return key
    return None


async def require_session_or_metrics_key(
    request: Request,
    authorization: Optional[str] = Header(default=None),
) -> None:
    """Dependency: allow a matching metrics API key, or fall back to the
    normal dashboard session (cookie or session Bearer JWT).

    ``last_used_at`` is updated in memory only, not persisted to
    local.yaml on every request -- same write-amplification reasoning as
    the ``/metrics`` endpoint itself.
    """
    matched_key = match_metrics_api_key(authorization)
    if matched_key is not None:
        matched_key.last_used_at = datetime.now(timezone.utc).isoformat()
        return
    await require_auth(request, authorization)
