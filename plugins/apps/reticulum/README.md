# Reticulum plugin

Native **Reticulum / LXMF** messaging — meshpoint's own LXMF delivery
destination on the local `rnsd` shared instance, the peer roster built
from received announces, the Reticulum page, and a compact topbar pill.

Extracted from core (`src/reticulum/`, `src/api/routes/reticulum_routes.py`,
Configuration → Reticulum, …) — that code is gone; this plugin is the whole
implementation now. `enabled: false` by default like every shipped plugin.

## What it provides

| Seam | What |
|---|---|
| `service` | `LxmfService` — RNS/LXMF client attach, started right after the packet pipeline is up (`src.api.service_registry`), stopped on shutdown |
| `routes` | `/api/reticulum/{status,peers,announces,messages,send,announce}` + `/api/reticulum/nomad/{nodes,page,file}` + `GET`/`PUT /api/config/reticulum` + `POST /api/config/reticulum/restart-rnsd` |
| `sidebar` | the **Reticulum** page under Networks — Peers / Activity / Messages / Send / Browse / Settings tabs |
| `topbar` | the compact status pill (own address · RNode frequency when an RNode is connected, else the peer count for a backbone-only node; hover title has the peer count + active interface), self-polling `/api/reticulum/status` |

## Enable it

First run the setup step (`pip install lxmf` + install/enable `rnsd.service`) —
either the **Run setup** button on the Settings → Plugins row (streams the
output in a modal), or from a shell:

```sh
sudo meshpoint plugin setup reticulum
```

Until that's done, Settings → Plugins shows **"⚠ Setup needed"** on the
Reticulum row — `check.sh` probes for `lxmf` in the venv plus an installed,
enabled `rnsd.service`. The loader re-runs it at every boot; the row's
**Re-check** button (or `meshpoint plugin check reticulum`) re-runs it on
demand, so a live change to `rnsd` shows up without restarting meshpoint. The
plugin still loads and serves its pages without setup; it just can't attach to
Reticulum.

```yaml
plugins:
  reticulum:
    enabled: true
    display_name: "Meshpoint"
    # RNode radio + TCP backbone (also editable from the page's Settings tab).
    # Independent on/off switches -- at least one must stay enabled:
    rnode_enabled: true
    rnode_serial_port: ""            # by-id/by-path; blank = no RNode either way
    rnode_frequency_hz: 869463000
    rnode_bandwidth_hz: 125000
    rnode_tx_power: 20
    rnode_spreading_factor: 8
    rnode_coding_rate: 5
    backbone_enabled: true
    backbone_host: node.reticulumnet.nl
    backbone_port: 4242
    # storage paths — defaults shown; only set to override:
    # reticulum_config_dir: data/reticulum/rns_config
    # identity_path: data/reticulum/identity
    # lxmf_storage_dir: data/reticulum/lxmf
```

`backend/state.py` documents every key + default. Restart meshpoint after
editing. The `rnode_*` / `backbone_*` keys are also consumed by
`scripts/write_rnsd_config.py` (rnsd's `ExecStartPre`) — those need an
`rnsd` restart too, which the Settings tab's **Restart rnsd** button does.

## `rnsd`

meshpoint's `LxmfService` attaches to a locally-running `rnsd` shared
instance as a *client* — it never opens a radio interface itself. `rnsd`
runs as its own opt-in systemd unit (`scripts/rnsd.service`,
`sudo systemctl enable --now rnsd`), deliberately **not** a dependency of
`meshpoint.service`. `reticulum_config_dir` must be the same directory
`rnsd` uses — the shared-instance RPC channel authenticates per-configdir.

The **RNode firmware flasher** and the **Heltec-V4 Reticulum-node firmware
card** stay in core (Configuration → Firmware) — they're hardware
provisioning, usable with or without this plugin.

## Layout

```
plugin.toml                    provides = ["service", "routes", "sidebar", "topbar"]
clear_reticulum_packets.py     maintenance: wipe reticulum messages / peer roster
backend/
  __init__.py                  register(reg) -- add_router x3 + add_service
  state.py                     plugins.reticulum.* config + set_config/_persist
  lxmf_service.py              the RNS/LXMF client + RNS-log bridge
  peer_repo.py                 reticulum_peers access (table schema stays in core)
  routes.py                    /api/reticulum/*
  config_routes.py             /api/config/reticulum (Settings tab)
  nomad.py                     NomadNet page fetch over RNS Links
  nomad_routes.py              /api/reticulum/nomad/{nodes,page,file}
  nomad_node.py                host our own nomadnetwork.node destination
  spaceapi.py                  SpaceAPI fetch/normalise (-> /page/spacestate.mu)
  ical.py                      iCalendar fetch/parse (-> /page/events.mu)
  tests/
frontend/
  reticulum_panel.js           the page (registerSidebarPage)
  reticulum_settings_tab.js    the Settings tab
  reticulum_nomad.js           the Browse (NomadNet) tab
  reticulum_micron.js          Micron markup -> DOM (window.MicronParser)
  reticulum_topbar_chip.js     the pill (registerTopbarChip)
  reticulum.css                Browse-tab layout
```

## NomadNet browsing (the "Browse" tab)

`nomadnetwork.node` is a Reticulum aspect the plugin already tracks in its
peer roster. The Browse tab fetches those nodes' Micron pages over standard
RNS `Link`/`Request` primitives (`backend/nomad.py`) and renders them
(`reticulum_micron.js`, ported from reticulum-meshchat's `MicronParser.js`,
MIT). It lives here rather than in a separate plugin because it needs the
same live `RNS` attach `LxmfService` provides — a second plugin would mean
a second client attach + a cross-plugin seam to share the handle.

The node picker filters live (the `/nodes` endpoint caps at 300 of the
network's many `nomadnetwork.node` announces) and the **☆** button keeps a
per-browser favourites list in `localStorage` — favourites get their own
optgroup at the top of the picker and stay selectable after they age off
the recent list. The address bar pre-fills with the current node's full
`<hash>:/page/…` address and accepts `:/page/x.mu` / `/page/x.mu`
shortcuts against it — edit the path and Go to reach a page nothing links
to (e.g. `:/page/info.mu`).

## Activity tab

The **Activity** tab is the raw announce feed — every `lxmf.delivery`,
`lxmf.propagation`, `nomadnetwork.node` and `call.audio` announce the
service has heard since it started, newest first, repeats and all. It's an
in-memory ring buffer (200 entries, `GET /api/reticulum/announces`), fed
live over the `reticulum_announce` WebSocket event, and gone on restart.
The **Peers** tab is the deduped roster; `call.audio` is Activity-only so
it doesn't pad the roster with every Sideband/MeshChat user on the public
network. `nomadnetwork.node` rows carry the same **Browse** button the
Peers tab has (admin only).

## Propagation node (opt-in)

Set **Settings → Propagation node → "Act as an LXMF propagation node"**
(`plugins.reticulum.propagation_enabled`) and the box runs a
store-and-forward relay: an LXMF message for a peer who's offline is held
here until their client next syncs from this node — the classic reason to
run an always-on Reticulum box.

It's an *added* role, nothing is replaced. The same identity now answers on
three aspects at once:

| Aspect | Role |
|---|---|
| `lxmf.delivery` | "message me" — the inbox (always on) |
| `nomadnetwork.node` | "browse me" — the hosted pages (`node_enabled`) |
| `lxmf.propagation` | "relay for others" — this feature |

`lxmf.propagation` is a **different hash** from the delivery/browse one — a
separate service other people point their clients at. `LXMF`'s own
`LXMRouter` does the relaying; the plugin calls `enable_propagation()`,
re-announces the propagation destination every 6 h (and on the **Announce**
button), and caps the on-disk store with **`propagation_storage_limit_mb`**
(default 250; `0` = LXMF's own default — don't leave it uncapped on a small
SD card). `GET /api/reticulum/status` reports a `propagation` block
(address, limit, messages held); the Settings tab shows it as a live line.
Takes effect on restart.

## Message notifications (opt-in)

Set **Settings → Message notifications → ntfy / webhook URL**
(`plugins.reticulum.notify_url`) and every inbound LXMF direct message
fires a one-line `POST` there — the message text as the body, the sender as
an ntfy-style `Title` header. Works with an [ntfy](https://ntfy.sh) topic
or any webhook that accepts a plain-text body. Fire-and-forget off the
event loop (`backend/notify.py`, stdlib `urllib`), 8 s timeout, failures
are logged and ignored. Note it hands the message text to that third party
— use a self-hosted ntfy or a private endpoint if that matters. Blank =
off.

## Hosting a NomadNet node (opt-in)

Off by default. Flip `plugins.reticulum.node_enabled: true` (or the toggle on
the Settings tab) and meshpoint registers a `nomadnetwork.node` destination
on the **same identity** as its LXMF address — one hash is both "message me"
(`lxmf.delivery`) and "browse me" (`nomadnetwork.node`), exactly how the
NomadNet client works. `backend/nomad_node.py` announces on an interval,
answers `Link`/`Request` with:

- `/page/index.mu` — generated: a branding/landing page (a blue figlet
  MESHPOINT banner, node name, a short "what is Meshpoint" blurb) linking
  to `info.mu`. An operator `index.mu` in `node_pages_dir` overrides it
  entirely.
- `/page/info.mu` — generated, **always served** regardless of your
  `index.mu` (a same-named file you drop in `node_pages_dir` is ignored):
  version / uptime / hardware / Reticulum peer + NomadNet node +
  conversation counts, a **`>Host`** block (board model, CPU temp, 1-min
  load, memory, free disk — all non-sensitive), and a **`>Mesh activity`**
  block (total + 24 h packet counts and a per-protocol split —
  **aggregate only, nothing node-level**, since the page is public on the
  Reticulum network). Refreshed every 60 s. The "Meshpoint on GitHub"
  link is derived from this checkout's `git` origin
  (`src.remote.repo_source`, falls back to `KMX415/meshpoint`). Safe to
  link to from your own `index.mu`.
- `/page/nodes.mu` — the recent `nomadnetwork.node` peers as Micron links
- `/page/spacestate.mu` — generated, only when `node_spaceapi_url` is set
- `/page/events.mu` — generated, only when `node_events_ical_url` is set
- any other `*.mu` file you drop in `node_pages_dir` (`data/reticulum/pages/`
  by default)
- `files/**` under that dir, served at `/file/<relpath>`

### Editing pages — the "Pages" tab

While a node is hosting, the Reticulum page grows a **Pages** tab (admin
only): a list of the `.mu` files in `node_pages_dir`, a raw-Micron editor
with a formatting toolbar (bold/underline/italic, fg + bg colour, H1–H3,
left/centre/right align, divider, link, emoji, a box-drawing/symbols
palette, text-field / checkbox / radio, and a **?** Micron cheat-sheet —
inserts at the cursor or wraps the selection), and a live preview
rendered by the same parser the Browse tab uses. (The field widgets
render but only submit to an *executable* NomadNet page, so a form on
your own node's page is display-only unless it POSTs elsewhere.) Save
(`PUT /api/reticulum/nomad/pages/{name}`) writes the file and re-registers
the node's request handlers, so a new or edited page is served
immediately — no restart. `info.mu` / `nodes.mu` / `spacestate.mu` /
`events.mu` are refused (they're generated); pages are always written
non-executable, so "dynamic pages" (executable `.mu` scripts) still need
SSH, on purpose. A **Load sample** button drops in `sample-pages/index.mu`.

`sample-pages/index.mu` is a copy-me starter page with a Micron cheat-sheet
in its header. `sample-bbs-techinc/` is a fuller worked example — a small
read-only "BBS" (splash + `techinc.mu` / `meshpoint.mu` / `mesh.mu` /
`links.mu`, all cross-linked, plus generated `spacestate.mu` / `events.mu`),
carrying real TechInc details; see its own README to deploy + adapt. On the Pi the pages dir is
`/opt/meshpoint/data/reticulum/pages/` (relative to the service's
`WorkingDirectory`) and isn't auto-created — the Pages tab creates it on
first save. Editing a `.mu` file **on disk** (SSH) is picked up per
request; *adding* one that way still needs a restart (or a save from the
Pages tab, which re-scans). Toggling `node_enabled` needs a restart.

```yaml
plugins:
  reticulum:
    node_enabled: true
    node_name: ""                        # blank = display_name
    node_pages_dir: data/reticulum/pages
    node_announce_interval_s: 21600       # 6h; min 600
    node_spaceapi_url: ""                 # optional hackerspace SpaceAPI feed
    node_events_ical_url: ""              # optional .ics calendar feed
```

`node_spaceapi_url` (optional, also on the Settings tab): a
[SpaceAPI](https://spaceapi.io) endpoint. Set it and the node serves a
generated `/page/spacestate.mu` (open/closed + address + contacts) and
replaces a `{spacestate}` token in any of your own `.mu` pages with a
colour-coded `OPEN` / `CLOSED` / `unknown` word. Find your space's URL at
`directory.spaceapi.io`. The `{spacestate}` substitution only happens when
the node serves the page — the dashboard preview shows the raw token.

`node_events_ical_url` (optional, also on the Settings tab): any
iCalendar (`.ics`) feed — a wiki's event export, a shared Google/Nextcloud
calendar. Set it and the node serves a generated `/page/events.mu` — the
next dozen upcoming events (`VEVENT` `SUMMARY` + start time + link),
past ones dropped, soonest first. `backend/ical.py` parses it with the
stdlib only (line unfolding, floating / `Z` times, all-day dates).

Both feeds follow the same rule: fetched **once at startup, then only when
someone actually loads the page** — never on a timer (`spacestate.mu`
cached 2 min, `events.mu` 15 min), so an idle node never touches either
endpoint. A fetch failure keeps the last good copy and shows a small note.

`GET /api/reticulum/status` reports the live `node` block
(`hosting`, `name`, `pages`, `requests_served`, `last_announce_s_ago`).
`GET/PUT/DELETE /api/reticulum/nomad/pages[/{name}]` (+ `GET
/api/reticulum/nomad/sample-page`) back the Pages tab.

Full write-up: [docs/PLUGINS.md](../../../docs/PLUGINS.md).
