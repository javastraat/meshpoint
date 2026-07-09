from __future__ import annotations

import asyncio
import base64
import logging
from datetime import datetime, timezone
from typing import AsyncIterator, Optional

from src.capture.base import CaptureSource
from src.models.packet import RawCapture
from src.models.signal import SignalMetrics
from src.radio.channel_frequency import resolve_frequency_mhz
from src.radio.presets import get_preset

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
        self._connected = False
        self._radio_info: dict = {}
        self._queue: asyncio.Queue[RawCapture] = asyncio.Queue(maxsize=500)

    @property
    def name(self) -> str:
        return f"serial_{self._label}" if self._label else "serial"

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def connected(self) -> bool:
        return self._connected

    def get_radio_info(self) -> dict:
        """Region/channel/name from the connect-time handshake.

        Empty dict before the first successful connect. Same role as
        MeshCore's ``self_info`` readout, exposed for the topbar chip
        and for stamping real signal metadata instead of a hardcoded
        placeholder.
        """
        return dict(self._radio_info)

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

            self._radio_info = self._read_radio_info(self._interface)
            self._connected = True
            pub.subscribe(self._on_receive, "meshtastic.receive")
            self._running = True
            logger.info(
                "Serial capture started on %s (region=%s channel_num=%s)",
                self._port or "auto-detect",
                self._radio_info.get("region"),
                self._radio_info.get("channel_num"),
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

    @staticmethod
    def _read_radio_info(interface) -> dict:
        """Region/channel/modem/name from the interface's own config.

        meshtastic-python's StreamInterface.__init__ already calls
        waitForConfig() synchronously before SerialInterface(...)
        returns, so localNode.localConfig.lora and the node identity
        are populated by the time this runs -- no extra wait needed.
        Best-effort: any read failure leaves that field None rather
        than raising, since this must never block a successful capture
        start.

        SF/bandwidth/coding rate depend on whether the node uses a
        named modem preset (the common case -- looked up in
        src.radio.presets, the same table the dashboard's preset
        picker uses) or a fully custom config (use_preset=False,
        reading the raw spread_factor/bandwidth/coding_rate fields
        directly; coding_rate is stored as just the denominator, e.g.
        5 means "4/5").
        """
        info: dict = {
            "region": None, "channel_num": None,
            "short_name": None, "long_name": None,
            "modem_preset": None, "use_preset": True,
            "spreading_factor": None, "bandwidth_khz": None, "coding_rate": None,
            "channel_name": None, "frequency_offset": 0.0, "override_frequency": 0.0,
            "own_node_num": None,
        }
        try:
            from meshtastic.protobuf import config_pb2
            lora = interface.localNode.localConfig.lora
            info["channel_num"] = int(lora.channel_num)
            info["region"] = config_pb2.Config.LoRaConfig.RegionCode.Name(lora.region)
            info["use_preset"] = bool(lora.use_preset)
            info["frequency_offset"] = float(lora.frequency_offset)
            info["override_frequency"] = float(lora.override_frequency)
            if lora.use_preset:
                preset_name = config_pb2.Config.LoRaConfig.ModemPreset.Name(
                    lora.modem_preset,
                )
                info["modem_preset"] = preset_name
                preset = get_preset(preset_name)
                if preset:
                    info["spreading_factor"] = preset.spreading_factor
                    info["bandwidth_khz"] = preset.bandwidth_khz
                    info["coding_rate"] = preset.coding_rate
            else:
                info["modem_preset"] = "CUSTOM"
                if lora.spread_factor:
                    info["spreading_factor"] = int(lora.spread_factor)
                if lora.bandwidth:
                    info["bandwidth_khz"] = float(lora.bandwidth)
                if lora.coding_rate:
                    info["coding_rate"] = f"4/{int(lora.coding_rate)}"
        except Exception:
            logger.debug("Could not read LoRa config from serial interface", exc_info=True)
        try:
            info["short_name"] = interface.getShortName()
            info["long_name"] = interface.getLongName()
        except Exception:
            logger.debug("Could not read node identity from serial interface", exc_info=True)
        try:
            info["channel_name"] = SerialCaptureSource._read_primary_channel_name(interface)
        except Exception:
            logger.debug("Could not read primary channel name from serial interface", exc_info=True)
        try:
            info["own_node_num"] = int(interface.myInfo.my_node_num)
        except Exception:
            logger.debug("Could not read own node number from serial interface", exc_info=True)
        return info

    @staticmethod
    def _read_primary_channel_name(interface) -> Optional[str]:
        """The primary channel's own name, for frequency-slot hashing.

        meshtastic/firmware's Channels::getName() hashes this string
        (falling back to the modem preset's display name when it's
        blank -- the common case for a stock setup) to pick a default
        frequency slot. Returns None (not "") when there's no primary
        channel, so callers can tell "blank name" from "no data".
        """
        from meshtastic.protobuf import channel_pb2
        channels = getattr(interface.localNode, "channels", None) or []
        for ch in channels:
            if ch.role == channel_pb2.Channel.Role.PRIMARY:
                return ch.settings.name
        return None

    async def stop(self) -> None:
        self._running = False
        self._connected = False
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
        own_node_num = self._radio_info.get("own_node_num")
        if own_node_num is not None and packet.get("from") == own_node_num:
            # The connected stick's own periodic self-telemetry/nodeinfo
            # (and anything else it locally originates) passes through
            # the same "meshtastic.receive" event stream as genuinely
            # received packets -- meshtastic-python doesn't distinguish
            # them. Firmware's own convention (rx_rssi == rx_snr == 0)
            # confirms these were never actually received over the air,
            # so there's no real signal to report; dropped here rather
            # than flowing through decode/storage/the packet feed/node
            # counters as a confusing, spammy "-100 dBm" reading of the
            # stick reporting on itself.
            logger.debug(
                "Dropping self-originated packet from own node %08x", own_node_num,
            )
            return None

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

        radio = self._radio_info
        signal = SignalMetrics(
            rssi=float(packet.get("rxRssi", packet.get("rssi", -100))),
            snr=float(packet.get("rxSnr", packet.get("snr", 0))),
            frequency_mhz=resolve_frequency_mhz(
                region=radio.get("region"),
                channel_num=radio.get("channel_num"),
                bandwidth_khz=radio.get("bandwidth_khz") or 250.0,
                channel_name=radio.get("channel_name"),
                modem_preset=radio.get("modem_preset"),
                use_preset=radio.get("use_preset", True),
                frequency_offset=radio.get("frequency_offset") or 0.0,
                override_frequency=radio.get("override_frequency") or 0.0,
            ),
            # Fall back to LongFast (the de facto default preset almost
            # every Meshtastic node runs) only when the handshake
            # hasn't populated these yet -- better than the previous
            # unconditional 11/250.0 which never reflected non-LongFast
            # presets either.
            spreading_factor=radio.get("spreading_factor") or 11,
            bandwidth_khz=radio.get("bandwidth_khz") or 250.0,
            coding_rate=radio.get("coding_rate") or "4/5",
        )

        return RawCapture(
            payload=raw_bytes,
            signal=signal,
            capture_source=self.name,
            timestamp=datetime.now(timezone.utc),
            pre_decoded=self._build_pre_decoded(packet),
        )

    @staticmethod
    def _build_pre_decoded(packet: dict) -> Optional[dict]:
        """Portnum + inner payload when meshtastic-python decrypted this
        packet locally with the connected radio's own key.

        "decoded" and "encrypted" share one protobuf oneof (see
        _packet_to_raw_capture's comment above), so when "decoded" is
        present there is no ciphertext left for Meshpoint's own
        crypto_service to attempt -- without this, such packets always
        showed as "Unknown" even though the actual decoded content
        (position, telemetry, nodeinfo, ...) was sitting right there in
        the dict the whole time. Portnum names/encoding verified against
        the installed meshtastic.protobuf.portnums_pb2 (MessageToDict
        emits the enum NAME string and base64-encodes payload bytes).
        """
        decoded = packet.get("decoded")
        if not isinstance(decoded, dict):
            return None
        portnum_name = decoded.get("portnum")
        if not portnum_name:
            return None
        try:
            from meshtastic.protobuf import portnums_pb2
            portnum = portnums_pb2.PortNum.Value(portnum_name)
        except (ImportError, ValueError):
            logger.debug("Unrecognized portnum name %r", portnum_name)
            return None

        payload_b64 = decoded.get("payload", "")
        try:
            payload = base64.b64decode(payload_b64) if payload_b64 else b""
        except Exception:
            logger.debug("Could not base64-decode decoded.payload", exc_info=True)
            payload = b""

        return {
            "portnum": portnum,
            "payload": payload,
            "request_id": decoded.get("requestId", 0),
        }

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
