"""Reticulum plugin -- entry point.

Meshpoint's plugin loader imports this module and calls ``register(reg)``
when ``plugins.reticulum.enabled: true`` is set -- opt-in, same as every
other shipped plugin. ``locked = true`` in ``plugin.toml`` only means
"can't be deleted from Settings -> Plugins", not "default-on".

Unlike the RTL-SDR family (subprocess listeners) or DAPNET (a
``CaptureSource`` in the packet pipeline), Reticulum produces no packets:
it's a lifespan-managed async service (``LxmfService`` -- an RNS/LXMF
client attach to the local ``rnsd`` shared instance), registered through
the ``"service"`` seam (``src.api.service_registry``). ``build()`` runs
once the pipeline is up (so ``context.pipeline.database`` is safe);
``wire()`` binds the routes module against the built service.

Also here, on the same RNS attach + identity:
  * **NomadNet browsing** (``backend/nomad*.py``) -- fetching Micron pages
    from ``nomadnetwork.node`` peers.
  * **NomadNet node hosting** (``backend/nomad_node.py``) -- serving pages,
    opt-in via ``plugins.reticulum.node_enabled``.
Both need the exact live ``RNS`` attach ``LxmfService`` provides, so it's
one plugin, not several with several client attaches.

Imports are deferred into ``register()`` so ``backend.state`` /
``backend.lxmf_service`` / ``backend.peer_repo`` / ``backend.nomad`` can
be imported for their own tests without pulling in FastAPI.

Extracted from core -- ``src/reticulum/`` and the core reticulum routes
are gone; this is the whole implementation. See
``memory/plugin-reticulum.md``.
"""

from __future__ import annotations

import time as _time

_wired_at: float | None = None


def register(reg) -> None:
    from src.storage.message_repository import MessageRepository
    from src.version import __version__

    from . import config_routes, nomad_routes, routes, state
    from .lxmf_service import LxmfService
    from .peer_repo import ReticulumPeerRepository

    state.init(reg.config)

    reg.add_router(routes.router)
    reg.add_router(config_routes.router)
    reg.add_router(nomad_routes.router)

    def build(context):
        peer_repo = ReticulumPeerRepository(context.pipeline.database)

        async def node_stats() -> dict:
            up = int(_time.time() - _wired_at) if _wired_at else 0
            nodes = await peer_repo.list_peers("nomadnetwork.node", limit=100)
            return {
                "version": __version__,
                "uptime": _fmt_uptime(up),
                "reticulum_peers": await peer_repo.count(),
                "nomad_nodes": await peer_repo.count("nomadnetwork.node"),
                "recent_nodes": [p.to_dict() for p in nodes],
            }

        return LxmfService(
            display_name=state.display_name(),
            reticulum_config_dir=state.reticulum_config_dir(),
            identity_path=state.identity_path(),
            lxmf_storage_dir=state.lxmf_storage_dir(),
            message_repo=MessageRepository(context.pipeline.database),
            peer_repo=peer_repo,
            ws_manager=context.ws_manager,
            node_cfg=state.node_config(),
            node_stats_provider=node_stats,
        )

    def wire(service, context):
        global _wired_at
        _wired_at = _time.time()
        routes.init_routes(service, MessageRepository(context.pipeline.database))
        nomad_routes.init_routes(service)

    reg.add_service("reticulum", build, wire)


def _fmt_uptime(seconds: int) -> str:
    d, rem = divmod(max(0, seconds), 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    if d:
        return f"{d}d {h}h"
    if h:
        return f"{h}h {m}m"
    return f"{m}m"
