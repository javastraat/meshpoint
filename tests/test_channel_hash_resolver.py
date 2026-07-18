"""Channel hash resolver for inbound Meshtastic broadcast routing (#89)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth.dependencies import require_admin, require_auth
from src.api.auth.jwt_session import ROLE_ADMIN, SessionClaims

from src.api.channel_hash_resolver import ChannelHashResolver
from src.api import channel_hash_resolver as resolver_module
from src.api.routes import config_routes as config_module
from src.config import AppConfig, MeshtasticConfig
from src.decode.crypto_service import CryptoService
from src.models.packet import Protocol


PRIVATE_PSK_B64 = "wLvS00jm+SlCkdkZ6DRZXvLoqoSgPT+3vh8zX+MJoyQ="


def _build_config_app() -> FastAPI:
    app = FastAPI()
    app.include_router(config_module.router)
    # Routes are auth-gated (fork viewer lockdown); satisfy the dependencies
    # with an admin session so these tests exercise the route logic itself.
    app.dependency_overrides[require_admin] = lambda: SessionClaims("test-admin", ROLE_ADMIN, 1)
    app.dependency_overrides[require_auth] = lambda: SessionClaims("test-admin", ROLE_ADMIN, 1)
    return app


def _reset_config_state() -> None:
    config_module._config = None
    config_module._crypto = None
    config_module._tx_service = None
    config_module._channel_hash_resolver = None


class TestChannelHashResolver(unittest.TestCase):
    def setUp(self) -> None:
        self.crypto = CryptoService()
        self.resolver = ChannelHashResolver()

    def test_rebuild_maps_primary_and_private_channel(self) -> None:
        self.crypto.add_channel_key("BayMesh", PRIVATE_PSK_B64)
        self.resolver.rebuild(self.crypto, "LongFast", {"BayMesh": PRIVATE_PSK_B64})

        primary_hash = self.crypto.compute_channel_hash(
            "LongFast", self.crypto.get_all_keys()[0]
        )
        private_hash = self.crypto.compute_channel_hash(
            "BayMesh", self.crypto.get_all_keys()[1]
        )

        self.assertEqual(self.resolver.lookup(primary_hash), 0)
        self.assertEqual(self.resolver.lookup(private_hash), 1)

    def test_rebuild_is_immune_to_crypto_keys_ordering_drift(self) -> None:
        """F5-hardening: rebuild() must look up each channel's key by
        NAME in crypto._keys, not by POSITION in crypto.get_all_keys().
        This reproduces the exact divergence confirmed in production
        (resolver's map vs TX's own hash computation disagreeing about
        which hash belongs to which index, 0xC9 vs 0x71) -- crypto._keys
        populated in one order (e.g. by coordinator._setup_channel_keys
        at startup) while the config's channel_keys dict handed to
        rebuild() lists the same channels in a different order (e.g.
        after a live PUT /api/config/channels reorder). A positional
        pairing would silently compute the wrong channel's hash for a
        given index; a name-keyed lookup cannot."""
        self.crypto.add_channel_key("Zulu", PRIVATE_PSK_B64)
        self.crypto.add_channel_key("Alpha", "AQ==")

        # channel_keys dict lists them in the OPPOSITE order to how
        # they were added to crypto -- exactly the drift scenario.
        self.resolver.rebuild(
            self.crypto, "LongFast", {"Alpha": "AQ==", "Zulu": PRIVATE_PSK_B64},
        )

        alpha_hash = self.crypto.compute_channel_hash(
            "Alpha", self.crypto._keys["Alpha"]
        )
        zulu_hash = self.crypto.compute_channel_hash(
            "Zulu", self.crypto._keys["Zulu"]
        )
        self.assertEqual(self.resolver.lookup(alpha_hash), 1)
        self.assertEqual(self.resolver.lookup(zulu_hash), 2)

    def test_rebuild_excludes_keys_not_in_the_meshtastic_channel_list(self) -> None:
        """crypto._keys is shared storage for BOTH Meshtastic and
        MeshCore channel keys (coordinator._setup_channel_keys adds
        both into the same CryptoService instance) -- rebuild() must
        only map hashes for channels actually present in the passed
        Meshtastic channel_keys dict, never every key crypto happens
        to hold, or a MeshCore channel key would get mis-hashed in as
        if it were an extra Meshtastic channel index."""
        self.crypto.add_channel_key("BayMesh", PRIVATE_PSK_B64)
        self.crypto.add_channel_key("McPublic", PRIVATE_PSK_B64)  # MeshCore's

        self.resolver.rebuild(self.crypto, "LongFast", {"BayMesh": PRIVATE_PSK_B64})

        self.assertEqual(len(self.resolver.mapping), 2)  # primary + BayMesh only
        mc_hash = self.crypto.compute_channel_hash(
            "McPublic", self.crypto._keys["McPublic"]
        )
        self.assertIsNone(self.resolver.lookup(mc_hash))

    def test_unknown_hash_returns_none_and_warns_once(self) -> None:
        """Unmapped hashes must never silently fall back to channel 0
        (LongFast) -- that masked a real config mismatch for weeks by
        blending unmapped traffic invisibly into LongFast's own
        history. Callers route a None result to their own distinct,
        visible bucket instead (see on_text_packet in server.py)."""
        self.resolver.rebuild(self.crypto, "LongFast", {})
        with patch.object(resolver_module.logger, "warning") as warn:
            self.assertIsNone(self.resolver.lookup(0xAB))
            self.assertIsNone(self.resolver.lookup(0xAB))
            warn.assert_called_once()

    def test_rebuild_after_crypto_refresh_updates_private_index(self) -> None:
        self.resolver.rebuild(self.crypto, "LongFast", {})
        private_hash_before = 0x99

        self.crypto.clear_channel_keys()
        self.crypto.add_channel_key("BayMesh", PRIVATE_PSK_B64)
        self.resolver.rebuild(self.crypto, "LongFast", {"BayMesh": PRIVATE_PSK_B64})

        private_hash = self.crypto.compute_channel_hash(
            "BayMesh", self.crypto.get_all_keys()[1]
        )
        self.assertEqual(self.resolver.lookup(private_hash), 1)
        self.assertIsNone(self.resolver.lookup(private_hash_before))


class TestChannelHashResolverPutChannels(unittest.TestCase):
    def setUp(self) -> None:
        _reset_config_state()
        self.crypto = CryptoService()
        self.resolver = ChannelHashResolver()
        self.config = AppConfig()
        self.config.meshtastic = MeshtasticConfig(
            primary_channel_name="LongFast",
            default_key_b64="AQ==",
            channel_keys={},
        )
        config_module.init_routes(
            config=self.config,
            crypto=self.crypto,
            channel_hash_resolver=self.resolver,
        )
        self.client = TestClient(_build_config_app())

    def tearDown(self) -> None:
        _reset_config_state()

    def test_put_channels_rebuilds_resolver_for_inbound_routing(self) -> None:
        self.resolver.rebuild(self.crypto, "LongFast", {})
        private_hash = self.crypto.compute_channel_hash(
            "BayMesh", self.crypto.get_all_keys()[0]
        )
        # Not configured yet -- must be unmapped, not silently channel 0.
        self.assertIsNone(self.resolver.lookup(private_hash))

        response = self.client.put(
            "/api/config/channels",
            json={
                "channels": [
                    {"index": 0, "name": "LongFast", "enabled": True},
                    {
                        "index": 1,
                        "name": "BayMesh",
                        "psk_b64": PRIVATE_PSK_B64,
                        "enabled": True,
                    },
                ],
            },
        )
        self.assertEqual(response.status_code, 200)

        private_hash = self.crypto.compute_channel_hash(
            "BayMesh", self.crypto.get_all_keys()[1]
        )
        self.assertEqual(self.resolver.lookup(private_hash), 1)

        node_id = f"broadcast:{Protocol.MESHTASTIC.value}:1"
        self.assertEqual(node_id, "broadcast:meshtastic:1")


if __name__ == "__main__":
    unittest.main()
