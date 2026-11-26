"""Every write route under /api/messages is admin-only (upstream b91d994b).

POST /conversation/{id}/read had no require_admin: a viewer opening a chat
marked it read for everyone (TODO.md item 37a).
"""

from __future__ import annotations

import unittest

from src.api.auth.dependencies import require_admin
from src.api.routes import messages


def _dependency_calls(route) -> set:
    calls, stack = set(), list(route.dependant.dependencies)
    while stack:
        dep = stack.pop()
        calls.add(dep.call)
        stack.extend(dep.dependencies)
    return calls


class MessagesWriteRoutesTest(unittest.TestCase):
    def test_all_write_routes_require_admin(self):
        writes = [r for r in messages.router.routes
                  if set(getattr(r, "methods", ())) & {"POST", "PUT", "PATCH", "DELETE"}]
        self.assertTrue(any(r.path.endswith("/read") for r in writes))
        for route in writes:
            with self.subTest(route=f"{sorted(route.methods)} {route.path}"):
                self.assertIn(require_admin, _dependency_calls(route))


if __name__ == "__main__":
    unittest.main()
