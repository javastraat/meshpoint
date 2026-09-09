# Reticulum plugin — backlog & handoff

What the plugin does today, what's in flight, and what could come next.
See `memory/plugin-reticulum.md` for implementation detail (dated sections,
one per feature) and `memory/project_m1_meshpoint.md` for wider session
context.

Last updated 2026-09-09 (new-builds #1 Contacts, #2 Propagation client, #3 Telemetry publish + location [Pi-verified], #4 Telemetry collector+map).

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
- **Contacts / petnames — BUILT 2026-09-09, PARTIALLY LIVE-VERIFIED
  same day** on ti-meshpoint (v0.8.1, HTTPS :8443). User saved a peer
  (`ffe6ea53…`, announced `echo@gvrd`) as "test" from the drawer's
  Contact section: "Saved." status shown, Peers row updated to `test ✓`
  (green checkmark = trusted), drawer header shows `test` + `announced
  as echo@gvrd` sub-line. Core save→render loop confirmed. **Still to
  check:** Send-tab picker shows the name (not the hash); Messages list
  shows it; Activity row + tooltip; **Remove** clears it on all
  surfaces and drops the ✓; both light/dark themes on the form; the
  JSON file at `/opt/meshpoint/data/reticulum/contacts.json`. **The
  dark-on-dark Name-input from the first screenshot was FIXED same
  day** — the Contact form inputs now reuse core's theme-aware
  `.cfg-field__input` instead of `#111`/`#eee` fallbacks (re-check both
  themes anyway). Detail: `memory/project_m1_meshpoint.md` dated
  2026-09-09.
- **Telemetry collect + map (#4) — BUILT + BROWSER-VERIFIED 2026-09-09**
  (user screenshot: TI-Meshpoint plotted near Schiphol at 52.3458/
  4.8264, table row, working OSM link, live WS). Two display tweaks from
  feedback: `_info_line` dropped its `°C` suffix (was double-printing —
  temp is its own sensor); then the temp moved from the cramped last
  column to the end of the STATUS cell, last column now Location-only.
  Both frontend-display only — wire `info` string stays temp-free.
  Still not a full two-node run.
  Check: with two nodes publishing to each other,
  each shows the other on its **Telemetry tab** (table row: heard /
  node / status + temp / location OSM link); a peer that sent location
  appears on the map; the `reticulum_telemetry` WS event live-updates
  the tab without reload; a telemetry-only frame does NOT show up as a
  blank message in the Messages tab (this was a latent bug — check it's
  gone); the map renders (Leaflet is globally loaded) and fits bounds.
- **Propagation client — BUILT 2026-09-09, not tested end-to-end.**
  Set `propagation_outbound_node` (Settings tab dropdown of
  `lxmf.propagation` peers), restart. Check: the dropdown lists heard
  relays; the saved hash stays selected after restart even if not
  re-heard; the client status line renders. Then the real test — from
  another node, send a DM to a third party who is **offline** with
  *this* box's peer set as *their* propagation node... actually the
  cleaner test: set a known public propagation node as our outbound,
  have someone send us a DM while we're stopped, start up, hit "Sync
  inbox", watch the transfer state cycle (requesting → link →
  receiving → complete) and the message land in Messages. Also: auto-
  sync interval > 0 actually re-syncs; a bad/unreachable node shows a
  failed state not a hang; "Sync inbox" hidden when no outbound node.
- **Telemetry publish — BUILT 2026-09-09, PARTIALLY VERIFIED on
  rakv2-meshpoint same day.** SID ids (`0x01`/`0x07`/`0x0F`) + `packed()`
  shape confirmed VERBATIM from Sideband `sense.py` (2nd WebFetch).
  **Confirmed working:** config saves, and after a **meshpoint** restart
  (not rnsd) the timed loop emits frames —
  `lxmf_service: telemetry frame sent to 5771b31b…` in the journal at
  the configured cadence.
  **NOT working — self-loopback:** frames sent to the Pi's own
  `lxmf.delivery` address did NOT come back (LXMF won't self-Link) —
  use two nodes.
  **TWO-NODE TEST PASSED 2026-09-09:** ti-meshpoint → rakv2. rakv2's
  journal:
  `LXMF telemetry from f59ffeffe1a465e6bbd0df88710db93a: {1: 1788948494, 7: 51.1, 15: 'TI-Meshpoint · load 0.42 · RAM 26% · disk 42.2 GB free · 51.1°C'}`
  — correct SIDs (1/7/15), correct types, well-formed string. Full
  pipeline verified: build → umsgpack → real LXMF DIRECT transport →
  receive → unpack. **Only remaining check (low-risk):** a real Sideband
  app rendering the frame — SIDs + `packed()` shape are verbatim from
  `sense.py` so structure matches; just not visually confirmed in
  Sideband yet.
  **SID_LOCATION added 2026-09-09 (after the two-node test):** opt-in
  `telemetry_include_location`; coords from core's
  `device.latitude/longitude` (Configuration → GPS pin) resolved in
  `__init__.py` `build()`, no plugin lat/lon keys. `_pack_location` =
  the 7-el struct-packed list from `sense.py`. Settings shows a warn
  hint if the toggle is on but no pin is set.
  **TWO-NODE VERIFIED WITH LOCATION 2026-09-09** (ti pin
  52.34579/4.82638/5m → rakv2): key `2` present, lat `0x031ebbbe`=
  52345790/1e6=52.34579, lon `0x0049a50c`=4826380/1e6=4.82638, alt
  `0x1f4`=5.0, speed/bearing/accuracy 0 — byte-exact match to
  `sense.py`. Only the Sideband-app visual render is still unconfirmed
  (low risk).
  **UX gotcha hit + fixed:** clicking "Send telemetry now" / "Sync
  inbox" right after Save (before a meshpoint restart) failed with a
  confusing "no collector/node" — the running service reads that config
  once at startup. Routes now detect "saved but service not restarted"
  and say so. The red "No telemetry collector configured" the user saw
  was this stale state.
  **Also noted:** core has its OWN unrelated `telemetry_broadcaster`
  module (`Telemetry broadcaster scheduled: first TX in 120s...`) —
  different feature, don't confuse the log sources. Ours is
  `lxmf_service: telemetry frame sent to…`.
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
| Propagation node | LXMF store-and-forward relay (server) | `propagation_enabled` + `propagation_storage_limit_mb`; own `lxmf.propagation` hash, re-announced 6 h; status line on Settings tab; `propagation` block on `GET /api/reticulum/status` |
| Propagation client | Use another node as your relay | `propagation_outbound_node` (Settings dropdown of `lxmf.propagation` peers) + `propagation_auto_sync_interval_s`; "Sync inbox" button in the Reticulum page header with live transfer state; `GET /api/reticulum/propagation` + admin `POST .../propagation/sync[/cancel]`; `propagation_client` block on `/status`. `backend/lxmf_service.py` `set_outbound_propagation_node`/`sync_propagation_messages`/`propagation_client_status`, mirrors reticulum-meshchat |
| Telemetry publish | Send host stats as LXMF telemetry | `telemetry_enabled` + `telemetry_collector` + `telemetry_interval_s` + `telemetry_include_location` (coords from core Configuration→GPS pin). `backend/telemetry.py` `build_telemetry` → Sideband `FIELD_TELEMETRY` (0x02) frame: `SID_TIME`/`SID_TEMPERATURE`/`SID_INFORMATION`/`SID_LOCATION`. `lxmf_service.send_telemetry()`/`_telemetry_loop()`. `GET /api/reticulum/telemetry` + admin `POST .../telemetry/send`; "Send telemetry now" button |
| Telemetry collect + map | Receive peers' telemetry | `_record_inbound_telemetry` decodes inbound `FIELD_TELEMETRY` → `telemetry.decode_telemetry` → `backend/telemetry_store.py` (in-mem, latest-per-peer, 24h prune, 500 cap). New **Telemetry tab** on the Reticulum page: table (heard / node / status / temp+location) + a small own-Leaflet map of located peers. `GET /api/reticulum/telemetry/peers`, live over `reticulum_telemetry` WS. Telemetry-only frames no longer create blank message rows |
| Peers/Activity | Click-to-detail | Peers row → right-side drawer (identity, live routing via `GET /peers/{hash}/link`: hops/path/next-hop/identity-resolved/announce-count, signal from most recent announce, recent activity, a Send Message button for `lxmf.delivery` peers, a favourite star for `nomadnetwork.node` peers sharing the Browse tab's own favourites list); Activity row → detail popup (routing, signal if heard via RNode, payload/app_data hex, "View peer"). Own JS/data (`reticulum_detail_panels.js`) but literally emits core's own `node_drawer.css`/`packet_detail_modal.css` class names (`nd-drawer`/`nd-section`/`nd-row`, `pdm-overlay`/`pdm-layer`/`pdm-row`) for pixel-identical styling — same reuse-not-duplicate pattern as `lw-*`/`mt-badge`/`terminal-button` elsewhere in this plugin |
| Contacts | Operator petnames for peers | Peers drawer → Contact section (admin): name + note + "known" flag per destination hash, `data/reticulum/contacts.json` (`backend/contacts.py`), never announced. Name wins across Peers/Activity/Messages/Send; announced name → "announced as X". `GET /contacts` + admin `PUT`/`DELETE /contacts/{hash}`; `/peers` + `/announces` gain `petname`/`trusted` |
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
    propagation_enabled: false           # LXMF store-and-forward relay (server side)
    propagation_storage_limit_mb: 250    # 0 = LXMF default (don't leave uncapped on SD)
    propagation_outbound_node: ""        # client side: use another node's lxmf.propagation hash
    propagation_auto_sync_interval_s: 0  # 0 = manual only; else every N s (min 300)
    telemetry_enabled: false             # publish host stats as LXMF FIELD_TELEMETRY frames
    telemetry_collector: ""              # LXMF address to send telemetry to
    telemetry_interval_s: 900            # min 300
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
| ~~Med~~ | ~~**Propagation node polish**~~ | **MOSTLY BUILT 2026-09-09** (new-build #2): outbound node + "Sync inbox" + live transfer state + auto-sync. Still open: **PN peering** (propagation nodes syncing to each other) and a message-arrival WS push after a sync completes | — |
| ~~Med~~ | ~~**Telemetry publish**~~ | **BUILT 2026-09-09** (new-build #3): time + temp + status-line frame, two-node verified. **+ SID_LOCATION added same day** — opt-in `telemetry_include_location`, coords from core's Configuration→GPS pin (`device.latitude/longitude`), no separate keys. Only follow-up left: structured processor/RAM/NVM sensors (nested `[[label,val],...]` — needs verifying against a real Sideband client; low value, INFO string already carries the numbers) | Low |
| ~~Med~~ | ~~**Telemetry collector + map**~~ | **BUILT 2026-09-09** (new-build #4). Telemetry tab: table + own-Leaflet map (not the dashboard NodeMap — Reticulum telemetry peers aren't in the core `nodes` table; a standalone mini-map was the right call). Not Pi-tested yet. Possible follow-up: also feed into the dashboard map, but that needs core `nodes`-table integration — probably not worth it | — |
| Low | **Audio calls** (`call.audio` / LXST) | answer / receive voice; min viable = a recorded announcement on call | High — audio I/O + codec on the Pi, its own project |
| Low | **Group chat** (`RNS.Destination.GROUP`) | experimental shared-key room, no membership mgmt | Medium — non-standard |
| Low | **Interface manager UI** | add / remove RNS interfaces from the dashboard vs hand-editing config | Medium |
| ~~Low~~ | ~~**Contacts / petnames**~~ | **BUILT 2026-09-09** (new-build #1) — see Done + Pi-verification list | — |
| Low | **Paper messages / QR** | Sideband-style offline message export | Low–Med |

## Done (this backlog's completed items)

- **2026-09-09** — Telemetry collector + map (new-build #4). Inbound
  `FIELD_TELEMETRY` decoded (`telemetry.decode_telemetry` +
  `_unpack_location`) into `backend/telemetry_store.py` (in-mem,
  latest-per-peer, 24h prune / 500 cap). New **Telemetry tab** on the
  Reticulum page: table + a self-contained Leaflet map of located peers
  (globally-loaded `L`, own markers — NOT the dashboard NodeMap, which
  is fed from the core `nodes` table). `GET /api/reticulum/telemetry/
  peers`, live over a new `reticulum_telemetry` WS event. Bonus fix: a
  telemetry-only LXMF frame no longer saves a blank message row /
  fires message events. 20 new tests. Suite 200 passed. NOT Pi-tested.
- **2026-09-09** — Telemetry publish, v1 subset (new-build #3).
  **Two-node round trip LIVE-VERIFIED same day** (ti → rakv2: frame
  built, msgpacked, transported over real LXMF, received + decoded
  correctly — `{1: ts, 7: temp, 15: info}`).
  `telemetry_enabled`/`telemetry_collector`/`telemetry_interval_s`;
  `backend/telemetry.py` `build_telemetry(host, node_name)` → a
  `{SID_TIME, SID_TEMPERATURE?, SID_INFORMATION}` dict the service
  msgpacks (`RNS.vendor.umsgpack`) into `lxm.fields[FIELD_TELEMETRY]`.
  `lxmf_service` gains `send_telemetry()` / `_telemetry_loop()` /
  `telemetry_status()`. `GET /api/reticulum/telemetry` + admin `POST
  .../telemetry/send`; Settings "Telemetry" fieldset + "Send telemetry
  now" button. Format verified against Sideband `sbapp/sideband/sense.py`
  via WebFetch — deliberately only the unambiguous single-value
  sensors; structured processor/RAM/NVM and location are follow-ups.
  16 new tests (6 telemetry-builder + 4 lxmf_service Mac-runnable, 5
  config-model + 5 route CI/Pi). NOT browser/Pi-verified — needs a
  real Sideband client subscribed as the collector to confirm the
  frame parses.
- **2026-09-09** — Propagation node polish, client side (new-build #2).
  `propagation_outbound_node` + `propagation_auto_sync_interval_s` config
  keys; `backend/lxmf_service.py` gains `set_outbound_propagation_node` /
  `sync_propagation_messages` / `cancel_propagation_sync` /
  `propagation_client_status` / `_propagation_sync_loop` (mirrors
  reticulum-meshchat's calls). `GET /api/reticulum/propagation` + admin
  `POST .../propagation/sync[/cancel]`; `propagation_client` on `/status`.
  Settings tab: outbound-node `<select>` (lxmf.propagation peers) +
  auto-sync interval + client status line. Panel header: "Sync inbox"
  button (shown when an outbound node is set) with a 60s poll loop
  rendering live transfer state. 13 new tests (7 Mac-runnable in
  `test_lxmf_service.py::TestPropagationClient`, 6 config-model +
  route tests CI/Pi-only). NOT done: PN peering; a WS push when a sync
  delivers new messages (the button reloads the Messages tab on
  completion, but an idle page won't notice a timed auto-sync). Not
  browser/Pi-verified.
- **2026-09-09** — Contacts / petnames (new-build #1). Editable Contact
  section in the Peers drawer, `data/reticulum/contacts.json` store
  (`backend/contacts.py`), `GET /contacts` + admin `PUT`/`DELETE`,
  `petname`/`trusted` enrichment on `/peers` + `/announces`, petname
  used across Peers/Activity/Messages/Send in the frontend. 16 tests
  (10 Mac-runnable). Not yet browser/Pi-verified — see list above.
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

New-builds #1 (Contacts), #2 (Propagation client), #3 (Telemetry
publish) all built 2026-09-09 — none Pi-verified yet.

From here (user asks "what is it" then decides, one at a time):
- **#4 Telemetry collector + map** — the natural pair for #3 now that
  publish exists. Parse inbound `FIELD_TELEMETRY`, plot on the
  dashboard's local map. Needs `SID_LOCATION` added to the publish side.
- **Contacts / petnames** — could integrate into the Send tab picker
  further, or an address-book tab.
- **Interface manager UI**, **Paper messages / QR** — standalone, low.
- **Attachments in Send** — still blocked on the `messages`-table
  decision.
- **Audio calls** — separate project.

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
