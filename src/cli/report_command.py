"""Full-screen operational report for the Meshpoint CLI.

Queries the running Meshpoint service via its local HTTP API and
renders a consolidated terminal dashboard. Requires the service to
be running on localhost:8080 and prompts for dashboard admin
credentials (the API sits behind the session-cookie auth).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from src.cli.api_client import ApiError, AuthRequired, CliApiClient, ServiceDown

_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_RED = "\033[31m"
_CYAN = "\033[36m"


@dataclass
class ReportData:
    device: dict = field(default_factory=dict)
    status: dict = field(default_factory=dict)
    metrics: dict = field(default_factory=dict)
    traffic: dict = field(default_factory=dict)
    signal: dict = field(default_factory=dict)
    nodes: dict = field(default_factory=dict)
    node_summary: dict = field(default_factory=dict)
    packet_count: dict = field(default_factory=dict)
    config: dict = field(default_factory=dict)
    lorawan_stats: dict = field(default_factory=dict)
    spectrum: dict = field(default_factory=dict)


def run_report() -> None:
    """Fetch data from the local API and render the report."""
    data = _fetch_all()
    if data is None:
        return
    _render_report(data)


def _fetch_all() -> ReportData | None:
    """Query all relevant API endpoints."""
    data = ReportData()
    client = CliApiClient()

    try:
        data.status = client.get("/api/device/status")
    except ServiceDown:
        print(f"\n  {_RED}Meshpoint service is not running or unreachable.{_RESET}")
        print("  Start it with: sudo systemctl start meshpoint\n")
        return None
    except AuthRequired:
        # Root / service user can read the signing key: no prompt needed.
        if client.login_local_root():
            try:
                data.status = client.get("/api/device/status")
            except ApiError:
                data.status = {}
        if not data.status:
            print("\n  Service is running; the report needs a dashboard admin login.")
            print("  (Tip: 'sudo meshpoint report' skips this prompt.)")
            try:
                client.login_interactive()
                data.status = client.get("/api/device/status")
            except AuthRequired:
                print(f"\n  {_RED}Login failed (wrong credentials?).{_RESET}\n")
                return None
            except (ServiceDown, ApiError) as exc:
                print(f"\n  {_RED}Login failed: {exc}{_RESET}\n")
                return None

    data.device = _get(client, "/api/device")
    data.metrics = _get(client, "/api/device/metrics")
    data.traffic = _get(client, "/api/analytics/traffic")
    data.signal = _get(client, "/api/analytics/signal/summary")
    data.nodes = _get(client, "/api/nodes/count")
    data.node_summary = _get(client, "/api/nodes/summary")
    data.packet_count = _get(client, "/api/packets/count")
    data.config = _get(client, "/api/config")
    data.lorawan_stats = _get(client, "/api/lorawan/stats")
    data.spectrum = _get(client, "/api/device/spectrum")

    return data


def _render_report(d: ReportData) -> None:
    """Render all report sections to stdout."""
    _print_header(d)
    _print_system_section(d)
    _print_traffic_section(d)
    _print_signal_section(d)
    _print_network_section(d)
    _print_protocols_section(d)
    _print_sources_section(d)
    _print_relay_section(d)
    _print_radio_section(d)
    _print_meshcore_section(d)
    _print_health_summary(d)
    print()


def _print_header(d: ReportData) -> None:
    name = d.device.get("device_name", "Meshpoint")
    version = d.status.get("firmware_version", "?")
    device_id = d.status.get("device_id", "")
    uptime = _fmt_uptime(d.status.get("uptime_seconds", 0))

    print()
    print(f"  {_BOLD}{_CYAN}{'=' * 56}{_RESET}")
    print(f"  {_BOLD}{_CYAN}  MESHPOINT OPERATIONAL REPORT{_RESET}")
    print(f"  {_BOLD}{_CYAN}{'=' * 56}{_RESET}")
    print()
    _kv("Name", name)
    _kv("Version", f"v{version}")
    _kv("Device ID", device_id)
    _kv("Uptime", uptime)
    _sep()


def _print_system_section(d: ReportData) -> None:
    m = d.metrics
    if not m:
        _section("SYSTEM")
        print(f"  {_DIM}Metrics unavailable{_RESET}")
        _sep()
        return

    _section("SYSTEM")

    cpu = m.get("cpu_percent", 0)
    _kv("CPU", f"{cpu}%", _bar(cpu, 100))
    _kv("Temperature", _fmt_temp(m.get("cpu_temp_c")))

    mem_pct = m.get("memory_percent", 0)
    mem_str = f"{m.get('memory_used_mb', '?')} / {m.get('memory_total_mb', '?')} MB"
    _kv("Memory", f"{mem_pct}%", _bar(mem_pct, 100), mem_str)

    disk_pct = m.get("disk_percent", 0)
    disk_str = f"{m.get('disk_used_gb', '?')} / {m.get('disk_total_gb', '?')} GB"
    _kv("Disk", f"{disk_pct}%", _bar(disk_pct, 100), disk_str)

    sys_uptime = m.get("system_uptime_seconds")
    if sys_uptime:
        _kv("System uptime", _fmt_uptime(sys_uptime))

    _sep()


def _print_traffic_section(d: ReportData) -> None:
    t = d.traffic
    _section("RX TRAFFIC")

    total = d.packet_count.get("count", t.get("total_packets", 0))
    _kv("Total packets", f"{total:,}")
    _kv("Last hour", f"{t.get('packets_last_hour', 0):,}")
    _kv("Rate", f"{t.get('packets_per_minute', 0):.1f} pkt/min")

    proto = t.get("protocol_distribution", {})
    if proto:
        parts = [f"{k}: {v}" for k, v in sorted(proto.items())]
        _kv("Protocols", ", ".join(parts))

    types = t.get("type_distribution", {})
    if types:
        sorted_types = sorted(types.items(), key=lambda x: -x[1])[:8]
        parts = [f"{k}: {v}" for k, v in sorted_types]
        _kv("Top types", ", ".join(parts))

    _sep()


def _print_signal_section(d: ReportData) -> None:
    s = d.signal
    _section("SIGNAL QUALITY")

    samples = s.get("sample_count", 0)
    if samples == 0:
        print(f"  {_DIM}No signal data yet{_RESET}")
        _sep()
        return

    avg_rssi = s.get("avg_rssi")
    min_rssi = s.get("min_rssi")
    max_rssi = s.get("max_rssi")
    avg_snr = s.get("avg_snr")

    _kv("Avg RSSI", _fmt_rssi(avg_rssi))
    _kv("RSSI range", f"{_fmt_rssi(min_rssi)} to {_fmt_rssi(max_rssi)}")
    _kv("Avg SNR", f"{avg_snr:.1f} dB" if avg_snr is not None else "--")
    _kv("Samples", f"{samples}")
    _sep()


def _print_network_section(d: ReportData) -> None:
    _section("NETWORK")
    total = d.nodes.get("count", 0)
    active = d.nodes.get("active", 0)
    positioned = d.node_summary.get("nodes_with_position", 0)

    _kv("Total nodes", f"{total}")
    _kv("Active (15 min)", f"{active}")
    _kv("With position", f"{positioned}")

    proto_map = d.node_summary.get("protocols", {})
    if proto_map:
        parts = [f"{k}: {v}" for k, v in sorted(proto_map.items())]
        _kv("By protocol", ", ".join(parts))

    ws = d.status.get("websocket_clients", 0)
    _kv("Dashboard clients", f"{ws}")
    _sep()


def _print_relay_section(d: ReportData) -> None:
    relay = d.status.get("relay", {})
    _section("RELAY")

    enabled = relay.get("enabled", False)
    _kv("Status", f"{_GREEN}enabled{_RESET}" if enabled else f"{_DIM}disabled{_RESET}")

    if enabled:
        relayed = relay.get("relayed", 0)
        rejected = relay.get("rejected", 0)
        total_eval = relayed + rejected
        rate = (relayed / total_eval * 100) if total_eval > 0 else 0

        _kv("Relayed", f"{relayed:,}")
        _kv("Rejected", f"{rejected:,}")
        _kv("Accept rate", f"{rate:.0f}%" if total_eval > 0 else "--")

    _sep()


def _print_protocols_section(d: ReportData) -> None:
    """One line per captured network: packets, nodes/devices, radio."""
    cfg = d.config
    proto_pkts = d.traffic.get("protocol_distribution", {})
    proto_nodes = d.node_summary.get("protocols", {})
    if not cfg and not proto_pkts:
        return

    _section("PROTOCOLS")

    lw_devices = d.lorawan_stats.get("unique_devices")
    lw_chans = [
        ch for ch in (cfg.get("concentrator", {}).get("channels") or [])
        if ch.get("enabled") and ch.get("protocol") == "lorawan"
    ]
    lw_parts = [f"{proto_pkts.get('lorawan', 0):,} pkts"]
    if lw_devices is not None:
        lw_parts.append(f"{lw_devices} devices")
    if lw_chans:
        freqs = [c["frequency_mhz"] for c in lw_chans]
        lw_parts.append(
            f"{min(freqs):.1f}-{max(freqs):.1f} MHz x{len(lw_chans)} ch"
        )
    lw_parts.append("sniff-only")
    _kv("LoRaWAN", " · ".join(lw_parts))

    radio = cfg.get("radio", {})
    tx_on = cfg.get("transmit", {}).get("enabled", False)
    mt_parts = [
        f"{proto_pkts.get('meshtastic', 0):,} pkts",
        f"{proto_nodes.get('meshtastic', 0):,} nodes",
    ]
    if radio.get("frequency_mhz"):
        mt_parts.append(
            f"{radio['frequency_mhz']} MHz SF{radio.get('spreading_factor', '?')}"
        )
    mt_parts.append("TX on" if tx_on else "TX off")
    _kv("Meshtastic", " · ".join(mt_parts))

    mc_radio = (cfg.get("meshcore") or {}).get("radio") or {}
    mc_parts = [
        f"{proto_pkts.get('meshcore', 0):,} pkts",
        f"{proto_nodes.get('meshcore', 0):,} nodes",
    ]
    if mc_radio.get("frequency_mhz"):
        mc_parts.append(
            f"{mc_radio['frequency_mhz']} MHz SF{mc_radio.get('spreading_factor', '?')}"
        )
    mc_parts.append("via companion")
    _kv("MeshCore", " · ".join(mc_parts))

    _sep()


def _print_sources_section(d: ReportData) -> None:
    """Capture hardware: concentrator plan, companions, last band sweep."""
    cfg = d.config
    if not cfg:
        return

    _section("CAPTURE SOURCES")

    conc = cfg.get("concentrator", {})
    channels = conc.get("channels") or []
    if conc.get("active") and channels:
        on = [c for c in channels if c.get("enabled")]
        lw = sum(1 for c in on if c.get("protocol") == "lorawan")
        mt = sum(1 for c in on if c.get("protocol") == "meshtastic")
        _kv(
            "Concentrator",
            f"SX1302 · {len(on)}/{len(channels)} channels on "
            f"({lw}x LoRaWAN + {mt}x Meshtastic)",
        )

    mc = cfg.get("meshcore", {})
    capture = cfg.get("capture", {})
    companions = capture.get("meshcore_usb") or []
    for comp in companions:
        port = comp.get("serial_port") or "auto"
        label = comp.get("label") or ""
        name = f"meshcore_usb{f'_{label}' if label else ''}"
        state = (
            f"{_GREEN}connected{_RESET}" if mc.get("connected") else f"{_DIM}--{_RESET}"
        )
        detail = mc.get("companion_name") or ""
        _kv(name, " · ".join(x for x in (port, state, detail) if x))
    if not companions and mc:
        state = "connected" if mc.get("connected") else "disconnected"
        _kv("meshcore_usb", state)

    sweep = (d.spectrum or {}).get("sweep") or {}
    if sweep.get("generated_at"):
        when = sweep["generated_at"][11:19]  # HH:MM:SS from ISO timestamp (UTC)
        _kv(
            "Band sweep",
            f"last {when} UTC · {sweep.get('point_count', '?')} pts "
            f"in {sweep.get('duration_seconds', '?')}s",
        )

    _sep()


def _print_radio_section(d: ReportData) -> None:
    cfg = d.config
    if not cfg:
        return

    _section("MESHTASTIC TX")
    radio = cfg.get("radio", {})
    if radio:
        _kv("Region", radio.get("region", "--"))
        _kv(
            "Preset",
            f"{radio.get('current_preset', '--')} · "
            f"CR{radio.get('coding_rate', '--')} · "
            f"BW{radio.get('bandwidth_khz', '--')}",
        )

    tx = cfg.get("transmit", {})
    if tx:
        tx_enabled = tx.get("enabled", False)
        _kv("TX", f"{_GREEN}enabled{_RESET}" if tx_enabled else f"{_DIM}disabled{_RESET}")
        _kv("TX power", f"{tx.get('tx_power_dbm', '--')} dBm")
        if tx.get("hop_limit") is not None:
            _kv("Hop limit", str(tx.get("hop_limit")))

    duty = cfg.get("duty_cycle", {})
    if duty:
        usage = duty.get("current_usage_percent", 0)
        budget = duty.get("remaining_budget_ms", 0)
        _kv("Duty cycle", f"{usage:.1f}%", f"({budget:.0f} ms remaining)")

    _sep()


def _print_meshcore_section(d: ReportData) -> None:
    mc = d.config.get("meshcore") or {}
    if not mc:
        return

    _section("MESHCORE")
    connected = mc.get("connected", False)
    state = f"{_GREEN}connected{_RESET}" if connected else f"{_DIM}disconnected{_RESET}"
    name = mc.get("companion_name") or ""
    _kv("Companion", " · ".join(x for x in (state, name) if x))

    radio = mc.get("radio") or {}
    if radio.get("frequency_mhz"):
        _kv("Radio", (
            f"{radio['frequency_mhz']} MHz · "
            f"BW{radio.get('bandwidth_khz', '--')} · "
            f"SF{radio.get('spreading_factor', '--')}"
        ))
    if radio.get("tx_power") is not None:
        _kv("TX power", f"{radio['tx_power']} dBm")

    channels = mc.get("channel_keys") or []
    names = ["Public"] + [
        (ch.get("name") or "").strip() or "(unnamed)" for ch in channels
    ]
    _kv("Channels", f"{len(names)}: {', '.join(names)}")

    _sep()


def _print_health_summary(d: ReportData) -> None:
    """Compute and display a composite health assessment."""
    _section("HEALTH")

    issues: list[str] = []

    m = d.metrics
    if m:
        if m.get("cpu_percent", 0) > 85:
            issues.append(f"{_YELLOW}CPU usage high ({m['cpu_percent']}%){_RESET}")
        if m.get("memory_percent", 0) > 85:
            issues.append(f"{_YELLOW}Memory usage high ({m['memory_percent']}%){_RESET}")
        if m.get("disk_percent", 0) > 90:
            issues.append(f"{_RED}Disk nearly full ({m['disk_percent']}%){_RESET}")
        temp = m.get("cpu_temp_c")
        if temp is not None and temp > 75:
            issues.append(f"{_YELLOW}CPU temperature high ({temp}C){_RESET}")

    avg_rssi = d.signal.get("avg_rssi")
    if avg_rssi is not None and avg_rssi < -110:
        issues.append(f"{_YELLOW}Weak average signal ({avg_rssi} dBm){_RESET}")

    if not issues:
        print(f"  {_GREEN}{_BOLD}All systems nominal{_RESET}")
    else:
        for issue in issues:
            print(f"  {_BOLD}!{_RESET} {issue}")


# ── Formatting helpers ──────────────────────────────────────────────

def _section(title: str) -> None:
    print(f"\n  {_BOLD}{title}{_RESET}")

def _sep() -> None:
    print(f"  {_DIM}{'─' * 52}{_RESET}")

def _kv(key: str, value: str, *extras: str) -> None:
    extra = "  ".join(str(e) for e in extras if e)
    suffix = f"  {_DIM}{extra}{_RESET}" if extra else ""
    print(f"  {key + ':':<20s} {value}{suffix}")

def _bar(value: float, maximum: float, width: int = 20) -> str:
    ratio = min(value / maximum, 1.0) if maximum > 0 else 0
    filled = int(ratio * width)
    if ratio > 0.9:
        color = _RED
    elif ratio > 0.7:
        color = _YELLOW
    else:
        color = _GREEN
    return f"{color}{'█' * filled}{'░' * (width - filled)}{_RESET}"

def _fmt_uptime(seconds: int | float) -> str:
    td = timedelta(seconds=int(seconds))
    days = td.days
    hours = td.seconds // 3600
    minutes = (td.seconds % 3600) // 60
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return " ".join(parts)

def _fmt_rssi(val) -> str:
    if val is None:
        return "--"
    return f"{val:.1f} dBm"

def _fmt_temp(val) -> str:
    if val is None:
        return "N/A"
    return f"{val}°C"


def _get(client: CliApiClient, path: str) -> dict:
    """GET one endpoint; missing/failed sections render as empty."""
    try:
        result = client.get(path)
        return result if isinstance(result, dict) else {"items": result}
    except ApiError:
        return {}
