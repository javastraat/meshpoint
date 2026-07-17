"""Flattens the JSON responses from /api/device/metrics and
/api/stats/summary into the same flat {key: value} shape the Prometheus
parser produces for /metrics, so all three sources can share sensor.py's
dynamic entity-creation logic.

Pure Python, no Home Assistant imports -- unit testable standalone.
"""

from __future__ import annotations

import re

_SANITIZE_RE = re.compile(r"[^a-z0-9]+")

# Known high-cardinality / not-sensor-shaped branches: histogram buckets
# and a time series, not meaningful as individual entities. Skipped
# outright rather than flattened into dozens of noisy sensors.
SKIP_KEYS = frozenset({"rssi_distribution", "snr_distribution", "traffic_timeline"})


def _sanitize(value: str) -> str:
    return _SANITIZE_RE.sub("_", value.lower()).strip("_")


def flatten_json(data, prefix: str = "") -> dict:
    """Recursively flatten a JSON-decoded dict into {snake_case_key: scalar}.

    - Dicts recurse, joining key names with ``_``.
    - Lists are skipped entirely (not scalar-shaped; avoids noisy indexed
      sensors for things like distribution buckets).
    - ``None`` is skipped (nothing to show yet -- e.g. "farthest node"
      before any qualifying packet has been heard).
    - Keys in SKIP_KEYS are skipped outright, at any nesting level.
    - Bools become 0/1 (still valid sensor states); non-empty strings
      pass through as-is; empty strings are skipped.
    """
    out: dict = {}
    if not isinstance(data, dict):
        return out

    for key, value in data.items():
        if key in SKIP_KEYS:
            continue
        clean_key = _sanitize(str(key))
        if not clean_key:
            continue
        full_key = f"{prefix}_{clean_key}" if prefix else clean_key

        if isinstance(value, dict):
            out.update(flatten_json(value, full_key))
        elif isinstance(value, bool):
            out[full_key] = int(value)
        elif isinstance(value, (int, float)):
            out[full_key] = value
        elif isinstance(value, str) and value:
            out[full_key] = value
        # lists and None: skipped

    return out
