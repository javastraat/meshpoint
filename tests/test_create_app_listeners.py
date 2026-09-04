"""Regression guard for src.api.server's built-in listener list.

Mirrors tests/test_create_app_routers.py: nothing else asserts that every
RTL-SDR listener still gets built and wired into its router at startup, so
a dropped entry would ship silently. Needs fastapi (the listener classes'
import chain + a TestClient for the status routes), so it runs on CI / the
Pi, not on the fastapi-less dev Mac.

It drives listener_registry.start_all() directly rather than create_app()
(whose lifespan needs a real concentrator + DB) -- the same shortcut the
router test takes.
"""

from __future__ import annotations

import asyncio
import unittest

from src.api import listener_registry
from src.api.listener_registry import ListenerSpec
from src.api.server import _BUILTIN_LISTENERS

# Empty -- Radio was the last built-in RTL-SDR listener, and it moved out
# to plugins/apps/radio/ the same way every other one already had
# (Pagers/P2000/POCSAG/RTL433/ADS-B/ACARS/DAB+). Kept as a named constant
# (rather than inlining `[]` below) so a future built-in re-added here
# updates one obvious place, matching the convention every prior version
# of this test already used.
_EXPECTED_NAMES: list[str] = []


class TestBuiltinListenerList(unittest.TestCase):
    def tearDown(self) -> None:
        listener_registry.reset()

    def test_names_and_shape(self) -> None:
        self.assertEqual([s.name for s in _BUILTIN_LISTENERS], _EXPECTED_NAMES)
        for s in _BUILTIN_LISTENERS:
            self.assertIsInstance(s, ListenerSpec)
            self.assertTrue(callable(s.build))
            self.assertTrue(callable(s.wire))

    def test_start_all_with_zero_builtins_is_a_no_op(self) -> None:
        listener_registry.start_all(_BUILTIN_LISTENERS)
        try:
            self.assertEqual(listener_registry.live(), [])
        finally:
            asyncio.run(listener_registry.stop_all())

    def test_plugin_listener_is_built_and_wired_after_builtins(self) -> None:
        built = []
        listener_registry.register_listener(
            ListenerSpec(
                "plugtest",
                lambda: built.append("build") or _NoopListener(),
                lambda obj: built.append("wire"),
            )
        )
        listener_registry.start_all(_BUILTIN_LISTENERS)
        try:
            self.assertEqual(built, ["build", "wire"])
            self.assertEqual(listener_registry.live()[-1][0], "plugtest")
        finally:
            asyncio.run(listener_registry.stop_all())


class _NoopListener:
    async def stop(self) -> None:
        pass


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
