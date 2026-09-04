"""Hello World Hook plugin -- entry point.

Nothing to register: this plugin only provides "hook" (content injected
into another plugin's page), which is wired declaratively through
plugin.toml's [hook] table + its frontend script, not through
PluginRegistry (there's no reg.add_hook() -- see docs/PLUGINS.md).
register() still has to exist and be callable, but has nothing to do.
"""

from __future__ import annotations


def register(reg) -> None:
    pass
