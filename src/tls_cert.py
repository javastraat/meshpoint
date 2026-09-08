"""Self-signed TLS cert for the dashboard's optional HTTPS mode
(``dashboard.tls_enabled``).

There's no real DNS name to get a CA-signed cert against for a LAN
device -- self-signed is the only option, so this module owns the whole
lifecycle: figure out every address the dashboard might actually be
reached at (every IP `hostname -I` reports -- LAN, Tailscale/VPN,
whatever's live -- plus the machine's hostname and its ``.local`` mDNS
name), bake all of them into the cert's ``subjectAltName``, and
regenerate whenever that set changes (DHCP renewal, Tailscale connect/
disconnect, a hostname change) so the cert never silently goes stale
relative to what a browser is actually connecting to. An out-of-date
SAN list means a *second*, more confusing browser warning ("certificate
doesn't match this address") stacked on top of the expected
self-signed-cert one.

Browsers still show that expected "this certificate is self-signed"
warning on first visit to each address -- that's inherent to not having
a real CA, not a bug here.

``cryptography`` is already a project dependency (requirements.txt), so
this needs no new package and no ``openssl`` subprocess for the cert
itself -- only ``hostname -I`` (present on any Debian/Raspberry Pi OS)
for address discovery, same approach ``src/log_format.py``'s
``_local_ip()`` already uses for the startup banner.
"""

from __future__ import annotations

import datetime
import ipaddress
import logging
import socket
import subprocess
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

logger = logging.getLogger(__name__)

# Regenerated on any address change anyway, so a long lifetime just
# means "won't expire out from under a box nobody's looked at in years."
_CERT_LIFETIME_DAYS = 3650


def _local_ip_addresses() -> list[str]:
    """Every IP bound to any interface -- LAN, Tailscale/VPN, whatever's
    live. Same ``hostname -I`` call as ``log_format._local_ip()``, but
    keeping every address instead of only the first."""
    try:
        result = subprocess.run(
            ["hostname", "-I"], capture_output=True, text=True, timeout=2,
        )
        return result.stdout.split()
    except Exception:
        logger.debug(
            "hostname -I failed; TLS cert will have no LAN/VPN IP SANs",
            exc_info=True,
        )
        return []


def collect_san_entries() -> tuple[list[str], list[str]]:
    """(ip_addresses, dns_names) to bake into the cert's
    ``subjectAltName`` -- every address this dashboard might actually
    be reached at right now."""
    ips = list(dict.fromkeys(["127.0.0.1", *_local_ip_addresses()]))
    # socket.gethostname() already includes ".local" on some platforms
    # (confirmed live: macOS) but not others (Raspberry Pi OS returns
    # just the short name) -- normalize to the short form first so the
    # ".local" variant below is never doubled up into "x.local.local".
    hostname = socket.gethostname()
    if hostname.endswith(".local"):
        hostname = hostname[: -len(".local")]
    dns_names = list(dict.fromkeys(["localhost", hostname, f"{hostname}.local"]))
    return ips, dns_names


def _san_extension(ips: list[str], dns_names: list[str]) -> x509.SubjectAlternativeName:
    general_names: list[x509.GeneralName] = []
    for ip in ips:
        try:
            general_names.append(x509.IPAddress(ipaddress.ip_address(ip)))
        except ValueError:
            continue  # not a valid IP literal -- skip rather than fail cert generation
    for name in dns_names:
        general_names.append(x509.DNSName(name))
    return x509.SubjectAlternativeName(general_names)


def _existing_san_entries(cert_path: Path) -> tuple[list[str], list[str]] | None:
    """The (ips, dns_names) already baked into the cert on disk, or
    ``None`` if there's no cert yet or it can't be read (corrupt file,
    old format, whatever -- any read failure just means "regenerate")."""
    if not cert_path.is_file():
        return None
    try:
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
        san = cert.extensions.get_extension_for_class(
            x509.SubjectAlternativeName,
        ).value
        ips = [str(ip) for ip in san.get_values_for_type(x509.IPAddress)]
        dns_names = list(san.get_values_for_type(x509.DNSName))
        return ips, dns_names
    except Exception:
        logger.debug(
            "could not read existing TLS cert %s; will regenerate",
            cert_path,
            exc_info=True,
        )
        return None


def _generate(
    cert_path: Path, key_path: Path, ips: list[str], dns_names: list[str],
) -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "meshpoint")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        # Backdated slightly so a cert generated seconds ago isn't
        # rejected as "not yet valid" by a client with a clock a
        # touch ahead of this box's.
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=_CERT_LIFETIME_DAYS))
        .add_extension(_san_extension(ips, dns_names), critical=False)
        .sign(key, hashes.SHA256())
    )

    cert_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.parent.mkdir(parents=True, exist_ok=True)
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ),
    )
    key_path.chmod(0o600)
    logger.info(
        "Generated self-signed TLS cert %s (SANs: %s)",
        cert_path,
        ", ".join([*ips, *dns_names]),
    )


def ensure_cert(cert_path_str: str, key_path_str: str) -> None:
    """Called once at startup when ``dashboard.tls_enabled`` is true.
    Generates a cert if none exists yet, or regenerates it if the set
    of addresses this box is reachable at has drifted from what's
    already baked in."""
    cert_path = Path(cert_path_str)
    key_path = Path(key_path_str)

    wanted_ips, wanted_dns = collect_san_entries()
    existing = _existing_san_entries(cert_path)

    if existing is not None and key_path.is_file():
        existing_ips, existing_dns = existing
        if set(existing_ips) == set(wanted_ips) and set(existing_dns) == set(wanted_dns):
            return  # already covers everything we're reachable at

    _generate(cert_path, key_path, wanted_ips, wanted_dns)
