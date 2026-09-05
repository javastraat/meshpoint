"""The surface a plugin's ``register()`` is handed.

One stable facade over the low-level seams (``src.api.route_registry``,
``src.api.listener_registry``, ``src.api.capture_source_registry``,
``src.api.protocol_registry``) so out-of-core code never imports
``src.api.*`` directly, and so what a plugin registers is checked against
its manifest's ``provides``.

Kept free of FastAPI imports -- the underlying registries are too, so the
loader + this facade unit-test on the Mac.
"""

from __future__ import annotations

import logging
from typing import Any

from src.api import (
    capture_source_registry,
    listener_registry,
    protocol_registry,
    route_registry,
)
from src.plugins.manifest import PluginManifest

logger = logging.getLogger(__name__)


class PluginRegistryError(Exception):
    """A plugin's ``register()`` did something its manifest doesn't declare."""


class PluginRegistry:
    """Passed to ``register(reg)`` in ``plugins/apps/<name>/backend/__init__.py``.

    * ``reg.manifest`` -- the parsed ``plugin.toml``.
    * ``reg.name`` -- the plugin id (folder name).
    * ``reg.config`` -- a copy of ``config.plugins["<name>"]`` (freqs, gain,
      device, ... -- the plugin's own sub-schema).
    """

    def __init__(self, manifest: PluginManifest, plugin_config: dict) -> None:
        self.manifest = manifest
        self.name = manifest.name
        self.config = dict(plugin_config)

    def _require(self, capability: str, call: str) -> None:
        if capability not in self.manifest.provides:
            raise PluginRegistryError(
                f"plugin {self.name!r} called {call} but {capability!r} is not "
                f"in its manifest 'provides' ({list(self.manifest.provides)})"
            )

    def add_router(self, router: Any, *, public: bool = False) -> None:
        """Mount an APIRouter. ``public=False`` keeps it behind the standard
        session gate, like every other ``/api/*`` route."""
        self._require("routes", "add_router()")
        route_registry.register_router(router, public=public)

    def add_listener(
        self, name: str, build: Any, wire: Any = None,
    ) -> None:
        """Register an RTL-SDR listener. *build* is a zero-arg callable
        returning the listener (or a tuple of them); *wire* is an optional
        callback handed that result to inject it into its router. Built idle
        at app startup, started on demand by the listener's ``/start`` route."""
        self._require("listener", "add_listener()")
        listener_registry.register_listener(
            listener_registry.ListenerSpec(name, build, wire),
        )

    def add_capture_source(
        self, name: str, build: Any, wire: Any = None,
    ) -> None:
        """Register a capture source that joins the real packet pipeline.
        *build* is a zero-arg callable returning a ``CaptureSource`` (or a
        tuple of them, e.g. one per configured device) -- unlike a
        listener, it's started unconditionally at boot, no on-demand
        ``/start`` route. *wire(sources, pipeline)*, if given, runs once
        the pipeline has started (``pipeline.packet_repo`` etc now exist),
        so this plugin's own routes can bind against them."""
        self._require("capture", "add_capture_source()")
        capture_source_registry.register_capture_source(
            capture_source_registry.CaptureSourceSpec(name, build, wire),
        )

    def add_protocol(
        self, protocol: str, *, capture_prefix: str, adapt: Any, tier: Any = None,
    ) -> None:
        """Register decode + classification for a protocol this plugin owns
        end to end. *adapt(raw)* turns a ``RawCapture`` whose
        ``capture_source`` starts with *capture_prefix* into a ``Packet``.
        *tier(packet)*, if given, may return ``"ignore"`` (never shown or
        stored) or ``"blacklist"`` (shown live, never stored) -- the same
        two tiers DAPNET's own capcode filters use."""
        self._require("protocol", "add_protocol()")
        protocol_registry.register_protocol(
            protocol_registry.ProtocolSpec(protocol, capture_prefix, adapt, tier),
        )
