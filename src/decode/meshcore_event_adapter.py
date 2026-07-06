"""Convert MeshCore USB events into decoded Packet objects.

The meshcore Python library yields high-level events (messages,
advertisements) rather than raw radio frames.  This adapter translates
those events into the standard Packet model so they flow through the
same storage, broadcast, and upstream paths as radio-captured packets.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from src.models.packet import Packet, PacketType, Protocol
from src.models.signal import SignalMetrics

logger = logging.getLogger(__name__)

_EVENT_TYPE_MAP: dict[str, PacketType] = {
    "contact_message": PacketType.TEXT,
    "channel_message": PacketType.TEXT,
    "advertisement": PacketType.NODEINFO,
    "raw_data": PacketType.UNKNOWN,
    "rx_log_data": PacketType.UNKNOWN,
}


def adapt_event(
    raw_payload: bytes,
    signal: Optional[SignalMetrics] = None,
) -> Optional[Packet]:
    """Deserialize a JSON-encoded meshcore event envelope into a Packet."""
    try:
        envelope = json.loads(raw_payload)
    except (json.JSONDecodeError, UnicodeDecodeError):
        logger.warning("adapt_event: JSON decode failed")
        return None

    event_type: str = envelope.get("event_type", "")
    payload: dict = envelope.get("payload", {})

    builder = _BUILDERS.get(event_type)
    if builder is None:
        logger.debug("adapt_event: no builder for %s", event_type)
        return None

    try:
        return builder(payload, signal)
    except Exception:
        logger.exception("adapt_event: builder failed for %s", event_type)
        return None


def _build_contact_message(
    payload: dict, signal: Optional[SignalMetrics]
) -> Packet:
    decoded = {"text": payload.get("text", "")}
    sender_name = (
        payload.get("sender_name")
        or payload.get("contact_name")
        or payload.get("name")
        or ""
    )
    if sender_name:
        decoded["long_name"] = sender_name
    return Packet(
        packet_id=_generate_id(),
        source_id=payload.get("pubkey_prefix", "unknown"),
        destination_id="self",
        protocol=Protocol.MESHCORE,
        packet_type=PacketType.TEXT,
        decoded_payload=decoded,
        hop_start=_hop_start_from_payload(payload),
        signal=_rf_signal_from_payload(payload, signal),
        timestamp=_parse_timestamp(payload.get("timestamp")),
        decrypted=True,
    )


def _build_channel_message(
    payload: dict, signal: Optional[SignalMetrics]
) -> Packet:
    channel_idx = payload.get("channel_idx", 0)
    raw_text = payload.get("text", "")

    sender_name = (
        payload.get("sender_name")
        or payload.get("contact_name")
        or payload.get("name")
        or ""
    )
    text = raw_text
    if not sender_name and ": " in raw_text:
        sender_name, text = raw_text.split(": ", 1)

    source_id = payload.get("pubkey_prefix", "")
    if not source_id and sender_name:
        source_id = f"mc:{sender_name}"
    elif not source_id:
        source_id = "mc:channel"

    decoded = {"text": text, "channel": channel_idx}
    if sender_name:
        decoded["long_name"] = sender_name

    return Packet(
        packet_id=_generate_id(),
        source_id=source_id,
        destination_id="broadcast",
        protocol=Protocol.MESHCORE,
        packet_type=PacketType.TEXT,
        decoded_payload=decoded,
        channel_hash=channel_idx,
        hop_start=_hop_start_from_payload(payload),
        signal=_rf_signal_from_payload(payload, signal),
        timestamp=_parse_timestamp(payload.get("timestamp")),
        decrypted=True,
    )


def _build_advertisement(
    payload: dict, signal: Optional[SignalMetrics]
) -> Packet:
    pubkey = _first_payload_value(
        payload,
        "public_key",
        "pubkey",
        "pub_key",
        "pubkey_prefix",
        default="unknown",
    )
    source_id = pubkey[:12] if len(pubkey) >= 12 else pubkey
    name = _find_payload_name(
        payload,
        "adv_name",
        "advName",
        "name",
        "long_name",
        "longName",
        "display_name",
        "displayName",
        "node_name",
        "nodeName",
        "repeater_name",
        "repeaterName",
    )
    decoded = {
        "public_key": pubkey,
        "advertisement": payload,
    }
    node_type = _find_payload_type(payload)
    if node_type is not None:
        decoded["node_type"] = node_type
    if name and not _looks_like_identifier(name, source_id, pubkey):
        decoded["long_name"] = name
        decoded["short_name"] = name[:4]
    lat = payload.get("adv_lat")
    lon = payload.get("adv_lon")
    if lat and lon:
        decoded["latitude"] = lat
        decoded["longitude"] = lon
    return Packet(
        packet_id=_generate_id(),
        source_id=source_id,
        destination_id="broadcast",
        protocol=Protocol.MESHCORE,
        packet_type=PacketType.NODEINFO,
        decoded_payload=decoded,
        signal=signal,
        timestamp=_parse_timestamp(payload.get("timestamp")),
    )


def _first_payload_value(payload: dict, *keys: str, default: str = "") -> str:
    """Return the first non-empty string-ish value from a MeshCore event."""
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        value = str(value).strip()
        if value:
            return value
    return default


def _find_payload_name(payload: dict, *keys: str) -> str:
    """Find a display name even when the meshcore library nests advert data."""
    direct = _first_payload_value(payload, *keys, default="")
    if direct:
        return direct

    wanted = {k.lower() for k in keys}
    stack = list(payload.values())
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            for k, v in value.items():
                if k.lower() in wanted and v is not None:
                    candidate = str(v).strip()
                    if candidate:
                        return candidate
                elif isinstance(v, (dict, list)):
                    stack.append(v)
        elif isinstance(value, list):
            stack.extend(value)
    return ""


def _find_payload_type(payload: dict) -> Optional[int]:
    """Extract the MeshCore node type (0=None, 1=Client, 2=Repeater,
    3=Roomserver, 4=Sensor) from an advertisement/new_contact event.

    ``new_contact`` payloads carry the companion contact dict with a
    top-level ``type``; some library versions nest the advert data one
    level deeper (e.g. under ``contact``).
    """
    for candidate in (payload, *(v for v in payload.values() if isinstance(v, dict))):
        for key in ("type", "adv_type", "node_type"):
            value = candidate.get(key)
            if value is None:
                continue
            try:
                value = int(value)
            except (TypeError, ValueError):
                continue
            if 0 <= value <= 15:
                return value
    return None


def _looks_like_identifier(name: str, source_id: str, pubkey: str) -> bool:
    lowered = name.lower().lstrip("!")
    identifiers = {
        source_id.lower().lstrip("!"),
        pubkey.lower().lstrip("!"),
        pubkey[:12].lower().lstrip("!"),
    }
    if lowered in identifiers:
        return True
    try:
        int(lowered, 16)
        return len(lowered) >= 8
    except ValueError:
        return False


def _build_raw_data(
    payload: dict, signal: Optional[SignalMetrics]
) -> Packet:
    return Packet(
        packet_id=_generate_id(),
        source_id="raw",
        destination_id="unknown",
        protocol=Protocol.MESHCORE,
        packet_type=PacketType.UNKNOWN,
        decoded_payload={"raw_hex": payload.get("payload", "")},
        signal=signal,
        timestamp=_parse_timestamp(payload.get("timestamp")),
    )


def _build_rx_log_data(
    payload: dict, signal: Optional[SignalMetrics]
) -> Packet:
    """Build a Packet from an RX_LOG_DATA event (raw RF frame with signal)."""
    raw_hex = payload.get("payload", payload.get("raw_hex", ""))
    rf_signal = _rf_signal_from_payload(payload, signal)
    return Packet(
        packet_id=_generate_id(),
        source_id="rf_log",
        destination_id="unknown",
        protocol=Protocol.MESHCORE,
        packet_type=PacketType.UNKNOWN,
        decoded_payload={
            "raw_hex": raw_hex,
            "payload_length": payload.get("payload_length"),
        },
        signal=rf_signal,
        timestamp=_parse_timestamp(payload.get("timestamp")),
    )


def _rf_signal_from_payload(
    payload: dict, fallback: Optional[SignalMetrics]
) -> Optional[SignalMetrics]:
    """Extract signal metrics from a payload, checking both lower and upper case keys.

    Frequency/bandwidth/SF aren't part of the per-event payload -- they're
    carried on `fallback` (the RawCapture signal built upstream in
    meshcore_usb_source.py from the companion's cached radio info), so they
    must be preserved here rather than re-zeroed.
    """
    rssi = payload.get("rssi", payload.get("RSSI"))
    snr = payload.get("snr", payload.get("SNR"))
    if rssi is None and snr is None:
        return fallback
    frequency_mhz = fallback.frequency_mhz if fallback else 0.0
    bandwidth_khz = fallback.bandwidth_khz if fallback else 0.0
    spreading_factor = fallback.spreading_factor if fallback else 0
    return SignalMetrics(
        rssi=float(rssi) if rssi is not None else -120.0,
        snr=float(snr) if snr is not None else 0.0,
        frequency_mhz=frequency_mhz,
        spreading_factor=spreading_factor,
        bandwidth_khz=bandwidth_khz,
        coding_rate="N/A",
    )


def _hop_start_from_payload(payload: dict) -> int:
    """Convert MeshCore's raw path_len into a hop count.

    CONTACT_MSG_RECV/CHANNEL_MSG_RECV events carry path_len -- the actual
    number of hops the packet traversed (not a remaining-TTL scheme like
    Meshtastic). The companion library uses path_len == 255 as a sentinel
    for "direct message" (0 hops), not a literal 255-hop path -- see
    meshcore/reader.py in the meshcore PyPI package. hop_limit is left at
    its Packet default (0) so the existing hop_count property
    (hop_start - hop_limit) yields path_len unchanged.
    """
    path_len = payload.get("path_len")
    if path_len is None or path_len == 255:
        return 0
    return int(path_len)


_BUILDERS = {
    "contact_message": _build_contact_message,
    "channel_message": _build_channel_message,
    "advertisement": _build_advertisement,
    "new_contact": _build_advertisement,
    "raw_data": _build_raw_data,
    "rx_log_data": _build_rx_log_data,
}


def _generate_id() -> str:
    return uuid.uuid4().hex[:16]


def _parse_timestamp(ts) -> datetime:
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    return datetime.now(timezone.utc)
