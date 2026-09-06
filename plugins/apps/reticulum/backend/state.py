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
``LxmfService`` -- they're held here so Phase 2's settings tab has a
single place to read/write them. Defaults below mirror core's
``ReticulumConfig`` exactly so an unset key behaves identically.
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
