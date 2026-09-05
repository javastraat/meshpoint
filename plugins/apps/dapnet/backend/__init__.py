"""DAPNET plugin -- entry point.

Meshpoint's plugin loader imports this module and calls ``register(reg)``
when ``plugins.dapnet.enabled: true`` is set -- opt-in, same as every
other shipped plugin (ACARS/RTL433/etc; `locked = true` in
``plugin.toml`` only means "can't be deleted from Settings -> Plugins",
not "default-on"). See ``plugins/apps/dapnet/plugin.toml`` and
``docs/CONFIGURATION.md`` (Plugins).

Unlike the RTL-SDR family (a "listener" built idle, started on demand by
its own ``/start`` route), DAPNET is a real ``CaptureSource`` joining the
core packet pipeline unconditionally at boot (``"capture"``) with its own
protocol identity (``"protocol"``) -- see ``src.api.capture_source_registry``
/ ``src.api.protocol_registry``. ``wire()`` runs once ``pipeline.start()``
has completed, since ``pipeline.packet_repo`` doesn't exist before then.

Imports are deferred into ``register()`` so ``backend.listener``/``decode``/
``state`` (stdlib + serial only) can be imported for their own tests
without pulling in FastAPI.
"""

from __future__ import annotations


def register(reg) -> None:
    from . import config_routes, decode, firmware_routes, routes, settings_routes, state
    from .listener import DapnetSerialSource

    state.init(reg.config)

    reg.add_router(routes.router)
    reg.add_router(config_routes.router)
    reg.add_router(firmware_routes.router)
    reg.add_router(settings_routes.router)

    def build() -> tuple[DapnetSerialSource, ...]:
        return tuple(
            DapnetSerialSource(
                serial_port=dev.get("serial_port"),
                serial_baud=dev.get("serial_baud", 115200),
                label=dev.get("label", ""),
                status_poll_interval_s=state.status_poll_interval_s(),
            )
            for dev in state.devices()
        )

    def wire(sources, pipeline) -> None:
        routes.init_routes(pipeline.packet_repo)
        config_routes.init_routes(dapnet_sources=list(sources))
        firmware_routes.init_routes(dapnet_sources=list(sources))
        settings_routes.init_routes(
            dapnet_sources=list(sources), packet_repo=pipeline.packet_repo,
        )

    reg.add_capture_source("dapnet", build, wire)
    reg.add_protocol(
        "dapnet", capture_prefix="dapnet",
        adapt=lambda raw: decode.adapt_event(raw.payload, signal=raw.signal),
        tier=state.tier,
    )
