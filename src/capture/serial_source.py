from __future__ import annotations

import asyncio
import base64
import logging
from datetime import datetime, timezone
from typing import AsyncIterator, Optional

from src.capture.base import CaptureSource
from src.models.packet import RawCapture
from src.models.signal import SignalMetrics

logger = logging.getLogger(__name__)


class SerialCaptureSource(CaptureSource):
    """Captures packets from a Meshtastic radio connected via USB serial.

    Uses the meshtastic-python pub/sub API to receive decoded packets.
    Packets arrive already decoded, so they are re-serialized as raw
    capture events for the pipeline to process uniformly.
    """

    def __init__(
        self,
        port: Optional[str] = None,
        baud: int = 115200,
        label: str = "",
    ):
        self._port = port
        self._baud = baud
        self._label = label
        self._interface = None
        self._running = False
        self._queue: asyncio.Queue[RawCapture] = asyncio.Queue(maxsize=500)

    @property
    def name(self) -> str:
        return f"serial_{self._label}" if self._label else "serial"

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self) -> None:
        try:
            import meshtastic.serial_interface
            from pubsub import pub

            if self._port:
                self._interface = meshtastic.serial_interface.SerialInterface(
                    devPath=self._port
                )
            else:
                self._interface = meshtastic.serial_interface.SerialInterface()

            pub.subscribe(self._on_receive, "meshtastic.receive")
            self._running = True
            logger.info(
                "Serial capture started on %s",
                self._port or "auto-detect",
            )
        except ImportError:
            logger.error(
                "meshtastic package not installed. "
                "Install with: pip install meshtastic"
            )
            raise
        except Exception:
            logger.exception("Failed to open serial interface")
            raise

    async def stop(self) -> None:
        self._running = False
        if self._interface:
            try:
                self._interface.close()
            except Exception:
                pass
            self._interface = None
        logger.info("Serial capture stopped")

    async def packets(self) -> AsyncIterator[RawCapture]:
        while self._running:
            try:
                raw = await asyncio.wait_for(
                    self._queue.get(), timeout=1.0
                )
                yield raw
            except asyncio.TimeoutError:
                continue

    def _on_receive(self, packet, interface) -> None:
        """Callback invoked by meshtastic-python on packet reception.

        meshtastic-python publishes every open interface's packets on one
        process-wide pypubsub topic ("meshtastic.receive"), so with more
        than one SerialCaptureSource running (multiple USB sticks), each
        instance's callback fires for every stick's packets, not just its
        own. Compare identity against our own interface so a multi-stick
        setup doesn't duplicate/misattribute packets across devices.
        """
        if not self._running or interface is not self._interface:
            return

        try:
            raw_capture = self._packet_to_raw_capture(packet)
            if raw_capture:
                try:
                    self._queue.put_nowait(raw_capture)
                except asyncio.QueueFull:
                    logger.warning("Serial capture queue full")
        except Exception:
            logger.debug("Failed to convert serial packet", exc_info=True)

    def _packet_to_raw_capture(self, packet: dict) -> Optional[RawCapture]:
        """Convert a meshtastic-python packet dict to a RawCapture."""
        raw_bytes = packet.get("raw", b"")
        if isinstance(raw_bytes, str):
            raw_bytes = bytes.fromhex(raw_bytes)
        elif not isinstance(raw_bytes, (bytes, bytearray)):
            # meshtastic-python always sets packet["raw"] to the decoded
            # MeshPacket protobuf object (mesh_interface.py explicitly
            # does `asDict["raw"] = meshPacket`), never actual bytes.
            # Treat anything that isn't bytes as absent so the
            # reconstruction fallback below actually runs instead of
            # passing a protobuf object downstream as if it were bytes.
            raw_bytes = b""

        if not raw_bytes:
            # Reconstruct regardless of whether "decoded" is present.
            # "decoded" and "encrypted" share one protobuf oneof: a
            # packet the connected radio's own key COULDN'T decrypt
            # (e.g. traffic on a channel it isn't configured for) has
            # "encrypted" set and NO "decoded" key at all -- gating on
            # "decoded" here silently dropped exactly that case, the
            # one a passive multi-channel sniffer most needs (its own
            # channel_keys config may decrypt what the stick couldn't).
            raw_bytes = self._reconstruct_raw(packet)

        if not raw_bytes:
            return None

        signal = SignalMetrics(
            rssi=float(packet.get("rxRssi", packet.get("rssi", -100))),
            snr=float(packet.get("rxSnr", packet.get("snr", 0))),
            frequency_mhz=906.875,
            spreading_factor=11,
            bandwidth_khz=250.0,
        )

        return RawCapture(
            payload=raw_bytes,
            signal=signal,
            capture_source=self.name,
            timestamp=datetime.now(timezone.utc),
        )

    @staticmethod
    def _reconstruct_raw(packet: dict) -> bytes:
        """Build a minimal raw frame from a decoded meshtastic packet.

        When the meshtastic library provides already-decoded data
        without raw bytes, we reconstruct the header so the pipeline
        can process it. The payload portion will be empty/encrypted.
        """
        import struct

        dest = packet.get("to", 0xFFFFFFFF)
        source = packet.get("from", 0)
        pkt_id = packet.get("id", 0)

        hop_limit = packet.get("hopLimit", 3)
        hop_start = packet.get("hopStart", 3)
        want_ack = packet.get("wantAck", False)

        flags = (hop_limit & 0x07)
        if want_ack:
            flags |= 0x08
        flags |= (hop_start & 0x07) << 5

        channel = packet.get("channel", 0)

        header = struct.pack("<III", dest, source, pkt_id)
        header += bytes([flags, channel, 0, 0])

        # google.protobuf.json_format.MessageToDict base64-encodes bytes
        # fields, and the MeshPacket field is named "encrypted" (verified
        # against the installed meshtastic.protobuf.mesh_pb2.MeshPacket
        # descriptor) -- not "encoded"/hex, which never matched any real
        # key from this library. "encrypted" and "decoded" share one
        # protobuf oneof, so it's empty whenever the connected radio's
        # own key already decrypted the packet locally -- that's the
        # "payload portion will be empty" case above, not a bug here.
        encoded = packet.get("encrypted", b"")
        if isinstance(encoded, str):
            encoded = base64.b64decode(encoded)

        return header + encoded
