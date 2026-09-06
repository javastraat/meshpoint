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

Imports are deferred into ``register()`` so ``backend.state`` /
``backend.lxmf_service`` / ``backend.peer_repo`` can be imported for their
own tests without pulling in FastAPI.

Phase 1 scaffold -- see ``memory/plugin-reticulum.md``. Core's own
Reticulum service/routes stay authoritative until this plugin is
live-verified and the atomic config flip happens (Phase 4).
"""

from __future__ import annotations


def register(reg) -> None:
    from src.storage.message_repository import MessageRepository

    from . import config_routes, routes, state
    from .lxmf_service import LxmfService
    from .peer_repo import ReticulumPeerRepository

    state.init(reg.config)

    reg.add_router(routes.router)
    reg.add_router(config_routes.router)

    def build(context):
        service = LxmfService(
            display_name=state.display_name(),
            reticulum_config_dir=state.reticulum_config_dir(),
            identity_path=state.identity_path(),
            lxmf_storage_dir=state.lxmf_storage_dir(),
            message_repo=MessageRepository(context.pipeline.database),
            peer_repo=ReticulumPeerRepository(context.pipeline.database),
            ws_manager=context.ws_manager,
        )
        return service

    def wire(service, context):
        routes.init_routes(service, MessageRepository(context.pipeline.database))

    reg.add_service("reticulum", build, wire)
