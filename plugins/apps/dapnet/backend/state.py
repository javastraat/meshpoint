"""In-memory DAPNET plugin state: configured devices + capcode filters.

Seeded once from ``plugins.dapnet.*`` config at register() time (an opaque
dict, never core-schema-validated, same as every other plugin's own
``plugins.<id>`` sub-schema). Replaces two separate core config sections
this plugin used to read directly -- ``capture.pocsag_serial`` (device
connection info) and ``dapnet.*`` (capcode filters + poll interval) --
combined into one ``plugins.dapnet.*`` shape:

    plugins:
      dapnet:
        enabled: true
        status_poll_interval_s: 60
        blacklist_capcodes: [200, 208, 216, 224]
        ignore_capcodes: [4512, 4520]
        devices:
          - serial_port: /dev/ttyUSB2
            serial_baud: 115200
            label: ttgo
            name: "POCSAG TTGO"
"""

from __future__ import annotations

from typing import Any, Optional

_DEFAULT_BLACKLIST_CAPCODES = [200, 208, 216, 224]
_DEFAULT_IGNORE_CAPCODES = [4512, 4520]
_DEFAULT_STATUS_POLL_INTERVAL_S = 60

_devices: list[dict] = []
_blacklist_capcodes: list[int] = list(_DEFAULT_BLACKLIST_CAPCODES)
_ignore_capcodes: list[int] = list(_DEFAULT_IGNORE_CAPCODES)
_status_poll_interval_s: int = _DEFAULT_STATUS_POLL_INTERVAL_S


def init(config: dict) -> None:
    """Seed state from ``reg.config`` (a copy of ``plugins.dapnet``) at
    register() time."""
    global _devices, _blacklist_capcodes, _ignore_capcodes, _status_poll_interval_s
    _devices = [dict(d) for d in (config.get("devices") or [])]
    _blacklist_capcodes = list(config.get("blacklist_capcodes") or _DEFAULT_BLACKLIST_CAPCODES)
    _ignore_capcodes = list(config.get("ignore_capcodes") or _DEFAULT_IGNORE_CAPCODES)
    _status_poll_interval_s = int(
        config.get("status_poll_interval_s") or _DEFAULT_STATUS_POLL_INTERVAL_S
    )


def devices() -> list[dict]:
    return [dict(d) for d in _devices]


def status_poll_interval_s() -> int:
    return _status_poll_interval_s


def blacklist_capcodes() -> list[int]:
    return list(_blacklist_capcodes)


def ignore_capcodes() -> list[int]:
    return list(_ignore_capcodes)


def to_dict() -> dict:
    return {
        "devices": _devices,
        "blacklist_capcodes": _blacklist_capcodes,
        "ignore_capcodes": _ignore_capcodes,
        "status_poll_interval_s": _status_poll_interval_s,
    }


def set_filters(
    *, blacklist_capcodes: Optional[list[int]] = None,
    ignore_capcodes: Optional[list[int]] = None,
) -> None:
    """Update the capcode filter lists and persist. ``None`` leaves that
    list unchanged (a settings-tab save that only touched one field)."""
    global _blacklist_capcodes, _ignore_capcodes
    if blacklist_capcodes is not None:
        _blacklist_capcodes = list(blacklist_capcodes)
    if ignore_capcodes is not None:
        _ignore_capcodes = list(ignore_capcodes)
    _persist()


def set_devices(devices: list[dict]) -> None:
    """Replace the device list and persist. Takes effect on the next
    restart, same as every other plugin's config change."""
    global _devices
    _devices = [dict(d) for d in devices]
    _persist()


def set_status_poll_interval_s(seconds: int) -> None:
    """Change the status-poll interval and persist. A DapnetSerialSource
    reads this once at construction, so -- like set_devices() -- this
    only takes effect on the next restart."""
    global _status_poll_interval_s
    _status_poll_interval_s = int(seconds)
    _persist()


def tier(packet: Any) -> Optional[str]:
    """Classify a decoded DAPNET packet -- "ignore" (pure noise, dropped
    entirely, not even shown live) or "blacklist" (shown live -- confirms
    the decoder/network are still alive -- but never persisted or acted
    on). Mirrors what src.coordinator._dapnet_capcode_tier used to
    hardcode against core's own AppConfig.dapnet.*."""
    payload = packet.decoded_payload or {}
    capcode = payload.get("capcode")
    if capcode in _ignore_capcodes:
        return "ignore"
    if capcode in _blacklist_capcodes:
        return "blacklist"
    return None


def _current_saved_config() -> dict:
    """Read plugins.dapnet's CURRENT on-disk shape (not this module's own
    load-time snapshot) so a settings save here never clobbers a
    same-session Settings -> Plugins enable/disable toggle (a separate,
    later write to the same local.yaml section) with a stale cached
    value -- save_section_to_yaml's own merge is a shallow dict.update()
    per section, so writing only {"dapnet": to_dict()} would otherwise
    silently wipe out "enabled" if it changed after this module's own
    init() ran."""
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
    current = section.get("dapnet")
    return dict(current) if isinstance(current, dict) else {}


def _persist() -> None:
    from src.config import save_section_to_yaml

    current = _current_saved_config()
    current.update(to_dict())
    save_section_to_yaml("plugins", {"dapnet": current})
