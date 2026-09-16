"""Reticulum Call plugin -- entry point.

Nothing to register on the backend: this plugin only provides "hook"
(a Call tab injected into the Reticulum page), and talks entirely to
the *reticulum* plugin's own backend -- POST /api/reticulum/call/
initiate, POST .../call/{hash}/hangup, and the WebSocket audio bridge
at .../call/{hash}/audio (all in plugins/apps/reticulum/backend/
call_routes.py + audio_call.py). Nothing here needs a route, a
service, or even Python at all -- register() still has to exist and be
callable, but has nothing to do, same as hello-world-hook.
"""

from __future__ import annotations


def register(reg) -> None:
    pass
