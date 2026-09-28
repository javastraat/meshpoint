"""Run ``sudo nmcli <args>`` for the narrowly-scoped subcommands granted
passwordless in ``config/sudoers-meshpoint``.

For the ``raspberry-network`` plugin (WiFi scan/connect/status) --
NetworkManager is this project's real target network stack (see
``scripts/provision_config.py``'s own ``.nmconnection`` writer and
``docs/COMMON-ERRORS.md``'s ``nmcli connection ...`` troubleshooting),
already installed by default on the Bookworm-era Raspberry Pi OS images
this ships against.

Same shape as ``src/api/systemctl.py``'s ``run_systemctl`` -- FastAPI-free,
no shell (``asyncio.create_subprocess_exec``, argv as a real list, never a
joined string), returns ``(returncode, output)`` rather than raising so the
caller decides what an error means. Anything outside the exact subcommands
listed in ``config/sudoers-meshpoint`` will prompt for a password rather
than run.

``wifi_connect()`` deliberately never tears down a working connection to
try a failing one -- ``nmcli device wifi connect`` itself blocks until the
attempt succeeds or fails and reports the real outcome; a failure here
just means the existing connection (if any) was left alone. This matters
more than almost anything else in this module: a bad SSID/password
submitted remotely must not strand the admin session that's using WiFi to
reach the dashboard at all.
"""

from __future__ import annotations

import asyncio

_SCAN_FIELDS = "SSID,SIGNAL,SECURITY,IN-USE"
_STATUS_FIELDS = "DEVICE,TYPE,STATE,CONNECTION"


async def _run_nmcli(*args: str) -> tuple[int, str]:
    """Run ``sudo nmcli <args>``; return ``(returncode, combined
    stdout+stderr)``."""
    process = await asyncio.create_subprocess_exec(
        "sudo", "nmcli", *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    output = await process.stdout.read() if process.stdout else b""
    returncode = await process.wait()
    return returncode, output.decode("utf-8", errors="replace").strip()


def _split_terse_line(line: str, field_count: int) -> list[str]:
    """Split one line of ``nmcli -t`` (terse, colon-separated) output.

    nmcli escapes a literal ``:`` or ``\\`` *within* a field as ``\\:``/
    ``\\\\`` in terse mode specifically so fields (an SSID can itself
    contain a colon) don't get mis-split -- a plain ``line.split(':')``
    would silently corrupt any such SSID into two fields instead of one.
    Splits only on unescaped colons, then un-escapes each field.
    """
    fields: list[str] = []
    current: list[str] = []
    escaped = False
    for ch in line:
        if escaped:
            current.append(ch)
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch == ":":
            fields.append("".join(current))
            current = []
        else:
            current.append(ch)
    fields.append("".join(current))
    # A short/malformed line (fewer real fields than expected) pads with
    # "" rather than raising -- one bad row from a flaky scan shouldn't
    # take down the whole list.
    while len(fields) < field_count:
        fields.append("")
    return fields[:field_count]


async def wifi_scan() -> list[dict]:
    """Rescan and list nearby WiFi networks: ``[{ssid, signal, security,
    in_use}, ...]``, one entry per network nmcli reports (already
    deduplicated by nmcli itself -- it merges multiple APs of the same
    SSID into one row, keeping the strongest signal)."""
    _rc, out = await _run_nmcli(
        "-t", "-f", _SCAN_FIELDS, "device", "wifi", "list", "--rescan", "yes",
    )
    networks = []
    for line in out.splitlines():
        if not line.strip():
            continue
        ssid, signal, security, in_use = _split_terse_line(line, 4)
        if not ssid:
            continue  # a hidden network with no broadcast SSID -- can't connect to it by name anyway
        networks.append({
            "ssid": ssid,
            "signal": int(signal) if signal.isdigit() else None,
            "security": security or None,  # "" means open/no security
            "in_use": in_use == "*",
        })
    return networks


async def wifi_status() -> dict | None:
    """The wifi device's current state: ``{device, state, connection}``,
    or ``None`` if this box has no wifi device at all (Ethernet-only
    carriers, or wifi disabled in raspi-config)."""
    _rc, out = await _run_nmcli("-t", "-f", _STATUS_FIELDS, "device", "status")
    for line in out.splitlines():
        if not line.strip():
            continue
        device, dev_type, state, connection = _split_terse_line(line, 4)
        if dev_type != "wifi":
            continue
        return {
            "device": device,
            "state": state,
            "connection": connection or None,
        }
    return None


async def wifi_connect(ssid: str, password: str) -> tuple[int, str]:
    """Connect to ``ssid``. Returns ``(returncode, output)`` -- 0 means
    connected, anything else is nmcli's real error text (bad password,
    out of range, ...), with the previous connection (if any) left
    untouched either way."""
    return await _run_nmcli("device", "wifi", "connect", ssid, "password", password)
