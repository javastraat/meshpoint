"""Tests for the plugin listener-registry seam.

Pure Python -- src/api/listener_registry.py has no FastAPI import. Fake
listener objects stand in for the real RTL-SDR listener classes; all the
registry needs is an async ``stop()``. The create_app side (that the
built-in list + these registrations actually build and wire) is covered by
tests/test_create_app_listeners.py, which needs fastapi and runs on CI.
"""

from __future__ import annotations

import asyncio
import unittest

from src.api import listener_registry
from src.api.listener_registry import ListenerSpec


class _Fake:
    def __init__(self, name: str) -> None:
        self.name = name
        self.stopped = 0

    async def stop(self) -> None:
        self.stopped += 1


class _Boom(_Fake):
    async def stop(self) -> None:
        raise RuntimeError("stop blew up")


class TestListenerRegistry(unittest.TestCase):
    def setUp(self) -> None:
        listener_registry.reset()

    def tearDown(self) -> None:
        listener_registry.reset()

    def test_register_and_read_back(self) -> None:
        spec = ListenerSpec("x", lambda: _Fake("x"))
        listener_registry.register_listener(spec)
        self.assertEqual(listener_registry.plugin_specs(), [spec])

    def test_plugin_specs_returns_a_copy(self) -> None:
        listener_registry.register_listener(ListenerSpec("x", lambda: _Fake("x")))
        listener_registry.plugin_specs().clear()
        self.assertEqual(len(listener_registry.plugin_specs()), 1)

    def test_start_all_builds_then_wires_builtins_before_plugins(self) -> None:
        seen: list[str] = []

        def spec(name: str) -> ListenerSpec:
            return ListenerSpec(
                name,
                lambda: _Fake(name),
                lambda obj: seen.append(obj.name),
            )

        listener_registry.register_listener(spec("plug"))
        listener_registry.start_all([spec("core-a"), spec("core-b")])

        self.assertEqual(seen, ["core-a", "core-b", "plug"])
        self.assertEqual(
            [n for n, _ in listener_registry.live()], ["core-a", "core-b", "plug"],
        )

    def test_tuple_build_wires_once_with_the_tuple(self) -> None:
        got = []
        trio = (_Fake("a"), _Fake("b"), _Fake("c"))
        listener_registry.start_all([
            ListenerSpec("trio", lambda: trio, got.append),
        ])
        self.assertEqual(got, [trio])

    def test_stop_all_stops_every_listener_including_tuple_members(self) -> None:
        one = _Fake("one")
        trio = (_Fake("a"), _Fake("b"), _Fake("c"))
        listener_registry.start_all([
            ListenerSpec("one", lambda: one),
            ListenerSpec("trio", lambda: trio),
        ])
        asyncio.run(listener_registry.stop_all())
        self.assertEqual(one.stopped, 1)
        self.assertEqual([m.stopped for m in trio], [1, 1, 1])
        self.assertEqual(listener_registry.live(), [])

    def test_stop_all_continues_past_a_raising_listener(self) -> None:
        first = _Fake("first")
        last = _Fake("last")
        listener_registry.start_all([
            ListenerSpec("first", lambda: first),
            ListenerSpec("boom", lambda: _Boom("boom")),
            ListenerSpec("last", lambda: last),
        ])
        asyncio.run(listener_registry.stop_all())
        # reverse order: last stopped, boom raised (swallowed), first stopped
        self.assertEqual(first.stopped, 1)
        self.assertEqual(last.stopped, 1)

    def test_reset_clears_specs_and_live(self) -> None:
        listener_registry.register_listener(ListenerSpec("x", lambda: _Fake("x")))
        listener_registry.start_all([ListenerSpec("c", lambda: _Fake("c"))])
        listener_registry.reset()
        self.assertEqual(listener_registry.plugin_specs(), [])
        self.assertEqual(listener_registry.live(), [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
