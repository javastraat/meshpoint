"""Tests for the plugin service-registry seam.

Pure Python -- src/api/service_registry.py has no FastAPI import. Fake
services (an object with async start()/stop()) stand in for real ones
(LxmfService et al); the registry only cares that build() returns
something awaitable-shaped, or None to opt out. The create_app side
(start_all() runs from lifespan right after pipeline.start(), stop_all()
in the shutdown block) is integration-level and needs fastapi, so it
isn't covered here.
"""

from __future__ import annotations

import asyncio
import unittest

from src.api import service_registry
from src.api.service_registry import ServiceContext, ServiceSpec


class _FakeService:
    def __init__(self, name: str, *, fail_stop: bool = False) -> None:
        self.name = name
        self.started = False
        self.stopped = False
        self._fail_stop = fail_stop

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        if self._fail_stop:
            raise RuntimeError("boom")
        self.stopped = True


def _ctx() -> ServiceContext:
    return ServiceContext(pipeline=object(), ws_manager=object(), config=object())


class TestServiceRegistry(unittest.TestCase):
    def setUp(self) -> None:
        service_registry.reset()

    def tearDown(self) -> None:
        service_registry.reset()

    def test_register_and_read_back(self) -> None:
        spec = ServiceSpec("x", lambda ctx: _FakeService("x"))
        service_registry.register_service(spec)
        self.assertEqual(service_registry.plugin_specs(), [spec])

    def test_plugin_specs_returns_a_copy(self) -> None:
        service_registry.register_service(
            ServiceSpec("x", lambda ctx: _FakeService("x")),
        )
        service_registry.plugin_specs().clear()
        self.assertEqual(len(service_registry.plugin_specs()), 1)

    def test_start_all_builds_wires_and_starts_in_order(self) -> None:
        seen_ctx = []
        wired = []
        ctx = _ctx()
        service_registry.register_service(
            ServiceSpec(
                "a",
                lambda c: (seen_ctx.append(c) or _FakeService("a")),
                wire=lambda svc, c: wired.append((svc.name, c)),
            ),
        )
        service_registry.register_service(
            ServiceSpec("b", lambda c: _FakeService("b")),
        )
        asyncio.run(service_registry.start_all(ctx))

        live = service_registry.live()
        self.assertEqual([name for name, _ in live], ["a", "b"])
        self.assertTrue(all(svc.started for _, svc in live))
        self.assertEqual(seen_ctx, [ctx])
        self.assertEqual(wired, [("a", ctx)])

    def test_build_returning_none_opts_the_service_out(self) -> None:
        service_registry.register_service(ServiceSpec("skip", lambda c: None))
        service_registry.register_service(
            ServiceSpec("keep", lambda c: _FakeService("keep")),
        )
        asyncio.run(service_registry.start_all(_ctx()))
        self.assertEqual([name for name, _ in service_registry.live()], ["keep"])

    def test_a_service_raising_on_start_does_not_abort_the_rest(self) -> None:
        class _Boom(_FakeService):
            async def start(self):
                raise OSError(98, "Address already in use")

        service_registry.register_service(ServiceSpec("boom", lambda c: _Boom("boom")))
        service_registry.register_service(
            ServiceSpec("ok", lambda c: _FakeService("ok")),
        )
        # must not raise
        asyncio.run(service_registry.start_all(_ctx()))
        live = dict(service_registry.live())
        self.assertTrue(live["ok"].started)  # the healthy one still came up

    def test_a_build_raising_does_not_abort_the_rest(self) -> None:
        def _bad_build(_c):
            raise RuntimeError("bad config")

        service_registry.register_service(ServiceSpec("bad", _bad_build))
        service_registry.register_service(
            ServiceSpec("ok", lambda c: _FakeService("ok")),
        )
        asyncio.run(service_registry.start_all(_ctx()))
        self.assertEqual([n for n, _ in service_registry.live()], ["ok"])

    def test_start_all_is_idempotent_per_call(self) -> None:
        service_registry.register_service(
            ServiceSpec("x", lambda c: _FakeService("x")),
        )
        asyncio.run(service_registry.start_all(_ctx()))
        asyncio.run(service_registry.start_all(_ctx()))
        # Second call clears _live first -- no accumulation.
        self.assertEqual(len(service_registry.live()), 1)

    def test_stop_all_survives_a_raising_stop_and_clears_live(self) -> None:
        good = _FakeService("good")
        bad = _FakeService("bad", fail_stop=True)

        service_registry.register_service(ServiceSpec("good", lambda c: good))
        service_registry.register_service(ServiceSpec("bad", lambda c: bad))
        asyncio.run(service_registry.start_all(_ctx()))
        asyncio.run(service_registry.stop_all())

        # bad raised but good still got stopped, and _live is cleared.
        self.assertTrue(good.stopped)
        self.assertEqual(service_registry.live(), [])

    def test_reset_clears_specs_and_live(self) -> None:
        service_registry.register_service(
            ServiceSpec("x", lambda c: _FakeService("x")),
        )
        asyncio.run(service_registry.start_all(_ctx()))
        service_registry.reset()
        self.assertEqual(service_registry.plugin_specs(), [])
        self.assertEqual(service_registry.live(), [])
        # stop_all() after a reset() is a no-op, not a crash.
        asyncio.run(service_registry.stop_all())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
