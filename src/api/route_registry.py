"""Plugin extension point for API routers.

``src.api.server.create_app`` mounts its own explicit built-in list
(``_ROUTERS`` there — kept greppable, not moved here) and then whatever a
plugin registered through this module. Built-ins do **not** call
``register_router``; this is purely the seam for out-of-core code under
``plugins/apps/<name>/``.

``public=False`` (the default) means the router is gated by
``Depends(require_auth)`` exactly like every other ``/api/*`` route.

Kept free of FastAPI imports so it loads on any machine (the type hint is
under ``TYPE_CHECKING``); ``register_router`` stores whatever object it is
handed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from fastapi import APIRouter


@dataclass
class RouterSpec:
    router: "APIRouter"
    public: bool = False


_registered: list[RouterSpec] = []


def register_router(router: "APIRouter", *, public: bool = False) -> None:
    """Add *router* to the app on the next ``create_app``. ``public=False``
    keeps it behind the standard session gate."""
    _registered.append(RouterSpec(router, public))


def registered() -> list[RouterSpec]:
    """The plugin-registered routers, in registration order."""
    return list(_registered)


def reset() -> None:
    """Drop every registration (test helper)."""
    _registered.clear()
