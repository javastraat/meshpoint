"""Tests for LxmfService that don't need a real RNS/LXMF stack.

On a machine without ``rns``/``lxmf`` installed (this project's dev Mac),
``RNS``/``LXMF`` are ``None`` and ``.available`` is ``False``. That path --
construction, the not-available guard in ``start()``, ``own_address``
before start -- is what's covered here. The real attach/announce/send
round trip is integration-level (needs rnsd) and lives on the Pi.
"""

from __future__ import annotations

import asyncio
import unittest

from plugins.apps.reticulum.backend import lxmf_service
from plugins.apps.reticulum.backend.lxmf_service import LxmfService, _route_rns_log


def _make_service() -> LxmfService:
    return LxmfService(
        display_name="Meshpoint",
        reticulum_config_dir="/tmp/does-not-matter/rns_config",
        identity_path="/tmp/does-not-matter/identity",
        lxmf_storage_dir="/tmp/does-not-matter/lxmf",
        message_repo=object(),
        peer_repo=object(),
        ws_manager=object(),
    )


@unittest.skipIf(
    lxmf_service.RNS is not None,
    "rns/lxmf installed -- this covers only the not-available path",
)
class TestLxmfServiceWithoutRns(unittest.TestCase):
    def test_available_is_false_without_rns(self) -> None:
        self.assertFalse(_make_service().available)

    def test_own_address_is_none_before_start(self) -> None:
        self.assertIsNone(_make_service().own_address)

    def test_start_is_a_no_op_when_not_available(self) -> None:
        svc = _make_service()
        asyncio.run(svc.start())  # logs a warning, returns -- must not raise
        self.assertIsNone(svc.own_address)

    def test_announce_before_start_raises_runtimeerror(self) -> None:
        with self.assertRaises(RuntimeError):
            _make_service().announce()

    def test_send_message_raises_runtimeerror_when_not_running(self) -> None:
        with self.assertRaises(RuntimeError):
            asyncio.run(_make_service().send_message("abcd", "hi"))


class TestRnsLogBridge(unittest.TestCase):
    """_route_rns_log parses RNS's "[ts] [Level] msg" format, maps the
    level into Python logging, and demotes one known-noisy LXMF line."""

    def test_real_error_stays_at_error(self):
        with self.assertLogs("RNS", level="DEBUG") as cm:
            _route_rns_log("[2026-09-06 14:15:44] [Error] Something actually broke")
        self.assertEqual(len(cm.records), 1)
        self.assertEqual(cm.records[0].levelname, "ERROR")
        self.assertEqual(cm.records[0].getMessage(), "Something actually broke")

    def test_noisy_announce_line_is_demoted_to_debug(self):
        with self.assertLogs("RNS", level="DEBUG") as cm:
            _route_rns_log(
                "[2026-09-06 14:15:44] [Error] Could not decode display name in "
                "included announce data. The contained exception was: "
                "'bool' object has no attribute 'decode'"
            )
        self.assertEqual(cm.records[0].levelname, "DEBUG")

    def test_notice_maps_to_info(self):
        with self.assertLogs("RNS", level="DEBUG") as cm:
            _route_rns_log("[2026-09-06 14:15:44] [Notice] Reticulum Transport enabled")
        self.assertEqual(cm.records[0].levelname, "INFO")

    def test_unparseable_line_falls_back_to_info(self):
        with self.assertLogs("RNS", level="DEBUG") as cm:
            _route_rns_log("a bare line with no prefix")
        self.assertEqual(cm.records[0].levelname, "INFO")
        self.assertEqual(cm.records[0].getMessage(), "a bare line with no prefix")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
