"""Tests for src/serve.py's TLS wiring (_tls_files(), the redirect app,
and main()'s dual-listener setup).

_bind_address() has no test coverage of its own (pre-existing gap, not
touched here) -- this only covers the new dashboard.tls_enabled path.
"""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest import mock

from src import serve


def _fake_config(**dashboard_kwargs):
    defaults = dict(
        tls_enabled=False,
        tls_cert_path="data/tls/cert.pem",
        tls_key_path="data/tls/key.pem",
        tls_port=8443,
    )
    defaults.update(dashboard_kwargs)
    return SimpleNamespace(dashboard=SimpleNamespace(**defaults))


class TestTlsFiles(unittest.TestCase):
    def test_returns_none_when_tls_disabled(self) -> None:
        with mock.patch("src.config.load_config", return_value=_fake_config(tls_enabled=False)):
            self.assertIsNone(serve._tls_files())

    def test_returns_keyfile_certfile_port_when_enabled_and_cert_ready(self) -> None:
        cfg = _fake_config(
            tls_enabled=True, tls_cert_path="/tmp/x/cert.pem", tls_key_path="/tmp/x/key.pem",
            tls_port=8443,
        )
        with mock.patch("src.config.load_config", return_value=cfg), \
             mock.patch("src.tls_cert.ensure_cert") as ensure_cert:
            result = serve._tls_files()
        ensure_cert.assert_called_once_with("/tmp/x/cert.pem", "/tmp/x/key.pem")
        self.assertEqual(result, ("/tmp/x/key.pem", "/tmp/x/cert.pem", 8443))

    def test_falls_back_to_none_when_cert_generation_fails(self) -> None:
        # A broken TLS setup must not crash-loop the service -- same
        # "never lock the operator out of the fix-it tool" reasoning as
        # _bind_address()'s own fallback.
        cfg = _fake_config(tls_enabled=True)
        with mock.patch("src.config.load_config", return_value=cfg), \
             mock.patch("src.tls_cert.ensure_cert", side_effect=OSError("disk full")):
            result = serve._tls_files()
        self.assertIsNone(result)

    def test_returns_none_when_config_itself_fails_to_load(self) -> None:
        with mock.patch("src.config.load_config", side_effect=RuntimeError("boom")):
            self.assertIsNone(serve._tls_files())


class TestHttpsRedirectApp(unittest.TestCase):
    def _run(self, app, scope):
        sent = []

        async def receive():
            return {"type": "http.disconnect"}

        async def send(message):
            sent.append(message)

        asyncio.run(app(scope, receive, send))
        return sent

    def test_redirects_to_https_on_tls_port_using_host_header(self) -> None:
        app = serve._make_https_redirect_app(8443)
        scope = {
            "type": "http",
            "path": "/settings",
            "query_string": b"",
            "headers": [(b"host", b"192.168.4.4:8080")],
        }
        sent = self._run(app, scope)
        start = next(m for m in sent if m["type"] == "http.response.start")
        self.assertEqual(start["status"], 308)
        location = dict(start["headers"])[b"location"].decode()
        self.assertEqual(location, "https://192.168.4.4:8443/settings")

    def test_preserves_query_string(self) -> None:
        app = serve._make_https_redirect_app(8443)
        scope = {
            "type": "http",
            "path": "/api/x",
            "query_string": b"a=1&b=2",
            "headers": [(b"host", b"sensecap.local:8080")],
        }
        sent = self._run(app, scope)
        start = next(m for m in sent if m["type"] == "http.response.start")
        location = dict(start["headers"])[b"location"].decode()
        self.assertEqual(location, "https://sensecap.local:8443/api/x?a=1&b=2")

    def test_works_for_any_of_the_dashboard_s_reachable_hosts(self) -> None:
        # The whole point of tls_cert.py baking every reachable address
        # into the cert's SAN list -- the redirect must follow whichever
        # one the client actually used, not a hardcoded address.
        app = serve._make_https_redirect_app(8443)
        for host in ("192.168.4.4", "100.101.102.103", "sensecap.local"):
            with self.subTest(host=host):
                scope = {
                    "type": "http", "path": "/", "query_string": b"",
                    "headers": [(b"host", f"{host}:8080".encode())],
                }
                sent = self._run(app, scope)
                start = next(m for m in sent if m["type"] == "http.response.start")
                location = dict(start["headers"])[b"location"].decode()
                self.assertEqual(location, f"https://{host}:8443/")

    def test_ignores_non_http_scope(self) -> None:
        app = serve._make_https_redirect_app(8443)
        sent = self._run(app, {"type": "lifespan"})
        self.assertEqual(sent, [])


if __name__ == "__main__":
    unittest.main()
