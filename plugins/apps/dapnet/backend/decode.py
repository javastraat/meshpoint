"""Convert POCSAG/DAPNET companion serial JSON lines into decoded Packet objects.

``pocsag_companion`` emits one JSON object per line for each
decoded page: ``{"capcode": <int>, "function": 0-3,
"type": "alpha"|"numeric"|"tone"|"activation", "text": "<optional>"}``.
The same shape covers both a genuinely received page and this
project's own sent-page echo (no direction marker on the wire) --
DapnetSerialSource is receive-only for now, so every line reaching
this adapter is treated as received traffic.

Non-JSON lines (boot banners, WiFi/OTA logs, "SEND BLOCKED"/"SEND
FAILED" confirmations) are not valid JSON and simply fail to parse
here; the capture source already filters most of these out before a
line ever reaches this adapter, but the JSON-decode guard stays
defensive since this function is reachable independently (tests).

Uses OpenProtocol/OpenPacketType (src.models.packet), not the core
Protocol/PacketType enum members DAPNET used to be a member of before
this plugin existed -- proves the open-protocol mechanism end to end
rather than leaving a core enum member whose only producer is a
plugin.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Optional

from src.models.packet import OpenPacketType, OpenProtocol, Packet
from src.models.signal import SignalMetrics

logger = logging.getLogger(__name__)

_TYPE_MAP: dict[str, OpenPacketType] = {
    "alpha": OpenPacketType("dapnet_alpha"),
    "numeric": OpenPacketType("dapnet_numeric"),
    "tone": OpenPacketType("dapnet_tone"),
    "activation": OpenPacketType("dapnet_activation"),
}
_UNKNOWN_TYPE = OpenPacketType("unknown")


def adapt_event(
    raw_payload: bytes,
    signal: Optional[SignalMetrics] = None,
) -> Optional[Packet]:
    """Deserialize one JSON-encoded DAPNET page line into a Packet.

    ``signal`` is accepted for interface parity with the other capture
    adapters but never used -- the companion board reports no RF signal
    metrics over its JSON serial protocol, so a DAPNET Packet's
    ``signal`` stays ``None`` rather than carry a fabricated value.
    """
    try:
        data = json.loads(raw_payload)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict) or "capcode" not in data or "type" not in data:
        return None

    try:
        capcode = int(data["capcode"])
    except (TypeError, ValueError):
        logger.debug("dapnet adapt_event: non-integer capcode %r", data.get("capcode"))
        return None

    packet_type = _TYPE_MAP.get(str(data.get("type", "")), _UNKNOWN_TYPE)
    decoded = {
        "capcode": capcode,
        "function": data.get("function"),
        "text": data.get("text", ""),
    }
    # POCSAG/DAPNET has no real "sender ID" -- a page is broadcast over
    # RF by the network and addressed TO a specific capcode (the pager
    # being paged), not FROM one. source_id="broadcast"/
    # destination_id=capcode matches that real-world direction (a page
    # goes broadcast -> capcode), the reverse of what the earlier
    # source_id=capcode/destination_id="broadcast" shape implied.
    return Packet(
        packet_id=uuid.uuid4().hex[:16],
        source_id="broadcast",
        destination_id=str(capcode),
        protocol=OpenProtocol("dapnet"),
        packet_type=packet_type,
        decoded_payload=decoded,
        decrypted=True,
    )
