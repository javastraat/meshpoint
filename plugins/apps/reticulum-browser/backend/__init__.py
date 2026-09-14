"""Reticulum Browser plugin -- entry point.

Nothing to register: this plugin only provides "sidebar" (a top-level
page), wired declaratively through plugin.toml's [sidebar] table + its
frontend script, not through PluginRegistry -- same minimal, backend-free
pattern as meshpoint core's own hello-world/reticulum-dashboard plugins.
register() still has to exist and be callable, but has nothing to do.

Reads the reticulum plugin's already-public /api/reticulum/nomad/*
endpoints (GET /nodes, POST /page, POST /file) via plain fetch() from the
frontend -- no new backend routes needed here at all.
"""

from __future__ import annotations


def register(reg) -> None:
    pass
