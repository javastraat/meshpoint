"""Minimal Prometheus text-exposition parser for Meshpoint's /metrics.

Deliberately dependency-free and HA-agnostic so it can be unit tested
in isolation. Meshpoint's own writer (src/api/routes/metrics_routes.py,
PrometheusWriter) only ever emits the small subset of the format this
parser understands: ``# HELP``/``# TYPE`` comments, and one gauge/counter
value per line, optionally with ``{label="value",...}`` pairs.
"""

from __future__ import annotations

import re

_METRIC_LINE_RE = re.compile(
    r"^(?P<name>[a-zA-Z_:][a-zA-Z0-9_:]*)(\{(?P<labels>[^}]*)\})?\s+(?P<value>\S+)$"
)
_LABEL_RE = re.compile(r'(\w+)="((?:[^"\\]|\\.)*)"')

INFO_METRIC = "meshpoint_info"


def _sanitize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def parse_prometheus_text(text: str) -> tuple[dict[str, float], dict[str, str]]:
    """Parse a Meshpoint /metrics response body.

    Returns ``(metrics, info)``:

    - ``metrics``: flat ``{key: value}`` for every series. An unlabeled
      series is keyed by its bare metric name. A labeled series is keyed
      by ``"<name>_<label_value>_<label_value>..."`` (sanitized, joined
      by insertion order) -- e.g.
      ``meshpoint_protocol_packets_session_total{protocol="meshcore"}``
      becomes ``meshpoint_protocol_packets_session_total_meshcore``.
    - ``info``: the label values from the special ``meshpoint_info``
      series (version, region). Its value is always ``1`` -- not a
      useful measurement -- so it's pulled out for device info instead
      of becoming a sensor.
    """
    metrics: dict[str, float] = {}
    info: dict[str, str] = {}

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        match = _METRIC_LINE_RE.match(line)
        if not match:
            continue

        name = match.group("name")
        raw_labels = match.group("labels")
        raw_value = match.group("value")

        try:
            value = float(raw_value)
        except ValueError:
            continue

        labels = dict(_LABEL_RE.findall(raw_labels)) if raw_labels else {}

        if name == INFO_METRIC:
            info.update(labels)
            continue

        if labels:
            suffix = "_".join(_sanitize(v) for v in labels.values())
            key = f"{name}_{suffix}" if suffix else name
        else:
            key = name

        metrics[key] = value

    return metrics, info
