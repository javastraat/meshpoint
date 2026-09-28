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


_IP4_FIELDS = "IP4.ADDRESS,IP4.GATEWAY,IP4.DNS"


async def _ip4_info(device: str) -> dict:
    """IPv4 address/gateway/DNS for *device*: ``{address, gateway,
    dns}`` -- ``address``/``gateway`` are ``None`` and ``dns`` is ``[]``
    when not connected (nmcli just returns those fields empty, not an
    error). Deliberately not run through ``_split_terse_line`` -- unlike
    the fixed-field queries above, ``nmcli device show``'s terse output
    is ``key:value`` per line with a *variable* number of lines for a
    multi-valued property (``IP4.DNS[1]``, ``IP4.DNS[2]``, ...), so
    parsing has to group by (de-indexed) key instead of assuming a
    fixed field count. A plain first-colon split is safe here
    specifically because IPv4 addresses/CIDR never contain a literal
    ``:`` themselves, unlike the SSID field elsewhere in this module.
    """
    _rc, out = await _run_nmcli("-t", "-f", _IP4_FIELDS, "device", "show", device)
    address = None
    gateway = None
    dns: list[str] = []
    for line in out.splitlines():
        key, sep, value = line.partition(":")
        if not sep:
            continue
        if key.startswith("IP4.ADDRESS"):
            address = value or address
        elif key == "IP4.GATEWAY":
            gateway = value or None
        elif key.startswith("IP4.DNS") and value:
            dns.append(value)
    return {"address": address, "gateway": gateway, "dns": dns}


async def _device_status(dev_type: str) -> dict | None:
    """The first device of *dev_type* ("wifi" or "ethernet")'s current
    state and IPv4 config: ``{device, state, connection, address,
    gateway, dns}``, or ``None`` if this box has no device of that type
    at all. ``address``/``gateway``/``dns`` are empty when not
    connected. Shared by :func:`wifi_status` and
    :func:`ethernet_status` -- same `nmcli device status` query either
    way, just a different type filter on the same output."""
    _rc, out = await _run_nmcli("-t", "-f", _STATUS_FIELDS, "device", "status")
    for line in out.splitlines():
        if not line.strip():
            continue
        device, found_type, state, connection = _split_terse_line(line, 4)
        if found_type != dev_type:
            continue
        ip4 = await _ip4_info(device)
        return {
            "device": device,
            "state": state,
            "connection": connection or None,
            **ip4,
        }
    return None


async def wifi_status() -> dict | None:
    """The wifi device's current state and IPv4 config -- see
    :func:`_device_status`. ``None`` if this box has no wifi device at
    all (Ethernet-only carriers, or wifi disabled in raspi-config)."""
    return await _device_status("wifi")


async def ethernet_status() -> dict | None:
    """The (first) ethernet device's current state and IPv4 config --
    see :func:`_device_status`. ``None`` if this box has no ethernet
    device at all (WiFi-only carriers)."""
    return await _device_status("ethernet")


async def wifi_connect(ssid: str, password: str = "") -> tuple[int, str]:
    """Connect to ``ssid``. Returns ``(returncode, output)`` -- 0 means
    connected, anything else is nmcli's real error text (bad password,
    out of range, ...), with the previous connection (if any) left
    untouched either way.

    An empty ``password`` omits the ``password`` argument entirely
    rather than passing an empty string -- confirmed live (real error:
    "802-11-wireless-security.key-mgmt: property is missing") that
    nmcli treats an *explicit* empty password as "build a connection
    profile with this (invalid, blank) PSK" rather than "no password
    given". Passing no `password` arg at all instead makes nmcli either
    reuse an already-saved profile's real stored credentials (the
    "reconnect to a known network without retyping the password" case)
    or connect outright if the network is genuinely open -- both of
    which a *blank* password was actually trying to mean.

    A *non-empty* password first deletes any existing connection
    profile of the same name -- also confirmed live, on a different
    network, same error text: `nmcli device wifi connect` doesn't
    always build a fresh profile, it can reuse/update an existing one
    of the same SSID, and a profile left over broken from an earlier
    attempt (this SSID may well have one from testing the empty-
    password bug above, before it was fixed) can still be missing its
    security fields after only its password gets updated. Deleting
    first guarantees a clean, correctly-typed profile every time a
    real password is actually being supplied -- never done when
    password is empty, since that path explicitly wants to *keep*
    whatever's already saved, not wipe it. "no such connection" from
    the delete is not an error, just nothing to clean up.
    """
    if password:
        await _run_nmcli("connection", "delete", ssid)
        args = ["device", "wifi", "connect", ssid, "password", password]
    else:
        args = ["device", "wifi", "connect", ssid]
    return await _run_nmcli(*args)
