"""MeshCore send feedback: repeats heard back for channel sends, ACKs for DMs.

Ported from upstream KMX415/meshpoint e8c4c6e1 (#151), adapted to this fork's
multi-companion sending: a channel message goes out through every connected
companion (TxService._send_meshcore), so one dashboard message can have one
tracked copy per companion. Copies share a ``packet_id``; the message row
shows the sum of their heard repeats, and "delivered" once any DM copy is
acknowledged.

Matching a channel echo uses the channel secret, the exact on-air text
("<sender>: <text>") and its sender timestamp -- never a short hash alone --
and only copies that carry a repeater path count. A count is what this
Meshpoint's own radios heard, not unique repeaters, reach or delivery.
DMs: stock companions return an ACK token on send (``expected_ack``) and
report the recipient's ACK later (``code``); that confirms receipt, not
reading. No repeat count for DMs (the encrypted TX packet isn't exposed).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

logger = logging.getLogger(__name__)

TRACK_SECONDS = 900      # echoes/ACKs matched for 15 minutes after a send
MAX_PENDING = 128        # at most this many recent sends tracked
ACK_KEEP_SECONDS = 30    # an ACK may arrive before the send result is bound


def new_packet_id() -> str:
    return "mc:" + uuid.uuid4().hex


@dataclass
class PendingSend:
    packet_id: str
    timestamp: int = 0
    message: str = ""
    parser: object = None
    created: float = field(default_factory=time.monotonic)
    count: Optional[int] = 0       # None: repeat tracking not available (DMs)
    expected_ack: str = ""
    status: str = "sent"
    ack_floor: int = 0


@dataclass
class _Binding:
    row_id: int
    node_id: str


class MeshcoreSendFeedback:
    """One instance per service, shared by the TX client and every companion."""

    def __init__(self, repository, broadcast: Callable[[str, dict], Awaitable[None]]):
        self.repository = repository
        self.broadcast = broadcast
        self._pending: dict[str, PendingSend] = {}   # unique key -> copy
        self._bound: dict[str, _Binding] = {}        # packet_id -> message row
        self._acks: dict[str, tuple[int, float]] = {}
        self._ack_sequence = 0
        self._lock = asyncio.Lock()

    # -- bookkeeping -----------------------------------------------------

    def _prune(self) -> None:
        now = time.monotonic()
        for key, item in list(self._pending.items()):
            if now - item.created > TRACK_SECONDS:
                del self._pending[key]
        for code, (_, arrived) in list(self._acks.items()):
            if now - arrived > ACK_KEEP_SECONDS:
                del self._acks[code]
        while len(self._pending) > MAX_PENDING:
            del self._pending[next(iter(self._pending))]
        live = {item.packet_id for item in self._pending.values()}
        for packet_id in list(self._bound):
            if packet_id not in live:
                del self._bound[packet_id]

    def _copies(self, packet_id: str) -> list[PendingSend]:
        return [item for item in self._pending.values() if item.packet_id == packet_id]

    def _totals(self, packet_id: str) -> dict:
        copies = self._copies(packet_id)
        counts = [c.count for c in copies if c.count is not None]
        return {
            "heard_repeats": sum(counts) if counts else None,
            "status": "delivered" if any(c.status == "delivered" for c in copies) else "sent",
        }

    # -- starting a send -------------------------------------------------

    def begin_channel(self, packet_id: str, channel_info: dict, sender: str,
                      text: str, timestamp: int) -> Optional[PendingSend]:
        """Track one companion's copy of a channel send; None if not possible."""
        from meshcore.meshcore_parser import MeshcorePacketParser

        secret = channel_info.get("channel_secret")
        if not isinstance(secret, bytes) or len(secret) != 16 or not sender:
            return None
        parser = MeshcorePacketParser()
        parser.channels = [{**channel_info,
                            "channel_hash": hashlib.sha256(secret).hexdigest()[:2]}]
        parser.decrypt_channels = True
        item = PendingSend(packet_id, timestamp, f"{sender}: {text}", parser)
        self._prune()
        self._pending[uuid.uuid4().hex] = item
        self._prune()
        return item

    def begin_direct(self, packet_id: str) -> PendingSend:
        item = PendingSend(packet_id, count=None)
        item.ack_floor = self._ack_sequence
        self._prune()
        self._pending[uuid.uuid4().hex] = item
        self._prune()
        return item

    def expect_ack(self, item: PendingSend, payload: dict) -> None:
        token = payload.get("expected_ack")
        if isinstance(token, (bytes, bytearray)) and len(token) == 4:
            item.expected_ack = bytes(token).hex()
        elif isinstance(token, str) and len(token) == 8:
            item.expected_ack = token.lower()
        else:
            return
        # The recipient's ACK can beat the send response back.
        if self._acks.get(item.expected_ack, (0, 0))[0] > item.ack_floor:
            item.status = "delivered"

    def discard(self, item: Optional[PendingSend]) -> None:
        for key, value in list(self._pending.items()):
            if value is item:
                del self._pending[key]

    async def bind(self, packet_id: str, row_id: int, node_id: str) -> Optional[dict]:
        """Attach a saved message row; returns the feedback so far, or None."""
        async with self._lock:
            if not self._copies(packet_id):
                return None
            self._bound[packet_id] = _Binding(row_id, node_id)
            await self._publish(packet_id)
            return self._totals(packet_id)

    # -- observations from the companions ---------------------------------

    async def acknowledge(self, payload: dict) -> None:
        code = payload.get("code")
        if not isinstance(code, str) or len(code) != 8:
            return
        try:
            bytes.fromhex(code)
        except ValueError:
            return
        code = code.lower()
        async with self._lock:
            self._prune()
            self._ack_sequence += 1
            self._acks[code] = (self._ack_sequence, time.monotonic())
            while len(self._acks) > MAX_PENDING:
                del self._acks[next(iter(self._acks))]
            for item in list(self._pending.values()):
                if item.expected_ack == code and item.status != "delivered":
                    item.status = "delivered"
                    await self._publish(item.packet_id)

    async def observe(self, payload: dict) -> None:
        """An RX log frame: count it if it is a repeated copy of one of our sends."""
        raw = payload.get("payload") if isinstance(payload, dict) else None
        if not isinstance(raw, str) or len(raw) > 1024:
            return
        try:
            frame = bytes.fromhex(raw)
        except ValueError:
            return
        # GRP_TXT (type 5), version 0, flood route (transport-scoped adds 4 bytes).
        if len(frame) < 2 or (frame[0] >> 2) & 15 != 5 or frame[0] >> 6 != 0:
            return
        route = frame[0] & 3
        if route not in (0, 1):
            return
        offset = 5 if route == 0 else 1
        if len(frame) <= offset:
            return
        path = frame[offset]
        hops, width = path & 63, (path >> 6) + 1
        body_start = offset + 1 + hops * width
        # Only repeated copies (a path) count; body = hash + MAC + AES blocks.
        if not hops or width > 3 or len(frame) < body_start + 19 \
                or (len(frame) - body_start - 3) % 16:
            return
        async with self._lock:
            self._prune()
            for item in list(self._pending.values()):
                if item.parser is None:
                    continue
                item.parser.channels_log.clear()  # SDK caches by short hash
                try:
                    decoded = await item.parser.parsePacketPayload(frame, {})
                except Exception:
                    continue
                if decoded.get("sender_timestamp") != item.timestamp \
                        or decoded.get("message") != item.message:
                    continue
                item.count += 1
                await self._publish(item.packet_id)
                return

    async def _publish(self, packet_id: str) -> None:
        binding = self._bound.get(packet_id)
        if binding is None:
            return
        totals = self._totals(packet_id)
        try:
            saved = await self.repository.update_meshcore_feedback(
                binding.row_id, totals["heard_repeats"], totals["status"],
            )
        except Exception:
            logger.exception("MeshCore send feedback: could not store")
            return
        if saved:
            await self.broadcast("message_repeats", {
                "id": binding.row_id, "packet_id": packet_id,
                "node_id": binding.node_id, "protocol": "meshcore", **totals,
            })
