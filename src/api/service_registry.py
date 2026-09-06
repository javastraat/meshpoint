"""Plugin extension point for lifespan-managed background services.

Neither ``listener_registry`` (RTL-SDR subprocess listeners, idle until a
``/start`` route) nor ``capture_source_registry`` (sources joining the
packet pipeline) fit a plugin that just needs to run an async service for
the lifetime of the app -- the same shape as core's own
``LxmfService``/``RfEnvCompanionScanService``: an object with ``async
start()`` / ``async stop()``, constructed once, started right after the
pipeline is up and stopped on shutdown.

A service is any object with an async ``start()`` and an async ``stop()``.
``start_all(context)`` runs each spec's ``build(context)`` (which may
return ``None`` to opt out -- e.g. an optional dependency isn't
installed), hands the result to ``wire(service, context)`` if given, then
``await``s ``service.start()``. ``stop_all()`` ``await``s ``stop()`` on
each, newest first; one that raises never holds up the rest.

``context`` is a :class:`ServiceContext` -- the live ``pipeline`` (so a
service can reach ``pipeline.database`` / ``pipeline.packet_repo``), the
shared ``ws_manager``, and the full ``AppConfig``. ``src.api.server``'s
``lifespan`` calls ``start_all`` right after ``await pipeline.start()``
(so ``pipeline.packet_repo`` no longer raises) and ``stop_all`` in the
shutdown block alongside the other companion services.

Kept free of FastAPI imports so it loads on any machine.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ServiceContext:
    """Live core objects handed to a plugin service's ``build``/``wire``."""

    pipeline: Any
    ws_manager: Any
    config: Any  # AppConfig


@dataclass
class ServiceSpec:
    name: str
    build: Callable[[ServiceContext], Any]  # -> a service, or None to opt out
    wire: Callable[[Any, ServiceContext], None] | None = None


_plugin_specs: list[ServiceSpec] = []
_live: list[tuple[str, Any]] = []  # (name, built service), in startup order


def register_service(spec: ServiceSpec) -> None:
    """Add *spec* -- built + started on the next ``create_app`` lifespan."""
    _plugin_specs.append(spec)


def plugin_specs() -> list[ServiceSpec]:
    """The plugin-registered specs, in registration order."""
    return list(_plugin_specs)


def live() -> list[tuple[str, Any]]:
    """``(name, service)`` for every service built + started by ``start_all``."""
    return list(_live)


async def start_all(context: ServiceContext) -> None:
    """Build, wire and ``start()`` every registered service, in registration
    order. A ``build`` returning ``None`` is skipped. Meant to run once per
    app lifecycle, with ``reset()`` between test runs.

    A service whose ``build``/``wire``/``start`` raises is logged and
    skipped -- one plugin service failing must never abort meshpoint
    startup, the same isolation guarantee the plugin loader gives
    ``register()``. (Real case: the reticulum plugin's ``RNS.Reticulum()``
    hitting "Address already in use" when it starts a beat before rnsd
    finishes coming up -- a transient it recovers from on the next
    restart, not a reason to crash-loop the whole dashboard.) A service
    that got as far as ``start()`` before raising is still tracked for
    ``stop_all()``, since it may hold resources."""
    _live.clear()
    for spec in _plugin_specs:
        try:
            service = spec.build(context)
            if service is None:
                logger.info("plugin service %s opted out of startup", spec.name)
                continue
            if spec.wire is not None:
                spec.wire(service, context)
            _live.append((spec.name, service))
            await service.start()
        except Exception:  # noqa: BLE001 - one service must not abort startup
            logger.exception(
                "plugin service %s failed to start -- skipping it, the rest "
                "of meshpoint starts normally", spec.name,
            )


async def stop_all() -> None:
    """``await .stop()`` on every started service, newest first. A service
    that raises on stop doesn't hold up the rest."""
    for name, service in reversed(_live):
        try:
            await service.stop()
        except Exception:  # noqa: BLE001 - shutdown must not abort
            logger.exception("plugin service %s failed to stop", name)
    _live.clear()


def reset() -> None:
    """Drop every plugin registration and built instance (test helper)."""
    _plugin_specs.clear()
    _live.clear()
