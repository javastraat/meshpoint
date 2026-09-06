"""Hello Service plugin -- entry point.

The minimal reference for the ``"service"`` seam: a lifespan-managed
background service. ``register()`` calls ``reg.add_service(name, build)``;
``build(context)`` returns an object with async ``start()`` / ``stop()``,
which ``src.api.service_registry`` starts right after the packet pipeline
is up and stops on shutdown.

This one does nothing but log -- which also makes it a handy probe for
confirming the wiring actually fires on a real device (``journalctl -u
meshpoint | grep hello_service``).

Kept free of heavy imports (no FastAPI) so the plugin loads anywhere.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("hello_service")


class HelloService:
    """A do-nothing background service. Real ones (e.g. Reticulum's
    ``LxmfService``) attach to something in ``start()`` and release it in
    ``stop()``; this just records that the lifecycle hooks ran."""

    def __init__(self, context) -> None:
        # context is a src.api.service_registry.ServiceContext:
        #   .pipeline    -- the live packet pipeline (.database, .packet_repo)
        #   .ws_manager  -- the shared WebSocketManager
        #   .config      -- the full AppConfig
        self._context = context

    async def start(self) -> None:
        has_pipeline = self._context.pipeline is not None
        has_ws = self._context.ws_manager is not None
        logger.info(
            "hello-service started (context: pipeline=%s ws_manager=%s)",
            has_pipeline, has_ws,
        )

    async def stop(self) -> None:
        logger.info("hello-service stopped")


def register(reg) -> None:
    reg.add_service("hello-service", lambda context: HelloService(context))
