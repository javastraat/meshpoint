"""Plugin extension point for a protocol a plugin owns end to end.

Lets a plugin's own capture source produce packets with a protocol
identity ``src.coordinator.PipelineCoordinator`` doesn't hardcode -- before
this existed, adding a protocol meant editing ``_process_capture``'s
capture-source dispatch and its capcode/tier-style filtering directly (the
DAPNET-shaped branches this module replaces). A registered ``ProtocolSpec``
supplies:

- ``adapt(raw)`` -- turns a ``RawCapture`` whose ``capture_source`` starts
  with ``capture_prefix`` into a ``Packet`` (or ``None``, treated as an
  undecodable stray frame same as any other decoder).
- ``tier(packet)``, optional -- post-decode classification returning
  ``"ignore"`` (dropped entirely, not even shown live), ``"blacklist"``
  (shown live, never stored/relayed/published), or ``None`` (normal
  handling) -- the same two tiers DAPNET's own capcode filters use.

Kept free of FastAPI imports so it loads on any machine.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class ProtocolSpec:
    protocol: str
    capture_prefix: str
    adapt: Callable[[Any], Optional[Any]]  # RawCapture -> Packet | None
    tier: Callable[[Any], Optional[str]] | None = None  # Packet -> "ignore"|"blacklist"|None


_specs: dict[str, ProtocolSpec] = {}
_by_prefix: list[ProtocolSpec] = []  # checked in registration order


def register_protocol(spec: ProtocolSpec) -> None:
    """Add *spec* -- consulted by ``PipelineCoordinator._process_capture``
    for every raw capture and decoded packet from here on."""
    _specs[spec.protocol] = spec
    _by_prefix.append(spec)


def for_capture_source(capture_source: str) -> Optional[ProtocolSpec]:
    """The first registered spec whose ``capture_prefix`` matches, or
    ``None`` if no plugin owns this capture source."""
    for spec in _by_prefix:
        if capture_source.startswith(spec.capture_prefix):
            return spec
    return None


def for_protocol(protocol: str) -> Optional[ProtocolSpec]:
    """The spec that owns *protocol*, or ``None`` if it isn't
    plugin-registered (a core protocol, or truly unknown)."""
    return _specs.get(protocol)


def reset() -> None:
    """Drop every registration (test helper)."""
    _specs.clear()
    _by_prefix.clear()
