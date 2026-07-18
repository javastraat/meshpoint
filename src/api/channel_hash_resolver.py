"""Meshtastic channel_hash → dashboard channel index for inbound routing."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.decode.crypto_service import CryptoService

logger = logging.getLogger(__name__)


class ChannelHashResolver:
    """Maps Meshtastic header channel_hash bytes to conversation channel index.

    Channel 0 is the primary channel (default PSK + ``primary_channel_name``).
    Additional configured keys are indexed 1..N in ``channel_keys`` order.
    """

    def __init__(self) -> None:
        self._hash_to_index: dict[int, int] = {}
        self._warned_hashes: set[int] = set()

    def rebuild(
        self,
        crypto: CryptoService,
        primary_channel_name: str,
        channel_keys: dict[str, str],
    ) -> None:
        """Rebuild the hash map from live crypto keys and config names.

        Looks up each channel's key by NAME directly in
        ``crypto._keys`` rather than by position in
        ``crypto.get_all_keys()`` -- the same self-consistent
        name-and-key-together principle ``tx_service._resolve_channel``
        already follows, just via a dict lookup instead of also
        iterating ``crypto._keys`` itself (which mixes in MeshCore's
        channel keys too, see ``coordinator._setup_channel_keys`` --
        iterating it directly here would mis-hash MeshCore's keys as
        if they were extra Meshtastic channel indices). The previous
        positional pairing (index N in ``channel_keys`` paired with
        index N in ``get_all_keys()``) assumed those two independently
        populated collections always stayed in the same order, which
        this method is not itself responsible for guaranteeing -- and
        which, per the worklist, once diverged in production: the
        resolver's inbound hash map and TX's own outbound hash
        computation disagreed about which hash belonged to which
        channel index for the exact same config (0xC9 vs 0x71). A
        name-keyed lookup makes that class of divergence structurally
        impossible regardless of either collection's insertion order.
        """
        self._hash_to_index.clear()
        self._warned_hashes.clear()

        primary = (primary_channel_name or "LongFast").strip() or "LongFast"
        all_keys = crypto.get_all_keys()
        if not all_keys:
            logger.warning("Channel hash map empty: no crypto keys loaded")
            return

        primary_hash = crypto.compute_channel_hash(primary, all_keys[0])
        self._hash_to_index[primary_hash] = 0

        for index, ch_name in enumerate(channel_keys.keys(), start=1):
            key = crypto._keys.get(ch_name)
            if key is None:
                continue
            ch_hash = crypto.compute_channel_hash(ch_name, key)
            self._hash_to_index[ch_hash] = index

        logger.info("Channel hash map: %s", self._hash_to_index)

    def lookup(self, channel_hash: int) -> int | None:
        """Return dashboard channel index for a packet header hash, or
        ``None`` if this hash isn't in the current map.

        Never silently defaults to channel 0 (LongFast). That used to
        happen here and it masked a real config mismatch for weeks --
        an unmapped hash's traffic blended invisibly into LongFast's
        own message history, indistinguishable from genuine LongFast
        packets. Callers must route a ``None`` result to their own
        distinct, visible bucket instead (see ``on_text_packet`` in
        ``server.py``, which builds a ``broadcast:meshtastic:unmapped:
        0xHH`` conversation id per unique hash).
        """
        mapped = self._hash_to_index.get(channel_hash)
        if mapped is not None:
            return mapped
        if channel_hash not in self._warned_hashes:
            self._warned_hashes.add(channel_hash)
            logger.warning(
                "Unmapped Meshtastic channel_hash=0x%02x; routing to a "
                "distinct 'unmapped' bucket instead of silently "
                "blending into channel 0/LongFast",
                channel_hash,
            )
        return None

    @property
    def mapping(self) -> dict[int, int]:
        """Read-only view of the current hash → index map (tests)."""
        return dict(self._hash_to_index)
