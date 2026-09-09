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

import logging
import time as _time
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

_wired_at: float | None = None


def register(reg) -> None:
    from src.remote.repo_source import resolve_owner_repo
    from src.storage.message_repository import MessageRepository
    from src.version import __version__

    from . import config_routes, host_stats, nomad_routes, routes, state
    from .lxmf_service import LxmfService
    from .peer_repo import ReticulumPeerRepository

    state.init(reg.config)

    reg.add_router(routes.router)
    reg.add_router(config_routes.router)
    reg.add_router(nomad_routes.router)

    project_url = f"https://github.com/{resolve_owner_repo()}"

    def build(context):
        peer_repo = ReticulumPeerRepository(context.pipeline.database)

        def _telemetry_cfg() -> dict:
            """plugins.reticulum.telemetry_* plus, when opted in, the
            operator's fixed location from core's Configuration -> GPS
            pin (device.latitude/longitude) -- no separate lat/lon keys."""
            cfg = state.telemetry_config()
            dev = context.config.device
            if cfg.get("include_location") and dev.latitude is not None and dev.longitude is not None:
                cfg = {**cfg, "location": (dev.latitude, dev.longitude, dev.altitude or 0.0)}
            return cfg

        async def _mesh_stats() -> dict:
            """Aggregate packet counts for /page/info.mu -- totals + a
            per-protocol split, nothing node-level (that page is served to
            anyone on the Reticulum network)."""
            try:
                pr = context.pipeline.packet_repo
                since = datetime.now(timezone.utc) - timedelta(hours=24)
                return {
                    "packets_total": await pr.get_count(),
                    "packets_24h": await pr.get_count_since(since),
                    "by_protocol": await pr.get_protocol_distribution(),
                }
            except Exception:  # noqa: BLE001 -- info.mu degrades, never 500s
                logger.debug("mesh stats unavailable", exc_info=True)
                return {}

        async def _conversation_count() -> int | None:
            try:
                mr = MessageRepository(context.pipeline.database)
                convs = await mr.get_conversations()
                return sum(1 for c in convs if c.protocol == "reticulum")
            except Exception:  # noqa: BLE001
                return None

        async def node_stats() -> dict:
            up = int(_time.time() - _wired_at) if _wired_at else 0
            nodes = await peer_repo.list_peers("nomadnetwork.node", limit=100)
            return {
                "version": __version__,
                "uptime": _fmt_uptime(up),
                "hardware": context.config.device.hardware_description,
                "reticulum_peers": await peer_repo.count(),
                "nomad_nodes": await peer_repo.count("nomadnetwork.node"),
                "conversations": await _conversation_count(),
                "recent_nodes": [p.to_dict() for p in nodes],
                "host": host_stats.read_host(),
                "mesh": await _mesh_stats(),
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
            hardware_description=context.config.device.hardware_description,
            project_url=project_url,
            spaceapi_url=state.node_config()["spaceapi_url"],
            events_ical_url=state.node_config()["events_ical_url"],
            notify_url=state.notify_url(),
            propagation_cfg=state.propagation_config(),
            talkback_enabled=state.node_config()["talkback_enabled"],
            telemetry_cfg=_telemetry_cfg(),
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
