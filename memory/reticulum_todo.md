# Reticulum plugin — backlog

Running list of what the plugin does today and what could come next. Not a
promise, just a map. See `memory/plugin-reticulum.md` for implementation
detail and `memory/project_m1_meshpoint.md` for session context.

Written 2026-09-07.

## Have

| Area | Feature | Notes |
|---|---|---|
| Transport | RNode radio + TCP backbone, independent on/off | attaches to `rnsd` shared instance; Settings tab + Restart-rnsd button |
| Messaging | LXMF direct messages, send + receive | own `lxmf.delivery` dest on the shared identity; Messages / Send tabs |
| Presence | Peer roster from announces | Peers tab; topbar pill = own address + RNode frequency |
| Activity | Raw announce feed | Activity tab: 200-entry ring buffer, live over `reticulum_announce` WS; incl. `call.audio` (stream-only) |
| Notifications | ntfy / webhook on inbound DM | `notify_url` config; fire-and-forget POST (`backend/notify.py`) |
| Browsing | NomadNet node browser | Browse tab: live filter, ☆ favourites, `:/page/x.mu` shortcuts |
| Hosting | Our own `nomadnetwork.node` | one hash = "message me" + "browse me" |
| Hosting | Generated `index` / `info` / `nodes` pages | `info.mu` = live version/uptime/host/mesh-activity stats |
| Hosting | Operator `.mu` pages + `files/` | Pages tab: editor, formatting toolbar, Micron cheat-sheet, live preview |
| Hosting | `/page/spacestate.mu` + `{spacestate}` token | SpaceAPI feed, lazy fetch (once at boot, then on view) |
| Hosting | `/page/events.mu` | iCalendar feed, lazy fetch |
| Ops | Dep check / setup / `meshpoint plugin check` | boot probe + on-demand + Run-setup modal |
| Samples | `sample-pages/`, `sample-bbs-techinc/` | |
| Core (not this plugin) | RNode firmware flasher, Heltec-V4 node card | Configuration → Firmware |

## Could build

| Prio | Feature | What it is | Effort / risk |
|---|---|---|---|
| High | **LXMF propagation node** | Store-and-forward relay so offline users collect their messages later — the natural job for an always-on box | Medium — LXMF router already loaded; needs config + announce + a status card |
| High | **LXMF talk-back bot** | Node auto-replies to DMs with commands: `help` / `stats` / `spacestate` / `events` / `nodes` | Low–Med — hook the existing inbound message handler |
| Med | **Attachments in Send** | images / small files over LXMF message fields | Medium — send side easy; inbound needs a decision on the shared `messages` table |
| ~~Med~~ | ~~Announce-stream tab~~ | done 2026-09-07 — Activity tab | |
| ~~Med~~ | ~~DM notifications~~ | done 2026-09-07 — `notify_url` | |
| Med | **Telemetry publish** (Sideband-style) | Push Pi telemetry — CPU temp, load, GPS, sensors — as LXMF telemetry to a collector / Sideband | Medium |
| Med | **Telemetry collector + map** | Receive other nodes' telemetry, plot on the dashboard's local map | Med–High |
| Low | **Audio calls** (`call.audio` / LXST) | Answer / receive voice; minimum viable = a recorded announcement played on call | High — needs audio I/O + codec on the Pi, a project on its own |
| Low | **Group chat** (`RNS.Destination.GROUP`) | Experimental shared-key room; no membership management, non-standard | Medium |
| Low | **Interface manager UI** | Add / remove RNS interfaces from the dashboard instead of hand-editing config | Medium |
| Low | **Contacts / petnames** | Address book with friendly names + trust / identity display | Low–Med |
| Low | **Paper messages / QR** | Sideband-style offline message export | Low–Med |

## Suggested order

1. ~~Activity tab~~ ✓  ~~DM notifications~~ ✓  (done 2026-09-07)
2. **Propagation node** — highest value for an always-on node.
3. **Talk-back bot** — cheap, and it makes the `spacestate` / `events` data
   reachable over DM, not just the browsable pages.
4. Everything else as interest / need dictates. Audio is the big one and
   should be scoped separately.

## Notes / constraints

- Reticulum messaging is **1:1 by design** — LXMF addresses one
  `lxmf.delivery` destination. Group chat only exists via the lower-level
  `RNS.Destination.GROUP` (shared symmetric key) or community tooling.
- Hosted `.mu` pages are served **non-executable** on purpose — dynamic
  content is done with generated pages (`_serve_*` in `backend/nomad_node.py`)
  or `{spacestate}`-style token substitution, never executable scripts.
- External feeds (SpaceAPI, iCal) use the **lazy fetch** pattern: prime once
  at startup, then refresh only when a page that needs it is viewed, off the
  RNS request thread (`_spaceapi_maybe_refresh` / `_events_maybe_refresh`).
  Reuse that shape for any new feed.
