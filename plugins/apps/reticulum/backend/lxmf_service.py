"""Native Reticulum/LXMF messaging -- meshpoint's own LXMF delivery
destination, verified against reticulum-meshchat's approach.

Moved from ``src/reticulum/lxmf_service.py`` as part of the core->plugin
extraction (see ``memory/plugin-reticulum.md``). Logic unchanged; the only
edits are the import of ``ReticulumPeerRepository`` from this package
(``.peer_repo``) and pushing the ``WebSocketManager`` / ``MessageRepository``
imports under ``TYPE_CHECKING`` (they were annotation-only) so this module
imports on a machine without FastAPI, the same way the RNS/LXMF imports are
already deferred for a machine without those.

Attaches to the local ``rnsd`` shared instance as a client (never opens
the RNode/TCP interfaces itself) -- see ``backend/state.py`` and the old
``config.ReticulumConfig`` docstring for why that ordering matters and why
this whole service is opt-in. The one architectural fact worth restating
here: ``RNS.Reticulum()`` auto-detects a local shared instance and
attaches to it if one is already running; if not, it falls back to reading
``~/.reticulum/config`` and bringing up whatever interfaces are configured
there itself, which is the exact scenario this service must never trigger
by starting before rnsd. Confirmed live on the deployment Pi (rnsd
running, a throwaway client script attached and exchanged a real LXMF
message with meshchat.py) before this was written.

Message history reuses the existing ``messages`` table
(protocol='reticulum'); only the peer roster (built from announces) is a
new table, since Reticulum has nothing like Meshtastic/MeshCore's NodeInfo
packet to enrich ``nodes`` from.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from . import notify, talkback

if TYPE_CHECKING:
    from src.api.websocket_manager import WebSocketManager
    from src.storage.message_repository import MessageRepository

    from .peer_repo import ReticulumPeerRepository

logger = logging.getLogger(__name__)

try:
    import RNS
    import LXMF
except ImportError:  # not installed -- e.g. Mac dev environment
    RNS = None
    LXMF = None

# Aspects that build the peer roster (a "who can I reach / what nodes exist"
# list). Kept deliberately narrow -- see _ROSTER_ASPECTS vs the wider set the
# Activity stream listens on.
_ROSTER_ASPECTS = ("lxmf.delivery", "lxmf.propagation", "nomadnetwork.node")
# Everything the Activity stream shows. `call.audio` is stream-only: an audio
# call announce means someone's reachable for voice, but it shouldn't pad the
# roster with every Sideband/MeshChat user on the public network.
_ANNOUNCE_ASPECTS = (*_ROSTER_ASPECTS, "call.audio")
_ANNOUNCE_LOG_MAX = 200  # in-memory ring buffer behind GET /api/reticulum/announces
_PROPAGATION_ANNOUNCE_INTERVAL_S = 21600  # 6h -- re-announce the lxmf.propagation dest

# Total wait budget for a cold-cache path request in send_message():
# 5 x 1s = 5s. Long enough for a same-network shared-instance response
# (confirmed live these resolve in well under a second once the master
# actually has the destination), short enough not to hang an HTTP
# request indefinitely for a genuinely offline/unknown peer.
_PATH_REQUEST_RETRIES = 5
_PATH_REQUEST_POLL_INTERVAL_S = 1.0

# Talkback (backend/talkback.py) is inherently loop-safe (its replies never
# start with a recognized command word, see that module's docstring), but a
# per-sender cooldown is cheap defence in depth against any bug that would
# let a reply re-trigger a reply.
_TALKBACK_COOLDOWN_S = 5.0


# --- RNS/LXMF log bridge ------------------------------------------------------
# RNS and LXMF do their own logging (RNS.log -> stdout, "[timestamp] [Level]
# msg" format), bypassing Python's logging entirely -- which is why those
# lines look different in journald. Route them through logging instead, with
# levels mapped, and quiet one known-noisy LXMF line.
_RNS_LOG_PREFIX_RE = re.compile(r"^\[[^\]]*\]\s*\[([A-Za-z]+)\]\s*(.*)$", re.DOTALL)
_RNS_LEVEL_MAP = {
    "critical": logging.CRITICAL, "error": logging.ERROR,
    "warning": logging.WARNING, "notice": logging.INFO,
    "info": logging.INFO, "verbose": logging.DEBUG,
    "debug": logging.DEBUG, "extreme": logging.DEBUG,
}
# LXMF logs this at ERROR whenever a peer's announce carries app_data its own
# display-name decoder can't parse -- common on a busy public network, not
# actionable, and it recovers on its own. Demote to DEBUG.
_RNS_DEMOTE = ("could not decode display name in included announce data",)

_rns_logger = logging.getLogger("RNS")


def _route_rns_log(formatted: str) -> None:
    match = _RNS_LOG_PREFIX_RE.match(formatted)
    if match:
        level = _RNS_LEVEL_MAP.get(match.group(1).lower(), logging.INFO)
        text = match.group(2).strip()
    else:
        level, text = logging.INFO, formatted.strip()
    if any(s in text.lower() for s in _RNS_DEMOTE):
        level = logging.DEBUG
    _rns_logger.log(level, "%s", text)


def _install_rns_log_bridge() -> None:
    """Point RNS's logging at :func:`_route_rns_log`. Idempotent; a no-op if
    RNS isn't installed or its logging API isn't shaped as expected. Call
    after ``RNS.Reticulum()`` so it wins over any config-driven logdest."""
    if RNS is None:
        return
    try:
        RNS.logdest = RNS.LOG_CALLBACK
        RNS.logcall = _route_rns_log
    except AttributeError:
        logger.debug("RNS logging API not as expected -- leaving RNS logs as-is")


class _AnnounceHandler:
    """Bridges RNS.Transport's announce callback (fired on RNS's own
    thread, one instance per aspect since aspect_filter is per-handler,
    not passed into the callback -- same shape as reticulum-meshchat's
    own AnnounceHandler) into LxmfService._on_announce."""

    def __init__(self, aspect_filter: str, on_announce):
        self.aspect_filter = aspect_filter
        self._on_announce = on_announce

    def received_announce(
        self, destination_hash, announced_identity, app_data,
        announce_packet_hash=None,
    ) -> None:
        self._on_announce(self.aspect_filter, destination_hash, app_data)


class LxmfService:
    """One LXMF delivery destination for meshpoint itself, backed by a
    persisted Identity. start()/stop() follow the same shape as every
    other companion service -- now wired through
    ``src.api.service_registry`` instead of directly in server.py's
    lifespan."""

    def __init__(
        self,
        display_name: str,
        reticulum_config_dir: str,
        identity_path: str,
        lxmf_storage_dir: str,
        message_repo: "MessageRepository",
        peer_repo: "ReticulumPeerRepository",
        ws_manager: "WebSocketManager",
        node_cfg: Optional[dict] = None,
        node_stats_provider=None,
        hardware_description: str = "",
        project_url: str = "https://github.com/KMX415/meshpoint",
        spaceapi_url: str = "",
        events_ical_url: str = "",
        notify_url: str = "",
        propagation_cfg: Optional[dict] = None,
        talkback_enabled: bool = False,
    ):
        self._display_name = display_name
        self._reticulum_config_dir = Path(reticulum_config_dir)
        self._identity_path = Path(identity_path)
        self._lxmf_storage_dir = lxmf_storage_dir
        self._message_repo = message_repo
        self._peer_repo = peer_repo
        self._ws_manager = ws_manager
        self._node_cfg = node_cfg or {"enabled": False}
        self._node_stats_provider = node_stats_provider
        self._hardware_description = hardware_description
        self._project_url = project_url
        self._spaceapi_url = spaceapi_url
        self._events_ical_url = events_ical_url
        self._notify_url = notify_url
        self._propagation_cfg = propagation_cfg or {"enabled": False}
        # Requires node hosting: every command answers from data a hosted
        # node already caches (see talkback.py's module docstring) -- this
        # flag alone does nothing unless node_cfg["enabled"] is also true
        # (enforced by config_routes.py's validator, not re-checked here).
        self._talkback_enabled = talkback_enabled
        self._talkback_last_reply: dict[str, float] = {}
        self._node = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._router = None
        self._source = None
        self._identity = None
        self._announce_log: deque = deque(maxlen=_ANNOUNCE_LOG_MAX)
        self._bg_tasks: set = set()
        self._pn_task: Optional[asyncio.Task] = None

    def _spawn(self, coro) -> None:
        """Fire-and-forget a coroutine, holding a strong ref so it isn't
        GC'd mid-flight, and swallowing its result/exception."""
        task = asyncio.ensure_future(coro)
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    @property
    def available(self) -> bool:
        """False when rns/lxmf aren't installed -- lets the caller log a
        clear reason instead of crashing startup when a user enables this
        plugin before running its setup step (`sudo meshpoint plugin
        setup reticulum`, which `pip install`s lxmf)."""
        return RNS is not None and LXMF is not None

    @property
    def own_address(self) -> Optional[str]:
        return RNS.prettyhexrep(self._source.hash) if self._source else None

    async def start(self) -> None:
        if not self.available:
            logger.warning(
                "reticulum plugin is enabled but rns/lxmf are not installed -- "
                "run `sudo meshpoint plugin setup reticulum` on the Pi (installs "
                "lxmf + the rnsd unit). Skipping Reticulum startup."
            )
            return

        self._loop = asyncio.get_running_loop()

        # Explicit configdir -- RNS.Reticulum()'s own default is
        # ~/.reticulum, which resolves against $HOME for whatever user
        # runs this process. The meshpoint systemd user has no real
        # home directory, which crashes RNS trying to create its local
        # client-side storage there. This directory only needs to be
        # writable by meshpoint itself -- it does not need to match
        # rnsd's own configdir (see the old ReticulumConfig docstring).
        self._reticulum_config_dir.mkdir(parents=True, exist_ok=True)

        # Deliberately NOT run via run_in_executor: RNS.Reticulum()'s
        # own __init__ calls signal.signal(SIGINT, ...), which Python
        # only permits from the main thread -- doing this from a
        # worker thread raises "signal only works in main thread"
        # (confirmed live). It's a one-time startup call before the
        # server accepts requests, same as the synchronous SX1302 HAL
        # init earlier in this same lifespan -- acceptable to block on
        # briefly here.
        reticulum = RNS.Reticulum(configdir=str(self._reticulum_config_dir))
        _install_rns_log_bridge()
        logger.info(
            "Reticulum instance ready (config dir: %s)", reticulum.configdir
        )

        self._identity_path.parent.mkdir(parents=True, exist_ok=True)
        if self._identity_path.exists():
            self._identity = RNS.Identity.from_file(str(self._identity_path))
            logger.info("Reticulum: loaded identity from %s", self._identity_path)
        else:
            self._identity = RNS.Identity()
            self._identity.to_file(str(self._identity_path))
            logger.info(
                "Reticulum: generated new identity at %s", self._identity_path
            )

        self._router = LXMF.LXMRouter(storagepath=self._lxmf_storage_dir)
        self._source = self._router.register_delivery_identity(
            self._identity, display_name=self._display_name,
        )
        self._router.register_delivery_callback(self._on_lxmf_message)

        for aspect in _ANNOUNCE_ASPECTS:
            RNS.Transport.register_announce_handler(
                _AnnounceHandler(aspect, self._on_announce)
            )

        self._source.announce()
        logger.info(
            "Reticulum LXMF service started -- address %s", self.own_address
        )

        if self._propagation_cfg.get("enabled"):
            self._start_propagation()

        if self._node_cfg.get("enabled"):
            from .nomad_node import NomadNode
            self._node = NomadNode(
                identity=self._identity,
                name=self._node_cfg.get("name") or self._display_name,
                pages_dir=self._node_cfg.get("pages_dir", "data/reticulum/pages"),
                announce_interval_s=self._node_cfg.get("announce_interval_s", 21600),
                stats_provider=self._node_stats_provider,
                hardware_description=self._hardware_description,
                project_url=self._project_url,
                spaceapi_url=self._spaceapi_url,
                events_ical_url=self._events_ical_url,
            )
            await self._node.start()

    async def stop(self) -> None:
        # Neither RNS nor LXMF expose a clean per-client detach -- process
        # exit is how meshchat.py itself relies on state being flushed too.
        if self._pn_task is not None:
            self._pn_task.cancel()
            self._pn_task = None
        if self._node is not None:
            await self._node.stop()
            self._node = None
        self._router = None
        self._source = None

    def node_status(self) -> Optional[dict]:
        return self._node.status() if self._node is not None else None

    # --- LXMF propagation node ------------------------------------------------

    @property
    def propagation_address(self) -> Optional[str]:
        """The ``lxmf.propagation`` destination hash (a *different* hash from
        the delivery/browse one -- this is what a client points at to sync)."""
        try:
            return RNS.prettyhexrep(self._router.propagation_destination.hash)
        except Exception:  # noqa: BLE001 -- RNS missing / not enabled yet
            return None

    def _start_propagation(self) -> None:
        """Turn this node into an LXMF store-and-forward relay. LXMF's own
        ``LXMRouter`` does the work; we just enable it, cap its on-disk store,
        and re-announce the propagation destination on an interval (same shape
        as reticulum-meshchat's local propagation node)."""
        limit_mb = int(self._propagation_cfg.get("storage_limit_mb") or 0)
        if limit_mb > 0:
            # Not in every LXMF version, and the kw name has changed across
            # releases -- best-effort, never let it block enabling propagation.
            try:
                self._router.set_message_storage_limit(megabytes=limit_mb)
            except Exception:  # noqa: BLE001
                logger.debug(
                    "LXMF: set_message_storage_limit unavailable -- store uncapped",
                    exc_info=True,
                )
        try:
            self._router.enable_propagation()
        except Exception:  # noqa: BLE001
            logger.exception("LXMF: could not enable the propagation node")
            return
        self._announce_propagation()
        logger.info(
            "LXMF propagation node enabled -- address %s (store limit %s MB)",
            self.propagation_address or "?",
            self._propagation_cfg.get("storage_limit_mb") or "unlimited",
        )
        if self._loop is not None:
            self._pn_task = self._loop.create_task(self._propagation_announce_loop())

    def _announce_propagation(self) -> None:
        try:
            self._router.announce_propagation_node()
        except Exception:  # noqa: BLE001
            logger.debug("LXMF: propagation-node announce failed", exc_info=True)

    async def _propagation_announce_loop(self) -> None:
        while True:
            await asyncio.sleep(_PROPAGATION_ANNOUNCE_INTERVAL_S)
            self._announce_propagation()

    def propagation_status(self) -> Optional[dict]:
        """``None`` unless the propagation node is enabled -- feeds
        GET /api/reticulum/status and the Settings tab."""
        if not self._propagation_cfg.get("enabled") or self._router is None:
            return None
        held = None
        try:
            entries = getattr(self._router, "propagation_entries", None)
            if entries is not None:
                held = len(entries)
        except Exception:  # noqa: BLE001
            pass
        return {
            "enabled": True,
            "address": self.propagation_address,
            "storage_limit_mb": int(self._propagation_cfg.get("storage_limit_mb") or 0),
            "messages_held": held,
        }

    def reload_node_pages(self) -> bool:
        """Re-register the hosted node's ``.mu`` request handlers (Pages
        tab, after a create/delete). Returns ``False`` when no node is
        running -- the file was still written, it just won't be served
        until the node starts."""
        if self._node is not None:
            self._node.reload_pages()
            return True
        return False

    def _on_announce(
        self, aspect: str, destination_hash: bytes, app_data: Optional[bytes],
    ) -> None:
        display_name = ""
        if app_data:
            if aspect == "nomadnetwork.node":
                # NomadNet node announces carry the node name as raw UTF-8
                # (see nomad_node.py / NomadNet's own Node.py) -- not LXMF's
                # structured app_data, which is why LXMF.display_name_from_
                # app_data logs "Could not decode" on these.
                try:
                    display_name = bytes(app_data).decode("utf-8", errors="replace").strip()
                except Exception:
                    display_name = ""
            else:
                try:
                    display_name = LXMF.display_name_from_app_data(app_data) or ""
                except Exception:
                    display_name = ""
        dest_hex = RNS.hexrep(destination_hash, delimit=False)
        # Kept alongside display_name for the Activity tab's detail popup --
        # display_name is already a lossy decode (utf-8 for NomadNet nodes,
        # LXMF's own parser otherwise), the raw hex is the actual bytes an
        # operator would want when display_name comes back empty/garbled.
        app_data_hex = bytes(app_data).hex() if app_data else None
        if self._loop is not None:
            asyncio.run_coroutine_threadsafe(
                self._handle_announce(dest_hex, display_name, aspect, app_data_hex), self._loop,
            )

    async def _handle_announce(
        self, destination_hash: str, display_name: str, aspect: str,
        app_data_hex: Optional[str] = None,
    ) -> None:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "destination_hash": destination_hash,
            "display_name": display_name,
            "aspect": aspect,
            "app_data_hex": app_data_hex,
        }
        self._announce_log.append(entry)
        await self._ws_manager.broadcast("reticulum_announce", entry)

        if aspect in _ROSTER_ASPECTS:
            await self._peer_repo.record_announce(
                destination_hash, display_name, aspect,
            )
            await self._ws_manager.broadcast(
                "reticulum_peer",
                {
                    "destination_hash": destination_hash,
                    "display_name": display_name,
                    "aspect": aspect,
                },
            )

    def announce_log(self) -> list[dict]:
        """The recent announce ring buffer, newest first -- backs
        GET /api/reticulum/announces and the Activity tab."""
        return list(reversed(self._announce_log))

    def _on_lxmf_message(self, message) -> None:
        if self._loop is not None:
            asyncio.run_coroutine_threadsafe(
                self._handle_inbound_message(message), self._loop,
            )

    async def _handle_inbound_message(self, message) -> None:
        source_hex = RNS.hexrep(message.source_hash, delimit=False)
        text = (
            message.content.decode("utf-8", errors="replace")
            if message.content else ""
        )
        packet_id = message.hash.hex() if getattr(message, "hash", None) else ""
        peers = await self._peer_repo.list_peers()
        name = next(
            (p.display_name for p in peers if p.destination_hash == source_hex), "",
        )
        row_id, is_duplicate = await self._message_repo.save_received(
            text=text, node_id=source_hex, node_name=name,
            protocol="reticulum", packet_id=packet_id,
        )
        if is_duplicate:
            return
        await self._ws_manager.broadcast(
            "reticulum_message",
            {
                "id": row_id, "direction": "received", "text": text,
                "node_id": source_hex, "node_name": name,
            },
        )
        # Also fire the core cross-protocol event (src/api/server.py's own
        # Meshtastic/MeshCore inbound path broadcasts this) so the shared
        # Messages page live-updates an open Reticulum thread the same way
        # it already does for every other protocol -- "reticulum_message"
        # above is plugin-private, only reticulum_panel.js listens for it.
        # Confirmed live 2026-09-08: without this, a reply only appeared
        # after a manual page reload.
        own_hex = RNS.hexrep(self._source.hash, delimit=False) if self._source else ""
        await self._ws_manager.broadcast(
            "message_received",
            {
                "text": text, "node_id": source_hex, "node_name": name,
                "protocol": "reticulum", "direction": "received",
                "packet_id": packet_id, "source_id": source_hex,
                "destination_id": own_hex,
            },
        )
        if self._notify_url:
            self._spawn(self._notify_inbound(name or source_hex[:16], text))
        if self._talkback_enabled and self._node is not None:
            self._maybe_talkback(source_hex, text)

    def _maybe_talkback(self, source_hex: str, text: str) -> None:
        command = talkback.parse_command(text)
        if command is None:
            return
        own_hex = RNS.hexrep(self._source.hash, delimit=False) if self._source else None
        if source_hex == own_hex:
            return  # never reply to ourselves (e.g. a self-test DM)
        last = self._talkback_last_reply.get(source_hex, 0.0)
        now = time.monotonic()
        if now - last < _TALKBACK_COOLDOWN_S:
            return
        self._talkback_last_reply[source_hex] = now
        reply = talkback.build_reply(
            command,
            node_name=self._node.name,
            stats=self._node.stats_snapshot(),
            spaceapi_configured=self._node.spaceapi_configured,
            spaceapi=self._node.spaceapi_snapshot() if self._node.spaceapi_configured else {},
            events_configured=self._node.events_configured,
            events=self._node.events_snapshot() if self._node.events_configured else [],
        )
        self._spawn(self._send_talkback_reply(source_hex, reply))

    async def _send_talkback_reply(self, destination_hash_hex: str, text: str) -> None:
        try:
            await self.send_message(destination_hash_hex, text)
        except Exception:  # noqa: BLE001 -- best-effort, same as notify
            logger.debug("talkback reply failed", exc_info=True)

    async def _notify_inbound(self, sender: str, text: str) -> None:
        preview = text if len(text) <= 240 else text[:237] + "..."
        try:
            await asyncio.to_thread(
                notify.post, self._notify_url,
                title=f"LXMF from {sender}", body=preview,
            )
        except Exception:  # noqa: BLE001 -- notification is best-effort
            logger.debug("inbound-message notification failed", exc_info=True)

    async def send_message(self, destination_hash_hex: str, text: str) -> int:
        """Sends a direct LXMF message. Raises ValueError if the
        destination's identity still can't be resolved after actively
        requesting its path (see below) -- the same real constraint
        reticulum-meshchat's own UI has, just with a real attempt at
        discovery first rather than failing on a cold local cache."""
        if not self.available or self._router is None or self._source is None:
            raise RuntimeError("Reticulum service is not running")

        dest_hash = bytes.fromhex(destination_hash_hex)
        identity = RNS.Identity.recall(dest_hash)
        if identity is None:
            # Identity.recall() only finds destinations we've seen a real
            # announce for -- a peer we only know about because a message
            # arrived FROM them (a Link handshake) isn't necessarily in
            # that same table yet, confirmed live: meshpoint received a
            # message from a peer's fresh session and still couldn't
            # recall() them seconds later to reply. request_path() asks
            # the network (or, on a shared instance, effectively asks
            # rnsd) to (re)announce that destination if it's reachable,
            # same as reticulum-meshchat and other real RNS apps do
            # before giving up -- not just a testing convenience, this
            # is the correct way to handle a cold cache in production too.
            RNS.Transport.request_path(dest_hash)
            for _ in range(_PATH_REQUEST_RETRIES):
                await asyncio.sleep(_PATH_REQUEST_POLL_INTERVAL_S)
                identity = RNS.Identity.recall(dest_hash)
                if identity is not None:
                    break

        if identity is None:
            raise ValueError(
                "Unknown destination -- requested its path but got no "
                "response; this peer may be offline or has never announced"
            )

        destination = RNS.Destination(
            identity, RNS.Destination.OUT, RNS.Destination.SINGLE,
            "lxmf", "delivery",
        )
        lxm = LXMF.LXMessage(
            destination, self._source, text, desired_method=LXMF.LXMessage.DIRECT,
        )
        self._router.handle_outbound(lxm)

        peers = await self._peer_repo.list_peers()
        name = next(
            (p.display_name for p in peers
             if p.destination_hash == destination_hash_hex), "",
        )
        row_id = await self._message_repo.save_sent(
            text=text, node_id=destination_hash_hex, node_name=name,
            protocol="reticulum",
        )
        # No core protocol actually fires this today (messaging.js's own
        # 'message_sent' listener only ever touches the sidebar/contacts
        # list, never the open thread -- so this is safe to add: it can't
        # double-render anything). Added so a *second* session watching
        # this same conversation (e.g. the admin dashboard of the node
        # that just auto-replied via the talkback bot) sees its sidebar
        # preview update without a reload -- the session that actually
        # called this (a human's Send tab) already renders optimistically
        # from the HTTP response, same as every other protocol.
        await self._ws_manager.broadcast(
            "message_sent",
            {
                "text": text, "node_id": destination_hash_hex, "node_name": name,
                "protocol": "reticulum", "direction": "sent",
            },
        )
        return row_id

    async def list_peers(self):
        return await self._peer_repo.list_peers()

    async def peer_count(self) -> int:
        return await self._peer_repo.count()

    def announce(self) -> None:
        """Re-sends meshpoint's own delivery announce on demand -- lets
        a peer whose local cache is cold (e.g. a freshly-attached
        client that missed the last automatic announce, exactly the
        failure mode send_message()'s own request_path/retry logic
        above works around) learn our identity immediately instead of
        waiting for the next automatic one."""
        if self._source is None:
            raise RuntimeError("Reticulum service is not running")
        self._source.announce()
        if self._node is not None:
            # one identity, two aspects -- announce the node hash too so
            # "Announce" refreshes both "message me" and "browse me".
            self._node.announce()
        if self._pn_task is not None:
            self._announce_propagation()
