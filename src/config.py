from __future__ import annotations

import dataclasses
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)


# Band-start frequencies (MHz) for the Meshtastic slot formula
# freq = freqStart + BW/2000 + (slot-1) * BW/1000
# Values match _REGION_BAND_LIMITS_HZ in hal/concentrator_config.py.
_REGION_FREQ_START: dict[str, float] = {
    "US":     902.0,
    "EU_868": 863.0,
    "ANZ":    915.0,
    "IN":     865.0,
    "KR":     920.0,
    "SG_923": 917.0,
}

# Regional default frequencies used when neither frequency_mhz nor slot
# is set. Values match REGION_DEFAULTS in radio/presets.py.
_REGION_DEFAULT_FREQ: dict[str, float] = {
    "US":     906.875,
    "EU_868": 869.525,
    "ANZ":    916.0,
    "IN":     865.4625,
    "KR":     921.9,
    "SG_923": 923.0,
}


@dataclass
class RadioConfig:
    region: str = "US"
    frequency_mhz: Optional[float] = None  # resolved at load time; wins over slot
    slot: Optional[int] = None             # Meshtastic 1-indexed slot; used when frequency_mhz absent
    spreading_factor: int = 11
    bandwidth_khz: float = 250.0
    coding_rate: str = "4/5"
    sync_word: int = 0x2B
    preamble_length: int = 16
    tx_power_dbm: int = 22
    # Periodic SX1302 spectral scan to measure ambient noise floor
    # directly. Each scan briefly pauses RX on the primary channel
    # (~50 ms). Default 60 s gives ~0.08% downtime; raise for less.
    # Set to 0 to disable (falls back to packet-derived noise floor).
    spectral_scan_interval_seconds: float = 60.0
    # Periodic full-band sweep for the Hardware page spectrum card
    # (one spectral scan per 100 kHz step across the region band,
    # a few seconds per sweep). 0 disables automatic sweeps; the
    # dashboard "Sweep now" button still works.
    spectrum_sweep_interval_seconds: float = 300.0
    # SPI device for the SX1261 companion radio used by spectral
    # scan. Empty string disables the SX1261 init step entirely
    # (default; spectral scan stays unavailable, packet-derived
    # noise floor remains in use).
    #
    # On RAK2287 / RAK5146 / SenseCap M1 the SX1261 sits behind the
    # SX1302 SPI router, not on a Pi-visible bus. Setting
    # ``/dev/spidev0.1`` there usually fails ``lgw_sx1261_setconf``
    # and can block ``lgw_start``. Leave empty on fleet hardware;
    # only set on carriers that expose SX1261 on a dedicated CE line
    # (Semtech reference kit, custom boards). See CONFIGURATION.md.
    sx1261_spi_path: str = ""
    # Emergency pager project: enables the concentrator's dedicated FSK
    # channel (ch9), independent hardware from every LoRa channel above.
    # There's no real pager protocol/firmware yet, so this only proves
    # reception works. Default off: nothing should start listening on a
    # new channel without an explicit opt-in.
    pager_enabled: bool = False
    # Defaults match the values chosen for the ETSI EU868 "sub-band P"
    # high-power window (869.40-869.65 MHz) -- see concentrator_source.py
    # and project memory for how these were picked. pager_frequency_mhz
    # and pager_sync_word(_size) are user-editable from Configuration ->
    # Radio (PUT /api/config/radio/pager), which validates the frequency
    # against RF1's real anchor before saving.
    pager_frequency_mhz: float = 869.4625
    pager_sync_word: int = 0x946437
    pager_sync_word_size: int = 3
    # Deliberately NOT exposed in that same UI/route: the validated
    # frequency range only makes physical sense on whichever RF chain
    # this is set to. Changing it away from the chain whose anchor
    # frequency is actually close to pager_frequency_mhz will make
    # configure_fsk_channel()'s IF offset too large for the hardware to
    # accept -- a YAML-only escape hatch for a genuine channel re-plan.
    pager_rf_chain: int = 1
    # This device's own POCSAG-style capcode -- the "from" on every
    # message Meshpoint sends on the pager channel, and the value
    # compared against an incoming message's "from" to detect and hide
    # the concentrator's own TX leaking straight back into its own RX
    # (confirmed live: near-field self-coupling, RSSI far too strong to
    # be a real remote device). 0 = unset; the send route refuses to
    # transmit without a real one configured, same reasoning as
    # pocsag_companion.ino requiring a callsign before it will key up.
    pager_capcode: int = 0


@dataclass
class LoRaWANConfig:
    # DevEUI (colon-formatted, e.g. "70:B3:D5:7E:D0:07:8B:FD", matching
    # lorawan_decoder.py's own _eui_str() output) -> {"app_key": hex32,
    # "nwk_key": hex32, "payload_fields": [...]} -- app_key/nwk_key are
    # the OTAA root keys from TTN Console's device registration page (NOT
    # the derived per-session AppSKey, which changes on every rejoin and
    # is never configured directly here -- see lorawan_keystore.py for
    # why: it's derived live from each device's own captured Join-Accept
    # instead). payload_fields is optional -- this device's own
    # declarative FRMPayload field list (see lorawan_payload_formats.py),
    # e.g.:
    #   payload_fields:
    #     - name: temperature_c
    #       type: int16_be
    #       scale: 0.01
    # Same shape/precedent as meshtastic.channel_keys/meshcore.channel_keys
    # below, other than payload_fields being a list, not a string.
    devices: dict[str, dict] = field(default_factory=dict)


@dataclass
class MeshtasticConfig:
    default_key_b64: str = "AQ=="
    primary_channel_name: str = "LongFast"
    channel_keys: dict[str, str] = field(default_factory=dict)


@dataclass
class MeshcoreConfig:
    default_key_b64: str = ""
    channel_keys: dict[str, str] = field(default_factory=dict)
    private_channels: list = field(default_factory=list)
    # Desired companion advert name. When set, the dashboard rename
    # path writes here, and the USB capture source re-applies it on
    # every connect via MeshCoreTxClient.set_companion_name. Leaving
    # this empty means "trust whatever name is on the companion's
    # flash" -- the v0.7.4 behavior.
    companion_name: Optional[str] = None


@dataclass
class MeshcoreUsbConfig:
    """MeshCore USB companion radio -- one entry per physical device."""

    serial_port: Optional[str] = None
    baud_rate: int = 115200
    auto_detect: bool = True
    label: str = ""   # e.g. "868" or "433" — shown in logs and capture_source tag
    # Desired advert name for THIS companion. Mirrors MeshcoreConfig.companion_name
    # above, just per-device instead of mesh-wide -- each companion is a
    # physically separate radio with its own identity. Re-applied on every
    # connect by this companion's own capture source.
    companion_name: Optional[str] = None


_MESHCORE_USB_FIELDS: frozenset[str] = frozenset(
    {"serial_port", "baud_rate", "auto_detect", "label", "companion_name"}
)


def _coerce_meshcore_usb(value) -> list[MeshcoreUsbConfig]:
    """Accept legacy single-dict or new list-of-dicts and return a list.

    Legacy local.yaml::

        capture:
          meshcore_usb:
            serial_port: /dev/ttyACM0
            auto_detect: true

    New multi-companion format::

        capture:
          meshcore_usb:
            - serial_port: /dev/ttyACM0
              label: "868"
            - serial_port: /dev/ttyACM1
              label: "433"
    """
    def _from_dict(d: dict) -> MeshcoreUsbConfig:
        return MeshcoreUsbConfig(**{k: v for k, v in d.items() if k in _MESHCORE_USB_FIELDS})

    if isinstance(value, dict):
        return [_from_dict(value)]
    if isinstance(value, list):
        return [_from_dict(d) for d in value if isinstance(d, dict)]
    return [MeshcoreUsbConfig()]


@dataclass
class SerialDeviceConfig:
    """Meshtastic USB serial radio -- one entry per physical device.

    Optional: single-stick setups use the legacy ``capture.serial_port`` /
    ``capture.serial_baud`` scalar fields instead. This list is only needed
    when more than one Meshtastic USB stick is connected at once (e.g. one
    on 433 MHz, one on 868 MHz).
    """

    serial_port: Optional[str] = None
    serial_baud: int = 115200
    label: str = ""   # e.g. "433" or "868" — shown in logs and capture_source tag
    # Desired identity for THIS stick, applied once at connect (start()).
    # Unlike MeshCore's companion_name, there's no reconnect-callback
    # mechanism to re-apply this live (SerialCaptureSource has no
    # auto-reconnect loop) -- a swapped-in replacement stick picks up
    # these values on the next service restart, matching this card's
    # existing "Requires a service restart after changes" convention.
    long_name: Optional[str] = None
    short_name: Optional[str] = None


_SERIAL_DEVICE_FIELDS: frozenset[str] = frozenset(
    {"serial_port", "serial_baud", "label", "long_name", "short_name"}
)


def _coerce_serial_devices(value) -> list[SerialDeviceConfig]:
    """Parse the multi-device ``capture.serial`` list.

    capture:
      serial:
        - serial_port: /dev/ttyUSB0
          label: "433"
        - serial_port: /dev/ttyUSB1
          label: "868"

    Only a list is accepted here -- the single-device case stays on the
    legacy ``capture.serial_port`` / ``serial_baud`` scalar fields, which
    are untouched for backward compatibility. Anything else (missing key,
    wrong type) yields an empty list so callers fall back to those scalars.
    """
    def _from_dict(d: dict) -> SerialDeviceConfig:
        return SerialDeviceConfig(**{k: v for k, v in d.items() if k in _SERIAL_DEVICE_FIELDS})

    if isinstance(value, list):
        return [_from_dict(d) for d in value if isinstance(d, dict)]
    return []


@dataclass
class PocsagSerialDeviceConfig:
    """POCSAG companion (``extra/pocsag_companion``) -- one entry per board.

    Connection info only: callsign, screen timeout, and everything else
    protocol-level is configured on the device's own WiFi web dashboard
    (``pocsag-companion.local``), not here. No identity/advert concept --
    unlike the Meshtastic/MeshCore companions, this board isn't itself a
    mesh node with a nameable identity.
    """

    serial_port: Optional[str] = None
    serial_baud: int = 115200
    label: str = ""   # e.g. "ttgo" or "heltec" — shown in logs and capture_source tag
    name: str = ""    # free-text display name shown in the dashboard UI


_POCSAG_SERIAL_DEVICE_FIELDS: frozenset[str] = frozenset(
    {"serial_port", "serial_baud", "label", "name"}
)


def _coerce_pocsag_serial_devices(value) -> list[PocsagSerialDeviceConfig]:
    """Parse the multi-device ``capture.pocsag_serial`` list (same shape as ``serial``)."""
    def _from_dict(d: dict) -> PocsagSerialDeviceConfig:
        return PocsagSerialDeviceConfig(
            **{k: v for k, v in d.items() if k in _POCSAG_SERIAL_DEVICE_FIELDS}
        )

    if isinstance(value, list):
        return [_from_dict(d) for d in value if isinstance(d, dict)]
    return []


@dataclass
class RfEnvCompanionDeviceConfig:
    """RF Environment companion (``extra/rfenv_companion``) -- one entry per
    board. A Heltec V3 with its own SX1262, polled over USB serial for a
    real ambient-RSSI histogram -- the fallback for boards (e.g. RAK2287)
    confirmed to have no SX1261, where a real hardware spectral scan is
    otherwise never possible. See ``RfEnvCompanionScanService``.
    """

    serial_port: Optional[str] = None
    serial_baud: int = 115200
    label: str = ""   # shown in logs
    name: str = ""    # free-text display name
    nb_scan: int = 512  # samples per scan; lower than the real HAL's 1024
                         # default since this device physically retunes and
                         # samples over a serial round-trip, not near-instant
                         # in-silicon sampling


_RFENV_COMPANION_DEVICE_FIELDS: frozenset[str] = frozenset(
    {"serial_port", "serial_baud", "label", "name", "nb_scan"}
)


def _coerce_rfenv_companion_devices(value) -> list[RfEnvCompanionDeviceConfig]:
    """Parse the multi-device ``capture.rfenv_companion`` list (same shape as ``pocsag_serial``)."""
    def _from_dict(d: dict) -> RfEnvCompanionDeviceConfig:
        return RfEnvCompanionDeviceConfig(
            **{k: v for k, v in d.items() if k in _RFENV_COMPANION_DEVICE_FIELDS}
        )

    if isinstance(value, list):
        return [_from_dict(d) for d in value if isinstance(d, dict)]
    return []


_REPEATER_FIELDS = {"key", "password", "name"}


def _coerce_repeaters(value) -> list["RepeaterConfig"]:
    """Parse ``repeater_poll.repeaters`` (list of {key, password, name})."""
    def _from_dict(d: dict) -> "RepeaterConfig":
        return RepeaterConfig(
            **{k: v for k, v in d.items() if k in _REPEATER_FIELDS}
        )

    if isinstance(value, list):
        out = [_from_dict(d) for d in value if isinstance(d, dict)]
        return [r for r in out if r.key]  # drop entries with no key
    return []


_METRICS_API_KEY_FIELDS = {"id", "label", "key_hash", "created_at", "last_used_at"}


def _coerce_metrics_api_keys(value) -> list["MetricsApiKey"]:
    """Parse ``metrics.api_keys`` (list of {id, label, key_hash, created_at, last_used_at})."""
    def _from_dict(d: dict) -> "MetricsApiKey":
        return MetricsApiKey(
            **{k: v for k, v in d.items() if k in _METRICS_API_KEY_FIELDS}
        )

    if isinstance(value, list):
        out = [_from_dict(d) for d in value if isinstance(d, dict)]
        return [k for k in out if k.id and k.key_hash]
    return []


@dataclass
class CaptureConfig:
    sources: list[str] = field(default_factory=lambda: ["mock"])
    serial_port: Optional[str] = None
    serial_baud: int = 115200
    serial: list[SerialDeviceConfig] = field(default_factory=list)
    pocsag_serial: list[PocsagSerialDeviceConfig] = field(default_factory=list)
    rfenv_companion: list[RfEnvCompanionDeviceConfig] = field(default_factory=list)
    concentrator_spi_device: str = "/dev/spidev0.0"
    meshcore_usb: list[MeshcoreUsbConfig] = field(
        default_factory=lambda: [MeshcoreUsbConfig()]
    )
    # UI-visibility only -- nothing server-side reads this. The RTL-SDR
    # ("Listener") sidebar page has always been shown unconditionally,
    # unlike every other optional feature here, so this defaults to True
    # (opt-out) instead of False (opt-in) to avoid silently hiding it for
    # existing installs on upgrade. "Bare minimum" users flip it off.
    rtl_sdr_page_enabled: bool = True


@dataclass
class StorageConfig:
    database_path: str = "data/concentrator.db"
    max_packets_retained: int = 100_000
    max_telemetry_retained: int = 100_000
    cleanup_interval_seconds: int = 3600


@dataclass
class MetricsApiKey:
    """A named, revocable bearer credential scoped to /metrics only.

    ``key_hash`` is a SHA-256 hex digest -- the raw key is shown to the
    user exactly once at creation time and never stored or logged.
    """

    id: str
    label: str
    key_hash: str
    created_at: str
    last_used_at: Optional[str] = None


@dataclass
class MetricsConfig:
    """Prometheus-compatible /metrics scrape endpoint (PR 09)."""

    enabled: bool = False
    require_auth: bool = True
    api_keys: list[MetricsApiKey] = field(default_factory=list)


@dataclass
class DashboardConfig:
    host: str = "0.0.0.0"  # nosec B104 -- intentional for local device dashboard
    port: int = 8080
    static_dir: str = "frontend"
    # Extra/community drop-ins (currently: plugins/themes/<id>/). Resolved
    # like static_dir, from the working dir (/opt/meshpoint on the Pi).
    plugins_dir: str = "plugins"
    # Default dashboard theme id (folder name under frontend/themes/ or
    # plugins/themes/). Browsers that have never picked a theme use this;
    # a per-browser choice made in the theme toggle overrides it locally.
    theme: str = "dark"


@dataclass
class UpstreamConfig:
    enabled: bool = False
    url: str = "wss://api.meshradar.io"
    reconnect_interval_seconds: int = 10
    buffer_max_size: int = 5000
    auth_token: Optional[str] = None


@dataclass
class DeviceConfig:
    device_id: Optional[str] = None
    device_name: str = "Meshpoint"
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    altitude: Optional[float] = None
    hardware_description: str = "RAK2287 + Raspberry Pi 4"


@dataclass
class RelayConfig:
    enabled: bool = False
    serial_port: Optional[str] = None
    serial_baud: int = 115200
    max_relay_per_minute: int = 20
    burst_size: int = 5
    min_relay_rssi: float = -110.0
    max_relay_rssi: float = -50.0


@dataclass
class TelemetryConfig:
    """Periodic device_metrics telemetry broadcast settings."""

    interval_minutes: int = 30
    startup_delay_seconds: int = 120


@dataclass
class PositionConfig:
    """Periodic POSITION broadcast settings."""

    interval_minutes: int = 15
    startup_delay_seconds: int = 180
    # Coordinates sent on the public LoRa mesh (Meshtastic POSITION packets).
    # ``static`` uses ``device.{latitude,longitude,altitude}`` (wizard pin).
    # ``live`` reads the active ``LocationSource`` (gpsd/uart) when a fix exists.
    coordinate_source: str = "static"
    # Privacy when ``coordinate_source`` is ``live``: exact, approximate
    # (~1.1 km rounding), or none (skip position on mesh). Ignored for static.
    location_precision: str = "approximate"


@dataclass
class MqttConfig:
    enabled: bool = False
    broker: str = "mqtt.meshtastic.org"
    port: int = 1883
    username: str = "meshdev"
    password: str = "large4cats"
    topic_root: str = "msh"
    region: str = "US"
    tls_enabled: bool = False
    tls_ca_cert: str = ""
    # Optional ``!xxxxxxxx`` override; blank uses MD5 hash of device name.
    gateway_id: Optional[str] = None
    publish_channels: list[str] = field(default_factory=lambda: ["LongFast", "MeshCore"])
    publish_json: bool = False
    location_precision: str = "exact"
    homeassistant_discovery: bool = False
    # Publish this Meshpoint's own identity to the official Meshtastic map.
    # Map reports are public, unencrypted, MQTT-only packets.
    map_reporting_enabled: bool = False
    map_report_interval_seconds: int = 3600
    map_report_position_precision: int = 14


@dataclass
class NodeInfoConfig:
    """Periodic NodeInfo broadcast settings.

    Identity (long_name, short_name, hw_model) is broadcast on the
    primary channel so receiving Meshtastic clients build a stable
    contact entry.

    Set ``interval_minutes`` to ``0`` to disable periodic broadcasts
    while keeping TX enabled (DMs and replies still work). Otherwise
    valid range is 5..1440 (5 min to 24 hr).
    """

    interval_minutes: int = 180
    startup_delay_seconds: int = 60


@dataclass
class TransmitConfig:
    """Native LoRa transmission settings.

    When enabled, the Meshpoint can send Meshtastic messages through
    the onboard SX1261 radio and MeshCore messages through the USB
    companion. Disabled by default: opt-in via local.yaml.
    """

    enabled: bool = False
    node_id: Optional[int] = None
    tx_power_dbm: int = 14
    # None = auto-derive from radio.region (10% US/ANZ/KR/SG_923,
    # 1% EU_868/IN). Set explicitly in local.yaml to override.
    max_duty_cycle_percent: Optional[float] = None
    long_name: str = "Meshpoint"
    short_name: str = "MPNT"
    hop_limit: int = 3
    nodeinfo: NodeInfoConfig = field(default_factory=NodeInfoConfig)
    telemetry: TelemetryConfig = field(default_factory=TelemetryConfig)
    position: PositionConfig = field(default_factory=PositionConfig)


@dataclass
class LocationConfig:
    """Where the Meshpoint's reported lat/lon/alt comes from.

    ``source`` values:
        - ``"static"``   : use ``device.latitude/longitude/altitude`` from
                           ``local.yaml``. Backward-compatible default.
        - ``"gpsd"``     : connect to a local or remote ``gpsd`` daemon for
                           live fixes (skyplot, optional mesh POSITION).
                           Does not change ``device.{lat,lon,alt}`` (Meshradar
                           pin). Auto-installed by ``scripts/install.sh``.
        - ``"uart"``     : reserved for direct on-board UART NMEA reading
                           (RAK Pi HAT GPS). Plumbing exists in
                           ``src.hal.gps_reader`` but is not wired into
                           the runtime yet; treated as ``static`` until
                           the source is implemented.

    ``gpsd_host`` / ``gpsd_port`` default to gpsd's well-known
    localhost socket. Override only when running gpsd on a peer
    device on the LAN.

    ``update_interval_seconds`` is the period the coordinator wakes up
    to poll the active source. Static is effectively idle. gpsd reads
    the latest TPV report each cycle (the daemon batches device data
    on its side, so this is cheap).

    ``min_fix_quality`` filters noisy fixes: ``0`` accepts anything
    gpsd publishes (including no-fix), ``1`` requires a 2D fix, ``2``
    requires a 3D fix. Default is ``1`` so the dashboard never moves
    based on a no-fix TPV.
    """

    source: str = "static"
    gpsd_host: str = "127.0.0.1"
    gpsd_port: int = 2947
    update_interval_seconds: int = 5
    min_fix_quality: int = 1


@dataclass
class WebAuthConfig:
    """Local dashboard authentication settings.

    First-run state is ``admin_password_hash == ""``: the dashboard
    forces the user through the ``/setup`` flow before any other page
    or API call resolves. Once a hash is written, the dashboard
    requires a valid session cookie (or ``Authorization: Bearer``)
    on every protected endpoint.

    ``jwt_secret`` is auto-generated on first run when empty and
    persisted to ``local.yaml``. Rotating it (via the
    ``meshpoint reset-password`` CLI) invalidates every existing
    session in one move. ``session_version`` is embedded in the JWT
    claim for finer-grained invalidation without rotating the secret.
    """

    admin_password_hash: str = ""
    viewer_password_hash: str = ""
    jwt_secret: str = ""
    # Session lifetime in minutes. v0.7.4 raised the default from 60 to
    # 480 (8 hours) after operators reported being kicked back to /login
    # mid-shift. Configurable from Settings -> Auth -> Session lifetime,
    # range-checked at the route layer (5 min .. 30 days).
    jwt_expiry_minutes: int = 480
    allow_read_only: bool = False
    lockout_attempts: int = 5
    lockout_cooldown_minutes: int = 5
    session_version: int = 1


@dataclass
class FanConfig:
    """SenseCap M1 onboard fan: temperature-driven PWM control.

    Disabled by default -- opt-in via local.yaml, since this board's
    fan/button/LED GPIOs (see scripts/test_gpio_hardware.py) don't exist
    on other supported carriers (RAK V2, Chameleon, DIY). GPIO 13 is a
    hardware-PWM-capable pin on the Pi 4 (BCM2711 PWM1), confirmed live
    as this board's fan pin.
    """

    enabled: bool = False
    gpio_pin: int = 13
    min_temp_c: float = 45.0
    max_temp_c: float = 65.0
    min_duty: float = 0.35
    hysteresis_c: float = 5.0
    poll_interval_s: float = 10.0


@dataclass
class LedConfig:
    """SenseCap M1 case LED: glanceable service/capture status light.

    Disabled by default -- opt-in via local.yaml, same rationale as
    ``FanConfig`` (this GPIO doesn't exist on other carriers). GPIO 22
    confirmed live as this board's LED via scripts/test_gpio_hardware.py.
    Steady on = all capture sources healthy; brief off-flicker = packet
    captured; 1 Hz blink = a configured source is down; dark = service
    not running.
    """

    enabled: bool = False
    gpio_pin: int = 22
    activity_blink: bool = True


@dataclass
class ButtonConfig:
    """SenseCap M1 user button: physical advert + service restart.

    Disabled by default -- opt-in via local.yaml, same rationale as
    ``FanConfig``/``LedConfig``. GPIO 27 confirmed live as this board's
    button via scripts/test_gpio_hardware.py button-scan. Short press
    adverts on every TX-capable radio (concentrator NodeInfo, MeshCore
    companion advert, Meshtastic USB sticks), serialized so the
    overlapping 868 signals don't collide; long press restarts the
    meshpoint service -- the one recovery action that works when the
    dashboard doesn't.
    """

    enabled: bool = False
    gpio_pin: int = 27
    hold_time_s: float = 3.0
    advert_cooldown_s: float = 30.0


@dataclass
class RepeaterConfig:
    """One MeshCore repeater to poll for status/telemetry.

    ``key`` is the node's public-key prefix (12 hex, == its node_id in
    our DB). ``password`` is the repeater's login password -- needed for
    ``req_status``; it's a secret and gets redacted for viewers like the
    channel keys. ``name`` is an optional label for logs only.
    """

    key: str = ""
    password: str = ""
    name: str = ""


@dataclass
class RepeaterPollConfig:
    """Periodically query configured MeshCore repeaters (opt-in).

    Uses the companion's own ``req_status``/``req_telemetry`` (the same
    the phone app and meshcore-cli use) to pull battery, uptime, airtime,
    packet counters and LPP sensors from repeaters you operate, filling
    the otherwise-empty MeshCore node stats. Active two-way RF, so it's
    off by default and targets a short list you have passwords for, not
    the whole contact roster.
    """

    enabled: bool = False
    interval_minutes: int = 30
    repeaters: list = field(default_factory=list)


@dataclass
class UpdateCheckConfig:
    """Periodic background check for a newer version on GitHub.

    Reuses the exact same git-fetch + commits-behind logic as the
    manual "Check for updates" button (build_install_status_payload),
    so the sidebar badge and the button always agree on whether an
    update is available -- never a separate, looser check that could
    disagree with it. Server-side and config-driven (not per-browser)
    so every client sees the same state regardless of who's looking.
    """

    enabled: bool = True
    interval_minutes: int = 60


@dataclass
class DapnetConfig:
    """DAPNET/POCSAG companion capture (extra/pocsag_companion) settings.

    Not a connection setting (that's ``capture.pocsag_serial``) -- this
    is what happens to a decoded page once received. Two independent
    tiers, both user-editable from Configuration -> POCSAG:

    - ``blacklist_capcodes``: DAPNET's own network housekeeping/time-
      sync beacons (real capcodes, confirmed) repeat every couple of
      minutes -- worth seeing live (confirms the decoder/network are
      still alive) but not worth persisting. Shown on the live DAPNET
      page but never written to the packets table.
    - ``ignore_capcodes``: pure noise the user never wants to see at
      all -- neither persisted nor shown live.

    ``status_poll_interval_s`` is unrelated to either tier -- it's how
    often (in seconds) DapnetSerialSource re-sends its {"cmd":"status"}
    query after the initial one-shot at connect, to keep tx_count/
    last_tx_ok/uptime_ms fresh. Global, not per-device -- no real
    reason one companion would want a different cadence than another.
    """

    blacklist_capcodes: list[int] = field(
        default_factory=lambda: [200, 208, 216, 224]
    )
    ignore_capcodes: list[int] = field(default_factory=lambda: [4512, 4520])
    status_poll_interval_s: int = 60


@dataclass
class ReticulumConfig:
    """Native Reticulum/LXMF messaging (companion to extra/heltec_v4_reticulum_bron).

    Disabled by default, and deliberately so: meshpoint's own
    ``RNS.Reticulum()`` call must only ever run *after* ``rnsd`` is
    already up as the local shared instance -- attach as a client, same
    as reticulum-meshchat does. If rnsd isn't running yet when this
    starts, RNS falls back to reading this same configdir itself and
    opening the RNode/TCP interfaces directly, which would then fight
    rnsd for them once it starts. ``scripts/rnsd.service`` (opt-in,
    not installed by default) plus a soft ``After=rnsd.service`` on
    meshpoint's own unit (ordering only, no hard dependency --
    meshpoint must never require rnsd to exist) covers this once a
    user opts in to both; until then this config flag alone keeps a
    routine meshpoint restart from silently grabbing the radio.

    ``reticulum_config_dir`` deliberately does NOT default to
    ``~/.reticulum`` (RNS's own default): the ``meshpoint`` systemd
    user is ``--no-create-home``, so ``$HOME`` resolves to a
    ``/home/meshpoint`` that doesn't exist and can't be created --
    confirmed live (``PermissionError`` on ``RNS.Reticulum()`` at
    startup). Pointing this at meshpoint's own writable ``data/`` tree
    instead sidesteps that entirely.

    Correction to an earlier assumption (found live, not guessed): this
    directory is NOT "purely local client-side cache, independent of
    the shared instance." The local-client RPC channel to the shared
    instance appears to authenticate per-configdir (confirmed against
    a real "digest received was wrong" error reproduced live when
    meshpoint's client used a different configdir than rnsd's) --
    meshpoint's own client and rnsd MUST share the exact same
    ``reticulum_config_dir`` for that RPC channel to work reliably.
    ``scripts/write_rnsd_config.py`` writes rnsd's own config file into
    this same directory for exactly that reason -- one shared configdir,
    not two independent ones that happen to have similar content.

    ``rnode_*``/``backbone_*`` fields are consumed by
    ``scripts/write_rnsd_config.py``, not by meshpoint's own
    ``LxmfService`` -- they describe rnsd's own interfaces (the
    physical RNode + the community TCP backbone), which meshpoint
    itself never touches directly. Defaults match the already-reserved
    ch7 Reticulum frequency from the earlier concentrator investigation
    (869.463 MHz) and the community backbone
    ``reticulum-meshchat``/the Heltec V4 companion firmware already use.
    """

    enabled: bool = False
    display_name: str = "Meshpoint"
    reticulum_config_dir: str = "data/reticulum/rns_config"
    identity_path: str = "data/reticulum/identity"
    lxmf_storage_dir: str = "data/reticulum/lxmf"

    rnode_serial_port: str = ""  # stable path (by-id/by-path); blank = not configured
    rnode_frequency_hz: int = 869_463_000
    rnode_bandwidth_hz: int = 125_000
    rnode_tx_power: int = 20
    rnode_spreading_factor: int = 8
    rnode_coding_rate: int = 5
    backbone_host: str = "node.reticulumnet.nl"
    backbone_port: int = 4242


@dataclass
class AppConfig:
    radio: RadioConfig = field(default_factory=RadioConfig)
    lorawan: LoRaWANConfig = field(default_factory=LoRaWANConfig)
    meshtastic: MeshtasticConfig = field(default_factory=MeshtasticConfig)
    meshcore: MeshcoreConfig = field(default_factory=MeshcoreConfig)
    capture: CaptureConfig = field(default_factory=CaptureConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    dashboard: DashboardConfig = field(default_factory=DashboardConfig)
    upstream: UpstreamConfig = field(default_factory=UpstreamConfig)
    device: DeviceConfig = field(default_factory=DeviceConfig)
    relay: RelayConfig = field(default_factory=RelayConfig)
    mqtt: MqttConfig = field(default_factory=MqttConfig)
    transmit: TransmitConfig = field(default_factory=TransmitConfig)
    web_auth: WebAuthConfig = field(default_factory=WebAuthConfig)
    location: LocationConfig = field(default_factory=LocationConfig)
    metrics: MetricsConfig = field(default_factory=MetricsConfig)
    fan: FanConfig = field(default_factory=FanConfig)
    led: LedConfig = field(default_factory=LedConfig)
    button: ButtonConfig = field(default_factory=ButtonConfig)
    repeater_poll: RepeaterPollConfig = field(default_factory=RepeaterPollConfig)
    update_check: UpdateCheckConfig = field(default_factory=UpdateCheckConfig)
    dapnet: DapnetConfig = field(default_factory=DapnetConfig)
    reticulum: ReticulumConfig = field(default_factory=ReticulumConfig)
    # Per-plugin config, keyed by plugin id (folder name under
    # plugins/apps/). Opaque: each plugin owns its own sub-schema. The
    # loader only reads plugins.<id>.enabled (default false -- an
    # in-process plugin runs with the service user's rights, so loading
    # is opt-in). See src/plugins/loader.py.
    plugins: dict = field(default_factory=dict)


def _resolve_radio_frequency(radio: "RadioConfig") -> None:
    """Resolve radio.frequency_mhz at startup.

    Priority (first match wins):
    1. frequency_mhz set in YAML  -> use as-is, slot ignored
    2. slot set in YAML           -> compute from slot + bandwidth + region
    3. neither set                -> regional default frequency
    """
    if radio.frequency_mhz is not None:
        return
    if radio.slot is not None:
        freq_start = _REGION_FREQ_START.get(radio.region)
        if freq_start is not None:
            spacing = radio.bandwidth_khz / 1000
            radio.frequency_mhz = round(
                freq_start + spacing / 2 + (radio.slot - 1) * spacing, 4
            )
            return
    radio.frequency_mhz = _REGION_DEFAULT_FREQ.get(radio.region, 906.875)


def _merge_dataclass(instance, overrides: dict):
    """Apply dict overrides onto a dataclass instance, merging nested dataclasses."""
    if not overrides:
        return
    for key, value in overrides.items():
        if not hasattr(instance, key):
            continue
        current = getattr(instance, key)
        if dataclasses.is_dataclass(current) and isinstance(value, dict):
            _merge_dataclass(current, value)
        else:
            setattr(instance, key, value)


def _collect_unknown_keys(instance, overrides: dict, prefix: str = "") -> list[str]:
    """Return dotted paths of override keys with no matching dataclass field.

    Mirrors the descent rules in :func:`_merge_dataclass`: it only recurses
    into a nested dataclass (e.g. ``transmit.nodeinfo``), so user-supplied
    mapping fields such as ``meshtastic.channel_keys`` are treated as opaque
    values rather than scanned for "unknown" keys.
    """
    unknown: list[str] = []
    for key, value in overrides.items():
        if not hasattr(instance, key):
            unknown.append(f"{prefix}{key}")
            continue
        current = getattr(instance, key)
        if dataclasses.is_dataclass(current) and isinstance(value, dict):
            unknown.extend(_collect_unknown_keys(current, value, f"{prefix}{key}."))
    return unknown


def _apply_yaml(cfg: AppConfig, path: Path) -> None:
    """Merge a single YAML file into an existing AppConfig."""
    if not path.exists():
        return

    with open(path, "r") as fh:
        raw = yaml.safe_load(fh) or {}

    if not isinstance(raw, dict):
        logger.warning("Ignoring %s: top-level YAML is not a mapping.", path)
        return

    # plugins.<id> is an opaque per-plugin mapping (the plugin owns its
    # sub-schema). Pop it before the section loop so _collect_unknown_keys
    # doesn't flag plugins.<id>.* as typos, and merge onto any existing
    # value so a second YAML file adds plugins rather than replacing them.
    plugins_raw = raw.pop("plugins", None)
    if isinstance(plugins_raw, dict):
        for plugin_id, plugin_conf in plugins_raw.items():
            if isinstance(plugin_conf, dict) and isinstance(
                cfg.plugins.get(plugin_id), dict
            ):
                cfg.plugins[plugin_id].update(plugin_conf)
            else:
                cfg.plugins[plugin_id] = plugin_conf

    # meshcore_usb supports both a legacy single-dict and a new list-of-dicts.
    # Pop it before the generic merge so _merge_dataclass doesn't store raw dicts.
    cap_raw = raw.get("capture")
    if isinstance(cap_raw, dict) and "meshcore_usb" in cap_raw:
        cfg.capture.meshcore_usb = _coerce_meshcore_usb(cap_raw.pop("meshcore_usb"))
    # serial is opt-in multi-device list; legacy serial_port/serial_baud
    # scalars keep working untouched when this key is absent.
    if isinstance(cap_raw, dict) and "serial" in cap_raw:
        cfg.capture.serial = _coerce_serial_devices(cap_raw.pop("serial"))
    # pocsag_serial is a list-of-dicts, same shape as serial; pop it before
    # the generic merge so _merge_dataclass doesn't store raw dicts.
    if isinstance(cap_raw, dict) and "pocsag_serial" in cap_raw:
        cfg.capture.pocsag_serial = _coerce_pocsag_serial_devices(cap_raw.pop("pocsag_serial"))
    # rfenv_companion is a list-of-dicts, same shape as pocsag_serial; pop
    # it before the generic merge so _merge_dataclass doesn't store raw dicts.
    if isinstance(cap_raw, dict) and "rfenv_companion" in cap_raw:
        cfg.capture.rfenv_companion = _coerce_rfenv_companion_devices(cap_raw.pop("rfenv_companion"))
    # repeater_poll.repeaters is a list-of-dicts; pop it before the
    # generic merge so _merge_dataclass doesn't store raw dicts.
    rp_raw = raw.get("repeater_poll")
    if isinstance(rp_raw, dict) and "repeaters" in rp_raw:
        cfg.repeater_poll.repeaters = _coerce_repeaters(rp_raw.pop("repeaters"))
    # metrics.api_keys is a list-of-dicts; pop it before the generic merge
    # so _merge_dataclass doesn't store raw dicts.
    metrics_raw = raw.get("metrics")
    if isinstance(metrics_raw, dict) and "api_keys" in metrics_raw:
        cfg.metrics.api_keys = _coerce_metrics_api_keys(metrics_raw.pop("api_keys"))

    section_map = {
        "radio": cfg.radio,
        "lorawan": cfg.lorawan,
        "meshtastic": cfg.meshtastic,
        "meshcore": cfg.meshcore,
        "capture": cfg.capture,
        "storage": cfg.storage,
        "dashboard": cfg.dashboard,
        "upstream": cfg.upstream,
        "device": cfg.device,
        "relay": cfg.relay,
        "mqtt": cfg.mqtt,
        "transmit": cfg.transmit,
        "web_auth": cfg.web_auth,
        "location": cfg.location,
        "metrics": cfg.metrics,
        "fan": cfg.fan,
        "led": cfg.led,
        "button": cfg.button,
        "repeater_poll": cfg.repeater_poll,
        "update_check": cfg.update_check,
        "dapnet": cfg.dapnet,
        "reticulum": cfg.reticulum,
    }

    unknown_keys: list[str] = []
    for section_name, section_value in raw.items():
        section_instance = section_map.get(section_name)
        if section_instance is None:
            unknown_keys.append(section_name)
            continue
        _merge_dataclass(section_instance, section_value)
        if isinstance(section_value, dict):
            unknown_keys.extend(
                _collect_unknown_keys(section_instance, section_value, f"{section_name}.")
            )

    if unknown_keys:
        logger.warning(
            "Ignoring %d unknown config key(s) in %s: %s. "
            "These were not applied -- check for typos against the documented schema.",
            len(unknown_keys),
            path,
            ", ".join(sorted(unknown_keys)),
        )


_VALID_CONFIG_EXTENSIONS = {".yaml", ".yml"}


def _validated_config_path(raw: str) -> Path:
    resolved = Path(raw).resolve()
    if resolved.suffix not in _VALID_CONFIG_EXTENSIONS:
        raise ValueError(f"Config path must be a .yaml/.yml file, got: {resolved.name}")
    return resolved


def load_config(config_path: Optional[str] = None) -> AppConfig:
    """Load config with two-layer merging: default.yaml then local overrides.

    Layer 1: config/default.yaml (always loaded, sane defaults in VCS)
    Layer 2: config/local.yaml or path from CONCENTRATOR_CONFIG env var
             (user-specific overrides, gitignored)
    """
    cfg = AppConfig()

    _apply_yaml(cfg, Path("config/default.yaml"))

    local = config_path or os.environ.get("CONCENTRATOR_CONFIG", "config/local.yaml")
    _apply_yaml(cfg, _validated_config_path(local))
    _resolve_radio_frequency(cfg.radio)

    return cfg


def _get_local_yaml_path() -> Path:
    """Resolve the local.yaml path used for user overrides."""
    raw = os.environ.get("CONCENTRATOR_CONFIG", "config/local.yaml")
    return _validated_config_path(raw)


def save_section_to_yaml(section: str, values: dict) -> None:
    """Merge values into a section of local.yaml without destroying other sections.

    Reads the existing file (if any), updates only the specified section,
    and writes back. Creates the file if it doesn't exist.
    """
    path = _get_local_yaml_path()
    existing: dict = {}
    if path.exists():
        with open(path, "r") as fh:
            existing = yaml.safe_load(fh) or {}

    if section not in existing:
        existing[section] = {}
    if isinstance(existing[section], dict):
        existing[section].update(values)
    else:
        existing[section] = values

    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, "w") as fh:
            yaml.dump(existing, fh, default_flow_style=False, sort_keys=False)
    except PermissionError:
        import getpass
        hint_user = getpass.getuser() or "meshpoint"
        raise PermissionError(
            f"Cannot write to {path}. "
            f"Fix with: sudo chown {hint_user}:{hint_user} {path}"
        )


def remove_subsection_key(section: str, key: str) -> None:
    """Drop one key from a nested section of local.yaml (e.g. plugins.<id>
    after deleting that plugin's folder). No-op if the file, section, or key
    doesn't exist -- deleting something already absent isn't an error here.
    """
    path = _get_local_yaml_path()
    if not path.exists():
        return
    with open(path, "r") as fh:
        existing = yaml.safe_load(fh) or {}

    sub = existing.get(section)
    if not isinstance(sub, dict) or key not in sub:
        return
    del sub[key]

    try:
        with open(path, "w") as fh:
            yaml.dump(existing, fh, default_flow_style=False, sort_keys=False)
    except PermissionError:
        import getpass
        hint_user = getpass.getuser() or "meshpoint"
        raise PermissionError(
            f"Cannot write to {path}. "
            f"Fix with: sudo chown {hint_user}:{hint_user} {path}"
        )


def validate_activation(config: AppConfig) -> None:
    """Require a valid signed API key only when upstream (Meshradar) is enabled."""
    if not config.upstream.enabled:
        return

    token = config.upstream.auth_token
    if not token:
        print("\n  Meshpoint is not activated.\n")
        print("  An API key is required to use Meshradar upstream.")
        print("  Get a free key at https://meshradar.io\n")
        print("  Then run:  meshpoint setup\n")
        sys.exit(1)

    from src.activation import verify_license_key

    if not verify_license_key(token):
        print("\n  Invalid API key.\n")
        print("  The key in your config is not a valid Meshradar license.")
        print("  Generate a new key at https://meshradar.io\n")
        print("  Then run:  meshpoint setup\n")
        sys.exit(1)
