"""Tests for src.plugins.registry.PluginRegistry.

Pure Python -- route_registry / listener_registry / PluginRegistry are all
FastAPI-free.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from src.api import listener_registry, route_registry, service_registry
from src.plugins.manifest import PluginManifest
from src.plugins.registry import PluginRegistry, PluginRegistryError


def _manifest(*provides: str) -> PluginManifest:
    return PluginManifest(
        name="acars",
        version="0.1.0",
        api_version=1,
        provides=tuple(provides),
        apt=(),
        setup=None,
        check=None,
        description="",
        homepage="",
        author="",
        frontend_scripts=(),
        frontend_styles=(),
        path=Path("/tmp/acars"),
    )


class TestPluginRegistry(unittest.TestCase):
    def setUp(self) -> None:
        route_registry.reset()
        listener_registry.reset()
        service_registry.reset()

    def tearDown(self) -> None:
        route_registry.reset()
        listener_registry.reset()
        service_registry.reset()

    def test_config_is_a_copy(self) -> None:
        src = {"enabled": True, "gain": 34}
        reg = PluginRegistry(_manifest("routes"), src)
        reg.config["gain"] = 99
        self.assertEqual(src["gain"], 34)
        self.assertEqual(reg.name, "acars")

    def test_add_router_delegates_when_declared(self) -> None:
        reg = PluginRegistry(_manifest("routes"), {})
        sentinel = object()
        reg.add_router(sentinel, public=True)
        specs = route_registry.registered()
        self.assertEqual(len(specs), 1)
        self.assertIs(specs[0].router, sentinel)
        self.assertTrue(specs[0].public)

    def test_add_listener_delegates_when_declared(self) -> None:
        reg = PluginRegistry(_manifest("listener"), {})
        build = lambda: None  # noqa: E731
        reg.add_listener("x", build, None)
        specs = listener_registry.plugin_specs()
        self.assertEqual(len(specs), 1)
        self.assertEqual(specs[0].name, "x")
        self.assertIs(specs[0].build, build)

    def test_add_service_delegates_when_declared(self) -> None:
        reg = PluginRegistry(_manifest("service"), {})
        build = lambda ctx: None  # noqa: E731
        reg.add_service("reticulum", build, None)
        specs = service_registry.plugin_specs()
        self.assertEqual(len(specs), 1)
        self.assertEqual(specs[0].name, "reticulum")
        self.assertIs(specs[0].build, build)

    def test_add_service_rejected_when_not_in_provides(self) -> None:
        reg = PluginRegistry(_manifest("routes"), {})
        with self.assertRaises(PluginRegistryError):
            reg.add_service("reticulum", lambda ctx: None)
        self.assertEqual(service_registry.plugin_specs(), [])

    def test_add_router_rejected_when_not_in_provides(self) -> None:
        reg = PluginRegistry(_manifest("listener"), {})
        with self.assertRaises(PluginRegistryError):
            reg.add_router(object())
        self.assertEqual(route_registry.registered(), [])

    def test_add_listener_rejected_when_not_in_provides(self) -> None:
        reg = PluginRegistry(_manifest("routes"), {})
        with self.assertRaises(PluginRegistryError):
            reg.add_listener("x", lambda: None)
        self.assertEqual(listener_registry.plugin_specs(), [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
