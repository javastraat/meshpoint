"""Tests for the plugin router-registry seam.

Pure Python -- src/api/route_registry.py has no FastAPI import, and
register_router stores whatever object it is handed, so a sentinel
stands in for an APIRouter here. The create_app side (that the built-in
list + these registrations actually mount) is covered by
tests/test_create_app_routers.py, which needs fastapi and runs on CI.
"""

from __future__ import annotations

import unittest

from src.api import route_registry


class _Sentinel:
    def __init__(self, name: str) -> None:
        self.name = name


class TestRouteRegistry(unittest.TestCase):
    def setUp(self) -> None:
        route_registry.reset()

    def tearDown(self) -> None:
        route_registry.reset()

    def test_register_and_read_back(self) -> None:
        r = _Sentinel("acars")
        route_registry.register_router(r, public=True)
        specs = route_registry.registered()
        self.assertEqual(len(specs), 1)
        self.assertIs(specs[0].router, r)
        self.assertTrue(specs[0].public)

    def test_default_is_protected(self) -> None:
        route_registry.register_router(_Sentinel("x"))
        self.assertFalse(route_registry.registered()[0].public)

    def test_order_preserved(self) -> None:
        for n in ("a", "b", "c"):
            route_registry.register_router(_Sentinel(n))
        self.assertEqual(
            [s.router.name for s in route_registry.registered()], ["a", "b", "c"],
        )

    def test_registered_returns_a_copy(self) -> None:
        route_registry.register_router(_Sentinel("a"))
        route_registry.registered().clear()
        self.assertEqual(len(route_registry.registered()), 1)

    def test_reset_empties(self) -> None:
        route_registry.register_router(_Sentinel("a"))
        route_registry.reset()
        self.assertEqual(route_registry.registered(), [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
