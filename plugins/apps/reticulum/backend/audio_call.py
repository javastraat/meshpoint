"""Reticulum voice calls -- a dumb byte pipe, nothing more.

Ported from reticulum-meshchat's ``src/backend/audio_call_manager.py``
(MIT, Liam Cottle) -- credit in this plugin's README. Adapted to this
codebase's style (logging, meshpoint's own async conventions) but the
mechanism is unchanged: a call is an ``RNS.Link`` to a ``"call"/"audio"``
destination on the peer's identity, and ``AudioCall.send_audio_packet()``
does exactly one thing, ``RNS.Packet(self.link, data).send()``. No audio
codec, no framing, no voice-activity logic lives here or anywhere in
this backend -- Codec2 encode/decode happens entirely client-side (the
``reticulum-call`` hook plugin's WASM), and this module has no opinion
about what the bytes it forwards actually are. That split is the whole
point: it's what makes the Pi side small enough to bundle in core while
the ~2.7 MB of WASM + call UI stays an opt-in plugin.

Each packet is capped at ``RNS.Link.MDU`` (the transport's own
per-packet limit) -- an oversized packet is silently dropped rather
than raised, matching the original; a caller who cares should check
``RNS.Link.MDU`` itself and frame audio accordingly before calling
``send_audio_packet``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Callable, Optional

try:
    import RNS
except ImportError:  # pragma: no cover -- same optional-dependency story as lxmf_service.py
    RNS = None  # type: ignore[assignment]

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

CALL_ASPECT = ("call", "audio")


class CallFailedException(Exception):
    """Raised by :meth:`AudioCallManager.initiate` when no path/link to
    the destination could be established within the timeout."""


class AudioCall:
    """One active (or hung-up) call -- a thin wrapper around an
    ``RNS.Link``. Owns no audio state at all; callers register a packet
    listener to receive forwarded bytes and push bytes out via
    ``send_audio_packet``."""

    def __init__(self, link: "RNS.Link", is_outbound: bool):
        self.link = link
        self.is_outbound = is_outbound
        self.established_at = time.time()
        self.link.set_link_closed_callback(self._on_link_closed)
        self.link.set_packet_callback(self._on_packet)
        self._audio_packet_listeners: list[Callable[[bytes], None]] = []
        self._hangup_listeners: list[Callable[[], None]] = []

    def register_audio_packet_listener(self, callback: Callable[[bytes], None]) -> None:
        self._audio_packet_listeners.append(callback)

    def unregister_audio_packet_listener(self, callback: Callable[[bytes], None]) -> None:
        if callback in self._audio_packet_listeners:
            self._audio_packet_listeners.remove(callback)

    def register_hangup_listener(self, callback: Callable[[], None]) -> None:
        self._hangup_listeners.append(callback)

    def _on_link_closed(self, _link) -> None:
        logger.debug("AudioCall: link closed (hash=%s)", self.link_hash_hex)
        for listener in list(self._hangup_listeners):
            try:
                listener()
            except Exception:  # noqa: BLE001 -- one bad listener can't break teardown
                logger.debug("AudioCall hangup listener raised", exc_info=True)

    def _on_packet(self, message, _packet) -> None:
        for listener in list(self._audio_packet_listeners):
            try:
                listener(message)
            except Exception:  # noqa: BLE001 -- one bad listener can't drop the call
                logger.debug("AudioCall packet listener raised", exc_info=True)

    def send_audio_packet(self, data: bytes) -> None:
        if not self.is_active():
            return
        if len(data) > RNS.Link.MDU:
            logger.debug(
                "AudioCall: dropping %d-byte packet, exceeds link MDU of %d",
                len(data), RNS.Link.MDU,
            )
            return
        RNS.Packet(self.link, data).send()

    def get_remote_identity(self):
        return self.link.get_remote_identity()

    def is_active(self) -> bool:
        return self.link.status == RNS.Link.ACTIVE

    def hangup(self) -> None:
        self.link.teardown()

    @property
    def link_hash_hex(self) -> str:
        return RNS.hexrep(self.link.hash, delimit=False) if self.link.hash else ""


class AudioCallReceiver:
    """Owns the inbound ``"call"/"audio"`` destination on our identity --
    a sibling of the LXMF delivery / NomadNet-hosting destinations
    already on the same identity, not a separate identity of its own."""

    def __init__(self, identity: "RNS.Identity", on_incoming: Callable[["AudioCall"], None]):
        self._on_incoming = on_incoming
        self.destination = RNS.Destination(
            identity, RNS.Destination.IN, RNS.Destination.SINGLE, *CALL_ASPECT,
        )
        self.destination.set_link_established_callback(self._client_connected)

    def announce(self, app_data: Optional[bytes] = None) -> None:
        self.destination.announce(app_data)

    def _client_connected(self, link: "RNS.Link") -> None:
        call = AudioCall(link, is_outbound=False)
        self._on_incoming(call)


class AudioCallManager:
    """Tracks every call (in either direction) on one identity. Owns no
    RNS.Reticulum instance of its own -- attaches to whatever's already
    running, same as LxmfService itself."""

    def __init__(self, identity: "RNS.Identity"):
        self.identity = identity
        self._on_incoming_call: Optional[Callable[["AudioCall"], None]] = None
        self.receiver = AudioCallReceiver(identity, self._handle_incoming)
        self.calls: list[AudioCall] = []

    def announce(self, app_data: Optional[bytes] = None) -> None:
        self.receiver.announce(app_data)

    def register_incoming_call_callback(self, callback: Callable[["AudioCall"], None]) -> None:
        self._on_incoming_call = callback

    def _handle_incoming(self, call: AudioCall) -> None:
        self.calls.append(call)
        if self._on_incoming_call is not None:
            self._on_incoming_call(call)

    def find_by_link_hash(self, link_hash: bytes) -> Optional[AudioCall]:
        return next((c for c in self.calls if c.link.hash == link_hash), None)

    def find_by_link_hash_hex(self, link_hash_hex: str) -> Optional[AudioCall]:
        try:
            return self.find_by_link_hash(bytes.fromhex(link_hash_hex))
        except ValueError:
            return None

    def forget(self, call: AudioCall) -> None:
        if call in self.calls:
            self.calls.remove(call)

    def hangup_all(self) -> None:
        for call in list(self.calls):
            call.hangup()

    async def initiate(
        self, destination_hash_hex: str, timeout_seconds: float = 15.0,
    ) -> AudioCall:
        """Establishes a link to *destination_hash_hex*'s ``"call"/
        "audio"`` destination and returns the resulting :class:`AudioCall`.
        Raises :class:`CallFailedException` if no path is found, or the
        link never reaches ``ACTIVE``, within the timeout."""
        dest_hash = bytes.fromhex(destination_hash_hex)
        deadline = time.monotonic() + timeout_seconds

        if not RNS.Transport.has_path(dest_hash):
            RNS.Transport.request_path(dest_hash)
            while not RNS.Transport.has_path(dest_hash) and time.monotonic() < deadline:
                await asyncio.sleep(0.1)
        if not RNS.Transport.has_path(dest_hash):
            raise CallFailedException("Could not find a path to that destination.")

        identity = RNS.Identity.recall(dest_hash)
        if identity is None:
            raise CallFailedException("Could not resolve the destination's identity.")
        destination = RNS.Destination(
            identity, RNS.Destination.OUT, RNS.Destination.SINGLE, *CALL_ASPECT,
        )
        link = RNS.Link(destination)

        while link.status is not RNS.Link.ACTIVE and time.monotonic() < deadline:
            await asyncio.sleep(0.1)
        if link.status is not RNS.Link.ACTIVE:
            raise CallFailedException("Could not establish a link to that destination.")

        call = AudioCall(link, is_outbound=True)
        self.calls.append(call)
        link.identify(self.identity)
        return call
