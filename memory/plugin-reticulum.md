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
- [ ] **Phase 2** — plugin frontend (sidebar page, **topbar pill**, settings tab) + move `config_routes.py` in (`/api/config/reticulum/*`, adapted to `plugins.reticulum.*` writes like dapnet's `state._persist()`) + lift `_run_systemctl` → `src/api/systemctl.py`, add `sidebar`+`topbar` to `provides`
- [ ] **Phase 3** — Messages page routes reticulum sends to `/api/reticulum/send`
- [ ] **Phase 4** — live-verify on the Pi (atomic config flip — see note), screenshots
- [ ] **Phase 5** — delete core reticulum service/routes/config/frontend. **Includes** repointing `scripts/write_rnsd_config.py` off `config.reticulum` → `config.plugins["reticulum"]` (can't do it earlier — would break the live Pi's rnsd, which reads the old path until the atomic Phase 4 flip).
- [ ] **Phase 6** — docs (CHANGELOG v0.8.1, PLUGINS.md, CONFIGURATION.md, README, API-ENDPOINTS, plugin README)

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

**Core untouched.** Zero `src/` changes. `src/reticulum/`, `reticulum_routes.py`,
`reticulum_config_routes.py`, `reticulum_peer_repository.py` all still present and
authoritative — deleted in Phase 5.

**test_plugin_loader.py:** +`TestShippedReticulumPlugin` (2 tests, `@skipUnless(_HAS_FASTAPI)`).
Also gated `TestShippedDapnetPlugin` the same way — it was failing (not skipping) on
the Mac, now matches `TestShippedAcarsPlugin`. Suite is fully green on the Mac now.

Verified: `pytest plugins/apps/reticulum/ tests/test_plugin_loader.py tests/test_service_registry.py`
→ 35 passed, 6 skipped. `ruff check src/ tests/ plugins/` clean. Manifest parses
(`provides=('service','routes') locked=True`). CHANGELOG parses (v0.8.1, 69 bullets).

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

### Phase 3 — chat send path (option 1)

- `frontend/js/messaging_chat.js` / `messaging_contacts.js`: `protocol === 'reticulum'`
  thread → POST `/api/reticulum/send` instead of `/api/messages/send`.
- Conversation list/history unchanged.
- Core `messages.py` branch left in place (dead once frontend switches); deleted Phase 5.

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
