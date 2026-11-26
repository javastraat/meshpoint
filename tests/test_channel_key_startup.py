"""A malformed saved Meshtastic channel PSK must fail closed, not crash startup.

Upstream KMX415/meshpoint #186 (c2e6c495). A wrong Base64 PSK in local.yaml
used to raise while loading channel keys; the channel must instead keep its
slot as "unavailable" so later channels keep their indices, TX on it must
refuse, and the Channels editor must reject a bad key before saving it.
"""

from __future__ import annotations

import asyncio
import base64
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from src.config import TransmitConfig
from src.decode.crypto_service import CryptoService
from src.transmit.tx_service import TxService

PRIVATE = bytes(range(16))
VALID = base64.b64encode(PRIVATE).decode()
INVALID = VALID.rstrip("=")  # wrong padding


def _crypto_with_bad_slot() -> CryptoService:
    crypto = CryptoService()
    crypto.add_channel_key("Broken", INVALID)
    crypto.add_channel_key("Working", VALID)
    return crypto


def _tx(crypto: CryptoService) -> TxService:
    return TxService(
        crypto=crypto,
        transmit_config=TransmitConfig(enabled=True, node_id=1234),
        primary_channel_name="LongFast",
        persist_derived_node_id=False,
    )


class TestCryptoBadSlot(unittest.TestCase):
    def test_bad_psk_does_not_raise_and_keeps_its_slot(self) -> None:
        crypto = CryptoService()
        with self.assertLogs("src.decode.crypto_service", level="WARNING") as logs:
            crypto.add_channel_key("Broken", INVALID)
        crypto.add_channel_key("Working", VALID)
        self.assertIsNone(crypto.get_channel_key("Broken"))
        keys = crypto.get_all_keys()
        self.assertEqual(keys[1:3], [None, PRIVATE])
        self.assertNotIn(INVALID, " ".join(logs.output))

    def test_line_wrapped_base64_is_still_accepted(self) -> None:
        crypto = CryptoService()
        crypto.add_channel_key("Wrapped", VALID[:8] + "\n" + VALID[8:])
        self.assertEqual(crypto.get_channel_key("Wrapped"), PRIVATE)

    def test_meshcore_key_with_same_name_does_not_heal_the_slot(self) -> None:
        crypto = CryptoService()
        crypto.add_channel_key("Broken", INVALID)
        crypto.add_meshcore_channel_key("Broken", "11" * 16)
        self.assertIsNone(crypto.get_channel_key("Broken"))
        self.assertIn(bytes.fromhex("11" * 16), crypto.get_all_keys())

    def test_clear_channel_keys_drops_meshcore_keys_too(self) -> None:
        crypto = CryptoService()
        crypto.add_meshcore_channel_key("Mc", "22" * 16)
        crypto.clear_channel_keys()
        self.assertEqual(crypto.get_all_keys(), [crypto._default_key])


class TestStartupLoad(unittest.TestCase):
    def test_setup_channel_keys_survives_a_bad_key(self) -> None:
        from src.coordinator import PipelineCoordinator

        crypto = CryptoService()
        fake = SimpleNamespace(
            _config=SimpleNamespace(
                meshtastic=SimpleNamespace(channel_keys={"Broken": INVALID, "Working": VALID}),
                meshcore=SimpleNamespace(channel_keys={"Broken": "11" * 16}),
                lorawan=SimpleNamespace(devices={}),
            ),
            _crypto=crypto,
            _lorawan_keystore=Mock(),
        )
        PipelineCoordinator._setup_channel_keys(fake)
        self.assertIsNone(crypto.get_channel_key("Broken"))
        self.assertEqual(crypto.get_channel_key("Working"), PRIVATE)


class TestTxFailsClosed(unittest.TestCase):
    def test_send_on_unavailable_channel_is_refused(self) -> None:
        tx = _tx(_crypto_with_bad_slot())
        tx._resolve_serial_send_source = AsyncMock()
        tx._get_builder = Mock()
        result = asyncio.run(tx.send_text("hi", 123, channel=1))
        self.assertFalse(result.success)
        self.assertIn("Broken", result.error)
        tx._resolve_serial_send_source.assert_not_awaited()
        tx._get_builder.assert_not_called()

    def test_resolve_channel(self) -> None:
        tx = _tx(_crypto_with_bad_slot())
        self.assertEqual(tx._resolve_channel(2)[1], PRIVATE)
        self.assertNotEqual(tx._resolve_channel(0)[1], PRIVATE)
        with self.assertRaises(ValueError):
            tx._resolve_channel(1)
        with self.assertRaises(ValueError):
            tx._resolve_channel(9)

    def test_reply_on_an_unknown_hash_never_uses_the_primary_key(self) -> None:
        tx = _tx(_crypto_with_bad_slot())
        valid_hash, _ = tx._resolve_channel(2)
        primary_hash, _ = tx._resolve_channel(0)
        self.assertEqual(tx._resolve_channel_by_hash(valid_hash)[1], PRIVATE)
        unknown = next(h for h in range(1, 256) if h not in (valid_hash, primary_hash))
        self.assertIsNone(tx._resolve_channel_by_hash(unknown)[1])

        tx._get_builder = Mock()
        original = Mock(packet_id="00000001", source_id="00000002", channel_hash=unknown)
        self.assertFalse(asyncio.run(tx.send_routing_ack(original)).success)
        tx._get_builder.return_value.build_routing_ack.assert_not_called()


class TestChannelsRoute(unittest.TestCase):
    def setUp(self) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from src.api.auth.dependencies import require_admin, require_auth
        from src.api.auth.jwt_session import ROLE_ADMIN, SessionClaims
        from src.api.routes import config_routes
        from src.config import AppConfig

        self._mod = config_routes
        self.cfg = AppConfig()
        self.crypto = CryptoService()
        config_routes.init_routes(config=self.cfg, crypto=self.crypto)

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "local.yaml"
        os.environ["CONCENTRATOR_CONFIG"] = str(self.path)
        self.addCleanup(os.environ.pop, "CONCENTRATOR_CONFIG", None)

        claims = SessionClaims(subject="admin", role=ROLE_ADMIN, session_version=1)
        app = FastAPI()
        app.dependency_overrides[require_admin] = lambda: claims
        app.dependency_overrides[require_auth] = lambda: claims
        app.include_router(config_routes.router)
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self._mod._config = None
        self._mod._crypto = None

    def test_bad_psk_is_rejected_before_anything_is_saved(self) -> None:
        channels = [
            {"index": 1, "name": "Broken", "psk_b64": INVALID},
            {"index": 2, "name": "Working", "psk_b64": VALID},
        ]
        response = self.client.put("/api/config/channels", json={"channels": channels})
        self.assertEqual(response.status_code, 400)
        self.assertNotIn(INVALID, response.text)
        self.assertFalse(self.path.exists())
        self.assertEqual(self.cfg.meshtastic.channel_keys, {})

        channels[0]["psk_b64"] = VALID
        response = self.client.put("/api/config/channels", json={"channels": channels})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.crypto.get_channel_key("Broken"), PRIVATE)

    def test_channel_list_flags_an_unavailable_key(self) -> None:
        self.cfg.meshtastic.channel_keys = {"Broken": INVALID, "Working": VALID}
        for name, key in self.cfg.meshtastic.channel_keys.items():
            self.crypto.add_channel_key(name, key)
        rows = {row["name"]: row for row in self._mod._build_channel_list(self.cfg.meshtastic)}
        self.assertTrue(rows["Broken"]["key_unavailable"])
        self.assertFalse(rows["Working"]["key_unavailable"])


if __name__ == "__main__":
    unittest.main()
