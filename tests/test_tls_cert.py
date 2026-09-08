"""Tests for the dashboard's self-signed TLS cert (src/tls_cert.py)."""

from __future__ import annotations

import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cryptography import x509

from src import tls_cert


class TestCollectSanEntries(unittest.TestCase):
    def test_includes_localhost_and_loopback(self) -> None:
        with mock.patch.object(tls_cert, "_local_ip_addresses", return_value=[]):
            ips, dns_names = tls_cert.collect_san_entries()
        self.assertIn("127.0.0.1", ips)
        self.assertIn("localhost", dns_names)

    def test_includes_every_hostname_ip(self) -> None:
        with mock.patch.object(
            tls_cert, "_local_ip_addresses",
            return_value=["192.168.4.3", "100.101.102.103"],
        ):
            ips, _ = tls_cert.collect_san_entries()
        self.assertIn("192.168.4.3", ips)  # LAN
        self.assertIn("100.101.102.103", ips)  # Tailscale-style VPN IP

    def test_hostname_dot_local_not_doubled_up(self) -> None:
        # Confirmed live on macOS: socket.gethostname() already returns
        # "name.local" there (unlike Raspberry Pi OS, which returns just
        # the short name) -- must not become "name.local.local".
        with mock.patch.object(tls_cert, "_local_ip_addresses", return_value=[]), \
             mock.patch.object(tls_cert.socket, "gethostname", return_value="sensecap.local"):
            _, dns_names = tls_cert.collect_san_entries()
        self.assertIn("sensecap", dns_names)
        self.assertIn("sensecap.local", dns_names)
        self.assertNotIn("sensecap.local.local", dns_names)

    def test_short_hostname_gets_dot_local_appended(self) -> None:
        with mock.patch.object(tls_cert, "_local_ip_addresses", return_value=[]), \
             mock.patch.object(tls_cert.socket, "gethostname", return_value="sensecap"):
            _, dns_names = tls_cert.collect_san_entries()
        self.assertIn("sensecap", dns_names)
        self.assertIn("sensecap.local", dns_names)


class TestEnsureCert(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.cert_path = Path(self.tmp.name) / "tls" / "cert.pem"
        self.key_path = Path(self.tmp.name) / "tls" / "key.pem"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _fixed_sans(self, ips, dns_names):
        return mock.patch.object(
            tls_cert, "collect_san_entries", return_value=(ips, dns_names),
        )

    def test_generates_cert_and_key_when_none_exist(self) -> None:
        with self._fixed_sans(["127.0.0.1", "192.168.4.3"], ["localhost", "sensecap"]):
            tls_cert.ensure_cert(str(self.cert_path), str(self.key_path))
        self.assertTrue(self.cert_path.is_file())
        self.assertTrue(self.key_path.is_file())

    def test_key_file_is_not_world_or_group_readable(self) -> None:
        with self._fixed_sans(["127.0.0.1"], ["localhost"]):
            tls_cert.ensure_cert(str(self.cert_path), str(self.key_path))
        mode = stat.S_IMODE(self.key_path.stat().st_mode)
        self.assertEqual(mode, 0o600)

    def test_cert_san_matches_requested_addresses(self) -> None:
        with self._fixed_sans(
            ["127.0.0.1", "192.168.4.3", "100.101.102.103"],
            ["localhost", "sensecap", "sensecap.local"],
        ):
            tls_cert.ensure_cert(str(self.cert_path), str(self.key_path))
        cert = x509.load_pem_x509_certificate(self.cert_path.read_bytes())
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        ips = [str(ip) for ip in san.get_values_for_type(x509.IPAddress)]
        dns_names = list(san.get_values_for_type(x509.DNSName))
        self.assertEqual(set(ips), {"127.0.0.1", "192.168.4.3", "100.101.102.103"})
        self.assertEqual(set(dns_names), {"localhost", "sensecap", "sensecap.local"})

    def test_does_not_regenerate_when_addresses_unchanged(self) -> None:
        with self._fixed_sans(["127.0.0.1"], ["localhost"]):
            tls_cert.ensure_cert(str(self.cert_path), str(self.key_path))
            first_key_bytes = self.key_path.read_bytes()
            tls_cert.ensure_cert(str(self.cert_path), str(self.key_path))
            second_key_bytes = self.key_path.read_bytes()
        # A fresh key is generated every call to _generate() -- if the
        # bytes are identical, the second ensure_cert() call was a no-op.
        self.assertEqual(first_key_bytes, second_key_bytes)

    def test_regenerates_when_an_ip_is_added(self) -> None:
        with self._fixed_sans(["127.0.0.1"], ["localhost"]):
            tls_cert.ensure_cert(str(self.cert_path), str(self.key_path))
            first_key_bytes = self.key_path.read_bytes()
        with self._fixed_sans(["127.0.0.1", "192.168.4.3"], ["localhost"]):
            tls_cert.ensure_cert(str(self.cert_path), str(self.key_path))
            second_key_bytes = self.key_path.read_bytes()
        self.assertNotEqual(first_key_bytes, second_key_bytes)
        cert = x509.load_pem_x509_certificate(self.cert_path.read_bytes())
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        ips = [str(ip) for ip in san.get_values_for_type(x509.IPAddress)]
        self.assertIn("192.168.4.3", ips)

    def test_regenerates_when_a_hostname_changes(self) -> None:
        with self._fixed_sans(["127.0.0.1"], ["localhost", "sensecap"]):
            tls_cert.ensure_cert(str(self.cert_path), str(self.key_path))
            first_key_bytes = self.key_path.read_bytes()
        with self._fixed_sans(["127.0.0.1"], ["localhost", "sensecap2"]):
            tls_cert.ensure_cert(str(self.cert_path), str(self.key_path))
            second_key_bytes = self.key_path.read_bytes()
        self.assertNotEqual(first_key_bytes, second_key_bytes)

    def test_regenerates_when_key_file_missing_but_cert_present(self) -> None:
        # An operator (or a backup/restore) could plausibly copy the cert
        # without the key, or the key could be deleted independently --
        # a cert with no matching key is useless to uvicorn, so this must
        # not be treated as "already up to date".
        with self._fixed_sans(["127.0.0.1"], ["localhost"]):
            tls_cert.ensure_cert(str(self.cert_path), str(self.key_path))
        self.key_path.unlink()
        with self._fixed_sans(["127.0.0.1"], ["localhost"]):
            tls_cert.ensure_cert(str(self.cert_path), str(self.key_path))
        self.assertTrue(self.key_path.is_file())

    def test_corrupt_existing_cert_triggers_regeneration(self) -> None:
        self.cert_path.parent.mkdir(parents=True, exist_ok=True)
        self.cert_path.write_bytes(b"not a real certificate")
        with self._fixed_sans(["127.0.0.1"], ["localhost"]):
            tls_cert.ensure_cert(str(self.cert_path), str(self.key_path))
        cert = x509.load_pem_x509_certificate(self.cert_path.read_bytes())
        self.assertIsNotNone(cert)


if __name__ == "__main__":
    unittest.main()
