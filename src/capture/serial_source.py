from __future__ import annotations

import asyncio
import base64
import logging
from datetime import datetime, timezone
from typing import AsyncIterator, Optional

from src.capture.base import CaptureSource
from src.models.packet import RawCapture
from src.models.signal import SignalMetrics
from src.radio.presets import get_preset

logger = logging.getLogger(__name__)

# Default LongFast center frequency per region (channel_num=0, the
# firmware's hash-derived default channel). Mirrors
# ConcentratorChannelPlan's own EU_868 default in
# src/hal/concentrator_config.py, plus EU_433 (433.875 MHz, the
# documented Meshtastic EU_433 LongFast default -- not on the
# concentrator table since the M1's SX1302 is 868-only hardware).
_REGION_DEFAULT_MHZ: dict[str, float] = {
    "US": 906.875,
    "EU_433": 433.875,
    "EU_868": 869.525,
    "ANZ": 919.875,
    "IN": 865.875,
    "KR": 922.875,
    "SG_923": 917.875,
}


def _default_frequency_mhz(region: Optional[str], channel_num: Optional[int]) -> float:
    """Best-effort center frequency for a region's default LongFast channel.

    Only meaningful when the node's own reported ``channel_num`` is 0
    (the default/auto channel, hash-derived by the firmware from the
    channel PSK name) -- these are the well-known default LongFast
    frequencies per region. A non-zero channel_num means the true
    frequency depends on that hash, which isn't replicated here, so
    this returns 0.0 (this codebase's existing "unknown" sentinel --
    see the MeshCore self_info fix) rather than guessing.
    """
    if not region or channel_num not in (0, None):
        return 0.0
    return _REGION_DEFAULT_MHZ.get(region, 0.0)


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
            "modem_preset": None, "spreading_factor": None,
            "bandwidth_khz": None, "coding_rate": None,
        }
        try:
            from meshtastic.protobuf import config_pb2
            lora = interface.localNode.localConfig.lora
            info["channel_num"] = int(lora.channel_num)
            info["region"] = config_pb2.Config.LoRaConfig.RegionCode.Name(lora.region)
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
        return info

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
            frequency_mhz=_default_frequency_mhz(
                radio.get("region"), radio.get("channel_num"),
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
