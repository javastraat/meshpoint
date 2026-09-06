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

- [ ] **Phase 0** — `add_service` core seam + repoint `write_rnsd_config.py`
- [ ] **Phase 1** — plugin backend scaffold (service + routes + peer repo + state), disabled by default
- [ ] **Phase 2** — plugin frontend (sidebar page, **topbar pill**, settings tab)
- [ ] **Phase 3** — Messages page routes reticulum sends to `/api/reticulum/send`
- [ ] **Phase 4** — live-verify on the Pi (atomic config flip — see note), screenshots
- [ ] **Phase 5** — delete core reticulum service/routes/config/frontend
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

### Phase 0 — `add_service` core seam (no plugin yet)

| File | Change |
|---|---|
| `src/api/service_registry.py` | **new** — `ServiceSpec(name, build, wire)`, `register_service()`, `build_all()`, `start_all()`, `stop_all()`, `wire_all(pipeline)`. FastAPI-free (unit-tests on Mac). |
| `src/plugins/registry.py` | `reg.add_service(name, build, wire=None)` — requires `"service"` in `provides`. `build()` → service object; `wire(service, pipeline)` runs after `pipeline.start()`. |
| `src/plugins/manifest.py` | `KNOWN_PROVIDES += "service"` |
| `src/api/server.py` lifespan | `service_registry.build_all()` + `start_all()` where `_reticulum_service.start()` is now; `stop_all()` in shutdown block |
| `tests/` | `test_service_registry.py`, extend `test_plugin_loader.py` |

**Wrinkle:** `scripts/write_rnsd_config.py` runs as **rnsd's `ExecStartPre`**
(separate process) and does `load_config().reticulum.rnode_*`. Breaks when
`ReticulumConfig` is deleted. Repoint it at `config.plugins["reticulum"]`
in this phase (it's already reticulum-specific). Also: `_run_systemctl` is
imported privately from `rnode_firmware_routes.py` (staying in core) —
lift it to a shared `src/api/` helper so the plugin doesn't depend on a
private name.

Ship as its own commit; verify with a no-op test plugin before touching Reticulum.

### Phase 1 — plugin backend scaffold (coexists, `enabled: false` default)

```
plugins/apps/reticulum/
  plugin.toml          provides = ["service", "routes", "sidebar", "topbar"]
                       locked = true
                       [sidebar] route="reticulum" label="Reticulum"
                                 category="networks" icon="reticulum"
                       [frontend] scripts = [panel, topbar_chip, settings_tab]
  backend/
    __init__.py        register(reg): state.init(reg.config);
                       add_router(routes.router); add_router(config_routes.router);
                       add_service("reticulum", build, wire)
    lxmf_service.py    ← src/reticulum/lxmf_service.py (keep deferred RNS/LXMF imports)
    peer_repo.py       ← src/storage/reticulum_peer_repository.py
    routes.py          ← src/api/routes/reticulum_routes.py
    config_routes.py   ← src/api/routes/reticulum_config_routes.py
    state.py           reads reg.config: display_name, dirs, rnode_*, backbone_*
                       (mirror dapnet/backend/state.py)
    tests/
  README.md            like plugins/apps/dapnet/README.md
```

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
