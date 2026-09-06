"""Host a NomadNet node -- serve Micron pages over Reticulum.

Registered on the **same RNS Identity** as ``LxmfService``'s
``lxmf.delivery`` destination, so this Meshpoint appears on the network as
both "message me" (LXMF) and "browse me" (``nomadnetwork.node``) on one
hash -- exactly how a NomadNet user with a hosted node appears.

Opt-in (``plugins.reticulum.node_enabled``, off by default). Serves:
  * ``/page/index.mu``  -- generated: node name + live Meshpoint stats +
    an "about" blurb. An operator ``index.mu`` in ``node_pages_dir``
    overrides it.
  * ``/page/nodes.mu``  -- generated: the other ``nomadnetwork.node``
    peers this Meshpoint has heard.
  * ``/page/<name>.mu`` -- any ``.mu`` file the operator drops in
    ``node_pages_dir``.
  * ``/file/<path>``    -- any file under ``node_pages_dir/files/``.

RNS matches request handlers by exact path (one per file), so there's no
traversal surface -- new files need a restart to be registered.

Mechanics ported in spirit from NomadNet's own ``nomadnet/Node.py`` (Mark
Qvist, markqvist/NomadNet, MIT).
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Awaitable, Callable, Optional

logger = logging.getLogger(__name__)

try:
    import RNS
except ImportError:
    RNS = None

_STATS_REFRESH_S = 300  # the node index page is rarely hit; don't poll hard


def _esc(s: str) -> str:
    """Micron has no escaping need for plain text except the backtick."""
    return str(s).replace("\\", "\\\\").replace("`", "\\`")


class NomadNode:
    def __init__(
        self,
        identity,
        name: str,
        pages_dir: str,
        announce_interval_s: int,
        stats_provider: Optional[Callable[[], Awaitable[dict]]] = None,
    ):
        self._identity = identity
        self._name = name
        self._pages_dir = Path(pages_dir)
        self._announce_interval_s = max(600, int(announce_interval_s))
        self._stats_provider = stats_provider

        self._destination = None
        self._announce_task: Optional[asyncio.Task] = None
        self._stats_task: Optional[asyncio.Task] = None
        self._stats: dict = {}
        self._last_announce: Optional[float] = None
        self._requests_served = 0

    # --- lifecycle ----------------------------------------------------------

    async def start(self) -> None:
        if RNS is None or self._identity is None:
            logger.warning("NomadNet node: RNS/identity not available -- not starting")
            return

        self._destination = RNS.Destination(
            self._identity, RNS.Destination.IN, RNS.Destination.SINGLE,
            "nomadnetwork", "node",
        )
        self._destination.set_link_established_callback(self._on_link)
        self._register_handlers()

        if self._stats_provider is not None:
            await self._refresh_stats()
            self._stats_task = asyncio.get_running_loop().create_task(self._stats_loop())

        self._announce()
        self._announce_task = asyncio.get_running_loop().create_task(self._announce_loop())
        logger.info(
            "NomadNet node hosting as %r (announce every %ds)",
            self._name, self._announce_interval_s,
        )

    async def stop(self) -> None:
        for task in (self._announce_task, self._stats_task):
            if task:
                task.cancel()
        self._announce_task = self._stats_task = None
        self._destination = None

    def status(self) -> dict:
        return {
            "hosting": self._destination is not None,
            "name": self._name,
            "pages": self._page_count(),
            "requests_served": self._requests_served,
            "last_announce_s_ago": (
                None if self._last_announce is None
                else int(time.monotonic() - self._last_announce)
            ),
        }

    # --- RNS wiring -------------------------------------------------------

    def _on_link(self, link) -> None:
        try:
            link.set_resource_strategy(RNS.Link.ACCEPT_ALL)
        except Exception:  # noqa: BLE001 -- older RNS may not need it
            pass

    def _register_handlers(self) -> None:
        d = self._destination
        pages = self._pages_dir

        op_index = pages / "index.mu"
        d.register_request_handler(
            "/page/index.mu",
            response_generator=(
                self._make_file_server(op_index) if op_index.exists()
                else self._serve_index
            ),
            allow=RNS.Destination.ALLOW_ALL,
        )
        d.register_request_handler(
            "/page/nodes.mu",
            response_generator=self._serve_nodes,
            allow=RNS.Destination.ALLOW_ALL,
        )

        if pages.is_dir():
            for p in sorted(pages.glob("*.mu")):
                if p.name in ("index.mu", "nodes.mu"):
                    continue
                d.register_request_handler(
                    f"/page/{p.name}",
                    response_generator=self._make_file_server(p),
                    allow=RNS.Destination.ALLOW_ALL,
                )
            files_dir = pages / "files"
            if files_dir.is_dir():
                for p in sorted(files_dir.rglob("*")):
                    if p.is_file():
                        rel = p.relative_to(files_dir).as_posix()
                        d.register_request_handler(
                            f"/file/{rel}",
                            response_generator=self._make_file_server(p, is_file=True),
                            allow=RNS.Destination.ALLOW_ALL,
                        )

    def _page_count(self) -> int:
        n = 2  # index + nodes (generated)
        if self._pages_dir.is_dir():
            n += sum(
                1 for p in self._pages_dir.glob("*.mu")
                if p.name not in ("index.mu", "nodes.mu")
            )
        return n

    # --- announce ------------------------------------------------------

    def announce(self) -> None:
        """Re-send the ``nomadnetwork.node`` announce on demand (the
        Reticulum page's Announce button), so a browsing client learns
        our node hash without waiting for the next automatic one."""
        if self._destination is not None:
            self._announce()

    def _announce(self) -> None:
        try:
            self._destination.announce(app_data=self._name.encode("utf-8"))
            self._last_announce = time.monotonic()
        except Exception:  # noqa: BLE001
            logger.exception("NomadNet node announce failed")

    async def _announce_loop(self) -> None:
        while True:
            await asyncio.sleep(self._announce_interval_s)
            self._announce()

    async def _stats_loop(self) -> None:
        while True:
            await asyncio.sleep(_STATS_REFRESH_S)
            await self._refresh_stats()

    async def _refresh_stats(self) -> None:
        try:
            self._stats = await self._stats_provider() or {}
        except Exception:  # noqa: BLE001
            logger.debug("NomadNet node stats refresh failed", exc_info=True)

    # --- request handlers (called on RNS's thread; return bytes) --------

    def _make_file_server(self, path: Path, is_file: bool = False):
        def _serve(request_path, data, request_id, link_id, remote_identity, requested_at):
            self._requests_served += 1
            try:
                return path.read_bytes()
            except OSError:
                return b"`!Not found`!"
        return _serve

    def _serve_index(self, request_path, data, request_id, link_id, remote_identity, requested_at):
        self._requests_served += 1
        s = self._stats
        lines = [
            "`c`F0a0`!" + _esc(self._name) + "`!`f`a",
            "`ca Meshpoint node`a",
            "-",
            "This node announces itself on the Reticulum network as "
            "`!nomadnetwork.node`!, sharing one identity with its LXMF",
            "address -- so you can browse it here and message it over LXMF.",
            "",
            ">Meshpoint",
        ]
        if s.get("version"):
            lines.append("Version              : " + _esc(s["version"]))
        if s.get("uptime"):
            lines.append("Uptime               : " + _esc(s["uptime"]))
        if s.get("reticulum_peers") is not None:
            lines.append("Reticulum peers heard : " + str(s["reticulum_peers"]))
        if s.get("nomad_nodes") is not None:
            lines.append("NomadNet nodes heard  : " + str(s["nomad_nodes"]))
        if s.get("conversations") is not None:
            lines.append("LXMF conversations    : " + str(s["conversations"]))
        lines += [
            "",
            ">Pages",
            "`[Nodes this Meshpoint has heard`:/page/nodes.mu]",
            "",
            ">About Meshpoint",
            "A multi-protocol LoRa mesh gateway + dashboard (Meshtastic,",
            "MeshCore, LoRaWAN, POCSAG/DAPNET, Reticulum).",
            "`[github.com/javastraat/meshpoint`https://github.com/javastraat/meshpoint]",
        ]
        return ("\n".join(lines)).encode("utf-8")

    def _serve_nodes(self, request_path, data, request_id, link_id, remote_identity, requested_at):
        self._requests_served += 1
        nodes = self._stats.get("recent_nodes") or []
        lines = [
            "`c`F0a0`!NomadNet nodes " + _esc(self._name) + " has heard`!`f`a",
            "-",
        ]
        if not nodes:
            lines.append("(none yet -- this Meshpoint hasn't heard a nomadnetwork.node announce)")
        for n in nodes[:100]:
            label = _esc(n.get("display_name") or n.get("destination_hash", ""))
            dh = n.get("destination_hash", "")
            lines.append(f"`[{label}`{dh}:/page/index.mu]")
        return ("\n".join(lines)).encode("utf-8")
