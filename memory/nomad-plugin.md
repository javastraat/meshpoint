# NomadNet browsing as a plugin — findings

Scoping notes only. Nothing built yet. Written after reading the actual
mechanics in `~/Software/reticulum-meshchat` (Liam Cottle's client, MIT
licensed, already on this Mac from an earlier session's exploration) --
it has a complete, working NomadNet browser on the same `RNS`/`LXMF`
stack meshpoint already depends on, so this isn't "reverse-engineer an
undocumented protocol," it's "port a working reference."

## What NomadNet actually is

A BBS for Reticulum. A NomadNet **node** is a small server that hosts
pages written in **Micron** -- a deliberately minimal markup language
(closer to old ANSI BBS menus than HTML: headings, colors, links, form
fields, no images/layout/CSS) -- because it has to render meaningfully
over a link that might be a few hundred bytes/sec. Users navigate a
node's page tree, submit forms, download files. LXMF (meshpoint's own
messaging) and NomadNet (page browsing) are sibling applications built
on the same Reticulum primitives, not the same thing.

## Discovery: meshpoint already has this half built

Nodes announce themselves with aspect `nomadnetwork.node` -- one of the
3 aspects `LxmfService` already registers a handler for
(`src/reticulum/lxmf_service.py`'s `_ANNOUNCE_ASPECTS`). Every
`nomadnetwork.node` announce already lands in the `reticulum_peers`
table via the existing `_on_announce`/`_handle_announce` path, and
already shows up on the Reticulum page's Peers tab under
**Infrastructure**. A browsing plugin would not need its own discovery
mechanism -- it can just read `reticulum_peers` filtered to
`aspect = 'nomadnetwork.node'` as its own "list of known nodes."
Confirmed reticulum-meshchat does the exact same thing (`meshchat.py`'s
`on_nomadnet_node_announce_received` -> its own announce table -> node
list), so this isn't a simplification unique to piggybacking on
meshpoint, it's how every NomadNet client actually works: there is no
central directory, only what you've personally heard announced.

## The actual page-fetch mechanics (traced from meshchat.py:3421-3533)

Standard RNS `Link`/`Request` primitives, nothing exotic:

```python
# 1. Path discovery (same pattern LxmfService.send_message() already uses)
if not RNS.Transport.has_path(destination_hash):
    RNS.Transport.request_path(destination_hash)
    # poll has_path() until found or timeout

# 2. Build the OUT destination and recall the identity
identity = RNS.Identity.recall(destination_hash)
destination = RNS.Destination(
    identity, RNS.Destination.OUT, RNS.Destination.SINGLE,
    "nomadnetwork", "node",
)

# 3. Establish a Link (cache it per destination_hash -- reuse across
#    page navigations instead of re-linking on every click)
link = RNS.Link(destination, established_callback=on_established)

# 4. Once ACTIVE, request a page path over the link
link.request(
    "/page/index.mu",          # path -- '/' is the index page
    data=field_data,            # optional dict, for form submissions
    response_callback=on_response,
    failed_callback=on_failed,
    progress_callback=on_progress,
    timeout=15,
)

# 5. Response arrives as raw bytes -- decode as UTF-8 Micron markup
micron_text = request_receipt.response.decode("utf-8")
```

File downloads (`nomadnet.file.download` in meshchat.py) use the
identical Link+Request shape against a different path prefix
(`/file/...`), just returning raw bytes instead of markup text -- not a
separate mechanism, worth supporting almost for free once page-fetch
works.

## Rendering: Micron -> HTML

`src/frontend/js/MicronParser.js` in reticulum-meshchat (714 lines, MIT,
ported from NomadNet's own Python `MicronParser.py` originally) walks
Micron markup line-by-line and emits real DOM elements directly --
colors, bold/underline/italic, headings, alignment, links
(`nomadnetwork://<hash>:<page>`-style), radio-button form groups. This
is the piece with no Reticulum-specific "just call an RNS method"
shortcut -- it's a real small markup-to-DOM interpreter that needs
porting (with attribution, MIT allows this) or reimplementing against
meshpoint's own vanilla-JS-no-build-step convention (reticulum-meshchat
is Vue3/Vite, meshpoint is plain JS -- the parser logic itself doesn't
depend on Vue, but the surrounding component does, so this is a port of
the parser class, not a copy-paste of the whole page component).

## Where this plugs into meshpoint specifically

**User's own framing (2026-09-06), narrower than my first guess below:**
not a new top-level page -- a `"hook"` plugin targeting the existing
**Reticulum** page as host, same shape DAB+ hooks into the RTL-SDR
Plugins page today. Clicking a `nomadnetwork.node` row in the Peers tab
would open the browser inline on that same page (a modal, or a
tab/panel that expands in place), not navigate somewhere else. This is
a smaller, more scoped frontend surface than a whole separate sidebar
page + nav entry, and it fits Reticulum's own existing Peers-tab data
directly (no separate node picker needed -- the row you clicked *is*
the destination).

`docs/PLUGINS.md`'s hook seam requires the **Reticulum page itself to
opt in as a host** (`window.mountPageHooks(hostId, containerEl)`,
called from the host's own `mount()`) -- the Reticulum page is core
today, so this means either (a) making core's Reticulum panel call
`mountPageHooks('reticulum', ...)` the same way `rtlsdr_panel.js` does
for its own hooks, a small core change independent of whether Reticulum
itself is core or a plugin, or (b) this becomes moot once Reticulum
itself is a plugin (see next section) and its *own* page already needs
to be hook-host-capable as part of that extraction anyway.

**Also noted, same conversation: "Reticulum as a plugin app" is a
separate, related backlog item.** Not scoped here in any depth, but
directly relevant to the RNS-attach question below -- if
`src/reticulum/lxmf_service.py` moves into `plugins/apps/reticulum/`
the same way DAPNET moved out of core this session, then:
- The Reticulum page becoming hook-host-capable (needed for inline
  Nomad browsing above) happens naturally as part of that extraction's
  own frontend work, not as a separate core change.
- The RNS-attach duplication question below gets more interesting, not
  simpler -- a "nomad" hook plugin and its "reticulum" host plugin would
  be two *separate* plugin packages, and there's no existing seam for
  one plugin to reach into another plugin's backend module (confirmed
  this exact limitation earlier this session re: why `sdr_registry.py`
  can't move into `plugins/apps/rtlsdr/` -- a hook plugin importing
  its host plugin's Python internals directly would be the same
  anti-pattern). So even with Reticulum as a plugin, "share the one RNS
  attach" would need a real new capability (something like
  `capture`/`protocol`'s registries, but for "expose a live service
  object to a specifically-dependent hook plugin") -- not something to
  design in the abstract before either extraction is actually underway.
- Worth sequencing: if both land eventually, Reticulum-to-plugin
  probably comes first (it's the bigger, more foundational move,
  mirrors the DAPNET precedent closely), with Nomad browsing built as a
  hook on top of it second -- rather than building Nomad against core's
  Reticulum now and re-plumbing it later.

**Open question, not decided, independent of the above:** a Link/Request
caller needs a live `RNS` module handle and a `RNS.Identity`. Two
shapes regardless of whether Reticulum is core or a plugin at the time:

1. **Attach to `rnsd` independently**, same shared-instance client
   pattern `LxmfService` uses (`RNS.Reticulum(configdir=...)`, pointed
   at the same `reticulum_config_dir`) -- its own separate
   `RNS.Identity` (a browsing client doesn't obviously need to reuse
   the LXMF delivery identity; NomadNet Links don't require one
   specific identity the way an LXMF delivery destination does).
   Simple, fully decoupled -- but a second client process attachment, a
   second identity file, and (per the plugin-isolation point above) no
   way to reuse the host's already-running `reticulum_peers` table/live
   announce stream without a new cross-plugin data-sharing seam.
2. **A new seam exposes the already-running Reticulum handle** to
   whatever owns it (core today, a plugin later) -- avoids a second
   identity/attachment and reuses the live peer table directly. More
   plumbing, and worth building for a real second consumer, not
   speculatively for one plugin, per this project's own "don't guess a
   shared seam's shape from one caller" rule (`docs/PLUGINS.md`'s
   Current Limitations section).

Leaning toward (1) for a first version (genuinely simpler, ships
faster, works the same whether Reticulum is core or a plugin) with (2)
as a later refactor if the duplication actually bites. Not decided --
flagging both for whoever picks this up.

Capability-wise this is a `"routes"` + `"hook"` plugin (own
`/api/nomad/*` backend routes for path lookup/link/request, `[hook]
host = "reticulum"` in `plugin.toml`) -- no `"capture"`/`"protocol"`
needed (NomadNet traffic never touches the packet pipeline; same reason
the existing Reticulum page has no Packets tab, see
`memory/project_m1_meshpoint.md`'s 2026-08-09/10 entries).

## Rough shape of the work

- **Backend**: an `RNS.Reticulum()` attach (own or shared, per the open
  question above), a link-cache dict keyed by destination_hash (mirror
  `nomadnet_cached_links`), path-lookup + link-establish + page-request
  wrapped in async methods, `GET /api/nomad/nodes` (from
  `reticulum_peers` or its own announce table), `POST /api/nomad/page`
  (destination_hash + path + optional form field_data -> raw Micron
  text), same for file downloads.
- **Frontend, scoped down by the hook-into-Reticulum-page framing**:
  port `MicronParser.js`'s parsing logic (the class itself, not the Vue
  wrapper) to plain JS/DOM, plus an inline browser view (modal or
  in-page panel, opened from a click on a Peers-tab
  `nomadnetwork.node` row -- no separate node picker needed, the row
  clicked *is* the destination) with back/forward navigation history
  and a form-field renderer for pages that accept input. Smaller than a
  standalone page + its own nav entry would have been, but the Micron
  parser port itself is the same amount of work either way.
- **Effort, relative to work already shipped this project**: the
  backend (Link/Request wrapper + 2 routes) is modest, comparable to a
  single RTL-SDR plugin's listener; the Micron parser port is the real
  chunk of new, unique-to-this-feature work, with no shortcut available
  since it's a real markup interpreter, not a thin API wrapper. Overall
  smaller than the original native Reticulum messaging build was (that
  needed a multi-tab standalone page; this reuses the existing
  Reticulum page as its host). Not a small feature, not a multi-week
  rewrite either -- the hard "how does the protocol even work" part is
  already answered by working reference code.

## Not investigated yet

- Whether `link.request()`'s `failed_callback`/timeout behavior needs
  any special handling for a LoRa-only node (much higher latency than
  meshchat's usual TCP-backbone-first testing environment) -- the
  15-second timeouts reticulum-meshchat defaults to may be too short
  over a multi-hop LoRa path. Worth checking once real hardware testing
  starts, not something to guess at now.
- Whether NomadNet supports pagination/large pages differently than a
  single request/response (likely fine for typical small BBS-style
  pages, not confirmed for anything unusual).
- Exact licensing/attribution mechanics for porting `MicronParser.js`
  (MIT requires keeping the copyright notice somewhere reachable, not
  complicated, just not yet done).
