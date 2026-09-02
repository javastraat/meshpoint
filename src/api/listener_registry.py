"""Plugin extension point for RTL-SDR subprocess listeners.

``src.api.server.create_app`` keeps its own built-in list (``_BUILTIN_LISTENERS``
there -- greppable, not moved here) and passes it to ``start_all`` alongside
whatever a plugin registered through this module. Built-ins do **not** call
``register_listener``; this is purely the seam for out-of-core code under
``plugins/apps/<name>/``.

A listener is any object with an async ``stop()``. ``start_all`` runs each
spec's ``build`` at app startup and hands the result to ``wire`` (which injects
the singleton into its already-mounted router) -- it does **not** call
``start()``; the listener's ``/start`` route does that on demand. ``build`` may
return one listener or a tuple of them (the pager trio shares one
``init_routes`` call).

Kept free of FastAPI imports so it loads on any machine.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ListenerSpec:
    name: str
    build: Callable[[], Any]  # -> a listener, or a tuple of listeners
    wire: Callable[[Any], None] | None = None  # gets build()'s return value


_plugin_specs: list[ListenerSpec] = []
_live: list[tuple[str, Any]] = []  # (name, build result), in startup order


def register_listener(spec: ListenerSpec) -> None:
    """Add *spec* -- built on the next ``create_app`` startup, after built-ins."""
    _plugin_specs.append(spec)


def plugin_specs() -> list[ListenerSpec]:
    """The plugin-registered specs, in registration order."""
    return list(_plugin_specs)


def live() -> list[tuple[str, Any]]:
    """``(name, build result)`` for every listener built by ``start_all``."""
    return list(_live)


def start_all(builtins: Iterable[ListenerSpec]) -> None:
    """Build every built-in then plugin listener and wire it into its router."""
    for spec in (*builtins, *_plugin_specs):
        obj = spec.build()
        if spec.wire is not None:
            spec.wire(obj)
        _live.append((spec.name, obj))


async def stop_all() -> None:
    """``await .stop()`` on every built listener, newest first. A listener that
    raises on stop doesn't hold up the rest."""
    for name, obj in reversed(_live):
        for listener in obj if isinstance(obj, tuple) else (obj,):
            try:
                await listener.stop()
            except Exception:  # noqa: BLE001 - shutdown must not abort
                logger.exception("listener %s failed to stop", name)
    _live.clear()


def reset() -> None:
    """Drop every plugin registration and built instance (test helper)."""
    _plugin_specs.clear()
    _live.clear()
