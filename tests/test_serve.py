"""Tests for src/serve.py's TLS wiring (_tls_files()).

_bind_address() has no test coverage of its own (pre-existing gap, not
touched here) -- this only covers the new dashboard.tls_enabled path.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from src import serve


def _fake_config(**dashboard_kwargs):
    defaults = dict(
        tls_enabled=False,
        tls_cert_path="data/tls/cert.pem",
        tls_key_path="data/tls/key.pem",
    )
    defaults.update(dashboard_kwargs)
    return SimpleNamespace(dashboard=SimpleNamespace(**defaults))


class TestTlsFiles(unittest.TestCase):
    def test_returns_none_when_tls_disabled(self) -> None:
        with mock.patch("src.config.load_config", return_value=_fake_config(tls_enabled=False)):
            self.assertIsNone(serve._tls_files())

    def test_returns_keyfile_certfile_when_enabled_and_cert_ready(self) -> None:
        cfg = _fake_config(
            tls_enabled=True, tls_cert_path="/tmp/x/cert.pem", tls_key_path="/tmp/x/key.pem",
        )
        with mock.patch("src.config.load_config", return_value=cfg), \
             mock.patch("src.tls_cert.ensure_cert") as ensure_cert:
            result = serve._tls_files()
        ensure_cert.assert_called_once_with("/tmp/x/cert.pem", "/tmp/x/key.pem")
        self.assertEqual(result, ("/tmp/x/key.pem", "/tmp/x/cert.pem"))

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


if __name__ == "__main__":
    unittest.main()
