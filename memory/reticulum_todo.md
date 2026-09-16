# Reticulum plugin — backlog & handoff

What the plugin does today, what's in flight, and what could come next.
See `memory/plugin-reticulum.md` for implementation detail (dated sections,
one per feature) and `memory/project_m1_meshpoint.md` for wider session
context.

Last updated 2026-09-16 — same session built item 1 (Attachments in
Send, image-only, fully Pi-verified live), item 7 (Messages filter
chips, in two passes), item 2 (Paper messages / QR, export-only), and
item 3 (Audio calls -- **both stages**, a new `reticulum-call` plugin,
not yet Pi-verified) — see **Done** below for all four. V6 also added
to the Todo table, still open/unverified. Session builds through 2026-09-09: #1 Contacts,
#2 Propagation client, #3 Telemetry publish (+location, +multi-collector),
#4 Telemetry collect+map, Extra interfaces, UI padding pass.
**Verification status table below** — #1, #3, #4 and multi-collector
Pi-verified; only #2 (propagation client) and extra interfaces still
never run on the Pi.

**Since then (2026-09-09 → 2026-09-14), two new companion plugins** — not
part of the prioritized backlog below, a separate track: **Reticulum
Dashboard** (`plugins/apps/reticulum-dashboard/`, a live standalone
stat-cards + announce-ticker page for Reticulum-only boxes) and
**Reticulum Browser** (`plugins/apps/reticulum-browser/`, a full
multi-tab NomadNet browser, feature set inspired by fr33n0w/rBrowser —
clean-room implementation, not a port). Both `requires = "reticulum"`,
both `locked = true` (shipped with the fork). Full detail in the **Have**
table and the **Done** log below. The prioritized Todo table right below
this is unaffected by that work — none of it touches attachments/audio/
paper-QR/group-chat/telemetry-sensors/PN-peering or the V1–V5
Pi-verification items, which are all still exactly where they were.

---

## Todo — prioritised (2026-09-09)

Builds first (priority order), then the Pi-verification backlog. Detail
for each build item is in **Could build — next up** further down.

| # | Item | Type | Effort | Impact | Risk | Notes |
|---|---|---|---|---|---|---|
| ~~1~~ | ~~**Attachments in Send**~~ | build | Med | High | Low | **BUILT + FULLY PI-VERIFIED 2026-09-16** — image-only (deliberately, not `FIELD_FILE_ATTACHMENTS`; see "Could build" below for why). Real two-node round trip confirmed between ti-meshpoint and rakv2-meshpoint |
| ~~2~~ | ~~**Paper messages / QR**~~ | build | Low–Med | Med | Low | **BUILT 2026-09-16, export-only.** Read the real `LXMF.LXMessage.PAPER` mechanism from source before building (not guessed) — see Done log below for the full research + implementation writeup. Not Pi-tested |
| ~~3~~ | ~~**Audio calls**~~ (`call.audio`) | build | Med–High | High | Med | **BOTH STAGES BUILT 2026-09-16** — see Done log below. New `plugins/apps/reticulum-call/` plugin (hook into the Reticulum page's new "Call" tab, ~1.9 MB vendored Codec2 WASM, no SOX needed after all — see Done log for why). Not Pi-tested / no live call ever attempted — the one thing this item still needs. |
| 4 | **Group chat** (`RNS.Destination.GROUP`) | build | Med | Low | Med | Non-standard, no membership model, easy to half-build. Only on request |
| 5 | **Structured telemetry sensors** (`SID_PROCESSOR/RAM/NVM`) | build | Med | Low | Med | Nested `[[label,val]]` pack format needs a careful `sense.py` read + Sideband cross-check. Only worth it once a graphing collector exists |
| 6 | **PN peering** (relay↔relay store sync) | build | Med | Low | Med | No reference impl (meshchat doesn't do it). Only matters for multi-relay setups |
| V1 | **Verify: propagation client (#2)** | verify | Low (½ day) | High | — | Never run on Pi. Dropdown lists relays, saved hash survives restart, Sync-inbox cycle (requesting→link→receiving→complete), auto-sync timer fires, unreachable node fails not hangs |
| V2 | **Verify: extra interfaces** | verify | Low | High | — | Never added one. Valid TCPClient lands in rnsd config + rnsd starts; broken entry skipped w/ journal warning and **rnsd still starts**; RNode+backbone off + one active extra accepted |
| V3 | **Verify: Contacts tab + peer-drawer additions** | verify | Low | Med | — | Inline-edit propagates name everywhere, add-from-hash + garbage rejected, Remove clears all surfaces; Send Message button pre-fills, favourite star syncs w/ Browse list, next-hop tooltip; light/dark |
| V4 | **Verify: telemetry collect+map (#4) leftovers** | verify | Low | Med | — | `reticulum_telemetry` WS live-updates the tab w/o reload; a telemetry-only frame leaves no blank row in Messages |
| V5 | **Verify: real-Sideband render** | verify | Low | Low | — | Telemetry frame is byte-exact vs `sense.py`; just never displayed in the actual Sideband app |
| V6 | **Verify: inbound Reticulum messages trigger Settings→System's message notifications (toast/sound)** | verify | Low | Med | — | Flagged by user 2026-09-16. Likely already works and just needs confirming: `frontend/js/message_notifier.js`'s `_onMessage()` listens for the core `message_received` WS event with zero protocol filtering (any `direction:'received'` triggers it), and `lxmf_service.py`'s `_handle_inbound_message()` already fires that exact event (added 2026-09-08, alongside its own plugin-private `reticulum_message`) — so the wiring looks complete on paper, just never watched live with an inbound DM to confirm the toast/sound actually fire |
| ~~7~~ | ~~**Add Reticulum (and Pager) to the Messages page's protocol filter chips**~~ | build | Low | Low–Med | Low | **BUILT 2026-09-16, in two passes.** Pass 1: added `data-filter="reticulum"` ("RT") and `data-filter="pager"` ("Pager") buttons alongside All/MT/MC/★ Fav in `frontend/js/messaging.js:49-55` + `flex-wrap` on `.msg-protocol-toggle` (`messaging.css`) so 6 buttons wrap instead of overflowing a narrow sidebar — user live-tested this on the Pi immediately and both screenshotted fine. Pass 2, same session: user pointed out a real gap — an empty "Pager" pill (no pager configured on that box) was a dead-end click ("No conversations yet"), but the fix couldn't be "just hide it," since disabling a protocol *with existing history* would then make those old chats look silently gone. Landed on OR-ing two signals per pill: **configured** (same signal the sidebar nav already uses to hide itself — `capture.sources` for MT/MC, `radio_pager.pager_enabled` for Pager, a `reticulum` entry in `window.MESHPOINT_SIDEBAR_PLUGINS` for RT) **or has any channel/conversation already** (new `MessagingContacts.protocolsInUse()`). A pill only disappears once both are false. New `MessagingPanel._updateProtocolPillVisibility()`, called after every conversations load (initial + each time the Messages page is revisited); falls back to the "All" filter if the currently-active pill gets hidden out from under it. Best-effort like `sidebar_controller.js`'s own `_applySourceGating()` — a failed config fetch just leaves every pill visible. Not yet seen live in a real browser. |

**Suggested sequence:** ~~1~~ → (V1, V2 on the Pi) → ~~2~~ → ~~3~~, with
V3·V4·V5 folded into the next Pi session and 4–6 left reactive. Items 1,
2, 3 and 7 are all built now (V6 still just flagged, not verified) —
**nothing left to build that's ahead of the Pi-verification backlog.**
Next session should be entirely Pi-verification: V1/V2 first (quick,
high-impact, never run), then a real two-node Audio Calls test (the
biggest unverified item now), then V3–V6 as time allows.

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

### Verification status — 2026-09-09 session builds

| Feature | Pi status |
|---|---|
| Contacts / petnames (#1) | ✅ **Verified 2026-09-09** — add + name propagation + Remove confirmed via the Peers drawer. **NEW: Contacts tab** (address book — inline-edit table + add-from-pasted-hash) built 2026-09-09, not yet walked on the Pi (check: table lists contacts, inline Save updates the name everywhere, "Add contact" with a valid hash works + a garbage hash is rejected, Remove works, Send/Browse row links jump correctly) |
| Propagation client (#2) | 🔴 **Untested** — never run on the Pi. Needs a real `lxmf.propagation` relay to point `propagation_outbound_node` at. Check: outbound-node dropdown lists heard relays + keeps the saved hash after restart; "Sync inbox" button appears; a stopped→start→sync cycle shows transfer state (requesting→link→receiving→complete) and a parked message lands; auto-sync interval fires; a completed sync (manual or auto) shows a "synced N messages" toast + refreshes the thread (new `reticulum_propagation_sync` WS, 2026-09-09); an unreachable node shows a failed state not a hang |
| Telemetry publish (#3) | ✅ **Verified** — two-node ti → rakv2, frame decoded byte-exact (SID_TIME/TEMPERATURE/INFORMATION + LOCATION from the GPS pin) |
| Telemetry collect + map (#4) | ✅ **Mostly verified** — rakv2's Telemetry tab plotted ti on the map ("techinc on the map"), so decode → store → table → map all work. **Still to check:** `reticulum_telemetry` WS live-updates the tab without a reload; a telemetry-only frame does NOT create a blank row in the Messages tab (was a latent bug — confirm it's gone) |
| Telemetry: multiple collectors | ✅ **Verified 2026-09-09** — 2+ addresses each got the frame, "Send telemetry now" reported "Sent to N collectors", a bad/unreachable address didn't block the others |
| Extra interfaces (Interface manager) | 🔴 **Untested** — never added one on the Pi. Check: the row editor works (add/remove/type-switch keeps edits); a valid TCPClient shows up in `data/reticulum/rns_config/config` and rnsd starts after Restart rnsd; a deliberately broken entry (missing port) is skipped with a journal warning and **rnsd still starts**; RNode+backbone both off + one active extra is accepted |
| Real-Sideband render | 🔴 Open — the telemetry frame's structure is verified against `sense.py` and byte-exact on the wire, but no real Sideband *app* has displayed one yet (low risk) |
| UI padding fixes (listener/SDR panels, sub-plugin chevron) | ✅ Tester confirmed |

**Quick summary:** Contacts (#1), telemetry publish (#3) + location +
multi-collector, and collect/map (#4) are all Pi-verified. The two
things that have never touched the Pi: **propagation client (#2)** and
**extra interfaces**. Nice-to-have: a real-Sideband render check.

### Pi verification still owed (older items)

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
- **Extra interfaces (Interface manager) — BUILT 2026-09-09, not
  Pi-tested.** Settings tab → "Extra interfaces": add a row, pick type
  (TCPClient/TCPServer/UDP), fill fields, Save → Restart rnsd. Check:
  the row editor works (add/remove/type-switch keeps in-progress
  edits); a valid TCPClient shows up in the rnsd config
  (`cat data/reticulum/rns_config/config`) and rnsd starts; a
  deliberately broken entry (missing port) is skipped with a journal
  warning and rnsd STILL starts (the whole point); RNode+backbone both
  off with one active extra interface is accepted. `write_rnsd_config`
  reads `plugins.reticulum.extra_interfaces` raw; `_extra_interface_blocks`
  is the pure, tested generator.
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
| Transport | **Extra interfaces** (operator-added) | `extra_interfaces` list: TCPClient/TCPServer/UDP; Settings-tab editor (add/remove rows, per-type fields), validated on save (`ExtraInterface` model) + again in `write_rnsd_config.py`'s `_extra_interface_blocks` (skips bad entries, never crashes rnsd's ExecStartPre); applied on Restart rnsd |
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
| Companion plugin | **Reticulum Dashboard** (`reticulum-dashboard`, 2026-09-14) | Standalone "top"-tier sidebar page (sits above Networks, next to the built-in Dashboard) for Reticulum-only boxes whose core Dashboard is otherwise empty (RF pipeline gets zero packets from Reticulum). Five stat cards (Status/Known Peers/People/Infrastructure/Conversations), a flashing real-time announce ticker, a live peer list, and a telemetry map of located peers built on the shared offline/online tile-source switch. Peer/activity rows open the same read-only detail drawer/popup the reticulum page uses. A NomadNet quick-browse modal (address bar, back/forward/reload, favourites shared with the Browse tab) for a lighter-weight browse than opening the full Reticulum Browser. `provides = ["sidebar"]` only — no backend of its own, reads the reticulum plugin's existing `/api/reticulum/*` + the shared dashboard WebSocket; `requires = "reticulum"` (enforced: can't enable without it, disabling reticulum cascades to disable this) |
| Companion plugin | **Reticulum Browser** (`reticulum-browser`, 2026-09-14) | Full multi-tab NomadNet browser — Networks-section sidebar page. Open several nodes at once, each tab keeps its own address/history; node picker + search (same shape as the reticulum plugin's Browse tab); favourites share the *exact same* `localStorage` list as the Browse tab, Peers drawer, and Dashboard's quick-browse modal — star anywhere, starred everywhere; raw/rendered Micron view toggle; keyboard shortcuts (Ctrl/Cmd+T/W/R, Alt+←/→). Feature set/name inspired by fr33n0w/rBrowser (MIT) — a clean-room implementation against Meshpoint's own patterns, not a code port; full credit in its README. `provides = ["sidebar"]` only, reads the reticulum plugin's public `/api/reticulum/nomad/*`; `requires = "reticulum"`. **Explicitly NOT built yet** (its own README's "What's not here" section): fingerprint identification of remote hosts (rBrowser's verification model wasn't studied closely enough to build honestly); a local NomadNet search engine + page cache (would need its own `service`-seam backend, comparable in scope to a separate plugin); form-field submission on interactive `.mu` pages and `/file/...` downloads (covered by the reticulum plugin's own Browse tab if needed meanwhile) |

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
    telemetry_collector: ""              # LXMF address(es), one per line — sent to each
    telemetry_interval_s: 900            # min 300
    telemetry_include_location: false    # add Configuration→GPS pin to the frame
    extra_interfaces: []                 # [{name,type,enabled,...}] TCPClient/TCPServer/UDP → write_rnsd_config
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
| ~~Med~~ | ~~**Attachments in Send**~~ | images over `LXMF.FIELD_IMAGE` | **BUILT + FULLY PI-VERIFIED 2026-09-16, image-only.** Nullable JSON `attachments` column on the shared `messages` table (guarded-added like rssi/snr/rx_count); each entry `{kind, id, mime, size}` — a random hex `id`, not the message row id (an outbound image is written to disk before `save_sent()` returns a row id at all, so a message-id-keyed path would need a second UPDATE; the random id works the same for both send and receive with no ordering dependency). Bytes live on disk (`data/reticulum/attachments/<id>.<ext>`, new `backend/attachments.py`), never in SQLite. Send tab gained an "Image (optional, max 5 MB)" file picker — base64 in the same JSON `POST /send` body (multipart would be marginally more efficient, but every other route in this plugin is plain JSON; kept consistent). `GET /api/reticulum/attachments/{id}` serves it back inline (no Content-Disposition), admin-auth-gated same as everything else, working as a plain `<img src>` because cookie session auth covers that. The shared `messaging_chat.js` (used by every protocol's chat view, not just Reticulum) renders a click-to-open thumbnail when `msg.attachments` is present — both bubble-render code paths (`_appendBubble` for a live new message, `_buildBubbleEl` for loading history) and the live `message_received` WS payload. **Decided image-only over also building `FIELD_FILE_ATTACHMENTS`** (general file attachments) after being asked directly — Sideband's own attachment story leans on images, it's the simplest to preview inline, and it keeps this at Med effort instead of pulling in MIME-type/arbitrary-file handling nobody's asked for; general files can follow later if there's real demand (tracked as the reopened item below). 19 new tests (11 `attachments.py`, 8 `lxmf_service.py`, all Mac-runnable via a hand-rolled `aiosqlite`-shim/direct-fake style, no real RNS/LXMF needed for any of them) + 5 `message_repository.py` round-trip tests. **Fully Pi-verified same day** — a real two-node send between ti-meshpoint and rakv2-meshpoint rendered a correct inline thumbnail on both the sender's own thread and the recipient's thread, no reload needed. Nothing left open. |
| Low | **File attachments in Send** (`LXMF.FIELD_FILE_ATTACHMENTS`) | general (non-image) files, e.g. a PDF or a text file | Reopened 2026-09-16 as the deliberately-deferred half of "Attachments in Send" above — same storage/serving shape would mostly reuse `attachments.py`/`attachments` column, just a second `kind` value + a download-not-inline response (`Content-Disposition: attachment`) on the GET route, and a generic MIME-type allowlist instead of the image-only `_MIME_BY_TYPE` map. Only worth it if someone actually asks — images cover the common case. |
| ~~Med~~ | ~~**Propagation node polish**~~ | **BUILT 2026-09-09** (new-build #2): outbound node + "Sync inbox" + live transfer state + auto-sync + a `reticulum_propagation_sync` WS event when any sync completes (2026-09-09). Untested on Pi. | — |
| ~~Med~~ | ~~**Telemetry publish**~~ | **BUILT 2026-09-09** (new-build #3): time + temp + status-line frame, two-node verified. **+ SID_LOCATION added same day** — opt-in `telemetry_include_location`, coords from core's Configuration→GPS pin (`device.latitude/longitude`), no separate keys. Only follow-up left: structured processor/RAM/NVM sensors (nested `[[label,val],...]` — needs verifying against a real Sideband client; low value, INFO string already carries the numbers) | Low |
| ~~Med~~ | ~~**Telemetry collector + map**~~ | **BUILT 2026-09-09** (new-build #4). Telemetry tab: table + own-Leaflet map (not the dashboard NodeMap — Reticulum telemetry peers aren't in the core `nodes` table; a standalone mini-map was the right call). Not Pi-tested yet. Possible follow-up: also feed into the dashboard map, but that needs core `nodes`-table integration — probably not worth it | — |
| ~~Med~~ | ~~**Audio calls**~~ (`call.audio`) | browser-to-browser voice, Pi as bridge | **BOTH STAGES BUILT 2026-09-16 — see Done log for the full writeup.** Architecture: `requires = "reticulum"` + `[hook] host = "reticulum"` (Call tab injected into the existing Reticulum page), backend in core (`plugins/apps/reticulum/backend/audio_call.py` + `call_routes.py`, since a call needs the exact same RNS identity `LxmfService` already owns), UI + Codec2 WASM in the separate `plugins/apps/reticulum-call/` plugin (opt-in, not shipped to every Reticulum install). One real deviation from reticulum-meshchat worth flagging if this ever gets revisited: skipped `sox.wasm` (~650 KB) entirely — its only real job in the reference's own encode/decode path is converting Float32 samples to/from headerless 16-bit PCM (a WAV-wrap-then-unwrap round trip), which is just arithmetic, not something that needs a WASM module; total vendored footprint came out to ~1.9 MB rather than the ~2.7 MB estimated before actually reading the reference's pipeline closely. Also deviated on wire framing (1 mode-index byte + raw Codec2 bytes, not reticulum-meshchat's protobuf `AudioCallPayload`) — meshpoint-to-meshpoint calls work, real Sideband/meshchat interop is NOT guaranteed and was never attempted. Real risk still worth testing carefully on the Pi, not assumed away: `AudioCall.send_audio_packet()` silently drops any frame over `RNS.Link.MDU` — fine over TCP, tight over LoRa. Not Pi-tested / no live call ever attempted. |
| Low | **Group chat** (`RNS.Destination.GROUP`) | experimental shared-key room, no membership mgmt | Medium — non-standard |
| ~~Low~~ | ~~**Interface manager UI**~~ | **BUILT 2026-09-09** — `extra_interfaces` (TCPClient/TCPServer/UDP), Settings-tab editor, dual validation, not Pi-tested. Chose structured over raw-textarea (bad config = rnsd won't start = all Reticulum down). Follow-up: more interface types (I2P needs i2pd; a 2nd RNode) if asked | — |
| ~~Low~~ | ~~**Contacts / petnames**~~ | **BUILT 2026-09-09** (new-build #1) — see Done + Pi-verification list | — |
| ~~Low~~ | ~~**Paper messages / QR**~~ | Sideband-style offline message export | **BUILT 2026-09-16, export-only.** Real LXMF `PAPER` delivery method (0x05, confirmed from `pip download lxmf` source, not guessed) — a fully real end-to-end-encrypted message that's never handed to a transport interface, only exported as an `lxm://...` URI via `LXMessage.as_uri()` for the frontend to render as a QR. New `LxmfService.paper_message()` (factored `_resolve_identity()` out of `send_message()` so both share the same path-discovery retry logic), admin `POST /api/reticulum/paper`. Send tab gets a "Paper message" button (reuses the same Peer/Message fields, 512-char cap so the QR stays scannable — image attachments deliberately not supported here, would make the QR too dense) → a result panel with a QR (reusing Quick Deploy's own vendored `qrcode.min.js` + `<canvas>` pattern, zero new deps) + copyable URI text + a Print button (`@media print` isolates just the QR). Recorded in the thread with `status: "paper"` (the existing generic ` · <status>` meta-line suffix in `messaging_chat.js` already renders it, no frontend change needed for that part). **Import/scan-back-in deliberately not built** — user confirmed the intended receiver is a real phone running Sideband-class software, which already has its own camera-scan path; meshpoint (a browser dashboard) has no camera to scan with. 4 new Mac-runnable tests, all passing. Not Pi-tested. |
| Low | **Reticulum Browser: remote-host fingerprint verification** | rBrowser has a model for this; ours doesn't yet | Unscoped — needs studying rBrowser's actual verification approach first, not just effort to build |
| Low | **Reticulum Browser: local NomadNet search engine + page cache** | Background crawler + index of NomadNet pages | Needs its own `service`-seam backend (same capability LXMF's own service uses) + a real cache schema — comparable in scope to a whole separate plugin |
| Low | **Reticulum Browser: form-field submission + `/file/...` downloads** | Interactive `.mu` page forms, file attachments | Low — the reticulum plugin's own Browse tab already covers both; only missing from the newer Browser plugin specifically |

### Future / only if there's a concrete need

- **Structured telemetry sensors** (`SID_PROCESSOR` 0x13 / `SID_RAM` 0x14 /
  `SID_NVM` 0x15) — show CPU/RAM/disk as proper gauges instead of the
  free-text status string, so a collector could graph them. Blocked on:
  the pack format is a nested `[[label, value], ...]` list the two
  `sense.py` WebFetches were shaky on — needs one careful read of the
  real Sideband source + a Sideband cross-check. Low value until someone
  builds a telemetry-graphing collector.
- **PN peering** — two nodes both running as `lxmf.propagation` relays
  sync their held-message stores to each other (store redundancy).
  `LXMRouter` has hooks but reticulum-meshchat doesn't implement it, so
  no reference — would be felt out from LXMF source. Only matters for a
  multi-relay setup; most run one relay. Medium effort.
- **WS push on auto-sync delivery** — ✅ **DONE 2026-09-09**
  (`reticulum_propagation_sync` event fires when any sync completes;
  `_watch_propagation_sync` polls the transfer state to a terminal
  state then broadcasts state + `last_result`; frontend shows a toast +
  reloads Messages). Was the third small follow-up.

## Done (this backlog's completed items)

- **2026-09-16** — Audio calls, item 3, **Stage 1 only (backend, no UI)**,
  same session as items 1/2/7, right after Paper messages. User picked
  the item, I explained it (verified against real reticulum-meshchat
  source rather than the old notes' guesses), user asked "maybe it
  should be a meshpoint-plugins app hook maybe?" -- talked through the
  tradeoff (see the "Could build" table entry above for the full
  reasoning) and landed on core-bundled `plugins/apps/reticulum-call/`
  instead of the separate community repo, once user clarified mid-
  conversation. Given the size (Med-High, the biggest item left), asked
  before building and got an explicit go-ahead, then proposed and got
  agreement on a two-stage split before starting.
  **What got built (Stage 1):**
  - New `backend/audio_call.py` -- `AudioCall`/`AudioCallManager`/
    `AudioCallReceiver`, ported from reticulum-meshchat's
    `audio_call_manager.py` (MIT, Liam Cottle -- credit belongs in the
    Stage-2 plugin's own README too, same as reticulum-browser did for
    fr33n0w/rBrowser). `AudioCall.send_audio_packet()` is genuinely one
    line, `RNS.Packet(self.link, data).send()` -- no codec/audio
    awareness anywhere in this file or anywhere else in the backend,
    confirmed against the real source rather than assumed.
  - Wired into `LxmfService`: new opt-in `audio_calls_enabled` (off by
    default, same reasoning as node_enabled/propagation_enabled/
    telemetry_enabled -- config plumbed through state.py →
    config_routes.py's `ReticulumUpdate` → `__init__.py`'s
    `LxmfService(...)` call, Settings tab gets a "Voice calls" toggle).
    On start(), creates an `AudioCallManager(self._identity)` --
    **the same identity object already backing LXMF delivery /
    NomadNet hosting** (confirmed by reading `start()`: `self._identity
    = RNS.Identity.from_file(...)`, a real `RNS.Identity`, distinct
    from `self._source` which is LXMF's own delivery-destination
    wrapper) -- a `"call"/"audio"` destination becomes a third sibling
    aspect on one identity, same pattern `NomadNode` already uses.
    Incoming calls broadcast a new `reticulum_incoming_call` WS event
    (same RNS-callback-thread → `asyncio.run_coroutine_threadsafe` fix
    used throughout this file for `_on_lxmf_message`).
  - New `LxmfService` methods: `initiate_call()`, `hangup_call()`,
    `get_call()`, `audio_call_status()` (None unless enabled, same
    `GET /status` convention as `node_status()`/`propagation_status()`).
  - New `backend/call_routes.py`: admin `POST /call/initiate` +
    `POST /call/{hash}/hangup` (plain REST, same `Depends(require_admin)`
    pattern as every other route), and the actual call --
    `@router.websocket("/call/{hash}/audio")`, a pure byte-forwarder
    between the browser's WS connection and `AudioCall.
    send_audio_packet()`/its packet-listener callback.
  - **Real architecture snag found and fixed, not glossed over**: a
    plugin router registered `public=False` gets `Depends(require_auth)`
    applied at the router level automatically -- but that dependency is
    typed for an HTTP `Request`, and confirmed (by reading how core's
    OWN dashboard `/ws` route is built) that it does **not** resolve
    correctly against a WebSocket scope; core had to write its own
    `_gate_ws_or_close`/`authenticate_websocket()` for exactly this
    reason. Registered `call_routes.router` with `public=True` instead
    (the REST routes keep their own explicit `Depends(require_admin)`,
    unaffected) and added a small public `get_jwt_service()` accessor to
    `src/api/auth/dependencies.py` (the only core-file change this
    needed) so the websocket handler can call the same
    `authenticate_websocket()` core's own `/ws` uses, replicating its
    accept-before-close close-code sequencing (there's a whole comment
    in server.py about a real bug from getting that order wrong).
  - **Ringing/answer semantics deliberately NOT built at the RNS layer**
    -- read reticulum-meshchat's actual `CallPage.vue` and confirmed
    there's no ring/answer/decline protocol at all: an `RNS.Link`
    reaches `ACTIVE` the moment the destination responds (no consent
    step), and the UI's only real action is "Join Call" on any active
    link. Meshpoint's Stage 2 can follow the identical simple model --
    an incoming link shows up via the WS event, the user chooses
    whether to open the audio bridge at all.
  - 24 new tests (15 `test_audio_call.py` with a hand-rolled fake
    `RNS.Link`, 9 `TestAudioCallIntegration` in `test_lxmf_service.py`),
    all Mac-runnable, all passing.
  **What's NOT built** (at the time this Stage 1 entry was written):
  the entire user-facing half -- no Call UI, no Codec2 WASM, no
  mic/speaker, nothing in the sidebar/Reticulum page at all yet. **Now
  built in the same session -- see the Stage 2 entry immediately
  below.**
- **2026-09-16** -- Audio calls, item 3, **Stage 2 (the actual UI + WASM)**,
  same session, right after Stage 1, no gap -- user said "keep going we
  submitted so we have a backup point" (Stage 1 had just been committed).
  **New plugin `plugins/apps/reticulum-call/`** (hook into the Reticulum
  page's new "Call" tab -- core's own `reticulum_panel.js` needed a small
  change too: a `data-rt-view="call"` tab + calling
  `window.mountPageHooks('reticulum', ...)` from its mount(), since
  nothing called that before this plugin needed it to).
  **Real findings from reading the reticulum-meshchat reference closely
  before porting, not guessing from the old backlog notes:**
  - `Codec2Lib.runEncode`/`runDecode` in the reference are literally a
    "shell out to a CLI tool via WASM" pattern -- each call spins up a
    *fresh* Emscripten module instance (`createC2Enc(module)`/
    `createC2Dec(module)`), writes a virtual file, runs the whole
    codec2 binary, reads a virtual file back. Ported the same shape
    (no persistent streaming codec instance exists to port instead --
    this genuinely is how reticulum-meshchat's own live calls work).
  - The reference's own live-call encode path routes every audio chunk
    through a WAV-wrap (`WavEncoder.encodeWAV`, pure JS) then
    `Codec2Lib.audioFileToRaw()` -- a SECOND vendored WASM module,
    `sox.wasm` (~650 KB) -- to strip the WAV header back off before
    codec2 encoding. That SOX round trip's only real effect is
    resampling, which is a no-op here: the AudioWorklet processor
    already delivers 8 kHz samples, codec2's own required rate.
    Skipped SOX entirely -- Float32 <-> 16-bit PCM directly (the exact
    same arithmetic `WavEncoder.floatTo16BitPCM` already does, just
    without ever writing a WAV header) gets the identical result with
    one fewer full WASM module boot per audio chunk and ~650 KB less
    vendored. Total footprint: **~1.9 MB**, not the ~2.7 MB estimated
    before this was actually checked.
  - For playback, skipped the reference's own `rawToWav` + 
    `AudioContext.decodeAudioData()` round trip too -- `AudioContext.
    createBuffer()` + `AudioBuffer.copyToChannel()` builds a playable
    buffer directly from Float32 samples, no container format needed
    at all for something that's already raw PCM in memory.
  - **Deliberately skipped the reference's protobuf `AudioCallPayload`
    wire wrapping** -- vendoring a protobuf runtime for a framing only
    one other project uses wasn't worth it. Used one mode-index byte +
    raw Codec2 bytes per frame instead. Consequence, stated plainly in
    this plugin's own README: **not guaranteed to interoperate with a
    real Sideband/reticulum-meshchat call** -- meshpoint-to-meshpoint
    is the actual target, matching the old backlog notes' own
    unresolved "verify" flag on this exact point.
  - Confirmed (reading `CallPage.vue` itself) that reticulum-meshchat
    has **no ring/answer/decline protocol at all** -- an `RNS.Link`
    reaches `ACTIVE` the instant the destination responds, no consent
    step; its own UI's only real action is "Join Call" on any active
    link. Built the identical simple model: an incoming link fires the
    Stage-1 `reticulum_incoming_call` WS event, shows as a banner, Join
    opens the audio bridge or Ignore dismisses it -- no separate
    signalling built or needed.
  - Found and fixed a real, unrelated-until-now bug in the **core
    plugin asset pipeline** while wiring the vendored WASM up:
    `src/plugins/assets.py`'s `plugin_asset_tags()` blindly emitted a
    literal `<script src="...">` for every `frontend.scripts` entry
    regardless of file type -- harmless for every plugin so far (all
    JS), but the first plugin shipping a non-JS asset (`.wasm`,
    servable only by being listed in `frontend.scripts` at all) would
    have gotten `<script src="c2enc.wasm">` on every page load, a
    permanent benign-but-real console parse-error whether or not a
    call ever happens. Fixed: only an actual `.js` entry gets
    `<script>`-tagged now; everything else stays servable via
    `resolve_plugin_asset()` (which still requires the entry be listed)
    without being force-loaded as a script. 2 new tests in the core
    `tests/test_plugin_assets.py` (not the reticulum plugin's own
    suite) lock this in.
  - `processor.js` (the AudioWorklet capture processor) gets the same
    `<script>`-tag treatment as any other `.js` file (it IS one), which
    would normally throw `ReferenceError: registerProcessor is not
    defined` if executed on the main thread -- guarded its whole body
    in `if (typeof registerProcessor !== 'undefined')` so an accidental
    main-thread load is a silent no-op instead.
  2 new tests in `tests/test_plugin_assets.py`, plus manual verification
  the new plugin's manifest parses cleanly and is picked up correctly by
  the real `tests/test_plugin_manifest.py::TestShippedPluginManifests`
  smoke test (which scans the actual `plugins/apps/` directory, not a
  fixture). No new Python tests for the plugin itself -- it has no
  backend beyond a no-op `register()`, everything testable lives in the
  Stage 1 entry above.
  **Live-tested immediately, found 2 real bugs, both fixed same
  session:** (1) the actual "Call button does nothing" cause -- a
  stray `"` in the Call and Hang up `<button>` tags
  (`data-rtcall-dial-btn">Call</button>` instead of
  `data-rtcall-dial-btn>Call</button>`, leftover copy-paste residue)
  broke the `querySelector('[data-rtcall-dial-btn]')` match, so the
  click listener never attached to the real button at all -- no fetch
  ever fired, no status message ever showed, exactly what the
  screenshot showed. (2) why the empty "Hang up" box was visible
  *before* any click too: `.rtcall__active`/`.rtcall__incoming` both
  set `display: flex` unconditionally in the CSS -- author-stylesheet
  rules always beat the browser's own `[hidden] { display: none }`
  default regardless of selector specificity, so JS setting
  `.hidden = true` was being silently overridden. Fixed with
  `:not([hidden])` guards on both rules. No test coverage added for
  either (pure rendering/DOM-selector bugs, not really unit-testable
  without a real browser) -- caught only because the user tried it live
  immediately, a good reminder that "the manifest parses and the tests
  pass" is not the same bar as "a human clicked the button."
  **Same session, immediately after: added push-to-talk.** User asked
  "isn't calling more like a PTT? on ratspeak etc its more a ptt" --
  correct critique of the full-duplex "phone call" model this (and
  reticulum-meshchat's own reference) both used: a poor fit for a
  typically-half-duplex LoRa link that can't spare continuous
  bidirectional audio. Key realization that made this cheap to add:
  PTT vs. open-mic is a **purely local, sender-side choice** -- the
  wire format doesn't change at all, a receiver just plays whatever
  frames show up and can't tell whether the sender is streaming
  continuously or only while a button's held. So both modes coexist
  with zero protocol/backend changes, entirely in the existing hook
  plugin's frontend: a `_pttActive` flag the AudioWorklet's onmessage
  handler checks before encoding+sending each chunk (worklet keeps
  running either way -- cheaper than pausing/resuming it, no
  start-up glitch on the next press), a "Hold to Talk" button
  (mouse+touch, with `document`-level release listeners so dragging
  off the button while held doesn't leave the mic stuck open), and a
  toggle to fall back to the old open-mic behavior for a hands-free
  call over a link that can afford it. Defaults to PTT on (remembered
  per-browser in localStorage) -- matches the actual use case and the
  ham/mesh-radio mental model the user's question was grounded in.
  **Same session, first real live-test round: 2 bugs found and fixed.**
  First attempt: "Could not establish a link to that destination" --
  diagnosed (not guessed) from the exact error text: since path-finding
  and identity resolution both clearly succeeded (a different message
  would've fired otherwise) and LXMF messaging to the same peer already
  worked, the only remaining explanation was that `call.audio` -- a
  genuinely separate destination from `lxmf.delivery`, only registered
  if `audio_calls_enabled` is on *and the service has been restarted
  since* -- simply wasn't listening on the remote box yet. Confirmed
  correct: user fixed the remote config, second attempt actually
  reached the remote side (its incoming-call banner appeared).
  **Second bug, worse: the call showed "Call ended." on the caller's
  side almost immediately, before the receiver could click Join.**
  Root cause was a real bug in this session's own code, not
  configuration: `_endCallLocally()` unconditionally overwrote
  `_msgEl` with "Call ended." -- so when `_startAudio()` (getUserMedia)
  failed, the specific "Microphone access failed" message that had
  *just* been set got immediately stomped by the generic one, hiding
  the actual reason. And getUserMedia's real failure mode here is
  almost certainly `window.isSecureContext === false` -- browsers
  flatly refuse mic access outside HTTPS/localhost, and these boxes are
  reached over a plain-HTTP LAN IP unless `dashboard.tls_enabled` is
  explicitly on (config-file only, no Settings-tab toggle exists --
  confirmed against `docs/CONFIGURATION.md` before writing the fix's
  own error message, not guessed). Fixed three things: (1)
  `_endCallLocally({silent, hangupServer})` -- `silent` stops the
  "Call ended." overwrite when a more specific message was just shown
  (also applied to the WS `onclose`-after-`onerror` case, same
  overwrite bug); `hangupServer` tells the backend to actually tear
  down the Link when the *local* side aborts before ever opening its
  audio WS, so the far end's incoming-call banner doesn't sit pointing
  at a call nobody's going to join. (2) A new `_micAvailabilityError()`
  pre-flight check (`window.isSecureContext`, `navigator.mediaDevices`)
  run *before* Call/Join ever touches the backend, with a plain-language
  message naming the actual fix (`dashboard.tls_enabled: true` +
  restart, or localhost). (3) Same check also runs once on tab mount,
  so the HTTPS requirement shows up before the user even tries, not
  only after a failed attempt. Not yet re-tested live after this fix.
  **Re-tested: still failed, but the HTTPS/mic-permission guesses were
  both wrong** -- user's actual browser console (`vm-meshpoint.local`,
  HTTPS already on, mic permission already granted, confirmed via the
  browser's own site-info panel before even asking me) showed the real
  error: `AbortError: Failed to load worklet module script ... (HTTP
  status: 404)` on `codec2/processor.js`. **The actual bug: a hardcoded
  path typo.** `RT_CALL_WORKLET_URL` was
  `/plugins/apps/reticulum-call/codec2/processor.js` -- missing the
  `frontend/` segment every *other* vendored asset gets automatically
  via its injected `<script src>` tag (`plugin_asset_url()` serves
  whatever's declared in `plugin.toml`'s `frontend.scripts` verbatim,
  `"frontend/..."` prefix included). `audioWorklet.addModule()` needs an
  explicit URL string instead of an auto-injected tag, and that string
  just didn't match. Fixed the one constant. **Also fixed the
  misdiagnosis-inducing part**: the catch block's on-screen message
  said "Microphone access failed — check browser permissions" for
  *any* `_startAudio()` failure, regardless of which step inside it
  actually failed (worklet loading vs. getUserMedia are very different
  problems) -- now shows the browser's own `e.message`/`e.name`
  directly, so a future failure states its real cause on screen
  instead of sending the next debugging session down the same two
  wrong paths (HTTPS, then mic hardware) this one went down before the
  console output settled it. Lesson worth remembering: this whole
  detour happened because nothing here could be live-tested from this
  side at all (no browser, no mic, no real RNS stack) -- the actual bug
  was a one-line path typo that a real page load would have caught
  instantly, but three rounds of plausible-sounding hypotheses (remote
  audio_calls_enabled, insecure context, no mic hardware) had to be
  ruled out first because none of them could be checked without the
  user's own browser. Not yet re-tested again after this fix.
  **Re-tested again: real progress.** The path-typo fix worked -- both
  ends now show "Call connected.", PTT toggles the Talk button
  correctly, no errors. But holding Talk and speaking produces no audio
  on the far end at all, with nothing in the console either. Given the
  actual chain here is long (mic -> AudioWorklet -> Codec2 encode -> WS
  -> RNS.Packet -> the other node's RNS -> its own WS -> Codec2 decode
  -> AudioBuffer playback) and a silent failure gives no clue which
  link broke, added a live `TX N · RX N` packet counter to the status
  line instead of guessing again -- `_txCount`/`_rxCount`, incremented
  at the exact two points bytes actually leave/arrive the browser's own
  WebSocket. Comparing both browsers' numbers side by side (both
  testers have their own tab open simultaneously) should localize the
  fault in one exchange: TX stuck at 0 while holding Talk = mic/encode
  never even happens; TX climbing but the other side's RX at 0 = the
  RNS packet isn't arriving or isn't being forwarded; both climbing
  with still no sound = decode/playback specifically.
  **Retested with the counter -- genuinely useful result: TX 5 · RX 5
  on both sides, zero console errors, still total silence.** That
  actually confirms the entire pipeline works end to end (mic, encode,
  WS, RNS packet delivery, the other node's RNS, its WS, decode) --
  the break is specifically the last step, turning decoded samples
  into audible sound. Diagnosed as a well-known Web Audio gotcha, not
  guessed: browsers create a new `AudioContext` **suspended** unless
  it's resumed in direct response to a user gesture, and "direct" can
  be lost across an `await` -- both Call and Join `await` a `fetch()`
  before ever reaching `_startAudio()`. A suspended context accepts
  every Web Audio call without error (`createBuffer()`,
  `AudioBufferSourceNode.start()`, all of it) and just never produces
  sound -- exactly the observed symptom. Fixed with an unconditional
  `await this._audioCtx.resume()` right after creating the context
  (a no-op if already running, so safe regardless of whether the
  gesture was actually lost) plus a defensive re-resume in
  `_playSamples()` for browsers that re-suspend a context on tab
  backgrounding. User confirmed testing both sides from the **same
  physical machine** on purpose -- a working receive side would be
  audible immediately as their own voice echoing back, no second
  tester needed. Not yet retested after this fix.
- **2026-09-16** — Paper messages / QR, item 2, **export-only** (same
  session as items 1 and 7, immediately after finishing item 1 — user
  asked "what about 2, what is this exactly" since the backlog only had
  a one-line description; researched the real mechanism from source
  before building, rather than guessing from the name). **What it
  actually is** (confirmed by cloning `markqvist/Sideband` and
  `pip download`ing the real `lxmf` 1.1.1 source, not assumed): LXMF has
  a fourth delivery method, `LXMessage.PAPER` (0x05) — a fully real,
  fully end-to-end-encrypted message against the recipient's actual
  identity that's never handed to any transport interface at all.
  `LXMessage.as_uri()` base64-encodes the packed bytes into an
  `lxm://...` URI; `.as_qr()` (Sideband-side, needs the Python `qrcode`
  package) renders that as a QR image. Deliver the QR by any means
  outside Reticulum — screen, print, another app, in person — and the
  recipient's own LXMF client scans/pastes it back in; their key
  decrypts it exactly like a normal received message.
  **Built:** factored `_resolve_identity()` out of `send_message()`
  (same path-discovery retry logic both `send_message` and the new
  `paper_message()` need) into its own method — `paper_message()` builds
  an `LXMessage(desired_method=LXMF.LXMessage.PAPER)`, calls
  `lxm.as_uri()` (which self-packs + finalises, no `handle_outbound`/
  router involvement whatsoever — the message is never transmitted),
  records it in the shared conversation history with `status: "paper"`
  (the existing generic ` · <status>` meta-line suffix in
  `messaging_chat.js` already renders any non-"delivered"/"read" status,
  free). Capped at 512 chars (tighter than the ~10,000-char normal-send
  cap — every extra character makes the QR denser, and the packed LXMF
  payload already carries real fixed overhead before user text even
  starts) — deliberately no image-attachment support here for the same
  density reason. Frontend: Send tab gets a **"Paper message"** button
  (reuses the same Peer/Message fields as a real send) → a result panel
  rendering the QR via the exact same vendored `qrcode.min.js` +
  `<canvas>` pattern Configuration → Channels' Quick Deploy export
  already uses (zero new dependencies) + the raw URI as copyable text +
  a Print button (new `@media print` block isolates just the QR,
  full-bleed, no dashboard chrome — works with the user's actual
  receipt printer via the OS's own print dialog, no custom printer
  integration built or needed). New admin `POST /api/reticulum/paper`.
  **Deliberately export-only** — importing/scanning a paper message
  *into* meshpoint isn't built. User confirmed the real intended
  receiver is a phone running Sideband (or similar), which already has
  its own camera-scan path; a browser dashboard has no camera to scan
  with, so building an import/decode path here would serve a receiver
  that doesn't really exist. 4 new tests (`TestPaperMessage`,
  Mac-runnable, mocked RNS/LXMF), all passing — including one confirming
  `_router.handle_outbound` is never called, the whole point of the
  feature. Not Pi-tested.
- **2026-09-16** — Attachments in Send, item 1, **image-only** (a deliberate
  scope call, made when directly asked — see the "Could build" table
  entry above for the full reasoning and file list; general file
  attachments reopened as its own low-priority item). New `attachments`
  JSON column on `messages` (guarded-added like rssi/snr/rx_count), new
  `backend/attachments.py` (disk storage, random-hex-id addressed), Send
  tab file picker (5 MB cap, base64 in the existing JSON POST), `GET
  /api/reticulum/attachments/{id}`, and a thumbnail in the **shared**
  `messaging_chat.js` (every protocol's chat view, not a Reticulum-only
  change) with live-WS support. 24 new tests, all Mac-runnable, all
  passing. **Fully Pi-verified same session** — real two-node round trip
  between ti-meshpoint and rakv2-meshpoint (192.168.4.4 ↔ .4.3): an
  image sent alongside "hi there" rendered as a correct inline thumbnail
  on **both** ends — the sender's own thread (ti-meshpoint) and the
  recipient's thread (rakv2-meshpoint) — confirming the whole chain for
  real: file picker → base64 upload → `FIELD_IMAGE` over a live LXMF
  send → received + decoded on the other Pi → written to disk → served
  back via `GET /attachments/{id}` → thumbnail in the shared
  `messaging_chat.js` view, no reload needed on either side. Nothing
  left open on this item. Same session also added two other Todo items
  (V6, 7) the user flagged while reviewing a live Messages screenshot —
  see their Notes in the prioritised table for what was found.
- **2026-09-14** — Two new companion plugins, a separate track from this
  backlog's prioritized items (see the **Have** table above for full
  detail): **Reticulum Dashboard** (`plugins/apps/reticulum-dashboard/`)
  — a standalone "top"-tier stat-cards + live peer list + announce
  ticker + telemetry map page for Reticulum-only boxes, built on the
  reticulum plugin's existing public API + the shared dashboard
  WebSocket, no backend of its own; iterated through ~15 commits
  (layout rebuilt onto the actual core Dashboard markup after a
  hand-rolled approximation had real bugs, map sizing/scroll fixes, a
  new "top" sidebar category created for it, a NomadNet quick-browse
  modal with favourites). **Reticulum Browser**
  (`plugins/apps/reticulum-browser/`) — a full multi-tab NomadNet
  browser (tabs, address bar, back/forward/reload, shared favourites,
  raw/rendered toggle, keyboard shortcuts), feature set inspired by
  fr33n0w/rBrowser (MIT) but a clean-room implementation, not a port;
  the reticulum plugin's Dashboard "Browse" actions now open this
  plugin's full experience when it's installed, falling back to the
  lighter quick-view modal otherwise. Both `requires = "reticulum"`
  (enforced server-side, cascading disable) and `locked = true`
  (shipped with the fork). Left explicitly unbuilt by Browser's own
  README: remote-host fingerprint verification, a local NomadNet
  search engine + page cache, and form-field/file-download submission
  — now tracked in **Could build** above.
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

**See "Todo — prioritised (2026-09-09)" near the top of this file** — that
table is the current answer. Short version: **Attachments in Send**,
**Paper messages / QR**, **Audio calls** (both stages), and item 7
(filter chips) are all built now (2026-09-16) — **the entire backlog's
"build" column is empty except group chat / structured sensors / PN
peering / file attachments / paper-message import, all reactive-only.**
Next session is pure Pi-verification: V1/V2 first, then a real
two-node Audio Calls test, then V3–V6.

Note the earlier "needs audio hardware" concern on Audio calls was
retracted 2026-09-09 — Codec2 runs in the browser, the Pi is only a
byte-pipe bridge (see the Could-build row).

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
