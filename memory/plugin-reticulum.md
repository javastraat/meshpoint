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

---

## 2026-09-07 — plugin `[deps] check` (not extraction work, but reticulum-owned)

Reticulum ships the first `[deps] check = "check.sh"` script (new optional
manifest key, see `memory/project_m1_meshpoint.md` for the whole feature).
`plugins/apps/reticulum/check.sh` — unprivileged probe, exit 0 = deps in
place: `venv/bin/python3 -c "import LXMF"` + `/etc/systemd/system/rnsd.service`
exists + `systemctl is-enabled rnsd`. Mirror of `setup.sh`'s own idempotency
checks minus the installing. Settings → Plugins shows "⚠ Setup needed" /
"✓ Dependencies installed" on the Reticulum row from this, with a Re-check
button (`POST /api/plugins/reticulum/check`). If check.sh ever needs to test
something new, keep it sudo-free — the loader runs it as the `meshpoint`
service account at boot.

---

## 2026-09-07 — "Pages" tab: in-dashboard .mu editor for hosted nodes

User asked for a way to edit `index.mu` etc. without SSH. Built as a 6th
tab on the Reticulum page (NOT a hook plugin — the page has no
registerPageHook and the editor is inseparable from node hosting).

- **`backend/node_pages.py`** (new, FastAPI-free): `validate_name`
  (`^[a-z0-9][a-z0-9._-]{0,62}\.mu$`, no `..`, `RESERVED_NAMES =
  {info.mu, nodes.mu}`), `list_pages` (index.mu first, always listed),
  `read_page`/`write_page` (128 KB cap, `chmod 0o644` — never +x)/
  `delete_page`, `sample_index()` (reads `sample-pages/index.mu`).
- **`NomadNode.reload_pages()`** — re-runs `_register_handlers()`. Editing
  existing file content was ALREADY live (`_make_file_server` does
  `read_bytes()` per request); only *new* files need this. Deleted files
  leave a stale handler returning "Not found" (RNS has no unregister) —
  harmless, restart clears it.
- **`LxmfService.reload_node_pages() -> bool`** — calls it if node running.
- **`nomad_routes.py`**: `GET /pages`, `GET /sample-page`,
  `GET/PUT/DELETE /pages/{name}` (all admin). PUT returns
  `{saved, page, served}` (`served` = node was reloaded).
- **`reticulum_node_pages_tab.js`** (new, `window.ReticulumNodePagesTab`):
  file list + New/Delete, textarea, live preview via
  `new window.MicronParser(true).parseToHtml()` (same as Browse tab, into
  `.rt-nomad__page`), Load-sample button. Added to `plugin.toml` scripts.
- **`reticulum_panel.js`**: `data-rt-tab="pages"` button (hidden until
  `_syncPagesTab()` sees `/status`.node), view div, lazy tab instance,
  `_activateSubTab`/`hide`/`_setTab` guards, restores from localStorage
  optimistically then bounces if not hosting.
- **`reticulum.css`**: `.rt-pages*` two-column layout (list + editor/preview
  grid, stacks <900px).
- Tests: `test_node_pages.py` (17, pure), `test_nomad_routes.py` (6,
  fastapi-gated → skip on Mac), `test_nomad_node.py` +1 (reload no-op).
  54 reticulum backend tests pass / 6 skip on Mac. ruff clean.
- Docs: CHANGELOG v0.8.1 (+1 → 87), plugin README + CONFIGURATION.md node
  sections.
- **NOT committed, NOT Pi-tested.** Pi test: enable node_enabled, open
  Pages tab, edit index.mu, Save, browse `<hash>:/page/index.mu` from the
  Browse tab → should show the edit with no restart. Create a new
  `about.mu`, link to it from index.mu, confirm it serves.

**LIVE on the SenseCap + browsed from ti-meshpoint (screenshots)**: Pages tab
edits index.mu with working live preview, Save serves it immediately, and
`359a563e...:/page/index.mu` renders correctly when browsed from another
Reticulum node. Feature confirmed end to end.
FOUND + FIXED a bug in `sample-pages/index.mu`: the Contact block used
`` `Foperator`` etc. -- `` `F`` consumes the next 3 chars as a hex colour, so
"ope"/"loc"/"not" became a bad colour and the labels rendered "rator :" /
"ation :" / "es :". Now `` `F888operator`f : ...`` (valid grey). Header note
updated to point at the Pages tab / Load sample; hardware line ->
"<your hardware>". Anyone who used the old sample must re-Load-sample + Save
(or hand-fix those 3 lines). Still uncommitted.

**Light-mode fix (same uncommitted batch)**: `.rt-pages__src` textarea was
`background: var(--bg, #111)` (--bg undefined -> always #111 dark) +
`color: inherit` -> dark-on-dark, invisible editor text in light mode. Now
explicit `background: var(--bg-elevated, #1a1a1a)` + `color: #d7dae0` +
`caret-color` + `::placeholder` -- editor is a dark "terminal" surface
matching the preview pane in every theme. (`--bg-elevated` has no light
value either but the fg is now explicit so it's fine.) User confirmed the
sample Contact-block fix renders correctly ("operator : YOURCALL").

**Browse tab: node picker filter + favourites (uncommitted, same session).**
User: the nomadnetwork.node list is huge. Added to `reticulum_nomad.js`:
- `<input type=search data-nomad-search>` -> `this._filter` -> `_renderNodeOptions()`
  (matches display_name OR hash, case-insensitive).
- `_renderNodeOptions()` rebuilds the `<select>` with `<optgroup label="★ Favourites">`
  then `<optgroup label="Recent nodes">`, filtered; favourites merged in even
  if aged off the 300-cap `/nodes` response ("no match" disabled option when
  the recent list filters to empty).
- Favourites in `localStorage` key `meshpoint.rtNomadFavourites` = `[{hash,name}]`.
  `_favourites/_saveFavourites/_isFavourite/_toggleFavourite/_syncFavBtn`.
- `☆`/`★` button (`data-nomad-fav`, `.rt-nomad__fav`) toggles the *currently
  open* node (`this._currentHash`, set in `_fetch` success); disabled until a
  node is open. `.rt-nomad__fav--on` = amber star.
- CSS: `.rt-nomad__search` flex 0 1 170px, narrowed addr to 300, fav button.
- No backend change (list endpoint already returns name+hash; favs client-side).
- Docs: CHANGELOG (+1 -> 88), plugin README Browse section.
- No JS tests (plugin frontend has none); `node --check` clean.

---

## 2026-09-07 — info.mu: Host + Mesh sections, git-derived GitHub URL (uncommitted)

- **`backend/host_stats.py`** (new, FastAPI-free): `read_host()` -> `{pi_model,
  cpu_temp_c, load_1m, mem_used_mb, mem_total_mb, disk_free_gb, disk_total_gb}`,
  every value None-safe. Plain `/proc/device-tree/model`, `/sys/class/thermal`,
  `os.getloadavg`, `/proc/meminfo`, `shutil.disk_usage` -- NO psutil. On the Mac:
  load+disk work, rest None.
- **`__init__.py` `node_stats()`**: adds `hardware` (from
  `context.config.device.hardware_description`), `conversations`
  (`MessageRepository.get_conversations()` filtered to protocol=='reticulum'),
  `host` (host_stats), `mesh` ({packets_total, packets_24h, by_protocol} from
  `context.pipeline.packet_repo.get_count / get_count_since / get_protocol_distribution`).
  Mesh + conversation queries wrapped try/except -> info.mu degrades, never 500s.
- **git-derived URL**: `from src.remote.repo_source import resolve_owner_repo`
  (ALREADY EXISTS -- reads `.git/config` origin, no git subprocess, falls back
  to `KMX415/meshpoint`). `project_url = f"https://github.com/{resolve_owner_repo()}"`
  threaded __init__ -> LxmfService(project_url=) -> NomadNode(project_url=).
  Replaces hardcoded `javastraat/meshpoint` in `_serve_index` + `_serve_info`.
  `_project_label()` strips scheme for the link label.
- **`_serve_info`**: `row(label,value)` helper (`f"{label:<22}: {value}"`),
  `>Host` block (only rows present), `>Mesh activity` block (packets + per-proto
  sorted desc, thousands-separated, 2-space indent -- Micron preserves leading
  spaces). AGGREGATE ONLY, no node-level data (page is public on the mesh).
- **`_STATS_REFRESH_S` 300 -> 60**.
- **`sample-pages/index.mu`**: header comment + Links label updated to say
  info.mu shows host/mesh + git-follows-origin. (User already added the figlet
  MESHPOINT banner to the sample.)
- Tests: `test_host_stats.py` (4, pure + mock OSError path), `test_nomad_node.py`
  +4 (host/mesh sections, forker project_url, KMX415 default). 61 reticulum
  backend pass / 6 skip. ruff + changelog(89) clean.
- **NOT committed, NOT Pi-tested.** Pi: browse `<hash>:/page/info.mu` -> should
  show real board/temp/load/disk + packet counts; GitHub link = whatever the
  device's `git remote get-url origin` resolves to (KMX415 if tracking upstream).

**Topbar pill: freq instead of peer count (uncommitted, user request).**
- `routes.py` GET /status: new `radio` block = `{rf, frequency_hz, backbone}`.
  `rf` = `rnode_enabled AND rnode_serial_port.strip()` (blank port = RF off,
  the established implicit switch). `frequency_hz` only when `rf`.
- `reticulum_topbar_chip.js` `_applyStatus`: freq slot shows
  `{(frequency_hz/1e6).toFixed(3)} MHz` when rf, peers when backbone-only,
  `--` otherwise; falls back to peers if `status.radio`
  missing (old backend). Peer count -> chip `.title` hover
  ("Reticulum · N peers heard"). Matches Meshtastic/MeshCore/Pager chips.
- Tests: `test_status_route.py` (3, fastapi-gated). Docs: CHANGELOG (90),
  README topbar row. Clean separation from the info.mu batch (only shared
  file would be routes.py, which info.mu didn't touch).

**Topbar pill refinement (user):** backbone-only shows PEER COUNT in the
freq slot (not "TCP" -- peers is the meaningful number for a node with no
radio). Logic: `rf && frequency_hz` -> "{MHz}", else -> "{N} peers".
Hover title: "Reticulum · {RNode radio|TCP backbone} · {N} peers heard".

**Pages-tab formatting toolbar (uncommitted).** Inspired by fr33n0w/
micron-composer (NC-OSL licensed -> ideas only, no code borrowed; our
MicronParser is already the reticulum-meshchat MIT port). Added to
`reticulum_node_pages_tab.js`: `.rt-pages__toolbar` row above the split,
buttons `data-mu=bold|underline|italic|reset|center|color|h1|h2|divider|
link`. `_insertMarkup(kind, colorHex)`: `wrap(open,close)` is
selection-aware (`` `!sel`! ``, `` `Fxxx sel`f ``, `` `c sel `a ``);
`linePrefix` for h1/h2; divider self-newlines; link uses two
`window.prompt`s. `_to3hex('#rrggbb')` -> Micron 3-hex.
`_setToolbarEnabled(on)` toggles with `_srcEl.disabled` (open/new/delete).
Native `<input type=color>` default `#3388ff`. CSS `.rt-pages__toolbar*`.
No backend/endpoint. CHANGELOG 91, README + file docstring updated.

**Toolbar parity pass (uncommitted).** Compared to fr33n0w/micron-composer,
added: H3, bg colour swatch (`data-mu-color="bg"` -> `` `Bxxx`b ``), left/
right align (`` `l ``/`` `r `` wrapping `` `a ``), Field (`` `<name`> ``),
Checkbox (`` `<?|slug|1`Label> ``), Radio (`` `<^|choice|slug`Label> ``),
emoji picker + ASCII/box-drawing palette (both `_buildCharMenu(sel, chars)`
dropdowns, one open at a time, close-on-outside-click). `_insertText(str)`
for plain-char insert. NOT copied: "Magic" = micron-composer's experimental
AI page-beautify (needs an LLM call -> doesn't fit an offline edge device).
Field/checkbox/radio widgets render but only submit to an *executable*
NomadNet page -- noted in docstring/README/CHANGELOG since our node serves
plain files.

**+ ? cheat-sheet popover (same batch).** Toolbar `?` button -> `.rt-pages__help`
popover (anchored right, `min(380px,90vw)`), a `<dl>` of Micron codes built by
`_helpHtml()`, closes on outside-click / Escape. Stays enabled with no page
open (`_setToolbarEnabled` excludes `[data-pg-help-toggle]`). Emoji + ASCII +
help are all "one open at a time". The note line spells out the
"centre aligns each line on its own -> multi-line ASCII must be left-aligned"
gotcha from earlier this session.
Micron-composer parity now: everything except "Magic" (AI beautify).

**Browse address bar (uncommitted).** User: want to reach info.mu on a node
even when unlinked. Turned out the address bar ALREADY pre-fills
`<hash>:/page/index.mu` (from `_fetch`), but `_goFromAddr` never passed
`this._currentHash` to `_splitAddr`, so the `:/page/x.mu` / `/page/x.mu`
current-node shortcuts errored ("must be <hash>:/page/path.mu"). Fixed:
`_splitAddr(raw, this._currentHash)`. Also widened `.rt-nomad__addr`
(flex 3 1 280px + min-width:0; search/select now `flex: 1 1` too) so the
whole address is editable. User said NO to an "info" quick button --
removed it, edit-the-path is the workflow.

**Node-picker width fix (same batch, LIVE-VERIFIED).** One node name ~140
chars ("ToReticuLoki – ...") blew the native <select> popup to full-screen
(CSS can't size a native popup -> only the option text drives it).
`_renderNodeOptions` `cap(s)` truncates the visible label to 46 chars + '…',
full name kept in the option `title` + still filters. CSS: `.rt-nomad__nodes`
`flex: 0 1 260px; max-width: 300px`. User confirmed dropdown now sane width
("much better") + the `:/page/x.mu` address-bar fix worked to check a
friend's info.mu. Browse batch (addr bar + dropdown cap) done, uncommitted.

**Figlet banner in generated index.mu — LIVE-VERIFIED.** `_MESHPOINT_BANNER`
(figlet "standard", 53 cols, raw tuple of raw-strings, no `_esc`) replaces the
`c'd one-liner in `_serve_index`; left-aligned, green node name directly under.
Browsed PD2EMC's default page from ti-meshpoint (screenshot) — renders clean.
Only affects nodes WITHOUT a custom index.mu. Uncommitted.

**index.mu header polish (uncommitted):** `Node    : <name>` (grey label +
green bold name) and `Address : <hash>` (nomadnetwork.node destination hex
via `_address_hex()` -> `self._destination.hash.hex()`, gated so tests /
pre-start skip it). Dropped "a Meshpoint node" subtitle. Blurb's stale
"message it over LXMF on the same hash" -> notes LXMF is a separate aspect
hash on the same identity (only when the Address line shows).

**Pages-tab confirms use the styled modal (uncommitted).** Delete /
discard-changes / load-sample were raw `window.confirm`. New `_confirm(opts)`
helper on `ReticulumNodePagesTab` -> `window.confirmModal({label,description})`
(the dashboard's DangerousModal, loaded globally via index.html), native
fallback. (User also hand-edited the index.mu blurb "-- it captures" ->
". It captures"; test assertion updated to match.)

**sample-bbs-techinc/ (uncommitted).** User wants a real deployable NomadNet
"BBS" for the TechInc node. New folder `plugins/apps/reticulum/sample-bbs-techinc/`:
index.mu (figlet splash + numbered main menu), techinc.mu, mesh.mu,
bulletins.mu, links.mu (all cross-linked `:/page/x.mu`), + README.md deploy
guide. All 5 pass the MicronParser via a DOM-shim (/tmp/micron_test.js pattern).
Real TechInc facts from web search (wiki.techinc.nl is behind Anubis): Louwesweg 1
1066 EA Amsterdam / ACTA building, Wednesday 19:30 open evening, member-funded
association, network@techinc.nl. `[EDIT]` markers everywhere for adaptation.
Micron notes baked into the README (`c per-line centring, 3-hex `F, no backticks
in art). CHANGELOG + plugin README updated.

---

## 2026-09-07 — SpaceAPI "is the space open" for hosted nodes (uncommitted)

User wanted live hackerspace status on the BBS. Wiki (wiki.techinc.nl/Events)
is behind Anubis -> no scraping. SpaceAPI works: TechInc =
`https://techinc.nl/space/spacestate.json` (v0.13, state.open + top-level
open, no events feed). Built (Settings-tab visibility, user picked option 1):
- **`backend/spaceapi.py`** (new): `fetch(url) -> dict|None` via urllib (8s,
  256KB cap). Normalises 0.13/13/14/15 (`state.open` vs top-level `open`,
  `state.lastchange` vs top). De-obfuscates `a AT b DOT c`. Returns
  `{space, open(bool|None), message, lastchange, address, url, irc, email, ml}`.
- **`state.py`**: `node_spaceapi_url: ""` in _DEFAULTS + `node_config()["spaceapi_url"]`.
- **`nomad_node.py`**: `NomadNode(spaceapi_url=)`, `_spaceapi` last-good cache.
  **LAZY refresh (no timer)** — one priming `_refresh_spaceapi()` in `start()`,
  then `_spaceapi_maybe_refresh()` called from the RNS request thread by
  `_serve_spacestate` + the `{spacestate}` path in `_make_file_server`: if cache
  empty or older than `_SPACEAPI_TTL_S` (120s) and not already `_spaceapi_refreshing`,
  `self._loop.call_soon_threadsafe(... create_task(_refresh_spaceapi()))` and
  serve cache immediately (never blocks the response on the 8s urllib call).
  `_refresh_spaceapi` stamps `_spaceapi_fetched_at` in `finally` even on failure
  (flap backoff). `self._loop` set in `start()`, cleared in `stop()`. An unbrowsed
  node never hits the endpoint.
  `_spaceapi_word()` -> `` `F0a0`!OPEN`!`f `` / `` `Fd44`!CLOSED`!`f `` /
  `` `F888unknown`f ``. `_serve_spacestate` generated page (registered only
  when url set, excluded from operator .mu loop like info/nodes). `_make_file_server`
  does a `{spacestate}` -> word substitution on operator .mu pages (not /file/,
  only when url set). `_page_count` +1. `_fmt_ago()` helper.
- Threaded: `__init__` -> `LxmfService(spaceapi_url=)` -> `NomadNode`.
- **`config_routes.py`**: `node_spaceapi_url` field + `_spaceapi_url_ok` validator
  (blank or http(s)) + write dict.
- **`reticulum_settings_tab.js`**: "SpaceAPI URL (optional)" input in node-hosting
  fieldset, `data-rt-node-spaceapi`, wired render/_onSubmit.
- Tests: `test_spaceapi.py` (6), `test_nomad_node.py` +6 (serve + token +
  gating + lazy-refresh scheduled-when-stale / not-when-fresh). 74 reticulum
  backend pass.
- Docs: CHANGELOG (92), plugin README + CONFIGURATION.md node blocks.
- BBS: `index.mu` gets "The space is right now: {spacestate}" + menu item
  "Space status" -> :/page/spacestate.mu; sample-bbs README widget section.
- NOTE the `{spacestate}` token is substituted only when the NODE serves the
  page -- the dashboard Pages-tab preview shows the raw token.

SpaceAPI lazy-refresh + BBS [EDIT]-marker removal + techinc.mu "Contact us"
block: committed 2026-09-07 (aeb6e72e / prior).

---

## 2026-09-07 — Events / iCal agenda for hosted nodes (uncommitted)

User found `https://wiki.techinc.nl/TechInc.ical` (SMW iCalendar export; 302
-> Special:Ask, urllib follows it). Floating times, no TZID/DESCRIPTION/RRULE,
sorted DTSTART desc, limit=100. Built to mirror SpaceAPI exactly:
- **`backend/ical.py`** (new): `fetch(url, *, now=None) -> list[dict]|None`.
  urllib 8s / 512KB. `_unfold` (RFC5545 space-continuation), `_vevents`,
  `_parse_vevent` (needs DTSTART+SUMMARY), `_parse_dt` (YYYYMMDD date-only /
  `VALUE=DATE`; `...THHMMSS[Z]` -> naive, `Z` converted UTC->local via
  `.astimezone()`), `_untext` (`\, \; \n \\`). Drops past events (end or
  start < now), sorts soonest-first, caps `_MAX_EVENTS=12`. `[]` = valid
  "nothing scheduled" (only fetch/decode failure -> None). `format_when(ev)`
  -> `Wed 9 Sep  19:00` / `Sun 20 Sep` (all-day).
- **`nomad_node.py`**: `NomadNode(events_ical_url=)`, `_events` list +
  `_events_fetched_at` + `_events_refreshing`. `_events_maybe_refresh()` /
  `_refresh_events()` = copy of the spaceapi lazy pattern, `_EVENTS_TTL_S=900`.
  `start()` primes. `_serve_events` generated page (registered + `_page_count`
  +1 only when url set). NB uses `_events_fetched_at>0` for the "fetched?"
  check, not `self._events` (empty list is legit). New module-level
  `_GENERATED_PAGES` frozenset (index/info/nodes/spacestate/events) replaces
  the two inline name tuples in `_register_handlers` + `_page_count`.
- **`state.py`** `node_events_ical_url` + `node_config()["events_ical_url"]`.
  **`config_routes.py`**: field + validator renamed `_spaceapi_url_ok` ->
  `_feed_url_ok` (now covers both url keys) + write dict.
  **`lxmf_service.py`** / **`__init__.py`**: threaded through.
  **`reticulum_settings_tab.js`**: "Events iCal URL (optional)" input
  `data-rt-node-events` after the spaceapi one; wired render/_onSubmit.
- **BBS**: `git rm sample-bbs-techinc/bulletins.mu`; `index.mu` menu item 4
  -> "Upcoming events" `:/page/events.mu`; `mesh.mu` footer -> "Upcoming
  events >>". README "Live bits" section rewritten for both URLs.
- Tests: `test_ical.py` (9), `test_nomad_node.py` +5. 88 reticulum backend.
- KNOWN NIT: feed is dense with the weekly "Social YYYY-MM-DD"; they crowd
  out real events in the 12-item window. No dedup done (fragile) -- revisit
  if user asks.

---

## 2026-09-07 — Activity tab + DM notifications (backlog items 11 & 12, uncommitted)

- **`backend/notify.py`** (new): `post(url, *, title, body) -> bool`. urllib
  POST, 8s, body capped 3072B, `Title` header sanitised to ASCII/printable
  (ntfy titles must be latin-1 single-line). Returns True on 2xx, never raises.
  ntfy-style: message text = body, sender = Title. Works for any plain-text
  webhook.
- **`lxmf_service.py`**:
  - `_ROSTER_ASPECTS` = the old 3; `_ANNOUNCE_ASPECTS` = `(*_ROSTER, "call.audio")`.
    `call.audio` is registered for the stream but NOT written to `reticulum_peers`
    (would pad the roster with every Sideband/MeshChat user).
  - `_announce_log` = `deque(maxlen=_ANNOUNCE_LOG_MAX=200)`. `_handle_announce`
    now: build `entry {ts,destination_hash,display_name,aspect}`, append, always
    `broadcast("reticulum_announce", entry)`; then if roster aspect →
    `record_announce` + `broadcast("reticulum_peer", ...)` (unchanged shape).
    `announce_log()` returns `list(reversed(...))` (newest first).
  - `notify_url` ctor param + `self._notify_url`. `_handle_inbound_message`:
    after the non-duplicate ws broadcast, `if self._notify_url: self._spawn(self._notify_inbound(name or source_hex[:16], text))`.
    `_notify_inbound` truncates to 240 (`...`), `asyncio.to_thread(notify.post)`,
    swallows errors. `_spawn` = fire-and-forget with a `self._bg_tasks` strong-ref set.
- **`routes.py`**: `GET /api/reticulum/announces` -> `_service.announce_log()` (503 if no service).
- **`state.py`**: `notify_url` in `_DEFAULTS` + `notify_url()` accessor (top-level,
  not node_config -- the inbox is always on). **`config_routes.py`**: `notify_url`
  field, added to `_feed_url_ok` validator, write dict. **`__init__.py`**:
  `notify_url=state.notify_url()`.
- **`reticulum_panel.js`**: new "Activity" tab (`data-rt-tab="announces"`, no
  admin gate), between Peers and Messages. `_announces` array,
  `_loadAnnounces`/`_renderAnnounces`, `_onWsAnnounce(entry)` unshift+cap 200 +
  re-render if active. `_load()` also refreshes announces when that tab is
  active. Tab restore allows 'announces'.
  `RT_ASPECT_BADGES['call.audio']='mt-badge--routing'`. `nomadnetwork.node`
  rows get the same `data-rt-browse` -> `browseNode()` button as `_renderPeers`.
- **`reticulum_settings_tab.js`**: new "Message notifications" fieldset,
  `data-rt-notify-url`, wired render/_onSubmit.
- Tests: `test_notify.py` (6), `test_lxmf_service.py` +7 (TestAnnounceLog x4,
  TestInboundNotify x3 with `_FakePeerRepo`/`_FakeWs`), `test_announces_route.py` (2).
  101 reticulum tests pass.
- **CI FIX (same session)**: `test_spacestate_lazy_refresh_scheduled_when_stale`
  set `_spaceapi_fetched_at = 0.0` -- on a freshly-booted CI runner
  `time.monotonic()` can be < `_SPACEAPI_TTL_S` (120), so `age` wasn't "stale".
  Now `time.monotonic() - 10_000`. (The events equivalent uses `0.0` but its
  guard is `if self._events_fetched_at and ...` so 0.0 is safely falsy.)

---

## 2026-09-07 — LXMF propagation node (backlog item, server side, uncommitted)

The box can now ALSO be a store-and-forward relay. THREE aspects on one
identity, all concurrent: `lxmf.delivery` (inbox), `nomadnetwork.node`
(pages, if `node_enabled`), `lxmf.propagation` (relay, if
`propagation_enabled`). Propagation dest is a SEPARATE hash.
- **`state.py`**: `propagation_enabled` (False), `propagation_storage_limit_mb`
  (250) in `_DEFAULTS`; `propagation_config()` accessor.
- **`config_routes.py`**: `propagation_enabled` bool, `propagation_storage_limit_mb`
  `Field(250, ge=0, le=100_000)` + write dict.
- **`lxmf_service.py`**: `propagation_cfg` ctor param. `_PROPAGATION_ANNOUNCE_INTERVAL_S=21600`.
  `start()` -> `_start_propagation()` after `_source.announce()`, before node.
  `_start_propagation`: best-effort `router.set_message_storage_limit(megabytes=)`
  in its OWN try/except (not in every LXMF version, kw name has changed --
  must not block enabling); then `router.enable_propagation()` (fatal fail ->
  log + return); `_announce_propagation()` (`router.announce_propagation_node()`);
  `_pn_task = loop.create_task(_propagation_announce_loop())` (6h re-announce).
  `stop()` cancels `_pn_task`. `announce()` also re-announces PN if `_pn_task`.
  `propagation_address` prop -> `RNS.prettyhexrep(router.propagation_destination.hash)`
  (None-safe). `propagation_status()` -> None unless enabled+router, else
  `{enabled, address, storage_limit_mb, messages_held}` (held from
  `len(getattr(router,"propagation_entries",{}))`, best-effort).
- **`routes.py`**: `/status` gains `"propagation": _service.propagation_status()`.
- **`__init__.py`**: `propagation_cfg=state.propagation_config()`.
- **`reticulum_settings_tab.js`**: "Propagation node" fieldset (toggle
  `data-rt-prop-enabled` + `data-rt-prop-storage` MB + `data-rt-prop-status`
  line) between TCP-backbone and NomadNet-node fieldsets. `_loadPropagationStatus()`
  reads `/status`.propagation.
- API refs from reticulum-meshchat `meshchat.py` (LXMF is the same lib):
  `enable/disable_propagation()`, `announce_propagation_node()`,
  `propagation_destination.hexhash`, client side (NOT done): `set_outbound_propagation_node`,
  `request_messages_from_propagation_node`, `propagation_transfer_state/progress`.
- Tests: `test_state.py` +2, `test_lxmf_service.py` +5 (`_FakeRouter`),
  `test_status_route.py` +2. 108 reticulum tests.
- NOT done (client side): syncing FROM a preferred propagation node, transfer
  progress UI, PN peering. -> backlog "Propagation node polish".
- Pi verification needed: enable, restart, check Settings status line shows a
  PN address; from another node/Sideband set this hash as propagation node and
  send to an offline 3rd party, then bring them online and sync.

## 2026-09-09 — Contacts / petnames (new-build #1)

Operator-assigned names for peers. Local address book, never announced.

- `backend/contacts.py` — `ContactStore`: one JSON file
  (`data/reticulum/contacts.json`), atomic write (tmp + `os.replace`),
  lazy load-once cache, corrupt-file tolerant, skips malformed entries.
  `set(hash, petname, note, trusted)` validates (petname required + ≤64,
  note ≤280); `delete()`; `all()` returns copies. Stdlib only, no FastAPI.
- `backend/state.py` — `contacts_path()` = `Path(identity_path).parent /
  "contacts.json"` (follows a relocated data dir).
- `backend/routes.py` — `_contacts` global (set in `init_routes`, cleared
  in `reset_routes`). `GET /contacts` (viewer), `PUT`/`DELETE
  /contacts/{hash}` (admin). Blank petname on PUT == delete. `/peers` +
  `/announces` gain `petname`/`trusted` when a contact exists — announce
  rows are copied before annotating so a removal leaves no stale key.
- `frontend/reticulum_panel.js` — `this._contacts` map;
  `_peerLabel(hash, announced)`; petname used in Peers/Activity/Messages
  tables + Send `<select>` + Send search; `_saveContact`/`_deleteContact`.
- `frontend/reticulum_detail_panels.js` — drawer header petname +
  `.nd-header__sub` "announced as X"; editable **Contact** `.nd-section`
  (`_buildContactSection`: Name/Note inputs, "Mark as known" checkbox,
  Save/Remove, inline status); `_refreshHeaderName()` avoids a full
  re-render (keeps the open form). Announce modal Payload gets a
  "Contact" row.
- `frontend/reticulum.css` — `.nd-header__sub`, `.rt-trust`,
  `.rt-contact-form*`. The Name/Note inputs carry core's
  `.cfg-field__input` class (fixed a same-day dark-on-dark bug — the
  first cut used `#111`/`#eee` fallbacks assuming dark theme).
- Naming: feature is **Contacts** everywhere user-facing; `petname` is
  only the JSON/wire field name (Sideband/NomadNet's term), UI says
  "Name". User explicitly rejected "petname address book" wording.
- Display decision: petname wins in compact lists; "announced as X"
  sub-line + tooltip in detail views, flags on change. (NomadNet's
  approach, not Sideband's silent override.)
- Tests: `test_contacts.py` ×10 (Mac-runnable), `test_contacts_route.py`
  ×6 (FastAPI-gated; points `routes._contacts` at a tempdir). Plugin
  suite 169 passed, no regressions.
- NOT done: petnames in the core cross-protocol Messages page (would need
  a core change — the plugin's own Messages tab does resolve them).
- Pi verification: see `memory/reticulum_todo.md`.

## 2026-09-09 — Extra interfaces / Interface manager UI

`plugins.reticulum.extra_interfaces` = `[{name, type, enabled, ...}]`,
types TCPClient/TCPServer/UDP. `write_rnsd_config.py`
`_extra_interface_blocks()` (pure, tested; `load_config` deferred into
`main()`) emits `[[name]]` blocks via a new `{extra_block}` slot —
**never raises**, skips bad/reserved/dup/missing with a warning.
`config_routes.ExtraInterface` model (name + type-fields + port
validators, `to_stored()`); `ReticulumUpdate` gains the list, the
"at least one interface" rule counts an active extra, + a dup-name
validator. `state.extra_interfaces()`. Settings tab: add/remove row
editor with type-specific fields + outage-risk warning. Chose
structured over raw textarea (rnsd ExecStartPre crash = Reticulum
down). Not Pi-tested. Not offered: I2P, 2nd RNode, AutoInterface.

## 2026-09-09 — Contacts tab (address book)

New admin-only **Contacts** tab on the Reticulum page (between Send and
Browse). Backend was already complete — this is a frontend view over the
existing `/api/reticulum/contacts` CRUD:
- `reticulum_panel.js`: `_renderContacts` (inline-editable table: name +
  note `<input>`s, known checkbox, per-row Save/Remove reusing
  `_saveContact`/`_deleteContact`, + a Send/Browse link joined from the
  roster), `_handleAddContact` (paste hash + name — client-side hex
  check `^[0-9a-f]{8,64}$` even-length, tolerates `<hex>`/`:`),
  `_saveContactRow`, `_refreshContactSurfaces` (Peers/Send/Activity/
  Contacts/Messages all re-render after any contact change).
  `_saveContact` now surfaces the server's error detail in the toast.
- `contacts.py`: `looks_like_hash()` helper + `_clean_hash()`; `set`/
  `get`/`delete` reshape RNS display forms (`<hex>`/`aa:bb`) to the bare
  hex key so entries stay consistent — but stay lenient on length only
  (no hex *rejection* server-side; the test fixtures use short fake
  hashes, and a dead contact from a bad API call is harmless — the Add
  *form* does the strict check).
- `reticulum.css`: `.rt-contact-add`, `.rt-contact-cell`,
  `.rt-contact-announced`, `.rt-contact-actions`.
- Tests: `test_contacts.py` +2 (display-form normalisation,
  `looks_like_hash`). Suite 217.

## 2026-09-09 — Propagation: WS push on sync completion

`sync_propagation_messages()` now spawns `_watch_propagation_sync()`
(bg task, guarded on `self._loop`) which — after a 3s initial delay
(`initial_delay_s` param, 0 in tests) — polls `propagation_client_status`
until `state` hits a terminal value (`_PROP_SYNC_TERMINAL`), then
broadcasts `reticulum_propagation_sync` = `{state, last_result}`. Covers
manual AND timed auto-sync. Frontend `_onWsPropagationSync` clears the
button poll, updates `#rt-sync-status`, and if `last_result > 0`
reloads Messages + toasts. (The synced messages themselves already
live-updated via the normal `register_delivery_callback` →
`_handle_inbound_message` path; this adds the "sync ran, got N" signal
the UI was missing on a background auto-sync.) 2 tests. Suite 215.

## 2026-09-09 — Telemetry: multiple collectors

`telemetry_collector` field is now a textarea — one LXMF hash per line
(commas / `<hex>` / `aa:bb` tolerated). `state._parse_collectors` →
`telemetry_config()` returns `collectors: list` (+ `collector` = first,
back-compat). `config_routes._collector_hashes_ok` field validator
splits/normalises/dedupes, re-joins one per line, rejects the whole
value if any line is a bad hash (shared `_clean_dest_hash` helper, also
used by `propagation_outbound_node`). `lxmf_service.send_telemetry()`
builds+packs once, loops `_send_telemetry_frame(collector, packed)` per
address, returns `{ok (>=1 sent), sent: int, error}`. `telemetry_status`
gains `collectors`/`collector_count`. Settings status line + "Send now"
report the count. Suite 213.

## 2026-09-09 — Telemetry collector + map (new-build #4)

Receive half. `telemetry.decode_telemetry` + `_unpack_location` (inverse
of `_pack_location`); `backend/telemetry_store.py` `TelemetryStore`
(in-mem, latest-per-peer, 24h prune, 500 cap, created in
`LxmfService.__init__`). `_log_inbound_telemetry` → `_record_inbound_
telemetry` (logs + records + returns had-field); `_handle_inbound_message`
records, fires `reticulum_telemetry` WS, and returns early for a
telemetry-only frame (fixed a latent "blank message row per frame" bug).
`telemetry_peers()` + `GET /api/reticulum/telemetry/peers`. Frontend:
**Telemetry tab** (`_loadTelemetry`/`_renderTelemetry` table +
`_renderTelemetryMap` own Leaflet map — `L` is globally loaded —
`_onWsTelemetry` live). NOT the dashboard NodeMap (core `nodes` table
coupling). Suite 200 passed. NOT Pi-tested.

## 2026-09-09 — Telemetry publish, v1 subset (new-build #3)

Broadcast this box's host stats as a Sideband-compatible LXMF telemetry
frame. Wire format pulled from `markqvist/Sideband`
`sbapp/sideband/sense.py` via WebFetch (no Sideband source locally, no
`lxmf` on the Mac, meshchat only *detects* Sideband telemetry requests).

- Format: `Telemeter.packed()` = `umsgpack.packb({sid: pack(), ...})`,
  `SID_TIME` always present. v1 uses only the unambiguous single-value
  sensors: `SID_TIME`(0x01)=int, `SID_TEMPERATURE`(0x07)=float °C,
  `SID_INFORMATION`(0x0F)=str. Structured `SID_PROCESSOR`/`RAM`/`NVM`
  (nested `[[label,val],...]`) and `SID_LOCATION`(0x02, 7-el
  struct-packed list) are follow-ups — the latter is what #4
  (collector/map) needs.
- `backend/telemetry.py` — `build_telemetry(host, node_name)` pure dict
  builder; `_info_line()` composes the INFORMATION string from
  `host_stats` fields.
- `state.py` `telemetry_config()`; `config_routes.py` 3 keys, the
  collector-hash validator is the renamed `_dest_hash_ok` now shared
  with `propagation_outbound_node`, plus an enabled-needs-collector
  model validator.
- `lxmf_service.py` `send_telemetry()` / `_telemetry_loop()` (30s warmup
  + interval) / `telemetry_status()`; packs with `RNS.vendor.umsgpack`,
  `lxm.fields[getattr(LXMF,"FIELD_TELEMETRY",0x02)] = packed`, empty
  text body, `handle_outbound`. `request_path` on a cold collector then
  asks the caller to retry. `telemetry_cfg` ctor param via `__init__.py`.
- `routes.py` `GET /api/reticulum/telemetry` + admin `POST
  .../telemetry/send`. Not on `/status` (avoids test-fake churn).
- `reticulum_settings_tab.js` "Telemetry" fieldset + "Send telemetry
  now".
- Tests: `test_telemetry.py` ×6, `test_lxmf_service.py::
  TestTelemetryPublish` ×4 (both Mac); `test_config_routes.py` ×5 +
  `test_telemetry_route.py` ×5 (CI/Pi). Suite 186 passed.
- SID ids + `packed()` shape confirmed verbatim from `sense.py` (2nd
  WebFetch): `SID_TIME=0x01`, `SID_TEMPERATURE=0x07`,
  `SID_INFORMATION=0x0F`; `packed()` = `umsgpack.packb({sid: pack()})`
  with TIME set directly. Encoding matches.
- `_log_inbound_telemetry(message, source_hex)` in
  `_handle_inbound_message` — decodes an inbound `FIELD_TELEMETRY` and
  logs `{sid: value}` at INFO. Observational only; groundwork for #4.
- **Partially verified on rakv2-meshpoint 2026-09-09:** the send loop
  works (`telemetry frame sent to <collector>` on cadence, after a
  *meshpoint* restart). **Self-loopback does NOT work** — LXMF won't
  deliver a DIRECT message to your own `lxmf.delivery` dest, so the
  inbound log never fired. Verify via real Sideband → Pi instead.
- `SID_LOCATION` (0x02) added same day: opt-in
  `telemetry_include_location` config key; coords come from core's
  `context.config.device.latitude/longitude` (Configuration → GPS pin),
  resolved into the telemetry cfg dict in `__init__.py` `build()` — no
  plugin lat/lon keys. `telemetry._pack_location()` = the 7-element
  `[pack("!i",lat*1e6), lon, alt*1e2, speed=0, bearing=0, accuracy=0,
  last_update]` list from `sense.py`. `telemetry_status()` reports
  `location_included`. Settings tab: "Include location" toggle + a hint
  that warns when on with no pin set.
- Config-needs-restart UX: `POST /telemetry/send` and
  `/propagation/sync` now detect "config saved but service not
  restarted yet" (running service's error says "no collector/node" but
  `state.*_config()` has one) and return a clearer message. This is
  what the stale red "No telemetry collector configured" was.
- Unrelated: core has its own `telemetry_broadcaster` module (logs
  "Telemetry broadcaster scheduled") — different feature entirely.
- Pi verification: see `memory/reticulum_todo.md`.

## 2026-09-09 — Propagation node polish, client side (new-build #2)

Server side (be a relay) shipped v0.8.1; this is the client half (use
someone else's relay). Mirrors reticulum-meshchat's `meshchat.py`.

- Config: `propagation_outbound_node` (a `lxmf.propagation` dest hash,
  validated hex 8-64 even-length in `config_routes.py`) +
  `propagation_auto_sync_interval_s` (0 = manual, else ≥300 — model
  validator rejects <300 and rejects >0 with no node). `state.py`
  `propagation_config()` gains `outbound_node`/`auto_sync_interval_s`.
- `lxmf_service.py`:
  - `set_outbound_propagation_node(hash|None)` — normalises
    (lower/strip/`:`-strip), `router.set_outbound_propagation_node(
    bytes.fromhex(h))`; clearing cancels in-flight + nulls
    `router.outbound_propagation_node`; bad hash → swallow + clear.
  - `sync_propagation_messages()` → `{ok, error}`, calls
    `router.request_messages_from_propagation_node(self._identity)`.
  - `cancel_propagation_sync()` → `router.cancel_propagation_node_requests()`.
  - `propagation_client_status()` → `{outbound_node, auto_sync_interval_s,
    state, progress, last_result}` from
    `router.propagation_transfer_state/_progress/_last_result`. `state`
    mapped via `_prop_state_names()` (built from `LXMRouter.PR_*` at
    runtime; `{}` when LXMF absent → "idle"/"unknown").
  - `_apply_outbound_propagation_node()` called in `_connect` (after
    `_start_propagation`, independent of the relay toggle); starts
    `_propagation_sync_loop` if interval > 0. `_prop_sync_task`
    cancelled in `stop()`.
- `routes.py`: `GET /propagation` (`{local, client}`), admin `POST
  /propagation/sync` (400 if no node) + `/propagation/sync/cancel`;
  `propagation_client` added to `/status`.
- Frontend:
  - `reticulum_settings_tab.js`: outbound-node `<select>` populated
    from `/peers` filtered to `lxmf.propagation` (saved hash kept
    selectable if not re-heard), auto-sync `<number>`, client status
    line; client-side validation mirrors the model validator.
  - `reticulum_panel.js`: "Sync inbox" button in the header (shown when
    `status.propagation_client.outbound_node` set + admin);
    `_handleSync()` POSTs then polls `GET /propagation` every 2s up to
    60s, rendering `state`, reloads Messages on a terminal state.
    `_renderSyncControls()` shows idle state / last_result when not
    polling.
  - `reticulum.css`: `.rt-prop-divider`.
- Tests: `test_lxmf_service.py::TestPropagationClient` ×7 (Mac-runnable,
  `_FakeRouter` extended), `test_config_routes.py::TestPropagationOutboundNode`
  ×6 + `test_propagation_route.py` ×5 (CI/Pi). Suite 176 passed.
- NOT done: **PN peering** (relays gossiping held messages to each
  other — `LXMRouter` has hooks, meshchat doesn't do it either); a WS
  push when an auto-sync delivers new messages (manual sync reloads the
  Messages tab, a timed one on an idle page goes unnoticed until the
  15s poll).
- Pi verification: see `memory/reticulum_todo.md`.

---

## 2026-09-14 — Reticulum Dashboard: new companion plugin (uncommitted)

User: core Dashboard is empty on a Reticulum-only box (concentrator/serial/
MeshCore all unconfigured) — "NODES DISCOVERED 0/0", empty map, empty
packet table — even though Reticulum clearly has data (1500+ peers, a live
Activity feed). Explored piping Reticulum announces into the *existing*
dashboard widgets as synthetic "packet" WS events (`simple_packet_feed.js`
and `node_cards.js` are both already protocol-tolerant — verified: RSSI/
SNR/freq/SF/hops already fall back to '--' for the pager project today, and
`lxmf_service.py`'s `_handle_announce()` already builds almost the exact
fields needed, including real rssi/snr when RNode resolves them for that
announce packet). Set that aside: volume risk (announces flood far faster
than RF packets) would need a noisy default-off toggle, and stat cards
(NODES DISCOVERED/TOTAL PACKETS/etc.) are SQL aggregates over the core
`packets`/`nodes` tables Reticulum deliberately never writes to — that
part can't be fixed by a WS event either way.

**Landed instead: a standalone "Reticulum Dashboard" page**, same stat-card
+ live-table visual language as the reticulum plugin's own page, fed from
Reticulum's own shape (no RF fields faked). New plugin, not a tab on the
existing Reticulum page or a new core dashboard widget seam — discovered
`src/plugins/manifest.py`'s `sidebar: SidebarSpec | None` only supports
ONE `[sidebar]` table per plugin (confirmed: `_parse_sidebar` + `mountPlugin
SidebarPages()` in `sidebar_plugin_registry.js` both assume 1:1 plugin→nav-
item), so a second top-level nav item needs a second plugin folder — user's
own suggestion mid-conversation, correct and confirmed zero-core-change
after checking the `hello-world` plugin precedent (`provides = ["sidebar"]`,
no-op `backend/__init__.py`, plain manifest `[sidebar]` table — the exact
shape needed, just pointed at reticulum's existing routes instead of saying
hello).

`plugins/apps/reticulum-dashboard/` (**new**, backend-free):
- `plugin.toml` — `provides = ["sidebar"]` only (no `routes`/`service`),
  `[sidebar]` route=`reticulum-dashboard`, category=`networks`,
  icon=`reticulum` (icon names are a shared set, not plugin-exclusive —
  confirmed in `sidebar_plugin_registry.js`), no `[frontend].styles` (reuses
  core's already-global `stat-card`/`lw-*`/`.packet-row--new` classes from
  `dashboard.css`+`lorawan.css`, both unconditionally `<link>`ed in
  `index.html`'s `<head>`).
- `backend/__init__.py` — no-op `register(reg): pass`, verbatim hello-world
  pattern.
- `frontend/reticulum_dashboard.js` (**new**, `ReticulumDashboard` class):
  5 stat cards (Status/Known Peers/People/Infrastructure/Conversations,
  same split logic as `reticulum_panel.js` — `lxmf.delivery` = People, rest
  = Infrastructure) + a live activity ticker table (Time/Display
  name/Destination/Aspect). Reads `/api/reticulum/status`,
  `/api/reticulum/peers`, `/api/reticulum/announces` (seed only, once),
  `/api/messages/conversations` (filtered `protocol==='reticulum'`) via
  plain `fetch()` — all already-public reticulum-plugin routes, no new
  backend. Subscribes to `window.concentratorWS.on('reticulum_announce', …)`
  / `('reticulum_peer', …)` (the SAME broadcasts `reticulum_panel.js`
  already listens for) for live updates. New announces are `insertBefore`d
  as individual `<tr class="packet-row--new">` (not a full re-render) so
  the core dashboard's own `@keyframes packetFlash` animation
  (`dashboard.css`) actually plays per row — reused verbatim, no new CSS.
  Ticker capped client-side at 60 rows (glanceable live view, not a log —
  smaller than the Activity tab's 200-row ring buffer). 20s refresh timer
  for stat cards as a fallback, same interval pattern as the main page's
  15s (slightly longer since this page has less to keep fresh).
  `hide()`/`show()` mirror `reticulum_panel.js`'s own (no WS unsubscribe
  primitive exists — documented as harmless, matches precedent).
- `README.md` — mirrors `hello-world/README.md`'s structure.
- Requires `plugins.reticulum.enabled: true` too (undeclared — no plugin
  dependency mechanism exists in the manifest; fails open, same as
  everywhere else in this app — a disabled reticulum plugin just means
  every fetch 404s and the page sits in its empty/`--` state, no crash).

Verified: `node --check` on the new JS; `parse_manifest()` +
`discover_plugins()` both succeed (15 plugins found, up from 14); full
plugin test suite (`test_plugin_loader.py`/`test_plugin_manifest.py`/
`test_plugin_registry_facade.py`, python3.11) 77 passed / 6 skipped — no
hardcoded plugin-count canary broke (checked specifically, given the
router-count canary bug earlier this session). `ruff check` clean.
CHANGELOG parses (31 sections). `docs/PLUGINS.md` intro paragraph gained a
4th worked-example pointer (the "read another plugin's API instead of
adding your own backend" pattern, since none of the existing 3 reference
plugins demonstrate that).

**NOT committed, NOT Pi-tested.** Pi verify: enable
`plugins.reticulum-dashboard.enabled: true` (needs `plugins.reticulum.
enabled: true` already on), restart, Networks → Reticulum Dashboard —
5 stat cards populate, announce rows flash in live as they're heard, no
console errors if reticulum ever gets disabled later.

**Deferred (2 + 3 from the original 3-part ask, not started):** hide core
Dashboard's nav item via `data-requires-source` when nothing RF is
configured, and a smarter `Router` `defaultRoute` fallback (currently
hardcoded `'dashboard'` in `app.js`) so a reticulum-only box actually lands
somewhere sensible on a fresh load instead of an empty, unlinked Dashboard
section.

**Follow-up, same session: generic plugin `requires` dependency (uncommitted).**
User, looking at Settings → Plugins with both `reticulum` and
`reticulum-dashboard` rows visible: "shouldn't it depend on reticulum, like
hello-world-hook to hello-world?" Checked and corrected an earlier
understatement — `[hook].host` isn't just soft/informational, `src/api/
routes/plugin_routes.py`'s `PUT` genuinely refuses to enable a hook plugin
whose host isn't enabled, and cascades disable to dependents
(`_cascade_disable_dependents`); the frontend already groups/indents a
dependent plugin under its host. But reticulum-dashboard isn't a `hook` —
it doesn't attach UI into reticulum's page, it renders its own page fine
standalone, just empty without reticulum's data. Asked user: enforce the
same hard way, or just show it softly? **User: hard, same as hook.**

Generalized rather than special-cased:
- `src/plugins/manifest.py`: new optional top-level `requires: str | None`
  on `PluginManifest` — another plugin's **name** (not a route, unlike
  `hook.host`). `_parse_requires()`: same slug shape as `name`, rejects
  self-reference. A plugin declares at most one dependency total (`hook` OR
  `requires`, checked structurally by which field is set — nothing stops a
  manifest setting both today, not worth guarding, no plugin does).
- `src/api/routes/plugin_routes.py`: new `_name_map()` (mirrors
  `_route_map()`, keyed by plugin name) + `_dependency_target(manifest,
  route_map, name_map)` replacing `_host_manifest()` — returns `(target,
  ref)` for EITHER a hook (`ref` = route) or a `requires` (`ref` = plugin
  name), or `(None, None)`. `_describe()`, `update_plugin()` (PUT
  enable-refusal, separate error messages for the two cases — hook says
  "nowhere to render", requires says "needs it enabled to show anything"),
  and `_cascade_disable_dependents()` all now key off this one function
  instead of `manifest.hook is not None` directly — hook and `requires`
  plugins are disabled-cascaded identically.
- **Frontend needed ZERO changes** — `plugins_panel_controller.js`'s
  "Depends on: … (not enabled)" row text and toggle-greying already keyed
  generically on `dependency.host_id`/`host_enabled` (only `host_route` is
  hook-specific-sounding, reused as the raw reference string either way).
- `plugins/apps/reticulum-dashboard/plugin.toml`: `requires = "reticulum"`.
- `docs/PLUGINS.md`: new manifest-fields-table row for `requires`.
- `docs/CHANGELOG.md`: separate v0.8.1 bullet (generalizable core feature,
  not just a reticulum-dashboard implementation detail).

Verified (Mac, no fastapi/pydantic installed — CLAUDE.md constraint):
manifest re-parses (`m.requires == 'reticulum'`), `discover_plugins()`
still finds 15; `ruff check` clean on `manifest.py`/`plugin_routes.py`/the
new plugin; full plugin-loader/manifest/registry suite still 77 passed / 6
skipped (no regression). `plugin_routes.py` itself can't run on the Mac
(needs fastapi+pydantic for `tests/test_plugin_routes.py`'s `TestClient`),
so hand-verified the actual changed logic instead: stubbed `fastapi`/
`pydantic` just enough to import the module, built real `PluginManifest`s
for reticulum/reticulum-dashboard/hello-world/hello-world-hook, and
asserted directly against `_dependency_target()` (both requires- and
hook-based resolve correctly, hook path unchanged from before — a real
regression check), `_describe()`'s `dependency` dict shape, and
`_cascade_disable_dependents()` (disabling `reticulum` while
`reticulum-dashboard` is enabled correctly cascades it off).

**NOT committed, NOT Pi-tested.** Pi/CI verify: `pytest tests/
test_plugin_routes.py` (needs the real venv, fastapi+pydantic present
there unlike the Mac) plus a live check — try enabling reticulum-dashboard
with reticulum off (should 400: "Enable 'reticulum' first..."), enable
both, then disable reticulum and confirm reticulum-dashboard auto-disables
too (`also_disabled` in the response) and the Settings → Plugins row shows
"Depends on: reticulum (not enabled)" / greys the toggle when reticulum is
off.

**Follow-up, same session: full dashboard layout (uncommitted).** User,
looking at both pages side by side: "cant you make the ret dashboard like
the real dashboard? we have contacts/peers for the right side, we have
activity for bottom and even telemetry with location etc for the map?"
Right call — reticulum_panel.js already has everything needed, just on a
different tab: a Leaflet telemetry map (`_renderTelemetryMap()`, own
markers keyed off `GET /api/reticulum/telemetry/peers` entries with
lat/lon — Sideband-style LXMF telemetry frames, not RF nodes) and the
peers roster (`GET /api/reticulum/peers`, `last_seen` DESC from the API).
Ported both into the new page:

- `reticulum_dashboard.js`: new `.rtd-grid` two-column row between the
  stat cards and the ticker — left: telemetry map (verbatim port of
  `_renderTelemetryMap`, own `#rtd-telemetry-map` Leaflet instance,
  `reticulum_telemetry` WS event -> `_loadTelemetry()`), right: a
  lighter "who's around" peers list (`display_name`/aspect badge/last-seen,
  client-side search-as-you-type by name or hash, capped at 150 — full
  sortable/searchable table stays on the Reticulum page). `_loadPeers()`
  (renamed from `_loadPeerCounts()`) now keeps `this._peers` around
  instead of discarding it after computing the stat-card counts.
- `reticulum_dashboard.css` (**new** — plugin previously had none):
  `.rtd-grid` (2fr/1fr, mirrors core `dashboard.css`'s own
  `.dashboard__main`, stacks under 900px since this page scrolls normally
  rather than living in the core dashboard's fixed-height flex shell),
  `.rtd-peers-list`/`.rtd-peer-row`, and a **verbatim copy** of
  reticulum.css's `.rt-telemetry-map`/`.rt-tele-popup*` rules — cross-plugin
  asset serving is scoped per-plugin (`resolve_plugin_asset` only serves a
  plugin's own manifest-listed files), so reticulum.css genuinely can't be
  linked from this plugin; documented as a "kept in sync by hand" copy in
  both the CSS file's header and this note.
- `plugin.toml`: added `[frontend].styles`.

Verified: `node --check`, manifest re-parses (styles tuple populated,
15 plugins still discovered), `ruff check` clean, plugin-loader/manifest/
registry suite still 77 passed / 6 skipped, CHANGELOG parses (31 sections,
bullet expanded in place rather than a new one — same feature landing in
the same version).

**NOT committed, NOT Pi-tested.** Pi verify: peers list populates and
search-filters live; telemetry map shows/hides correctly (most Reticulum
peers won't have telemetry, so likely empty unless the VM/Pi has telemetry
senders on the mesh — the "No located peers yet" empty state should show
cleanly in that case, not a broken/blank map); WS-driven updates (new
peer, new telemetry report, new announce) all reflect live without a
manual refresh.

**Follow-up, same session: real layout bug found live on the VM
(uncommitted).** After the restart fixed the missing-stylesheet issue, user
reported the layout still broke a beat after a correct-looking first paint
-- "like it overwrites instead of showing it in the correct spot" (one
panel visually overlapping/ballooning over the section below it).
Root cause: `.rtd-map-panel`/`.rtd-peers-panel`/the ticker's wrapper all
reused core's `.panel`/`.panel__header`/`.panel__body` (`dashboard.css:304`)
-- that trio is built specifically for the core Dashboard's fixed-height
flex shell (`.panel { height: 100%; overflow: hidden; display: flex; }`,
meaningful only because `.dashboard`/`.dashboard__main` above it pin a real
viewport-bound height). This page scrolls normally with no such ancestor,
so `height: 100%` has nothing definite to resolve against -- inside a CSS
grid item specifically, that's exactly the kind of situation where a
browser can stretch the item to some much larger height than intended
instead of falling back to content-sized `auto`, reading as one panel
"overwriting" the one below it. Same general lesson as [[feedback_grep_shared_css_classes]]
(grep a shared class's own rules before reusing it for a new purpose), this
time on the giving end rather than the receiving end.

Fix: stopped reusing `.panel`/`.panel__header`/`.panel__body` entirely.
`reticulum_dashboard.css` gained `.rtd-panel`/`.rtd-panel__header`/
`.rtd-panel__body` -- same visual look (bg-glass/border/radius/header
typography), no fixed-height assumption. `reticulum_dashboard.js`'s markup
updated to match (map panel, peers panel, ticker panel all three).
Double-checked `.lw-table-wrap`/`.lw-panel__limit`/`.lw-empty` (still
reused) for the same class of bug -- clean, no height assumption, matches
that they already work fine in reticulum_panel.js's own normal-scrolling
page context.

Also (separate finding, same investigation): the VM's meshpoint hadn't
picked up the CSS/`requires` manifest additions at all before the first
restart the user did just now -- `_loaded_plugins` (`src/api/server.py`)
is a module-level global set once in `create_app()`; a plugin.toml edit
made after the process started (this whole `[frontend].styles` +
`requires` addition) needs a `systemctl restart meshpoint` to actually
take effect, same as any other plugin manifest change. Not a bug, just a
real operational gotcha worth remembering for the rest of this feature's
iteration -- expect to ask for another restart before the next round of
live verification.

Verified (Mac): `node --check`, manifest re-parses, `discover_plugins()`
still finds 15, `ruff check` clean. **NOT committed.** Still waiting on the
user's next restart + hard-refresh to confirm the actual fix live.

**Follow-up, same session: the REAL root cause of the layout mess
(uncommitted).** After the `.rtd-panel` fix, user still saw a broken
layout live (map/peers not side by side, content looking squeezed/
overlapping) even though the CSS was verifiably loading (the new
`.rtd-panel` header typography/border WAS visibly applying). Traced it to
one level higher in the DOM than either previous fix: every plugin sidebar
page's outer wrapper (`mountPluginSidebarPages()` in
`sidebar_plugin_registry.js`) is `<section class="section"
data-section="<routeId>">`, and the BASE `.section` rule
(`dashboard.css:88`) is `overflow: hidden; display: flex; flex-direction:
column;` -- clipped by default. Every *other* normal-scrolling content
page opts out via a per-`data-section` override in `lorawan.css:6-10`
(`.section[data-section="lorawan"], ..., .section[data-section=
"reticulum"] { overflow-y: auto; }` -- this exact line has a comment in
THIS memory file already, from the Phase 2a port: "KEEP the
`.section[data-section="reticulum"]` line ... the plugin section still
needs it"). `reticulum-dashboard` was never added to that list, so the
page was stuck in the clipped, fixed-height default -- .rtd-grid's own
CSS was correct the whole time, it just had a hostile containing block a
level up. Fixed: added `.section[data-section="reticulum-dashboard"]` to
that same lorawan.css selector list (one line, core file, same
established pattern).

**Also this batch: telemetry map now follows the shared "Dashboard map
source" switch** (user request, referencing the existing Settings ->
... offline-map toggle for the Dashboard/Topology maps). `_initTelemetryMap`
now uses `window.MAP_TILE_URL_FALLBACK` + `window.getMapTileUrl()` from
`frontend/js/map_tile_source.js` (core, globally loaded in index.html --
no plugin script dependency needed) instead of a hardcoded public-OSM tile
URL, mirroring `frontend/js/components/node_map.js`'s own sync-fallback-
then-async-swap pattern exactly (a map needs a tile layer synchronously at
construction or `fitBounds`/`setView` throws "no maxZoom specified" -- see
that file's own comment). Reads live from `GET /api/config`, no restart
needed, same as the Dashboard/Topology maps.

Verified (Mac): `node --check`, ruff clean, plugin-loader/manifest suite
70 passed / 6 skipped (subset run, faster iteration). **NOT committed.**
Waiting on the user's next hard-refresh (no restart needed for this
batch -- lorawan.css and both JS/CSS files are all read fresh per
request) to confirm the overflow fix actually resolves the layout live.

**Follow-up, same session: full rebuild on the REAL Dashboard markup
(uncommitted).** Found the actual reason `.rtd-grid` never split into
columns, and it was a genuinely silly one: this file's own CSS header
comment contained the literal text "lw-*/stat-card" -- the `*` ending
"lw-*" immediately followed by the `/` starting "/stat-card" forms an
accidental `*/`, closing the block comment 11 lines early. Everything from
there to the REAL intended `*/` (11 lines of prose) was then parsed as
malformed CSS "code", which lost the parser's sync enough to also corrupt
the very next real rule -- `.rtd-grid` itself, appearing right after.
Confirmed via a small brace-balance script (comment `/*`/`*/` count: 5
vs. 6, i.e. one orphaned closer). `.rtd-panel`'s styling, defined further
down, happened to be past the corrupted region and parsed fine -- which is
exactly why some of the page's custom CSS visibly worked while `.rtd-grid`
silently didn't, the whole confusing split symptom this session chased
across several turns.

User, having watched multiple rounds of hand-rolled-CSS bugs (the
`.panel{height:100%}` assumption, this comment bug): "cant you make a real
copy of the dashboard a fix the data into it? so it is exact the same not
thee cards orso?" -- right call, taken. Full rebuild:

- `reticulum_dashboard.js` `mount()`: now the literal core Dashboard
  markup from `frontend/index.html`'s own `data-section="dashboard"`
  section -- `<main class="dashboard">` > `.dashboard__stats` (stat cards,
  now 6: Status/Known Peers/People/Infrastructure/Conversations/**You**
  [own address, was a separate header line before]) + `.dashboard__main`
  (`.dashboard__map` > `.panel` "Telemetry Map" holding
  `#rtd-telemetry-map.rt-telemetry-map.map-container`, `.dashboard__side`
  > `.panel.panel--nodes` "Peers" with the real `.node-search`/
  `.node-search-wrap` classes, `#rtd-peers-list` now *is* the
  `.panel__body` directly -- core already gives it `flex:1;overflow:auto`
  scrolling, no wrapper div needed) + `.dashboard__feed` > `.panel` "Live
  Activity" (unchanged table). `_loadStatus()` simplified to match (own
  address is now a plain stat-card value, no "You: " prefix needed since
  the card label already says it).
- `reticulum_dashboard.css`: gutted. Dropped `.rtd-grid`/`.rtd-panel*`/
  `.rtd-peers-list` entirely (all now literal core classes/behaviour --
  `.panel{height:100%}` now correctly resolves, because `.dashboard{height:
  100%}` above it is the SAME fixed-height shell the core page uses, not
  a normal-scrolling page pretending to have one). Kept: the telemetry-map
  Leaflet popup re-skin (still page-specific, copied from reticulum.css)
  and `.rtd-peer-row*` (the simple peer-row look, no equivalent core
  component -- user's "not these cards" read as "don't reimplement
  NodeCards, just match the panel layout", not "match every pixel of the
  node card design too"). Also fixed the comment bug while rewriting.
- `frontend/css/lorawan.css`: **reverted** the `data-section=
  "reticulum-dashboard"` addition from the previous batch -- that
  `overflow-y:auto` opt-out is for normal-scrolling pages; the real
  Dashboard's own `data-section="dashboard"` deliberately does NOT have
  it (confirmed: not in that selector list), because `.dashboard{height:
  100%;overflow:hidden}` manages its own internal per-panel scrolling
  instead. Adding both would have meant two nested, conflicting scroll
  contexts.
- `plugin.toml`: `[frontend].styles` comment updated to match.

Verified: `node --check`; CSS comment-balance script now reports 0 (was
-1); manifest re-parses, `discover_plugins()` still finds 15; `ruff check`
clean; plugin-loader/manifest suite 70 passed / 6 skipped. **NOT
committed, NOT yet re-verified live** -- this is a genuinely bigger
rewrite than the previous two patches, waiting on the user's next
hard-refresh to confirm the map/peers actually sit side-by-side now with
the real Dashboard's own proven layout engine under it.

**Follow-up, same session: map/peers columns not equal height
(uncommitted).** After the full rebuild, grid split correctly (map left,
peers right, confirmed live) but heights didn't match -- Peers grew tall
with its own content, Telemetry Map stayed short. Cause: core's `#map {
height: 100%; ... }` is an **ID selector**, not tied to `.map-container`
(which only has `min-height:0;overflow:hidden`) -- this page's map div has
a different id (`#rtd-telemetry-map`), so it never got that height rule
and just sat at whatever height Leaflet happened to compute once, instead
of stretching with the grid row the way `#map` does. Added `height:100%;
width:100%` to `.rt-telemetry-map` directly in reticulum_dashboard.css
(overrides the reticulum plugin's own Telemetry-tab version of that class,
which deliberately uses a fixed 300px since it lives in a normal-scrolling
page -- correctly different for this page's fixed-height shell context).
Verified: comment-balance script still 0. **NOT committed, NOT yet
re-verified live.**

**Follow-up, same session: map header action buttons (uncommitted).**
User: match the core Dashboard's NODE MAP header buttons (home/basemap/
cluster/expand). Added 3 of the 4 to the Telemetry Map panel header:

- **Basemap dark/light toggle** -- reimplemented (not reused) since
  node_map.js's `toggleBasemap()`/`_applyBasemap()` and dashboard.css's
  filter rules are hardwired to the core map's own `#map` id. New
  `_loadBasemapPref()`/`_applyBasemap()`/`_toggleBasemap()`/
  `_syncBasemapBtn()` on `ReticulumDashboard`, same behaviour, same
  `window.themeGlyph` icon helper, and **deliberately the same
  `meshpoint.nodeMap.basemap` localStorage key** -- one shared "I like a
  light map" preference across every map in the app, not a second one to
  set. CSS: `.rt-telemetry-map.map--basemap-dark/light .leaflet-tile-pane`
  filter rules copied from `#map.map--basemap-dark/light` (same reason,
  can't reuse an id-scoped rule).
- **"Fit all located peers"** button, replacing "center on home" -- this
  page has no device lat/lon to recenter on, but a one-click reset to "see
  every dot" is the same kind of utility. Reused the exact home-icon SVG
  for visual consistency; `_fitTelemetryBounds()` extracted out of
  `_updateTelemetryMarkers()` so both the button and every marker refresh
  share one implementation, recomputing from `this._telemetry` fresh each
  time (not a stale closure).
- **Expand** -- same `dashboard--map-expanded` class dashboard.css already
  defines (a plain class-scoped rule, not id-scoped, so directly reusable)
  toggled on `this._q('.dashboard')` -- root-scoped, deliberately NOT
  `document.querySelector('.dashboard')` the way app.js's own handler
  does it, which would ambiguously match whichever `.dashboard` comes
  first in the whole document now that two pages have one.
- **Not added: cluster toggle.** Located telemetry peers are typically a
  small fraction of the full peer roster (most Reticulum peers report no
  location at all) -- nowhere near dense enough to need grouping the way
  RF nodes can be, and clustering needs a marker-cluster library dependency
  this page doesn't otherwise need.

New ids used throughout (`rtd-map-basemap-btn`/`rtd-map-fit-btn`/
`rtd-map-expand-btn`) -- checked, no collision with the core buttons'
own ids.

Verified: `node --check`, CSS comment-balance script still 0, manifest
re-parses, `ruff check` clean, plugin-loader/manifest suite still
70 passed / 6 skipped. **NOT committed, NOT yet verified live.**

**Follow-up, same session: scroll-to-zoom (uncommitted, one-liner).** User:
scrolling over the map didn't zoom, scrolled the page ~10px instead.
Cause: `_initTelemetryMap` had `scrollWheelZoom: false`, copied from the
reticulum plugin's own small embedded Telemetry-tab map (correct there --
a widget in a normal-scrolling page shouldn't hijack scroll). This page's
map plays the core Dashboard's dominant NODE MAP role instead, which is
`scrollWheelZoom: true` (node_map.js) -- flipped to match. Verified:
`node --check`. **NOT committed, NOT yet verified live.**

**Follow-up, same session: peer drawer + announce modal click-through
(uncommitted).** User: clicking a peer/activity row should open the same
right-side drawer / center modal the Reticulum page's own Peers/Activity
rows do. Turned out cleanly reusable -- `reticulum_detail_panels.js`
exposes `window.ReticulumPeerDrawer`/`ReticulumAnnounceModal`/
`ReticulumTelemetryModal` as plain globals (self-contained, no host
element needed, `new X()` then `.open()`/`.show()`), and since
`requires = "reticulum"` guarantees that plugin's scripts are always
loaded alongside this page's own, no cross-plugin asset-serving workaround
needed this time (unlike the CSS files earlier).

- Constructed both (`ReticulumPeerDrawer`/`ReticulumAnnounceModal`) once
  in `mount()`, guarded by `if (window.X)` -- fails visibly once at mount
  if reticulum's scripts somehow aren't loaded, rather than silently on
  every click.
- Added `this._announces` array (mirrors the ticker's DOM rows -- needed
  a backing array to look an entry up by `{ts, destination_hash}` on
  click, which the DOM-only ticker never needed before). Seeded in
  `_loadTickerSeed()`, kept in sync in `_onWsAnnounce()` (unshift + trim,
  same cap as the DOM rows). Row markup (`_rowHtml` and the WS-driven
  `<tr>` in `_onWsAnnounce`) both gained `data-rt-ts`/`data-rt-hash` +
  "Click for details" title, matching reticulum_panel.js's own Activity
  rows exactly.
- Peer rows gained `data-hash`; click-delegation listeners on
  `#rtd-peers-list` and `#rtd-ticker-tbody` (added once in `mount()`) look
  up the entry/peer and call the new `_openPeerDrawer(peer)`/
  `_openAnnounceModal(entry)`, same method names and same
  `onViewAnnounce`/`onViewPeer` cross-link `reticulum_panel.js` wires
  between the two -- clicking "view announce" in the drawer or "view peer"
  in the modal works the same way here.
- **Deliberately read-only**, unlike the real page's version: no
  `onBrowse`/`onSendMessage`/`onSaveContact`/`onDeleteContact` passed to
  the drawer (all optional per `ReticulumPeerDrawer.open()`'s own JSDoc,
  confirmed safe to omit) -- this page is a glanceable companion, not a
  second copy of the management page; full peer/contact/message actions
  stay on the Reticulum page.
- CSS: `.rtd-peer-row` gained `cursor:pointer` + `:hover` background,
  matching `.lw-pkt-row`'s own existing affordance for the ticker rows.

Verified: `node --check`, comment-balance script 0, ruff clean,
plugin-loader/manifest suite 70 passed / 6 skipped, no duplicate method
definitions. **NOT committed, NOT yet verified live.**

**Follow-up, same session: NomadNet quick-browse modal + home location
(uncommitted).** Two asks in the same message, plus a follow-up.

**1. Quick-browse modal.** User: a way to browse `nomadnetwork.node`
peers from this page without the full Browse tab (address bar, history,
node picker) -- "an inline modal" instead. New `ReticulumQuickBrowseModal`
class (local to this file, not exposed on `window` -- nothing else needs
it). Reuses `.pdm-overlay`/`.pdm-modal.pdm-modal--wide`
(`frontend/css/packet_detail_modal.css`, core, already loaded -- the exact
chrome `ReticulumAnnounceModal` above it already uses, confirmed by
grepping which stylesheet actually defines those classes) and
`window.MicronParser` (guaranteed loaded, `reticulum` is a hard
`requires`) -- zero new CSS. `POST /api/reticulum/nomad/page` (same
endpoint `reticulum_nomad.js`'s own `_fetch` uses) fetches `index.mu`;
clicking a `data-nomad-url` link re-fetches + re-renders in place, no
history stack. `_followLink`/address-splitting logic is a simplified
port of `reticulum_nomad.js`'s own `_followLink`/`_splitAddr` (same
`<hash>:/path` / `:/path` / `/path` shortcuts, external `https://` opens
a new tab) -- **deliberately dropped**: form-field submission (backtick
request-vars, `data-nomad-fields` inputs) and `/file/` downloads, both
real complexity the full Browse tab has that a "quick view" doesn't need.
Wired from two places: a `data-browse` button on `nomadnetwork.node` rows
in the peers list (delegated click handler, checked before the
row-click-opens-drawer path), and the peer drawer's own `onBrowse`
callback (confirmed via grep that `ReticulumPeerDrawer` already
conditionally renders a Browse button whenever `opts.onBrowse` is a
function and the peer is `nomadnetwork.node` -- so passing it was all
that was needed, no drawer changes).

**2. Home location on the map.** User: show the device's configured home
location, and make the map-header "home" button (previously repurposed as
"fit all located peers", back when I'd reasoned home doesn't apply to a
Reticulum-only page) actually center on it, matching `node_map.js`'s own
`centerOnHome()`. Corrected that earlier reasoning -- home
(`device.latitude`/`longitude`, Configuration -> Identity) is a
device-level setting, not RF-specific, so it applies here regardless of
data source. `_loadHomeLocation()` fetches `/api/device` once (same field
names `centerOnHome()` reads); `_renderHomeMarker()` draws a distinct pin
(new `.rtd-home-marker` divIcon, cyan circle + house glyph, own Leaflet
layer so peer-marker refreshes never clear it -- the core map has no
pin-drawing equivalent to port, `centerOnHome()` only recenters the view,
so this part is new rather than a port) -- safe to call from either
direction (home loads before the map exists, or the map inits before home
is known), whichever finishes second actually adds it. `_renderTelemetryMap`'s
old "hide if no located peers" gate widened to "hide only if no located
peers AND no home" -- otherwise a box with a home location set but zero
located telemetry peers yet would never show the map (or the home pin) at
all. `_initTelemetryMap` falls back to `_centerOnHome()` for the initial
view when there are no peers to fit bounds to. The header button
(`#rtd-map-home-btn`, was `#rtd-map-fit-btn`) now calls `_centerOnHome()`;
the old fit-bounds logic (`_fitTelemetryBounds`) stays but is auto-only
now (still runs after every marker refresh to frame the peers), no longer
button-triggered.

Verified: `node --check`, CSS comment-balance script 0, ruff clean,
plugin-loader/manifest suite 70 passed / 6 skipped, no duplicate method
definitions, no stale `rtd-map-fit-btn` references left. **NOT committed,
NOT yet verified live.**

**Follow-up, same session: quick-browse modal polish -- dark page
styling + nav chrome (uncommitted, 2 asks).**

1. "make it the same as the one on reticulum page it has ba[ck/lack]
   background" -- ported the Browse tab's own dark "BBS terminal" page
   styling (`.rt-nomad__page` in reticulum.css: `--bg-elevated`
   background, monospace, `white-space: pre-wrap`, link/hr colours) into
   `reticulum_dashboard.css` as `.rtd-browse-modal .pdm-modal__body`
   (copied, same cross-plugin-asset reason as everything else this page
   copies rather than links; scoped to the browse modal specifically,
   not `.pdm-modal__body` generally, since that class is shared with
   `ReticulumAnnounceModal`'s plain key-value layout).
2. "can we have url forward back and reload also" -- walked the modal
   back toward more of a real browser (still without the node-picker/
   favourites/forms the full Browse tab has). Added a `.rtd-browse-toolbar`
   row (back/forward/reload buttons + an editable address input + Go),
   mirroring `reticulum_nomad.js`'s own `.rt-nomad__bar` almost exactly
   minus the parts this modal doesn't need. `ReticulumQuickBrowseModal`
   gained a real `_history`/`_historyIdx` stack and
   `_go`/`_historyGo`/`_goFromAddr`/`_syncNav`, ported near-verbatim from
   that file's own `_go`/`_history_go`/`_goFromAddr`/`_syncNav`
   (`_followLink`/`_splitAddr` already existed from the first version,
   `_followLink` now calls `_go()` instead of fetching directly, so link
   clicks push history too).

Verified: `node --check`, CSS comment-balance script 0, ruff clean,
plugin-loader/manifest suite 70 passed / 6 skipped, no duplicate method
definitions. **NOT committed, NOT yet verified live.**

**Follow-up, same session: Browse tab two-row toolbar restructure +
shared favourites on the quick-browse modal (uncommitted, both
confirmed after an explicit "tell me first" design discussion).**

**1. Reticulum page's own Browse tab -- two-row toolbar.** User liked the
new quick-browse modal's cleaner toolbar and asked to bring that design
language to the real Browse tab too, keeping its search/node-picker/
favourites. Recommended (and built, after "yes please"): don't clone the
modal's toolbar 1:1 (it has fewer responsibilities), instead split the
existing 7-control single flex-wrap row into two purpose-grouped rows --
"find a node" (search/picker/favourite) above "navigate"
(back/forward/reload/address/Go, reordered to match the modal's own
control order). `reticulum_nomad.js`'s `_mount()` template gained
`.rt-nomad__bar-row--find`/`--nav` wrapper divs (pure markup nesting, zero
JS query/wiring changes needed -- attribute selectors don't care about
depth); `reticulum.css`'s `.rt-nomad__bar` became `flex-direction:
column`, new `.rt-nomad__bar-row { display:flex; flex-wrap:wrap; ...}`
for each row (the existing per-control flex-basis rules needed no
changes).

**Found + fixed while in there (pre-existing, unrelated to today):**
`reticulum.css` had the *exact* comment-closing bug from earlier this
session ("lw-*/foo" -- the `*` ending "lw-*" immediately followed by `/`
accidentally closes the block comment) -- **twice**, at the file's own
header comment (line 2) and the Peer-drawer/Announce-modal explanation
comment (line 338). Found via the same brace-balance script + a targeted
regex (`[\w-]+-\*/[\w.]+`) that pinpointed both exactly. Confirmed via
`git show HEAD:...` that both predate this session entirely. Lower real
impact than my own version of this bug (each corrupted span was comment
prose followed by a blank line then a cleanly-separated rule, not glued
directly onto a real rule the way `.rtd-grid` was), but genuinely
malformed source -- fixed both the same way as before (comma instead of
slash to break the adjacency). Comment-balance script confirms 0 now.

**2. Quick-browse modal -- shared favourites star.** Asked first
(feasibility + scope), user confirmed. `_rtIsFavourite`/`_rtToggleFavourite`
(reticulum_detail_panels.js) and their independent copy
(reticulum_nomad.js) are **already duplicated on purpose** between those
two files, same `RT_NOMAD_FAV_KEY`/`meshpoint.rtNomadFavourites`
localStorage key+shape, neither exported to `window` -- matches this
codebase's established small-duplication convention (same reasoning as
`RTD_ASPECT_BADGES`). Added a third copy (`_RTD_FAV_KEY`/
`_rtdFavourites`/`_rtdIsFavourite`/`_rtdToggleFavourite`, module-level
functions) to `reticulum_dashboard.js`, same key -- a node favourited from
any of the three places (this modal, the Peers drawer, the Browse tab)
now shows favourited in all three, one shared list. New `data-qb-fav`
star button in the toolbar (between Reload and the address input),
`.rt-nomad__fav`/`.rt-nomad__fav--on`/`:disabled` CSS copied from
reticulum.css (same cross-plugin-asset reason as the rest of this file).
`_syncFavBtn(isFav)` called after every successful `_fetch()`, keyed off
`_rtdIsFavourite(hash)` for whichever node is now showing.
`this._currentName` (only real for the node the modal was opened *with*
-- link-followed nodes have no display name in the page response) is
cleared whenever `_fetch` lands on a different hash than before, so a
favourite added after following a link doesn't get mislabelled with the
stale original name.

**Deliberately NOT added:** a node-picker dropdown + search in the quick-
browse modal. Explicit design call, explained to the user before
building: the modal always opens scoped to one specific peer (there's no
free "switch to a different node" concept in it at all), so a picker
would mean re-adding exactly what makes the real Browse tab "full" --
the whole reason this is a separate, smaller modal. Jumping between
favourited nodes freely stays a Browse-tab-only workflow.

Verified: `node --check` both `reticulum_nomad.js` and
`reticulum_dashboard.js`, CSS comment-balance script 0 on both
`reticulum.css` and `reticulum_dashboard.css`, `ruff check` clean on both
plugin dirs, plugin-loader/manifest suite 70 passed / 6 skipped, no
duplicate method definitions. **NOT committed, NOT yet verified live.**

**Follow-up, same session: favourites-jump select (uncommitted).** User
hit the exact gap flagged when the star was added: they could favourite a
node from the quick-browse modal, saw it show up starred in the real
Browse tab's node picker, but had no way to *select* a favourite from the
dashboard's own modal -- the star alone was only half-useful. Confirmed
("yes please") the compromise proposed: not the full node-picker+search
(needs a fetch + filter box for a list that runs to hundreds), just a
compact `<select data-qb-favs>` populated from `_rtdFavourites()` --
choosing an entry calls `_go(hash, '/page/index.mu')` then resets to the
"★ Favourites" placeholder (a jump menu, not a persistent selection).
Rebuilt on `open()` and again every time the star button changes the list
(`_renderFavsSelect()` called from both), so it never goes stale
mid-session. New `.rtd-browse-toolbar__favs` CSS (compact width, matches
the address bar's neighbourly sizing). Toolbar comment updated -- it's no
longer accurate to say "no picker at all", just "no *general* picker".

Verified: `node --check`, CSS comment-balance script 0, ruff clean,
plugin-loader/manifest suite 70 passed / 6 skipped, no duplicate method
definitions. **NOT committed, NOT yet verified live.**

**Follow-up, same session: general "Browse" entry point (uncommitted).**
User asked where a general (not-tied-to-a-peer) Browse button should go --
next to "You: <hash>" at the top, or the Peers panel header next to
search? Recommended the Peers panel header: the "You" line is identity/
status display, not action territory, while Browse is fundamentally about
the peers/nodes that panel already lists, and every row already has its
own Browse button -- a general one in the same header reads as a natural
escalation of something already familiar, not a new concept elsewhere.
Flagged one real wrinkle before building: `open(hash, label)` always
assumed a starting node and fetched immediately -- a general button has
no peer to hand it, so it needed a genuine "empty" open state. Confirmed
("yes please"), built:

- `open(hash = null, label = null)` -- both now optional. Empty case:
  title falls back to "Browse", `.pdm-modal__body` shows a placeholder
  ("Type a node address above ... or pick a favourite") instead of
  fetching, focus goes to the address input instead of the close button.
  Non-empty case (peer row's own Browse button, or the drawer's) is
  completely unchanged. `_favsEl`'s populate/disable logic already
  worked unconditionally either way (just reads localStorage, not tied
  to whether a node is loaded); `_backBtn`/`_fwdBtn`/`_reloadBtn`/
  `_favBtn` already default to `disabled` in the static template HTML,
  so the empty state needed no extra JS to *look* right, only to *not*
  fetch. Typing an address or picking a favourite hands off to the
  existing `_fetch()` flow unchanged (its own "Loading…" state
  overwrites the empty-state placeholder naturally).
- New `#rtd-browse-btn` (`.lw-link-btn`, same class the per-row inline
  Browse buttons already use) in the Peers panel header, calling
  `this._quickBrowse.open()` with no args.
- Placement subtlety caught before shipping: `.panel__header` is
  `justify-content: space-between` (core), so adding the button as a
  THIRD direct child would've spread Peers/search/Browse evenly across
  the row instead of keeping search+Browse grouped. New
  `.rtd-peers-header-actions` wrapper holds both, so `.panel__header`
  still only sees two children (the label and this group).

Verified: `node --check`, CSS comment-balance script 0, ruff clean,
plugin-loader/manifest suite 70 passed / 6 skipped. **NOT committed, NOT
yet verified live.**

**Follow-up, same session: the ACTUAL "show both" request, resolved
(uncommitted).** After two rejected split-pane-browser proposals
("nono") and an image that repeatedly failed to send (over size limit),
user re-explained in plain words: they wanted their own identity hash
AND their hosted NomadNet node's hash both visible/copyable on the
Reticulum Dashboard, to eyeball whether the node is running -- NOT a
two-arbitrary-nodes compare view at all. The earlier "techinc" hashes
were just example data, not two nodes to browse side by side.

Real gap found: `NomadNode.status()` (nomad_node.py) never included the
node's own destination hash at all -- only `hosting`/`name`/`pages`/
`requests_served`/`last_announce_s_ago`. The Reticulum Dashboard's "You"
stat card was always showing the LXMF identity hash only, because that's
literally the only hash the backend exposed -- there was nothing to show
for the node even if the frontend had wanted to. A NomadNet node's
destination hash is genuinely different from the identity's LXMF/delivery
hash (different aspect namespace hashed separately, same identity/same
box) -- confirmed against `_address_hex()` (`self._destination.hash.hex()`),
already existed as a private helper, just never surfaced.

- `nomad_node.py` `status()`: added `"hash": self._address_hex()`.
- `test_nomad_node.py::test_status_shape`: +1 assertion (`st["hash"] ==
  ""` in the not-hosting-yet state, matching `_address_hex()`'s own
  documented pre-start fallback).
- `reticulum_dashboard.js`: new 7th stat card "Nomad Node", `hidden`
  by default -- only shown when `GET /api/reticulum/status`'s `node`
  field is non-null (node hosting configured at all; same gate the main
  Reticulum page's Pages tab uses). Shows the hash when `node.hosting`,
  "Not hosting yet" for the window between "configured" and "destination
  actually registered". No copy button added -- plain selectable text,
  same as the existing "You" card already was.

Verified: `node --check`, `ruff check` clean on both plugin dirs,
`test_nomad_node.py` 35/35, full reticulum backend suite (minus the
pydantic-gated config_routes file, same Mac constraint as before) 219
passed / 35 skipped. **NOT committed, NOT yet verified live** -- worth
Pi-checking specifically since this is the first change this session that
touches the reticulum plugin's *backend* (everything else was frontend-
only) -- confirm the hash actually shows and matches what `info.mu`/the
main Reticulum page's own header line reports for the hosted node.

**Nomad-node hash — LIVE VERIFIED on the VM (Sept 14).** User hit exactly
the deploy-timing trap flagged when this landed: browser hard-refresh
alone doesn't apply backend Python changes (`nomad_node.py`'s new
`status()["hash"]` field), needs `sudo systemctl restart meshpoint` too.
Confirmed via the `/api/reticulum/status` JSON directly (`"node"` object
had no `"hash"` key at all pre-restart -- not empty, absent -- proving old
code was still running) before the restart, then confirmed working after.
Dashboard's "Nomad Node" stat card now shows `693b94beae452e8bf286aca4d3193cfc`
correctly on vm-meshpoint.

**Follow-up: "You" hash bracket inconsistency (uncommitted, JS-only).**
User noticed "You" showed `<22a60e4b...>` (angle brackets) while "Nomad
Node" showed plain `693b94be...` -- traced to `own_address` being built
via `RNS.prettyhexrep()` (lxmf_service.py, Reticulum's own log-display
convention) vs. my `node.hash` being plain `.hex()`. Stripped brackets
client-side in `reticulum_dashboard.js`'s `_loadStatus()` only (regex
`.replace(/[<>]/g, '')`) -- scoped to this page, `own_address` stays
bracketed everywhere else (e.g. the Reticulum page's own header) since
that's not this page's call to change. Plain hex is also the more useful
format for the stated "easy to copy" goal -- no bracket-trimming needed
before pasting into an address bar or curl command. Verified: `node
--check`, ruff clean. JS-only, hard refresh applies it, no restart
needed.

**Follow-up, same session: new "top" sidebar category (uncommitted,
shared core plugin infra).** User: get Reticulum Dashboard out from under
Networks, next to the built-in Dashboard itself. Confirmed no existing
category did this -- Dashboard isn't a `KNOWN_SIDEBAR_CATEGORIES` value
at all, it's a bare ungrouped `<li>` above the "Networks" header with no
`data-category` marker, and `_findInsertionTarget()` only knew how to
insert relative to a group header or a nested group. Built as a genuine
new category (same weight/precedent as the earlier `requires` field
generalization -- shared infra, not scoped to one plugin):

- `src/plugins/manifest.py`: `KNOWN_SIDEBAR_CATEGORIES` gains `"top"`.
- `sidebar_plugin_registry.js`: `_findInsertionTarget()` gets a new
  branch for `category === 'top'` -- anchors on `a[data-route="dashboard"]`'s
  `<li>` instead of a group header, then walks forward the *same* way
  every other category does (stop at the first `.sidebar__group-header`/
  `.sidebar__group`), so a second "top" plugin appends after the first
  instead of always reinserting directly under Dashboard and reversing
  order.
- `reticulum-dashboard/plugin.toml`: `category = "networks"` -> `"top"`.
- Docs: `PLUGINS.md`'s two `category = ...` examples + prose explanation
  updated (`top | networks | radio | ops | configuration | settings`);
  `reticulum-dashboard/README.md` and the CHANGELOG's own Reticulum
  Dashboard bullet both had stale "Networks -> Reticulum Dashboard"
  wording, fixed to describe the new placement.

Verified: `node --check` on `sidebar_plugin_registry.js`, manifest
re-parses (`category: top`), `discover_plugins()` still finds 15,
`ruff check` clean, plugin-loader/manifest suite 70 passed / 6 skipped
(no test pins the exact category set, so nothing else needed updating).
**NOT committed, NOT yet verified live** -- worth a specific live check
that the item actually lands directly under Dashboard (not, say, above
it or with a stray gap) once deployed.

**Follow-up, same session: Reticulum Browser -- rBrowser feature-parity
plugin, moved from community to bundled (uncommitted, new plugin +
CHANGELOG bullet).** User: liked fr33n0w's rBrowser
(github.com/fr33n0w/rBrowser), asked for a look at its license/features,
then to build a Meshpoint plugin with its feature set. Confirmed MIT
(verified the actual LICENSE file content directly, not just the README
claim) -- permissive, but the two codebases are structurally
incompatible to literally port between (rBrowser: one ~200KB Flask
index.html + Python backend; Meshpoint plugin: a small ES6 class reading
`/api/reticulum/nomad/*`) -- built as a clean-room feature-parity
reimplementation instead of a code port, documented as such.

**Scope, agreed before building ("tell me first" honored):** ported --
node picker/search, address bar, back/forward/reload, favourites (shared
list), Micron rendering, dark BBS-terminal page styling, all reusing
proven patterns from reticulum_nomad.js / the reticulum-dashboard
plugin's quick-browse modal. New for this plugin -- **multi-tab browsing**
(the real architectural piece: each tab = its own `{hash, path, title,
content, rawMode, history[], historyIdx}`; switching tabs never
re-fetches, just redisplays cached state), a **raw/rendered view
toggle**, and **keyboard shortcuts** (Ctrl/Cmd+T/W/R, Alt+←/→).
Deliberately deferred (documented, not silently dropped): fingerprint
identification (need to study rBrowser's actual verification model
first) and a local search engine + page cache (a background-crawler-
sized feature, its own service-seam plugin if built at all). Also
skipped, matching the dashboard modal's own scope line: form-field
submission, `/file/` downloads.

**Built first in `meshpoint-plugins` (community repo) as "rbrowser",
then moved into meshpoint core (bundled) as "reticulum-browser"** per a
follow-up request. Along the way:
- `make-repo-json.py` (meshpoint-plugins' catalog generator) gained
  `requires` surfacing in generated entries, mirroring how it already
  surfaces `hook_host` -- a genuine, permanent improvement to that script
  independent of this plugin, kept even after the plugin itself moved out.
- Rename: `rbrowser` -> `reticulum-browser` (folder, `name`, `[sidebar].route`,
  file names, the `RBrowserPanel` class -> `ReticulumBrowserPanel`, sidebar
  label "rBrowser" -> "Reticulum Browser"). Internal implementation-only
  identifiers (`_rb*` functions, `.rb-*` CSS classes, `data-rb-*`
  attributes) deliberately left alone -- invisible to users, renaming them
  across two files was pure risk for zero benefit.
- `locked = true` added (bundled-with-fork convention, matching
  reticulum/reticulum-dashboard) -- wasn't set for the community version.
- **Credit history, corrected mid-build:** first pass removed the
  external GitHub link/big license block entirely (misread "remove the
  stuff to the rnode github" as "strip all reference to the source").
  User corrected: "leave the url in the plugin so we refer to him at
  least" -- restored `[meta].homepage` pointing at
  `github.com/fr33n0w/rBrowser` and kept a full Credit section (with the
  same MIT-compliance framing already used for `reticulum_micron.js`'s
  own ported-from-reticulum-meshchat credit) in the plugin's README.md.
  Just dropped the in-UI "inspired by" link line from the page header
  itself, keeping the credit in metadata/README rather than the live page.
- **Self-containment, corrected mid-build:** first pass added
  `"reticulum-browser"` to `frontend/css/lorawan.css`'s shared
  `overflow-y:auto` selector list (now bundled in the same repo, so
  technically reachable) -- user pushed back ("no why" / "we have it all
  in the plugin"): a plugin shouldn't need a core-file edit just to
  exist, even a bundled one. Reverted `lorawan.css` to its exact
  committed state (confirmed via `git diff` -> empty); the plugin's own
  CSS keeps a **local** `.section[data-section="reticulum-browser"] {
  overflow-y: auto; }` rule instead, same self-contained pattern
  `reticulum-dashboard` would have used had it needed one (it didn't --
  fixed-height dashboard-shell page, different situation).

Verified: `node --check`, CSS comment-balance script 0, manifest
re-parses through meshpoint's REAL parser (`parse_manifest()`, not just
eyeballed -- `requires: reticulum`, `locked: True`, `route:
reticulum-browser`), `discover_plugins()` finds 16 (up from 15), `ruff
check` clean, plugin-loader/manifest suite 70 passed / 6 skipped,
`git diff frontend/css/lorawan.css` empty (confirms the revert landed
clean). meshpoint-plugins' own `apps/rbrowser/` removed, its `repo.json`
regenerated (3 plugins, rbrowser gone). CHANGELOG bullet added + parses
(31 sections). **NOT committed, NOT yet verified live** -- first
backend-adjacent plugin this session built without ever touching a
running device at all (pure new-plugin add, no existing behavior to
regress) -- still worth a real restart + smoke test (open a tab, browse
a known node, confirm favourites sync with the other three surfaces)
before calling it done.

**Follow-up, same session: Reticulum Dashboard's Browse prefers the full
browser when installed (uncommitted).** User: can the dashboard's Browse
button open the reticulum-browser plugin's full multi-tab experience
instead of the smaller quick-view modal, if it's installed? Yes --
optional, soft integration (reticulum-dashboard doesn't `requires`
reticulum-browser, it's a nice-to-have, not a dependency):

- `reticulum_browser_panel.js`: `registerSidebarPage`'s `make()` now
  stashes the instance on `window.reticulumBrowserPanel` -- same
  feature-detection-handle pattern `app.js`'s own `window.dabPanel` (the
  sidebar mini-player's hook into DAB+) already uses, confirmed by
  grepping that exact precedent before copying it. New public
  `openHash(hash, label)` -- opens a fresh tab (never clobbers whatever
  the user already has open there), provisionally sets the tab title from
  `label` before `_fetch()`'s real data overwrites it.
- `reticulum_dashboard.js`: all three "Browse" call sites (the peer
  drawer's `onBrowse`, the inline peer-row button, the general
  Peers-panel-header button) now go through one new `_openBrowse(hash =
  null, label = null)` helper -- if `window.reticulumBrowserPanel` exists,
  navigates to `#/reticulum-browser` (plain `location.hash =`, same
  native hashchange event `router.js`'s own `navigate()` relies on, safe
  to trigger from outside the Router) and hands the hash off via
  `openHash()`; otherwise falls back to this page's own
  `ReticulumQuickBrowseModal`, completely unchanged. Fails open cleanly
  either way -- reticulum-browser being disabled/not installed just means
  every call site behaves exactly as it did before this change.

Verified: `node --check` both files, ruff clean, plugin-loader/manifest
suite 70 passed / 6 skipped, confirmed no leftover direct
`this._quickBrowse.open(...)` call sites outside the new helper's own
fallback line. **NOT committed, NOT yet verified live** -- worth checking
both states on a real device: reticulum-browser disabled (dashboard's
Browse should behave exactly as before) and enabled (Browse should jump
to a fresh tab there instead).
