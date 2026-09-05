"""Plugin extension point for capture sources.

Unlike ``listener_registry`` (RTL-SDR subprocess listeners, built idle at
startup and started on demand by their own ``/start`` route), a capture
source is started unconditionally at boot -- same lifecycle as the
core-owned sources (concentrator, meshcore_usb, serial). ``CaptureCoordinator``
already owns that start/stop lifecycle once a source is in its list, so this
module has no ``start_all``/``stop_all`` of its own: it only exists to get a
plugin-built ``CaptureSource`` into that list before ``pipeline.start()``
runs, and to hand the plugin a chance to bind against the live pipeline
(``pipeline.packet_repo`` etc) once it exists.

``src.api.server._build_pipeline`` drains ``build_all()`` right after its own
``for source_name in config.capture.sources`` loop, before returning (i.e.
before ``pipeline.start()``); ``wire_all(pipeline)`` runs from ``lifespan``
right after ``await pipeline.start()`` completes, since ``pipeline.packet_repo``
raises ``RuntimeError`` until then.

Kept free of FastAPI imports so it loads on any machine.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CaptureSourceSpec:
    name: str
    build: Callable[[], Any]  # -> a CaptureSource, or a tuple/list of them
    wire: Callable[[Any, Any], None] | None = None  # (built sources, pipeline)


_plugin_specs: list[CaptureSourceSpec] = []
_built: list[tuple[str, tuple]] = []  # (spec name, built sources tuple)


def register_capture_source(spec: CaptureSourceSpec) -> None:
    """Add *spec* -- built on the next ``create_app`` startup, before
    ``pipeline.start()``."""
    _plugin_specs.append(spec)


def plugin_specs() -> list[CaptureSourceSpec]:
    """The plugin-registered specs, in registration order."""
    return list(_plugin_specs)


def build_all() -> list[Any]:
    """Build every registered spec, returning the flat list of
    ``CaptureSource`` objects for the caller to add to the coordinator.

    Must run before ``CaptureCoordinator.start()`` -- a source added
    afterwards never gets its reader task spawned. Idempotent per call --
    clears any previous ``_built`` state first, since this (like
    ``listener_registry.start_all``) is meant to run once per app
    lifecycle, with ``reset()`` between test runs.
    """
    _built.clear()
    built_flat: list[Any] = []
    for spec in _plugin_specs:
        result = spec.build()
        sources = result if isinstance(result, (list, tuple)) else (result,)
        _built.append((spec.name, tuple(sources)))
        built_flat.extend(sources)
    return built_flat


def wire_all(pipeline: Any) -> None:
    """Hand each spec's built source(s) + the live pipeline to its ``wire``
    callback, once ``pipeline.start()`` has completed (``pipeline.packet_repo``
    etc now exist) -- lets a plugin's route module late-bind against them,
    same as core's own ``dapnet_routes.init_routes(coord.packet_repo, ...)``
    pattern.
    """
    for spec, (_, sources) in zip(_plugin_specs, _built):
        if spec.wire is not None:
            spec.wire(sources, pipeline)


def reset() -> None:
    """Drop every plugin registration and built instance (test helper)."""
    _plugin_specs.clear()
    _built.clear()
