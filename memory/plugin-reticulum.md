# Reticulum core → plugin extraction — plan + progress tracker

Follows the DAPNET extraction precedent (`memory/project_m1_meshpoint.md`,
`docs/PLUGINS.md`). Written 2026-09-06 after tracing the full Reticulum
footprint in core. **Nothing built yet** — this is the agreed plan.

Related: `memory/nomad-plugin.md` (NomadNet browsing as a hook plugin —
sequenced *after* this; it wants the Reticulum page to be a hook host,
which this extraction's frontend work delivers naturally).

---

## Progress tracker

Update this block as phases land. `[ ]` todo, `[~]` in progress, `[x]` done.

- [x] **Phase 0** — `add_service` core seam ✅ (commit pending). `write_rnsd_config.py` repoint + `_run_systemctl` lift **deferred** — see notes below.
- [x] **Phase 1** — plugin backend scaffold ✅ (commit pending). `service` + `routes` only; `config_routes.py` + `_run_systemctl` lift **moved to Phase 2** (coupled to the settings tab + the rnsd-config question).
- [x] **Phase 2** — plugin frontend. **2a** (commit): sidebar page + **topbar pill**, `sidebar`+`topbar` in `provides`. **2b** (commit): Settings tab (`reticulum_settings_tab.js`) + `backend/config_routes.py` (`GET`/`PUT /api/config/reticulum` → `plugins.reticulum.*` via `state.set_config`/`_persist`, `POST .../restart-rnsd`) + `_run_systemctl` lifted → `src/api/systemctl.py`.
- [x] **Phase 3** — Messages page routes reticulum sends to `/api/reticulum/send` (commit). `messaging.js._onSendMessage` early-returns to a new `_sendReticulumMessage()` for `protocol==='reticulum'`. Core `messages.py` branch LEFT in place as a fallback (deleted Phase 4). Works live now — core already serves `/api/reticulum/send`.
- [x] **Phase 4 + 5** — core deleted + `write_rnsd_config.py` repointed to `config.plugins["reticulum"]` (commit `feat: reticulum is now a plugin ...`). Awaiting atomic Pi flip (migration diff below) + screenshots.
- [x] **Phase 6** — docs. CHANGELOG ⚠️ entry + `service`-hardening bullet; CONFIGURATION.md § rewritten for the plugin shape + upgrade note; README "What's Different" Reticulum block + plugins paragraph (`service` seam, Reticulum/Hello Service as references) + Local API table rows; PLUGINS.md — "nine seams", new **Adding a background service (`"service"`)** section, `provides` table + `register(reg)` + Current-limitations updated, intro reference list; API-ENDPOINTS.md — new **Reticulum (plugin)** section.
- [x] **rnsd into the plugin** (commit): `scripts/rnsd.service` + `scripts/write_rnsd_config.py` → `plugins/apps/reticulum/`; new `setup.sh` (`pip install lxmf` + install/enable the rnsd unit); `lxmf` dropped from `requirements.txt` (`rns` stays — rnsd binary + rnodeconf); `install.sh` migration re-copies the unit for pre-move installs. ⚠️ existing users run `sudo meshpoint plugin setup reticulum`.
- **NomadNet browsing — IN the reticulum plugin** (decided: needs the same RNS attach LxmfService gives, so not a separate plugin). `memory/nomad-plugin.md` has the traced mechanics.
  - [x] **N1 — backend** (commit): `backend/nomad.py` (`fetch_page()` — path lookup → cached Link → `link.request`, callbacks bridged to a Future via `call_soon_threadsafe`; `available()` checks `RNS.Reticulum.get_instance()`), `backend/nomad_routes.py` (`GET /api/reticulum/nomad/nodes`, `POST /api/reticulum/nomad/page`). Wired in `register()` + `wire()`. 4 tests (not-available path). Ported in spirit from meshchat's `NomadnetDownloader`.
  - [x] **N2 — Micron parser** (commit): `frontend/reticulum_micron.js` ← meshchat's `MicronParser.js` (MIT). `parseToHtml()` builds DOM via `textContent` (no innerHTML). Links → `<a data-nomad-url data-nomad-fields href="nomadnetwork://…">` (no inline onclick); Browse tab delegates. Smoke-tested with a node-jsdom stub.
  - [x] **N3 — Browse tab** (commit): `frontend/reticulum_nomad.js` — 5th tab (`data-rt-tab="browse"`, admin-only). Node `<select>` + address bar + Go/←/→/⟳; `_splitAddr` handles `<hash>:/path`, `:/path` (same node), `/path`; history array; `_followLink` parses `data-nomad-url` backtick-vars → `var_*`, gathers named inputs for `data-nomad-fields` (`*` or `a|b`) → `field_*`. `panel.browseNode(hash)` from a Peers-row **Browse** button on `nomadnetwork.node` rows. New `frontend/reticulum.css` (Browse tab layout only). `plugin.toml`: 5 scripts + `styles`.
  - [x] **N4 — polish** (commit): file downloads — `nomad.fetch_file()` (`io.BufferedReader` / `[bytes,{name}]` / `[name,bytes]` shapes) + `POST /api/reticulum/nomad/file` (binary `Response` + `Content-Disposition`); Browse tab detects `/file/` links → blob + `<a download>`. Timeouts — `nomad.set_timeouts(base)` scales path/link (=base) + request (1.5x) from `plugins.reticulum.nomad_timeout_s` (default 20, was hardcoded 15); Settings-tab field, applies live (config_routes PUT calls `set_timeouts`). Docs: API-ENDPOINTS 3 rows, README + CONFIGURATION Browse mentions. +7 tests (timeouts, `_extract_file`).
    - **Perf fix (same commit):** opening the Reticulum page took ~10s because the panel's `show()` fired BOTH the Settings tab's 3 API calls AND the Browse tab's node load (11k-row query + ~3k `<option>`s) every visit. Now `_activateSubTab()` loads only the visible sub-tab (from `show()` + `_setTab()`); Settings tab renders the (fast) `plugins.reticulum.*` fields immediately and fills the port dropdown async; `/nodes` capped to 300 most-recent.
  - [x] **N5 — host a NomadNet node** (commit): `backend/nomad_node.py` — `NomadNode` registers a `nomadnetwork.node` `RNS.Destination` on `LxmfService._identity` (same hash as LXMF), `set_link_established_callback` + per-path `register_request_handler`, announce loop, 5-min stats-refresh task. Serves generated `/page/index.mu` (version/uptime/peer counts + about) + `/page/nodes.mu` (recent `nomadnetwork.node` peers) + operator `.mu` files + `files/` at `/file/…`. Folded into `LxmfService` (owns identity + attach) — `node_cfg` + `node_stats_provider` ctor args, started at the end of `start()` if `node_cfg["enabled"]`, stopped in `stop()`. `state.node_config()` + 4 keys (`node_enabled` off default, `node_name`, `node_pages_dir`, `node_announce_interval_s`). `_on_announce` now decodes `nomadnetwork.node` app_data as raw UTF-8 (was the "Could not decode display name" noise). `/api/reticulum/status` gains a `node` block + stops pulling the full peer table (new `peer_repo.count()`). Settings-tab "NomadNet node" section (toggle/name/interval/pages-dir + live status line). +13 tests.
    - **N5 follow-ups (same/next commit):** `NomadNode.announce()` public wrapper — `LxmfService.announce()` (the Reticulum page's Announce button) now re-announces the node hash too, not just `lxmf.delivery` (user hit this: only saw the LXMF announce). Operator override lives at `<node_pages_dir>/index.mu` = `/opt/meshpoint/data/reticulum/pages/index.mu` on the Pi (relative to `WorkingDirectory=/opt/meshpoint`); dir not auto-created; handlers registered once at startup so new/changed `.mu` files need a meshpoint restart. Toggling `node_enabled` also needs a full restart (NomadNode only started inside `LxmfService.start()`). Sample page shipped at `plugins/apps/reticulum/sample-pages/index.mu`. User deployed 3 default Meshpoint nomads on the live net.
  - [ ] **N6 (later)** — live toggle (register destination always, gate announce/serve on the flag); richer index stats (packets/protocol from the pipeline); a "Node" status readout somewhere more prominent than the Settings hint.

**Decisions locked with the user (2026-09-06):**
- **Firmware stays in core** (option C) — RNode + Heltec-V4 flashers are
  hardware provisioning, usable without the LXMF service. Untouched.
- **Chat send = frontend reroute** (option 1) — Messages page POSTs
  reticulum sends to `/api/reticulum/send`; delete core's
  `messages.py` `protocol == "reticulum"` branch. A proper "chat
  provider registry" is a possible later refactor, not now.

---

## The one big difference from DAPNET

DAPNET slotted into the **existing packet pipeline** — `DapnetSerialSource`
is a `CaptureSource`, so start/stop came free from the capture coordinator.
Reticulum produces **zero packets**; `LxmfService` is a lifespan-managed
async service (`start()`/`stop()` wired directly into `server.py`'s
lifespan). **No plugin seam exists for that** — so this extraction starts
with a core-seam build (Phase 0), the analogue of the
`capture_source_registry`/`protocol_registry` work that preceded DAPNET.

---

## Reticulum's core footprint (inventory)

| Piece | Lines | What it is | Fate |
|---|---|---|---|
| `src/reticulum/lxmf_service.py` | 302 | `LxmfService` async companion, lifespan start/stop | → plugin `backend/lxmf_service.py` |
| `src/api/routes/reticulum_routes.py` | 89 | `/api/reticulum/{status,peers,messages,send,announce}` | → plugin `backend/routes.py` |
| `src/api/routes/reticulum_config_routes.py` | 143 | `/api/config` RNode/backbone fields + `restart_rnsd()` | → plugin `backend/config_routes.py` |
| `src/storage/reticulum_peer_repository.py` | 94 | `reticulum_peers` table access | → plugin `backend/peer_repo.py` (table schema stays in core `database.py`) |
| `src/storage/database.py` | ~15 | `CREATE TABLE reticulum_peers` | **stays** (precedent: DAPNET kept shared `packets`) |
| `src/config.py` | ~85 | `ReticulumConfig` dataclass + `AppConfig.reticulum` | **deleted** Phase 5 (read via `reg.config` instead) |
| `config/default.yaml` | ~few | `reticulum:` block | **deleted** Phase 5 (DAPNET missed this first pass — caught by a test) |
| `src/api/routes/config_enrichment.py` | ~11 | `base["reticulum"] = {...}` in `GET /api/config` | **deleted** Phase 5 — **AttributeError trap** |
| `src/api/routes/messages.py` | ~30 | `if req.protocol == "reticulum"` branch + `_reticulum_service` global | **deleted** Phase 5 (frontend reroutes in Phase 3) |
| `src/api/server.py` | ~25 | `_reticulum_service`, import, lifespan start/stop, 2 `_BUILTIN_ROUTERS` entries, `_init_routes` param | **deleted** Phase 5 |
| `frontend/js/reticulum_panel.js` | 530 | the page | → plugin `frontend/reticulum_panel.js` (`registerSidebarPage`) |
| `frontend/topbar/topbar_reticulum_chip.js` | 120 | **the topbar pill** | → plugin `frontend/reticulum_topbar_chip.js` (`registerTopbarChip`) |
| `frontend/js/configuration/reticulum_config_card.js` | 357 | Configuration → Reticulum card | → plugin **Settings tab** on its own page (DAPNET pattern) |
| `frontend/index.html` | ~8 | 3 `<script>` tags, `#/reticulum` + `#/configuration/reticulum` nav `<li>`s, 2 `<section>`s, `#topbar-reticulum-group` | **edited** Phase 5 |
| `frontend/js/app.js` | ~6 | `_bootReticulumPanel`, route lists (~L58, ~L64, ~L932) | **deleted** Phase 5 |
| `tests/test_messages_reticulum_send.py` | 140 | superseded by plugin's own tests | **deleted** Phase 5 |
| `scripts/clear_reticulum_packets.py` | — | maintenance script | → plugin root (DAPNET precedent: `clear_dapnet_packets.py`) |

**Stays in core, untouched (option C):**
- `src/api/routes/rnode_firmware_routes.py` (535) — `rnodeconf` "dumb modem" flasher
- `src/api/routes/reticulum_companion_firmware_routes.py` (331) — Heltec V4 node via PlatformIO
- `frontend/js/configuration/reticulum_companion_firmware_card.js` (386) + `rnode_firmware_card.js`
- `data-firmware-reticulum` / `data-firmware-rnode` slots in
  `frontend/js/configuration/configuration_panel.js` (the Firmware page is
  a **hardcoded core list of 7 cards** — there is *no* firmware-page hook
  seam; DAPNET's own `pocsag_firmware_card.js` is likewise still
  orphaned-in-core calling plugin routes)
- `scripts/write_rnsd_config.py` + `scripts/rnsd.service` — rnsd infra
  (but the script needs repointing, see Phase 0)

---

## How DAPNET's firmware actually works (for reference)

Backend `/api/pocsag/firmware/*` **moved into the plugin**; the compile/flash
**UI card stayed in core**, hardcoded as card 3 of 7 on
`Configuration → Firmware` by `configuration_panel.js`, just pointed at the
plugin's routes. There is **no `registerFirmwareCard()` hook**. Reticulum's
two firmware cards sit in that same hardcoded list — under option C we
leave both the routes and the cards entirely in core.

---

## The chat coupling

- **Conversation list / history — already decoupled.** Messages page reads
  reticulum threads from the shared `messages` table (`protocol='reticulum'`,
  written by `LxmfService._handle_inbound_message`) via
  `/api/messages/conversations`. No change needed.
- **Send path — coupled.** `messages.py:92-113` has a `protocol == "reticulum"`
  branch → `_reticulum_service` module global (set by `_init_routes`). The
  "Unknown protocol: reticulum" fix (commit b0bd0d7) was exactly this.
  Phase 3 fix: frontend (`messaging_chat.js` / `messaging_contacts.js`)
  POSTs to `/api/reticulum/send` when the thread is reticulum; core branch
  deleted Phase 5.

---

## Phased plan

### Phase 0 — `add_service` core seam (no plugin yet) — ✅ DONE

Shipped as `feat: "service" plugin capability ...`. What actually landed:

| File | Change |
|---|---|
| `src/api/service_registry.py` | **new** — `ServiceSpec(name, build, wire)`, `ServiceContext(pipeline, ws_manager, config)`, `register_service()`, `plugin_specs()`, `live()`, **async** `start_all(context)` / `stop_all()`, `reset()`. FastAPI-free. No `build_all`/`wire_all` split (services build+start together, post-pipeline — unlike capture sources). |
| `src/plugins/registry.py` | `reg.add_service(name, build, wire=None)` — requires `"service"` in `provides`. `build(context)` → service or `None` to opt out; `wire(service, context)` runs between build and `start()`. |
| `src/plugins/manifest.py` | `KNOWN_PROVIDES += "service"` (backend-only — NOT added to the frontend-scripts-required list) |
| `src/api/server.py` | import + `service_registry.reset()` in `create_app`; `await service_registry.start_all(ServiceContext(...))` right after `capture_source_registry.wire_all(pipeline)` + `message_repo`; `await service_registry.stop_all()` in shutdown after `listener_registry.stop_all()` |
| `tests/test_service_registry.py` | **new**, 8 tests (asyncio.run style, mirrors `test_listener_registry.py`) |
| `tests/test_plugin_registry_facade.py` | +2 (`add_service` delegates / rejected) |
| `tests/test_plugin_manifest.py` | +1 (`service` is a known provides value, no frontend script needed) |
| `plugins/apps/hello-service/` | **new** reference plugin — `provides = ["service"]`, `locked = true`, a `HelloService` that logs on start/stop (no heavy imports, loads on the Mac). Doubles as the Pi verification probe (`journalctl -u meshpoint \| grep hello_service`) and the Phase 6 doc example. |
| `tests/test_plugin_loader.py` | +`TestShippedHelloServicePlugin` (3 tests: registers when enabled, builds/starts/stops, skipped when disabled) |
| `docs/CHANGELOG.md` | "Internal:" bullet under `### v0.8.1` |

Verified: `python3.11 -m pytest tests/test_service_registry.py tests/test_plugin_registry_facade.py
tests/test_plugin_manifest.py tests/test_plugin_loader.py tests/test_capture_source_registry.py
tests/test_listener_registry.py tests/test_protocol_registry.py tests/test_route_registry.py`
→ 103 passed, 2 skipped, **1 pre-existing env failure** (`TestShippedDapnetPlugin::test_dapnet_loads_when_enabled`
needs `fastapi`, not installed on the Mac — confirmed fails identically on a clean `git stash`).
`ruff check` clean. CHANGELOG parses (`ChangelogParser.parse_file` → v0.8.1 has 68 bullets).

**Deferred out of Phase 0** (were listed as "wrinkles" here, moved to their real phases):
- `_run_systemctl` lift → **Phase 1** (plugin `config_routes.py` is what needs it)
- `scripts/write_rnsd_config.py` repoint → **Phase 5** (repointing now breaks the
  live Pi's rnsd, which reads `config.reticulum` until the atomic Phase 4 flip)

### Phase 1 — plugin backend scaffold — ✅ DONE

Shipped as `feat: reticulum plugin — Phase 1 backend scaffold ...`. What landed:

```
plugins/apps/reticulum/
  __init__.py           (empty, pytest importability)
  plugin.toml           provides = ["service", "routes"], locked = true, [meta]
                        (sidebar/topbar deferred to Phase 2 — declaring them
                        without the frontend files would fail manifest parse)
  backend/
    __init__.py         register(): state.init(reg.config); add_router(routes.router);
                        add_service("reticulum", build, wire)
                          build(context)  -> LxmfService(state.*, MessageRepository(
                                             context.pipeline.database),
                                             ReticulumPeerRepository(...), context.ws_manager)
                          wire(svc, ctx)  -> routes.init_routes(svc, MessageRepository(...))
    state.py            plugins.reticulum.* — defaults mirror core ReticulumConfig
                        EXACTLY (display_name/dirs + rnode_*/backbone_* held for Ph2)
    lxmf_service.py     ← src/reticulum/lxmf_service.py, VERBATIM logic; only edits:
                          - WebSocketManager/MessageRepository imports -> TYPE_CHECKING
                            (annotation-only) so it imports on the Mac
                          - ReticulumPeerRepository from .peer_repo
                          - added reset_routes() to routes.py
    peer_repo.py        ← src/storage/reticulum_peer_repository.py, verbatim
                          (table schema stays in core database.py)
    routes.py           ← src/api/routes/reticulum_routes.py; only the LxmfService
                          import path changed (.lxmf_service) + reset_routes()
    tests/
      test_state.py         4 tests (pure, Mac)
      test_lxmf_service.py  5 tests (not-available path — RNS is None on Mac)
  README.md            "Phase 1 scaffold" banner + don't-enable-alongside-core warning
```

**Core untouched by the scaffold.** `src/reticulum/`, `reticulum_routes.py`,
`reticulum_config_routes.py`, `reticulum_peer_repository.py` all still present and
authoritative — deleted in Phase 5.

**Side fix (separate commit, not a phase): RNS/LXMF log bridge.** `_route_rns_log`
+ `_install_rns_log_bridge()` added to **both** `lxmf_service.py` copies (core +
plugin) — routes RNS's stdout logging through Python `logging` under an `RNS`
logger, levels mapped, and demotes the noisy `Could not decode display name in
included announce data` LXMF line to DEBUG. Called in `start()` right after
`RNS.Reticulum(...)`. The core copy goes away with core in Phase 5; the plugin
copy is self-contained (deliberately inlined, not a shared import). Same commit
also fixed the LoRaWAN `YOUR_DEVICE_EUI_HEX` placeholder traceback (unrelated).

**test_plugin_loader.py:** +`TestShippedReticulumPlugin` (2 tests, `@skipUnless(_HAS_FASTAPI)`).
Also gated `TestShippedDapnetPlugin` the same way — it was failing (not skipping) on
the Mac, now matches `TestShippedAcarsPlugin`. Suite is fully green on the Mac now.

Verified: `pytest plugins/apps/reticulum/ tests/test_plugin_loader.py tests/test_service_registry.py`
→ 35 passed, 6 skipped. `ruff check src/ tests/ plugins/` clean. Manifest parses
(`provides=('service','routes') locked=True`). CHANGELOG parses (v0.8.1, 69 bullets).

### Phase 2a — sidebar page + topbar pill — ✅ DONE

`plugins/apps/reticulum/frontend/`:
- `reticulum_panel.js` ← `frontend/js/reticulum_panel.js`, ported: `mount(rootEl)`/`show()`/`hide()`,
  root-scoped `_q(sel)` helper (no `document.getElementById`), `window.meshpointIdentity?.role`,
  `window.registerSidebarPage({route:'reticulum', make})`. Behaviour identical (Peers/Messages/Send).
- `reticulum_topbar_chip.js` ← `frontend/topbar/topbar_reticulum_chip.js`, ported to
  `window.registerTopbarChip({id:'reticulum', make})` + `mount`/`init`/`destroy`, self-polls
  `/api/reticulum/status` (mirrors dapnet_topbar_chip.js). Hidden only when `available === false`.
- `plugin.toml`: `provides = ["service","routes","sidebar","topbar"]`, `[frontend].scripts`,
  `[sidebar]` (route=reticulum, label=Reticulum, category=networks, icon=reticulum).

**No CSS file needed.** Reuses core shared classes (`lw-*`, `stat-card`, `mt-badge`, `cfg-*`,
`terminal-button`, `r-toast`, `lw-link-btn`). `lorawan.css`'s `.section[data-section="reticulum"]
{ overflow-y: auto }` already covers the plugin section (`mountPluginSidebarPages` sets
`section.dataset.section = "reticulum"`).

**⚠️ Phase 5 note:** when deleting core's reticulum frontend, KEEP the
`.section[data-section="reticulum"]` line in `frontend/css/lorawan.css` — the plugin section
still needs it (it's keyed on the same `data-section` value).

**Dormant until Phase 4.** Plugin `enabled: false` → `inject_plugin_assets` / `sidebar_descriptor_tags`
only run for loaded plugins, so the scripts aren't served and nothing registers. Core frontend
(index.html nav/section/scripts, `topbar_reticulum_chip.js`, `_bootReticulumPanel`) stays
authoritative. They CANNOT coexist live (both would add a `#/reticulum` nav entry + a pill), so
the frontend cutover is atomic with the Phase 4 flip.

Verified: manifest parses (`provides` + `frontend_scripts` + `[sidebar]`), `node --check` both JS
files, 77 passed / 6 skipped.

### Phase 2b — Settings tab + config_routes + systemctl lift — ✅ DONE

- `src/api/systemctl.py` (**new**) — `run_systemctl(*args)` lifted from
  `rnode_firmware_routes.py`, which now does `from src.api.systemctl import
  run_systemctl as _run_systemctl` (keeps the old private name working for its
  own uses AND for core's `reticulum_config_routes.py`, which imports it from
  there until Phase 5).
- `plugins/apps/reticulum/backend/config_routes.py` (**new**, from
  `src/api/routes/reticulum_config_routes.py`):
  - `GET /api/config/reticulum` → `state.to_dict()` (new — the settings tab
    needs its own load; core's card read the full `/api/config`)
  - `PUT /api/config/reticulum` — pydantic `ReticulumUpdate` (bandwidth
    whitelist kept), **no `enabled` field** (Settings→Plugins owns it),
    → `state.set_config()` → `state._persist()` → `plugins.reticulum.*`
  - `POST /api/config/reticulum/restart-rnsd` → `run_systemctl("restart","rnsd")`
- `backend/state.py` +`set_config()` / `_current_saved_config()` / `_persist()`
  (mirror dapnet's `state.py`; `_ALLOWED_UPDATE_KEYS` excludes `enabled`).
- `backend/__init__.py` +`reg.add_router(config_routes.router)`.
- `frontend/reticulum_settings_tab.js` (**new**, from `reticulum_config_card.js`)
  — plain-`fetch` tab class (`show`/`hide`/`_mount`/`_load`), own `_request`/
  `_toast` (dapnet pattern), port picker from `/api/config/serial-ports` +
  usage map from `/api/config`, `window.confirmModal` for the rnsd restart.
  No `enabled` checkbox.
- `frontend/reticulum_panel.js` — 4th tab "Settings" (admin-only), instantiates
  `window.ReticulumSettingsTab` in `mount()`, forwards `show()`/`hide()`.
- `plugin.toml` — settings-tab script added to `[frontend].scripts`.
- Tests: `test_systemctl.py` (**new**, 2), `test_state.py` +4 (set_config /
  persist-merge), loader test asserts `/api/config` prefix registered too.

**Route shadowing during coexistence** (same as Phase 1): core's
`reticulum_config_routes` (in `_BUILTIN_ROUTERS`) wins `PUT /api/config/reticulum`
+ the restart route over the plugin's. Moot — the settings tab is dormant until
Phase 4, and core's routes are deleted at the cutover, so the plugin's win then.

Verified: manifest parses (3 scripts), `node --check` all 3 JS, py compile,
89 passed / 6 skipped, ruff clean.

### Phase 2 — plugin frontend (coexists)

**Current page UI to preserve on the port** (screenshot 2026-09-06):
- **Topbar pill:** `RETICULUM · 5771b31b… · 10306 peers` (own-hash prefix + peer count)
- **Page header:** `You: <full own hash>` + `Announce now` button (→ `POST /api/reticulum/announce`) + `Refresh` button
- **5 stat cards:** STATUS (`Running`), KNOWN PEERS (`10307`), PEOPLE (`7605`
  = `lxmf.delivery` count), INFRASTRUCTURE (`2702` = `lxmf.propagation` +
  `nomadnetwork.node`), CONVERSATIONS (`3` = distinct reticulum threads)
- **Tabs:** PEERS / MESSAGES / SEND
  - PEERS table cols: `LAST SEEN` · `DISPLAY NAME` · `DESTINATION` (hash, amber monospace) · `ASPECT` (badge — `lxmf.propagation` + `lxmf.delivery` cyan, `nomadnetwork.node` amber) · `FIRST SEEN`; client-side `RT_PEER_LIMIT = 100` + "Show all"
  - MESSAGES table cols: `LAST MESSAGE` · `PEER` · `PREVIEW` · `UNREAD` (right-aligned). Reuses `/api/messages/conversations` filtered to `protocol==='reticulum'`
  - SEND (admin-only): `PEER` label → "Search by name" filter input above a `<select>` dropdown of known peers (`Arty [wardrive]` etc) → `MESSAGE` label → "Message text" input → yellow `Send message` button

| New plugin file | From | Conversion |
|---|---|---|
| `frontend/reticulum_panel.js` | `frontend/js/reticulum_panel.js` | `window.registerSidebarPage({route:'reticulum', make})`, root-scoped (`this._root.querySelector`), identity from `window.meshpointIdentity`, plain `fetch()` |
| `frontend/reticulum_topbar_chip.js` | `frontend/topbar/topbar_reticulum_chip.js` | `window.registerTopbarChip({id:'reticulum', make})`, self-polls `/api/reticulum/status` (it already self-polls today — closest existing precedent, see PLUGINS.md topbar section) |
| `frontend/reticulum_settings_tab.js` | `frontend/js/configuration/reticulum_config_card.js` | Settings tab on the plugin's own page; core `Configuration → Reticulum` nav+card deleted Phase 5 |
| `frontend/reticulum_panel.css` | extract if needed | |

### Phase 3 — chat send path (option 1) — ✅ DONE

- `frontend/js/messaging.js`: `_onSendMessage()` early-returns to new
  `_sendReticulumMessage(text, convo)` when `convo.protocol === 'reticulum'` —
  POSTs `{destination_hash: convo.node_id, text}` to `/api/reticulum/send`
  (returns `{id,status}` / `{detail}`), same optimistic-bubble + status flow.
  `messaging_chat.js` / `messaging_contacts.js` needed no change (badges only).
- Conversation list/history unchanged (shared `messages` table).
- Core `messages.py` `protocol=='reticulum'` branch + `_reticulum_service`
  global LEFT in place as a fallback; `tests/test_messages_reticulum_send.py`
  too — both deleted at Phase 4.
- **Live now:** core already serves `/api/reticulum/send` (its
  `reticulum_routes.init_routes` runs whenever `config.reticulum.enabled`), so
  the reroute works immediately and keeps working after the plugin takes over.

### Phase 4 + 5 — core deleted — ✅ DONE (code); awaiting Pi flip

**Deleted:** `src/reticulum/` (whole dir), `src/api/routes/reticulum_routes.py`,
`reticulum_config_routes.py`, `src/storage/reticulum_peer_repository.py`,
`tests/test_messages_reticulum_send.py`. `scripts/clear_reticulum_packets.py`
→ `plugins/apps/reticulum/`.

**Edited:**
- `server.py`: dropped the `LxmfService`/`ReticulumPeerRepository` imports, the
  `_reticulum_service` global + lifespan start/stop, 2 `_BUILTIN_ROUTERS`
  entries (→ 49), the `_init_routes`/`messages.init_routes` reticulum params.
- `messages.py`: dropped `LxmfService` import, `_reticulum_service` global +
  param, the `protocol == "reticulum"` branch (frontend hits `/api/reticulum/send`).
- `config_enrichment.py`: dropped `base["reticulum"]`.
- `config.py`: dropped `ReticulumConfig`, `AppConfig.reticulum`, the section_map
  entry. (`config/default.yaml` never had a `reticulum:` block — nothing to remove.)
- **AttributeError trap caught:** `rnode_firmware_routes.py`'s `_rnsd_owns_port()`
  read `_config.reticulum.rnode_serial_port` → new `_rnsd_configured_port()`
  helper reads `_config.plugins.get("reticulum", {})`. Also `identity_routes.py`
  `_ADMIN_SECTIONS` lost `"configuration.reticulum"`.
- `scripts/write_rnsd_config.py`: `cfg.reticulum.*` → `cfg.plugins["reticulum"]`
  dict with a local `_DEFAULTS` fallback.
- Frontend: deleted `reticulum_panel.js`, `topbar_reticulum_chip.js`,
  `configuration/reticulum_config_card.js`; `index.html` lost 3 `<script>` tags
  + the `#/reticulum` nav `<li>` + `#/configuration/reticulum` subitem + 2
  `<section>`s + `#topbar-reticulum-group`; `app.js` lost `_bootReticulumPanel`
  + 3 route-list/command-palette entries; `topbar_controller.js` lost the
  `TopbarReticulumChip` construct + `setReticulum` call; `configuration_panel.js`
  lost the `section === 'reticulum'` branch.

**Kept (verified):** `reticulum_peers` table in `database.py`;
`rnode_firmware_routes.py` + `reticulum_companion_firmware_routes.py` + both
cards + their `configuration_panel.js` firmware-page slots; `frontend/css/
lorawan.css`'s `[data-section="reticulum"]` + `topbar.css`'s `.topbar-reticulum`
(the plugin's page/chip still use both); `sidebar_plugin_registry.js`'s
`reticulum:` icon glyph; `scripts/rnsd.service`.

**Tests:** `test_create_app_routers.py` 51 → 49; `test_messages_advert_route.py`
dropped a `_reticulum_service` reset line. `TestShippedReticulumPlugin` stays
`@skipUnless(_HAS_FASTAPI)`. 135 passed / 12 skipped on the Mac subset.

**Hardening (same commit), motivated by the Pi flip:** `service_registry.start_all`
now wraps each service's `build`/`wire`/`start` in try/except -- a failure is
logged + skipped, meshpoint starts normally. The Pi flip hit `RNS.Reticulum()`
→ `[Errno 98] Address already in use` when meshpoint started a beat before rnsd
finished; the exception propagated through the lifespan and crash-looped
(`Meshpoint started` x3) until rnsd was up. Now it degrades gracefully. +2 tests.

---

## Migration diff for the Pi (Phase 4 flip)

In `local.yaml`: **delete the top-level `reticulum:` block** and add its
contents under `plugins:` as `reticulum:` with `enabled: true`. The user's
current real block:

```yaml
# DELETE this top-level block:
reticulum:
  enabled: true
  rnode_serial_port: /dev/serial/by-path/platform-fd500000.pcie-pci-0000:01:00.0-usb-0:1.1:1.0
  rnode_frequency_hz: 869463000
  rnode_bandwidth_hz: 125000
  rnode_tx_power: 20
  rnode_spreading_factor: 8
  rnode_coding_rate: 5
  backbone_host: node.reticulumnet.nl
  backbone_port: 4242
  display_name: PD2EMC Meshpoint

# ADD under plugins: (alongside hello-service etc)
plugins:
  reticulum:
    enabled: true
    display_name: PD2EMC Meshpoint
    rnode_serial_port: /dev/serial/by-path/platform-fd500000.pcie-pci-0000:01:00.0-usb-0:1.1:1.0
    rnode_frequency_hz: 869463000
    rnode_bandwidth_hz: 125000
    rnode_tx_power: 20
    rnode_spreading_factor: 8
    rnode_coding_rate: 5
    backbone_host: node.reticulumnet.nl
    backbone_port: 4242
```

Storage-path keys (`reticulum_config_dir`/`identity_path`/`lxmf_storage_dir`)
were on defaults → the plugin defaults match → same identity, no need to copy.
`sudo systemctl restart meshpoint` (and, since rnsd's config generator now
reads the new path, `sudo systemctl restart rnsd` so it picks up the RNode
keys from their new location).

Verify: `#/reticulum` page loads with the 4th **Settings** tab, topbar pill
shows `5771b31b… · N peers`, a reply from the Messages page round-trips,
Settings tab loads current values + saves, `Restart rnsd` works, peer count
keeps climbing.

### Phase 4 — live-verify on the Pi (gate before any deletion)

**Core + plugin CANNOT both run** — two `RNS.Reticulum()` attachments, two
LXMF routers, two delivery identities announcing = collision. So the enable
step is **atomic**: one `local.yaml` edit sets `reticulum.enabled: false`
**and** `plugins.reticulum.enabled: true`, one restart. (Less "coexist"
than DAPNET, where the plugin could run with no devices configured.)

Verify (screenshots): Peers tab populates from announces, Messages tab
shows history, send round-trips to meshchat, **topbar pill** shows own
address + peer count, Settings tab saves + `restart rnsd` works.

Migration diff handed to user: `reticulum:` block → `plugins.reticulum:`
(enabled, display_name, reticulum_config_dir, identity_path,
lxmf_storage_dir, rnode_serial_port, rnode_frequency_hz, rnode_bandwidth_hz,
rnode_tx_power, rnode_spreading_factor, rnode_coding_rate, backbone_host,
backbone_port) — their real values, not defaults.

### Phase 5 — delete core (only after Phase 4 passes)

See the inventory table's "Fate" column. Key traps from the DAPNET
experience:
- **AttributeError trap:** after deleting `ReticulumConfig`, grep
  `\.reticulum\b` across `src/` specifically (not the string
  `"reticulum"`) — a surviving `cfg.reticulum.x` crashes every
  `GET /api/config`. `config_enrichment.py` is the known one.
- **`config/default.yaml`** — delete the `reticulum:` block too, or a
  test fails with an "unknown config key" warning.
- `_BUILTIN_ROUTERS` count drops by 2.

### Phase 6 — docs

- `docs/CHANGELOG.md` — under `### v0.8.1` (matches `src/version.py` 0.8.1),
  ⚠️ breaking-change callout for the config move. Verify parse:
  `ChangelogParser.parse_file(Path('docs/CHANGELOG.md'))`.
- `docs/PLUGINS.md` — new "Adding a background service (`"service"`)"
  section, "eight seams" → nine, trim Current-limitations.
- `docs/CONFIGURATION.md` — `reticulum:` → `plugins.reticulum:`
- `README.md` — plugin list + "What's Different" + Local API table
- `docs/API-ENDPOINTS.md` — Reticulum routes under a "(plugin)" heading
- `plugins/apps/reticulum/README.md` — new
- `memory/project_m1_meshpoint.md` — session log

---

## Expected commit sequence

1. `feat: generic "service" plugin capability — plugins can register a lifespan-managed async background service`
2. `feat: reticulum plugin scaffold (backend service + routes + peer repo), disabled by default, core still authoritative`
3. `feat: reticulum plugin frontend — sidebar page, topbar pill, settings tab`
4. `feat: main Messages page routes reticulum sends to the plugin's /api/reticulum/send`
5. `refactor: delete core reticulum service/routes/config/frontend now that the plugin is live-verified`
6. docs / changelog / memory
