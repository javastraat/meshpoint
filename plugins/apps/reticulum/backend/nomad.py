"""NomadNet page/file fetching over Reticulum Links.

A NomadNet node (aspect ``nomadnetwork.node``) is a small BBS-style server
that hosts pages written in Micron markup, served over standard RNS
``Link`` + ``Request`` primitives -- the same ones ``lxmf_service``'s
``send_message()`` already uses (path discovery, ``Identity.recall``).
This module wraps that callback-based API in ``async`` calls that a
FastAPI route can ``await``.

Ported in spirit from reticulum-meshchat's ``NomadnetDownloader``
(``meshchat.py``, MIT) -- same Link-cache-per-destination, same
request-path-then-link-then-request sequence.

RNS is a process-global singleton: once ``LxmfService.start()`` has run
``RNS.Reticulum()``, ``RNS.Transport`` / ``RNS.Link`` work here with no
extra attach. Read-only browsing needs no local identity (NomadNet Links
are anonymous unless a page explicitly requires ``link.identify()``).

Kept importable without ``rns`` -- ``fetch_page`` returns an error result
rather than raising when RNS isn't available.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import RNS
except ImportError:  # not installed -- e.g. Mac dev environment
    RNS = None

# Established links, keyed by destination_hash hex -- reused across page
# navigations on the same node instead of re-linking on every click.
_links: dict = {}

_PATH_LOOKUP_TIMEOUT_S = 15
_LINK_TIMEOUT_S = 15
_REQUEST_TIMEOUT_S = 20


@dataclass
class NomadResult:
    ok: bool
    content: Optional[str] = None      # Micron markup, for a page
    error: Optional[str] = None
    destination_hash: str = ""
    path: str = ""


def available() -> bool:
    """True once RNS is importable AND a Reticulum instance exists in this
    process (i.e. the reticulum plugin's LxmfService has started)."""
    if RNS is None:
        return False
    try:
        return RNS.Reticulum.get_instance() is not None
    except Exception:  # noqa: BLE001 -- old RNS without get_instance(); treat as unavailable
        return False


async def _ensure_path(dest_hash: bytes) -> bool:
    loop = asyncio.get_running_loop()
    if RNS.Transport.has_path(dest_hash):
        return True
    RNS.Transport.request_path(dest_hash)
    deadline = loop.time() + _PATH_LOOKUP_TIMEOUT_S
    while not RNS.Transport.has_path(dest_hash) and loop.time() < deadline:
        await asyncio.sleep(0.1)
    return RNS.Transport.has_path(dest_hash)


async def _ensure_link(destination_hash_hex: str, dest_hash: bytes):
    """Return an ACTIVE RNS.Link to the node, from cache or freshly made."""
    loop = asyncio.get_running_loop()
    link = _links.get(destination_hash_hex)
    if link is not None and link.status == RNS.Link.ACTIVE:
        return link

    identity = RNS.Identity.recall(dest_hash)
    if identity is None:
        return None

    destination = RNS.Destination(
        identity, RNS.Destination.OUT, RNS.Destination.SINGLE,
        "nomadnetwork", "node",
    )
    link = RNS.Link(destination)
    _links[destination_hash_hex] = link
    deadline = loop.time() + _LINK_TIMEOUT_S
    while link.status != RNS.Link.ACTIVE and loop.time() < deadline:
        await asyncio.sleep(0.1)
    return link if link.status == RNS.Link.ACTIVE else None


async def fetch_page(
    destination_hash_hex: str,
    path: str = "/page/index.mu",
    field_data: Optional[dict] = None,
) -> NomadResult:
    """Fetch one NomadNet page. ``field_data`` (optional) is a dict of
    form-field values submitted with the request -- keys are used verbatim
    (NomadNet's own convention prefixes ``field_``/``var_``; the caller
    passes them already-prefixed)."""
    result = NomadResult(ok=False, destination_hash=destination_hash_hex, path=path)

    if not available():
        result.error = "Reticulum is not running (enable + set up the reticulum plugin)"
        return result

    try:
        dest_hash = bytes.fromhex(destination_hash_hex)
    except ValueError:
        result.error = "Invalid destination hash"
        return result

    if not await _ensure_path(dest_hash):
        result.error = "No path to that node -- it may be offline or unreachable"
        return result

    link = await _ensure_link(destination_hash_hex, dest_hash)
    if link is None:
        result.error = "Could not establish a link to that node"
        return result

    loop = asyncio.get_running_loop()
    fut: asyncio.Future = loop.create_future()

    def _on_response(receipt) -> None:
        try:
            data = receipt.response
            if isinstance(data, (bytes, bytearray)):
                text = bytes(data).decode("utf-8", errors="replace")
            else:
                text = str(data)
            loop.call_soon_threadsafe(fut.set_result, ("ok", text))
        except Exception as exc:  # noqa: BLE001
            loop.call_soon_threadsafe(fut.set_result, ("err", f"decode failed: {exc}"))

    def _on_failed(receipt=None) -> None:
        loop.call_soon_threadsafe(fut.set_result, ("err", "the node rejected or dropped the request"))

    try:
        link.request(
            path,
            data=field_data or None,
            response_callback=_on_response,
            failed_callback=_on_failed,
            timeout=_REQUEST_TIMEOUT_S,
        )
    except Exception as exc:  # noqa: BLE001
        result.error = f"Request could not be sent: {exc}"
        return result

    try:
        kind, payload = await asyncio.wait_for(fut, timeout=_REQUEST_TIMEOUT_S + 5)
    except asyncio.TimeoutError:
        result.error = "Timed out waiting for the page"
        return result

    if kind == "ok":
        result.ok = True
        result.content = payload
    else:
        result.error = payload
    return result


def reset() -> None:
    """Drop the link cache (test helper / teardown)."""
    _links.clear()
