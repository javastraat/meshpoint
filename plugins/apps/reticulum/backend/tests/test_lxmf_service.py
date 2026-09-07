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
from unittest import mock

from plugins.apps.reticulum.backend import lxmf_service
from plugins.apps.reticulum.backend.lxmf_service import LxmfService, _route_rns_log


def _make_service(**kw) -> LxmfService:
    return LxmfService(
        display_name="Meshpoint",
        reticulum_config_dir="/tmp/does-not-matter/rns_config",
        identity_path="/tmp/does-not-matter/identity",
        lxmf_storage_dir="/tmp/does-not-matter/lxmf",
        message_repo=kw.pop("message_repo", object()),
        peer_repo=kw.pop("peer_repo", object()),
        ws_manager=kw.pop("ws_manager", object()),
        **kw,
    )


class _FakePeerRepo:
    def __init__(self):
        self.recorded = []

    async def record_announce(self, dh, name, aspect):
        self.recorded.append((dh, name, aspect))

    async def list_peers(self, *a, **kw):
        return []


class _FakeWs:
    def __init__(self):
        self.events = []

    async def broadcast(self, event_type, data):
        self.events.append((event_type, data))


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


class TestAnnounceLog(unittest.TestCase):
    """_handle_announce feeds both the roster (roster aspects only) and the
    in-memory Activity ring buffer (every aspect), newest-first."""

    def _svc(self):
        return _make_service(peer_repo=_FakePeerRepo(), ws_manager=_FakeWs())

    def test_starts_empty(self) -> None:
        self.assertEqual(_make_service().announce_log(), [])

    def test_roster_aspect_records_and_broadcasts_both(self) -> None:
        svc = self._svc()
        asyncio.run(svc._handle_announce("aa" * 16, "Bob", "lxmf.delivery"))
        self.assertEqual(len(svc._peer_repo.recorded), 1)
        kinds = [e[0] for e in svc._ws_manager.events]
        self.assertIn("reticulum_announce", kinds)
        self.assertIn("reticulum_peer", kinds)
        log = svc.announce_log()
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0]["display_name"], "Bob")
        self.assertTrue(log[0]["ts"])

    def test_call_audio_is_stream_only(self) -> None:
        svc = self._svc()
        asyncio.run(svc._handle_announce("bb" * 16, "", "call.audio"))
        self.assertEqual(svc._peer_repo.recorded, [])          # not in the roster
        kinds = [e[0] for e in svc._ws_manager.events]
        self.assertEqual(kinds, ["reticulum_announce"])         # stream only
        self.assertEqual(len(svc.announce_log()), 1)

    def test_newest_first_and_capped(self) -> None:
        svc = self._svc()
        for i in range(lxmf_service._ANNOUNCE_LOG_MAX + 25):
            asyncio.run(svc._handle_announce(f"{i:032x}", str(i), "lxmf.delivery"))
        log = svc.announce_log()
        self.assertEqual(len(log), lxmf_service._ANNOUNCE_LOG_MAX)
        self.assertEqual(log[0]["display_name"], str(lxmf_service._ANNOUNCE_LOG_MAX + 24))


class TestInboundNotify(unittest.TestCase):
    def test_notify_inbound_posts_preview_and_sender(self) -> None:
        svc = _make_service(notify_url="https://ntfy.sh/topic")
        with mock.patch.object(lxmf_service.notify, "post") as post:
            asyncio.run(svc._notify_inbound("Bob", "hello there"))
        post.assert_called_once()
        self.assertEqual(post.call_args.kwargs["title"], "LXMF from Bob")
        self.assertEqual(post.call_args.kwargs["body"], "hello there")

    def test_notify_inbound_truncates_long_text(self) -> None:
        svc = _make_service(notify_url="https://x")
        with mock.patch.object(lxmf_service.notify, "post") as post:
            asyncio.run(svc._notify_inbound("Bob", "x" * 500))
        body = post.call_args.kwargs["body"]
        self.assertEqual(len(body), 240)
        self.assertTrue(body.endswith("..."))

    def test_notify_inbound_swallows_errors(self) -> None:
        svc = _make_service(notify_url="https://x")
        with mock.patch.object(lxmf_service.notify, "post", side_effect=RuntimeError):
            asyncio.run(svc._notify_inbound("Bob", "hi"))  # must not raise


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
