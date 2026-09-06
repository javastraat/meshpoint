"""In-memory Reticulum plugin config, seeded once from ``plugins.reticulum.*``
at ``register()`` time.

``plugins.reticulum`` is an opaque per-plugin dict (never core-schema
validated), the same shape core's ``AppConfig.reticulum`` dataclass has
today -- this plugin is being extracted from core, and Phase 4 hands the
user a migration diff moving their real ``reticulum:`` values here:

    plugins:
      reticulum:
        enabled: true
        display_name: "Meshpoint"
        reticulum_config_dir: data/reticulum/rns_config
        identity_path: data/reticulum/identity
        lxmf_storage_dir: data/reticulum/lxmf
        rnode_serial_port: ""
        rnode_frequency_hz: 869463000
        rnode_bandwidth_hz: 125000
        rnode_tx_power: 20
        rnode_spreading_factor: 8
        rnode_coding_rate: 5
        backbone_host: node.reticulumnet.nl
        backbone_port: 4242

The ``rnode_*`` / ``backbone_*`` fields are consumed by
``scripts/write_rnsd_config.py`` (rnsd's own interfaces), not by
``LxmfService`` -- they're held here so the Settings tab has a single
place to read/write them. Defaults below match what core's old
``ReticulumConfig`` dataclass used, so an unset key behaves identically.

``reticulum_config_dir`` MUST be the same directory ``rnsd`` uses (that's
why ``write_rnsd_config.py`` writes rnsd's config into it): the
shared-instance RPC channel authenticates per-configdir -- a mismatch
produces a real, reproducible "digest received was wrong" RPC error
(confirmed live). It deliberately is NOT ``~/.reticulum``: the
``meshpoint`` systemd user is ``--no-create-home``, so ``$HOME`` resolves
to a path that doesn't exist and RNS crashes trying to create storage
there.
"""

from __future__ import annotations

from typing import Any

_DEFAULTS: dict[str, Any] = {
    "display_name": "Meshpoint",
    "reticulum_config_dir": "data/reticulum/rns_config",
    "identity_path": "data/reticulum/identity",
    "lxmf_storage_dir": "data/reticulum/lxmf",
    "rnode_serial_port": "",
    "rnode_frequency_hz": 869_463_000,
    "rnode_bandwidth_hz": 125_000,
    "rnode_tx_power": 20,
    "rnode_spreading_factor": 8,
    "rnode_coding_rate": 5,
    "backbone_host": "node.reticulumnet.nl",
    "backbone_port": 4242,
    # NomadNet "Browse" tab: path/link timeout budget in seconds (request
    # gets 1.5x). 20 suits a TCP backbone; bump for multi-hop LoRa nodes.
    "nomad_timeout_s": 20,
}

_config: dict[str, Any] = dict(_DEFAULTS)


def init(config: dict) -> None:
    """Seed from ``reg.config`` (a copy of ``plugins.reticulum``). A missing
    or blank key falls back to core's original default -- a user-edited
    YAML typo must not crash the plugin."""
    global _config
    merged = dict(_DEFAULTS)
    for key in _DEFAULTS:
        value = config.get(key)
        if value is not None and value != "":
            merged[key] = value
    # rnode_serial_port is legitimately "" (not configured) -- take it verbatim.
    if "rnode_serial_port" in config:
        merged["rnode_serial_port"] = config.get("rnode_serial_port") or ""
    _config = merged


def display_name() -> str:
    return str(_config["display_name"])


def reticulum_config_dir() -> str:
    return str(_config["reticulum_config_dir"])


def identity_path() -> str:
    return str(_config["identity_path"])


def lxmf_storage_dir() -> str:
    return str(_config["lxmf_storage_dir"])


def to_dict() -> dict[str, Any]:
    return dict(_config)


# --- settings-tab writes ----------------------------------------------------

_ALLOWED_UPDATE_KEYS = frozenset(_DEFAULTS)  # never "enabled" -- that's the
# Settings -> Plugins toggle, same as every other plugin.


def set_config(updates: dict) -> None:
    """Merge settings-tab values (already validated by config_routes.py's
    pydantic model) into state and persist to ``plugins.reticulum``. A
    ``DapnetSerialSource``-style live effect isn't possible here -- the
    LxmfService reads these once at construction -- so, like every other
    plugin's config change, this takes effect on the next restart (and,
    for the RNode/backbone fields, an rnsd restart too)."""
    global _config
    merged = dict(_config)
    for key, value in updates.items():
        if key in _ALLOWED_UPDATE_KEYS:
            merged[key] = value
    _config = merged
    _persist()


def _current_saved_config() -> dict:
    """Read ``plugins.reticulum``'s CURRENT on-disk shape (not this
    module's load-time snapshot) so a settings save never clobbers a
    same-session Settings -> Plugins enable/disable toggle -- same
    reasoning as the DAPNET plugin's own state._current_saved_config()."""
    import yaml

    from src.config import _get_local_yaml_path  # noqa: SLF001 -- see docstring

    path = _get_local_yaml_path()
    if not path.exists():
        return {}
    with open(path) as fh:
        data = yaml.safe_load(fh) or {}
    section = data.get("plugins")
    if not isinstance(section, dict):
        return {}
    current = section.get("reticulum")
    return dict(current) if isinstance(current, dict) else {}


def _persist() -> None:
    from src.config import save_section_to_yaml

    current = _current_saved_config()
    current.update(to_dict())
    save_section_to_yaml("plugins", {"reticulum": current})
