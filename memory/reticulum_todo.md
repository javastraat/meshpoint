# Reticulum plugin — backlog & handoff

What the plugin does today, what's in flight, and what could come next.
See `memory/plugin-reticulum.md` for implementation detail (dated sections,
one per feature) and `memory/project_m1_meshpoint.md` for wider session
context.

Last updated 2026-09-08 (talk-back bot built + switched to dot-prefixed commands).

---

## Status — where we are

All three items from the first pass are **built and committed** on `main`:

| Feature | Commit | Pi-verified? |
|---|---|---|
| Activity tab (raw announce feed) | `073f9ba7` | ⏳ needs a look on the device |
| DM notifications (`notify_url`) | `073f9ba7` | ⏳ (user said they won't use it — low priority) |
| LXMF propagation node (server side) | `9fdada63` | 🟡 **UI confirmed on rakv2-meshpoint 2026-09-07** (fieldset renders, values load). **Relay function NOT yet tested** — see below. |

Dev is on the Mac; the device is the user's Pi (SenseCap M1 / RAK V2),
deployed by the user. Mac has **no `rns` / `lxmf`** — backend logic is
tested with fakes; anything touching the live RNS/LXMF stack must be
checked on the Pi.

### Pi verification still owed

- **Activity tab — LIVE-VERIFIED 2026-09-08**: user shared a live capture,
  announces streaming in fast (public Reticulum network), all three
  aspects present (`lxmf.delivery`, `lxmf.propagation`,
  `nomadnetwork.node` with working Browse buttons) plus a `call.audio`
  row (Philster) confirming the stream-only voice-peer path too.
- **Peer drawer / Announce popup — REDESIGNED 2026-09-08, not opened in a
  real browser since the redesign**: user compared the original simple
  version against MeshCore's richer contact drawer ("we like gui design
  of the contacts better more info etc") and asked for real routing/
  signal data plus the same layered-section visual style as Meshtastic's
  packet-detail popup. Rebuilt: click a Peers row → drawer now shows
  Identity, a live-fetched Routing section (hops/path/next-hop/identity-
  resolved/announce-count via new `GET /peers/{hash}/link`), a Signal
  section when the peer's most recent announce carried RSSI/SNR (RNode-
  heard only), then Recent activity; click an Activity row → popup shows
  Routing/Signal/Payload the same way. **LIVE-VERIFIED same day** — user
  shared screenshots of both working on the device: the announce popup
  showing Routing + Payload, the peer drawer showing a live-resolved
  Routing section (Hops: 4, Path known: Yes, Next hop interface
  `TCPInterface[...]`, Identity resolved: Yes, Announces this session).
  **Then asked "why can't we have them 100% the same looking as in
  meshcore or meshtastic"** -- correctly pushed back on the first pass
  using hand-copied `rt-pdm-*` CSS that only *approximated*
  `packet_detail_modal.css`. Rebuilt to literally emit core's own class
  names (`nd-drawer`/`nd-header`/`nd-section`/`nd-row` for the peer
  drawer, `pdm-overlay`/`pdm-modal`/`pdm-layer`/`pdm-row` for the
  announce popup) instead of duplicating them -- both stylesheets
  already load globally, same reasoning as this plugin already reusing
  `lw-*`/`mt-badge`/`terminal-button`/`cfg-*`, so this is genuinely
  pixel-identical now, not a lookalike. Peer drawer sections are also
  now collapsible (matching NodeDrawer's own arrow-toggle behavior),
  and the avatar circle uses the exact same hash-to-HSL-color function.
  **Not yet re-verified live with this second (exact-reuse) version** --
  the screenshots above are from the *first* (`rt-pdm-*`) version; check
  both light/dark theme again, confirm the live Routing/Signal fetch
  populates, confirm a TCP-only peer shows no Signal section at all, and
  that section-collapse/expand + "View peer"/"Browse this node" still
  work. **LIVE-VERIFIED the exact-reuse version too** — user confirmed
  side-by-side with Meshtastic's Packet detail that the announce popup
  is genuinely identical (the one visible difference, a focus-ring box
  around the close button in one screenshot but not the other, was just
  a focus-vs-blurred-state artifact, not a style gap). Then compared the
  peer drawer against Meshtastic's node drawer and found three **real**
  (non-cosmetic) gaps, all fixed same day: added a **Send Message**
  button (admin-only, `lxmf.delivery` peers) that jumps to the Send tab
  pre-filled with that peer; added a **favourite star** for
  `nomadnetwork.node` peers, sharing the exact same `localStorage` list
  (`meshpoint.rtNomadFavourites`) the Browse tab's own favourites
  already use — a node starred from either place shows starred in both;
  and shortened the "Next hop interface" row (a long RNS descriptor like
  `TCPInterface[ReticulumNet Internet/node.reticulumnet.nl:4242]`,
  wrapped across two lines before) to just the interface class name with
  the full string as a hover tooltip. **These three additions
  themselves haven't been opened in a browser yet** — check the Send
  Message button actually pre-fills and focuses the Send tab, that
  starring a node from the drawer shows up in the Browse tab's
  Favourites optgroup and vice versa, and that the interface name looks
  right (short text + working tooltip).
- **sample-bbs-techinc nav links (fixed 2026-09-07, not walked in a real
  NomadNet client)**: browse the hosted node in Sideband/NomadNet/
  MeshChat, click "Next" through every page, confirm no dead links and
  that the `spacestate.mu`/`events.mu` cross-link only appears when both
  `node_spaceapi_url` and `node_events_ical_url` are actually set.
- **Talk-back bot — FULLY LIVE-VERIFIED 2026-09-08, all 6 commands.**
  Ran a real two-node exchange (rakv2-meshpoint ↔ ti-meshpoint), pre- and
  post-dot-prefix. All six commands confirmed correct with the final
  `.`-prefixed syntax: `.help` lists all six correctly, `.ping`→`pong`,
  `.stats` shows live version/uptime/peer counts, `.spacestate` shows
  real SpaceAPI status (TechInc: CLOSED, address), `.events` lists real
  upcoming events with correct truncation ("...and 7 more"), `.nodes`
  lists real heard NomadNet nodes with correct truncation ("...and 85
  more"). Live-update (no reload) confirmed throughout. Only remaining
  untested edge cases: a bare word (no dot) actually getting no reply,
  and the save form rejecting `talkback_enabled` with `node_enabled`
  off — both low-risk, covered by unit tests already.
- **Fixed + LIVE-VERIFIED 2026-09-08: Reticulum messages (including
  talkback replies) didn't live-update the Messages page.** Root cause:
  the core Messages page only listens for a `message_received` WS event;
  `lxmf_service.py` was only firing its own plugin-private
  `reticulum_message` event. Now fires both. `send_message()` also now
  fires `message_sent` (previously nothing did, anywhere). Confirmed
  working: `ping`→`pong` and `stats` both appeared live in the open
  thread with no reload.
- **Propagation node — NEEDS TESTING** (UI is confirmed on the device, the
  relay itself is not):
  1. Settings → Propagation node → tick "Act as an LXMF propagation node" →
     Save → `sudo systemctl restart meshpoint`.
  2. Re-open the tab — the grey hint line should become
     `Relaying now — address <lxmf.propagation hash>, 250 MB store, 0 message(s) held…`.
     If it doesn't, `enable_propagation()` failed — check the journal.
  3. In the journal on first start, look for a `set_message_storage_limit`
     line — `LXMRouter.set_message_storage_limit(megabytes=)` is called
     best-effort/guarded; if the LXMF version lacks it you'll see a debug
     note and the store stays at LXMF's default. Decide then whether to keep
     that call.
  4. Real end-to-end: from Sideband (or another node) set that
     `lxmf.propagation` hash as your propagation node, send a message to a
     third party who is **offline**, bring them online, have them sync —
     the message should arrive via the Pi.
  5. Check `messages_held` on the status line goes up while a message is
     parked, and the on-disk store under `data/reticulum/lxmf/` grows.

---

## Have

| Area | Feature | Notes |
|---|---|---|
| Transport | RNode radio + TCP backbone, independent on/off | attaches to `rnsd` shared instance; Settings tab + Restart-rnsd button |
| Messaging | LXMF direct messages, send + receive | own `lxmf.delivery` dest on the shared identity; Messages / Send tabs |
| Presence | Peer roster from announces | Peers tab; topbar pill = own address + RNode frequency |
| Activity | Raw announce feed | Activity tab: 200-entry ring buffer, live over `reticulum_announce` WS; incl. `call.audio` (stream-only); `nomadnetwork.node` rows get a Browse button |
| Notifications | ntfy / webhook on inbound DM | `notify_url` config; fire-and-forget POST (`backend/notify.py`) |
| Propagation node | LXMF store-and-forward relay | `propagation_enabled` + `propagation_storage_limit_mb`; own `lxmf.propagation` hash, re-announced 6 h; status line on Settings tab; `propagation` block on `GET /api/reticulum/status` |
| Peers/Activity | Click-to-detail | Peers row → right-side drawer (identity, live routing via `GET /peers/{hash}/link`: hops/path/next-hop/identity-resolved/announce-count, signal from most recent announce, recent activity, a Send Message button for `lxmf.delivery` peers, a favourite star for `nomadnetwork.node` peers sharing the Browse tab's own favourites list); Activity row → detail popup (routing, signal if heard via RNode, payload/app_data hex, "View peer"). Own JS/data (`reticulum_detail_panels.js`) but literally emits core's own `node_drawer.css`/`packet_detail_modal.css` class names (`nd-drawer`/`nd-section`/`nd-row`, `pdm-overlay`/`pdm-layer`/`pdm-row`) for pixel-identical styling — same reuse-not-duplicate pattern as `lw-*`/`mt-badge`/`terminal-button` elsewhere in this plugin |
| Browsing | NomadNet node browser | Browse tab: live filter, ☆ favourites, `:/page/x.mu` shortcuts |
| Hosting | Our own `nomadnetwork.node` | one hash = "message me" + "browse me" |
| Hosting | Generated `index` / `info` / `nodes` pages | `info.mu` = live version/uptime/host/mesh-activity stats |
| Hosting | Operator `.mu` pages + `files/` | Pages tab: editor, formatting toolbar, Micron cheat-sheet, live preview |
| Hosting | `/page/spacestate.mu` + `{spacestate}` token | SpaceAPI feed, lazy fetch (once at boot, then on view) |
| Hosting | `/page/events.mu` | iCalendar feed, lazy fetch |
| Hosting | Generated-page cross-links | `info.mu`↔`nodes.mu` always; `spacestate.mu`↔`events.mu` only when the other is configured. Never link into an operator's own custom pages — shared code, most installs won't have e.g. `meshpoint.mu` |
| Hosting | Talk-back bot | `talkback_enabled` (requires `node_enabled`); DM `.help`/`.ping`/`.stats`/`.spacestate`/`.events`/`.nodes` (dot required — a bare word doesn't trigger it) for a plain-text reply built from the same cached data the `.mu` pages read. Pure functions in `backend/talkback.py`; loop-safe by construction (replies never start with `.`) + a per-sender cooldown |
| Ops | Dep check / setup / `meshpoint plugin check` | boot probe + on-demand + Run-setup modal |
| Samples | `sample-pages/`, `sample-bbs-techinc/` | TechInc BBS carries real address + "Contact us" (IRC/Matrix/email/phone) |
| Core (not this plugin) | RNode firmware flasher, Heltec-V4 node card | Configuration → Firmware |

### Config keys (all in `plugins.reticulum.*`, all also on the Settings tab)

```yaml
plugins:
  reticulum:
    enabled: false                      # Settings → Plugins owns this, not the tab
    display_name: "Meshpoint"
    rnode_enabled: true
    rnode_serial_port: ""
    rnode_frequency_hz: 869463000
    rnode_bandwidth_hz: 125000
    rnode_tx_power: 20
    rnode_spreading_factor: 8
    rnode_coding_rate: 5
    backbone_enabled: true
    backbone_host: node.reticulumnet.nl
    backbone_port: 4242
    nomad_timeout_s: 20                  # Browse tab link/path budget
    notify_url: ""                       # ntfy / webhook, POSTed on inbound DM
    propagation_enabled: false           # LXMF store-and-forward relay
    propagation_storage_limit_mb: 250    # 0 = LXMF default (don't leave uncapped on SD)
    node_enabled: false                  # host a NomadNet node
    node_name: ""                        # blank = display_name
    node_pages_dir: data/reticulum/pages
    node_announce_interval_s: 21600
    node_spaceapi_url: ""                # → /page/spacestate.mu + {spacestate}
    node_events_ical_url: ""             # → /page/events.mu
    talkback_enabled: false              # DM bot; requires node_enabled
```

---

## Could build — next up

| Prio | Feature | What it is | Effort / risk |
|---|---|---|---|
| Med | **Attachments in Send** | images / small files over `LXMF.FIELD_IMAGE` / `FIELD_FILE_ATTACHMENTS` | Send side is easy (set `lxm.fields` before `handle_outbound`). Inbound is the blocker: shared `messages` table (`src/storage/message_repository.py`) has no attachment columns and core's conversation UI can't render them — needs a design decision (disk store + flag vs a JSON column on the shared table) |
| Med | **Propagation node polish** | client side: sync *from* a preferred propagation node, show transfer progress; PN peering | Med — LXMF client API: `set_outbound_propagation_node`, `request_messages_from_propagation_node`, `propagation_transfer_state/progress/last_result` (all used in reticulum-meshchat `meshchat.py`) |
| Med | **Telemetry publish** (Sideband-style) | push Pi telemetry (CPU temp, load, GPS, sensors) as LXMF telemetry fields to a collector | Medium — reuse `backend/host_stats.py` |
| Med | **Telemetry collector + map** | receive peers' telemetry, plot on the dashboard's local map tiles | Med–High |
| Low | **Audio calls** (`call.audio` / LXST) | answer / receive voice; min viable = a recorded announcement on call | High — audio I/O + codec on the Pi, its own project |
| Low | **Group chat** (`RNS.Destination.GROUP`) | experimental shared-key room, no membership mgmt | Medium — non-standard |
| Low | **Interface manager UI** | add / remove RNS interfaces from the dashboard vs hand-editing config | Medium |
| Low | **Contacts / petnames** | address book with friendly names + trust / identity display | Low–Med |
| Low | **Paper messages / QR** | Sideband-style offline message export | Low–Med |

## Done (this backlog's completed items)

- **2026-09-08** — LXMF talk-back bot (`.help`/`.ping`/`.stats`/
  `.spacestate`/`.events`/`.nodes` over DM, requires `node_enabled`;
  dot prefix required, added same day so a bare conversational word
  can't trigger it). Live-tested same day (pre-dot-prefix), reply
  content confirmed correct; found + fixed a live-update bug in the
  same session (Reticulum messages weren't reaching the core Messages
  page's WS listener) — see Pi-verification list above for what's still
  unconfirmed.
- **2026-09-07** — Activity tab, DM notifications, LXMF propagation node
  (server side), click-to-detail on Peers/Activity, sample-bbs-techinc nav
  fixes + generated-page cross-links. Details: `memory/plugin-reticulum.md`
  dated sections.
- Earlier in the same session — SpaceAPI `/page/spacestate.mu` + `{spacestate}`
  token (later switched to lazy fetch), iCal `/page/events.mu`, the
  `sample-bbs-techinc/` page set, plugin dep-check / setup flow.

## Suggested order from here

1. Whatever the user's interested in next. Telemetry is a coherent pair
   (publish + collector). Audio is a separate project. Attachments need the
   `messages`-table decision first.

## Notes / constraints (read before building)

- Reticulum messaging is **1:1 by design** — LXMF addresses one
  `lxmf.delivery` destination. Group chat only exists via the lower-level
  `RNS.Destination.GROUP` (shared symmetric key) or community tooling.
- **Three aspects on one identity**, all concurrent: `lxmf.delivery`
  (inbox), `nomadnetwork.node` (pages, if `node_enabled`), `lxmf.propagation`
  (relay, if `propagation_enabled`). The propagation destination is a
  **separate hash**.
- Hosted `.mu` pages are served **non-executable** on purpose — dynamic
  content is done with generated pages (`_serve_*` in `backend/nomad_node.py`)
  or `{spacestate}`-style token substitution, never executable scripts.
- External feeds (SpaceAPI, iCal) use the **lazy fetch** pattern: prime once
  at startup, then refresh only when a page that needs it is viewed, off the
  RNS request thread (`_spaceapi_maybe_refresh` / `_events_maybe_refresh`).
  Reuse that shape for any new feed.
- Mac tests: `python3.11 -m pytest plugins/apps/reticulum/` (python3.14 has
  no pytest). No `fastapi` / `rns` / `lxmf` on the Mac — route tests are
  gated behind `_HAS_FASTAPI` and only run on CI / the Pi; RNS/LXMF paths
  are tested with fakes.
- LXMF API reference: `/Users/einstein/Software/reticulum-meshchat/meshchat.py`
  uses the same `LXMF` library — grep it for the real call shapes.
- CI gotcha (hit + fixed 2026-09-07): don't use `time.monotonic() - 0.0` as
  a "stale" marker in tests — on a freshly-booted runner `monotonic()` can be
  smaller than the staleness window. Use `time.monotonic() - <big>`.

## Resuming on another machine

Everything lives in the repo: `git pull` on `main` gets all the code plus
these `memory/*.md` files. Then:

1. Read `memory/project_m1_meshpoint.md`, `memory/plugin-reticulum.md`, this
   file.
2. `git log --oneline -20` — recent commits are the feature history.
3. If picking up mid-feature: `git status` for anything uncommitted.
4. Pi verification steps above are the open loop — the code is done, it just
   hasn't been run against a live RNS stack yet.
