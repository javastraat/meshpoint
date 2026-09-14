"""Reticulum Dashboard plugin -- entry point.

Nothing to register: this plugin only provides "sidebar" (a top-level
live-activity page), wired declaratively through plugin.toml's [sidebar]
table + its frontend script, not through PluginRegistry (see
plugins/apps/hello-world/backend/__init__.py for the same pattern).
register() still has to exist and be callable, but has nothing to do.

Deliberately backend-free: the page reads the reticulum plugin's own
already-public /api/reticulum/* endpoints and the shared dashboard
WebSocket (window.concentratorWS -> "reticulum_announce"/"reticulum_peer"
broadcasts) via plain fetch()/the existing WS singleton -- same cross-page
reuse the core Reticulum page itself does, no new routes needed. If the
reticulum plugin isn't enabled those fetches just fail and the page shows
its empty state (see reticulum_dashboard.js's own note on this).
"""

from __future__ import annotations


def register(reg) -> None:
    pass
