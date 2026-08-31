# Plugin architecture review — "should everything be plugins?"

**Date:** 2026-08-31
**Question asked:** Is it an idea to have everything in plugins? e.g. an `rtl-sdr`
plugin holding all SDR functionality, a `themes` plugin with extra themes, a
`lorawan` plugin (install it ⇒ LoRaWAN decoding becomes available), etc. Is this
doable in Meshpoint, and is it a good idea?

**Verdict:** **Do it partially — as internal modularization, not a user-facing
plugin marketplace.**

---

## Executive summary

Meshpoint has real seams to exploit (capture sources, packet callbacks, a portnum
handler dict, a dangerous-action registry, config feature-flags), but the
top-level wiring is aggressively centralized:

- [src/api/server.py](../src/api/server.py) is a ~2,100-line hand-wired
  `create_app` + `lifespan` — ~90 static route-module imports, ~60 explicit
  `app.include_router(...)`, every service `global`-assigned and started/stopped
  by hand, `init_routes(...)` module-global injection everywhere. Nothing
  iterates a list.
- Frontend has **no module system**: 139 `<script>` tags in
  [frontend/index.html](../frontend/index.html) dumping classes onto `window`,
  load-order-sensitive, no bundler.
- Deployment is in-tree git: `git reset --hard origin/<branch>` +
  `pip install -r requirements.txt` + `systemctl restart`
  ([src/api/update/apply.py](../src/api/update/apply.py)). No package manager,
  no `plugins/` dir, no entry-points scan. Dashboard apply deliberately does
  **not** run `install.sh` (no apt on every update).

**Biggest non-technical blocker:** this repo is a fork that upstreams one PR at a
time to KMX415/meshpoint (see [upstream_sync_todo.md](upstream_sync_todo.md),
`docs/plans/master-pr-roadmap.md`). A plugin framework is an all-at-once change
upstream must bless, or the fork diverges permanently and every upstream merge
becomes a conflict minefield.

**Do anyway (wins regardless):** collapse the god-function wiring into registries,
ship an auto-scanned `themes/` directory, formalize the feature-flag "modules"
already emerging (`capture.sources`, `rtl_sdr_page_enabled`, `transmit.enabled`,
`fan.enabled`, …).

---

## Findings from the codebase

### Extension points that already exist

| Seam | Location | Quality as a plugin hook |
|---|---|---|
| Capture sources | `CaptureCoordinator.add_source()`, `src/capture/capture_coordinator.py`; `capture/base.py` defines the interface | **Good.** Clean `start()/stop()/packets()`, name-prefixed, isolated. |
| Packet callbacks | `PipelineCoordinator.on_packet(cb)` `src/coordinator.py:136` | **Good.** Exception-isolated fan-out list. MQTT, upstream, public radar, inbound responder all attach here. |
| Portnum decoders | `_HANDLERS` dict in `src/decode/portnum_handlers.py` | **Good but narrow** — already a registry; Meshtastic sub-messages only. |
| Dangerous actions | `DangerousActionRegistry` `src/api/dangerous/` | **Good precedent** for a typed, permissioned action registry. |
| Remote command handlers | `handler.register("ping", …)` `src/api/upstream_client.py:306` | Registry precedent. |
| Config | dataclass tree + `default.yaml` ⊕ `local.yaml` deep-merge, `src/config.py` | **Partial.** Merge is generic; schema is a closed dataclass set, no third-party namespace. |
| Themes | `data-theme` attr + CSS file + `valid` array in `frontend/js/theme_controller.js` + `<link>` in index.html | **Almost data-driven already.** 3 hardcoded names (`dark`, `high-contrast`, `sunlight`). |
| SDR arbitration | `sdr_registry` module-global mutex `src/audio/sdr_registry.py` | Shows the hardware-contention problem plugins inherit. |

### Coupling that blocks a plugin-first rewrite

1. **`create_app` / `lifespan` is a manual assembly line.** New capability = edit
   server.py in 3–5 places. Nothing iterates a registry.
2. **`Protocol` is a closed enum** (`src/models/packet.py:11`):
   `MESHTASTIC/MESHCORE/LORAWAN/DAPNET/PAGER`. `PipelineCoordinator._process_capture`,
   `_update_node`, `_store_telemetry` all branch `if packet.protocol == Protocol.X`.
   A decoder plugin cannot add a protocol without editing the core enum +
   coordinator branches + DB assumptions.
3. **`PacketRouter.__init__` hardcodes three decoders**
   (`src/decode/packet_router.py:28`) with a fixed try-order. No registry.
4. **Frontend has zero packaging.** Global `window.*`, load order matters.
   `serve_dashboard_root` already rewrites asset URLs with a cache-bust token but
   the list is static HTML.
5. **Deployment is in-tree git.** No `plugins/` dir, no `pip install <plugin>`.
   `apply.py` deliberately excludes apt — any plugin needing `rtl_433`,
   `dump1090`, `nrsc5`, `redsea` can't self-provision.
6. **Single trust boundary.** The `meshpoint` service user has sudo rules
   (`config/sudoers-meshpoint`). In-process Python plugins run with that
   authority. No sandbox, and hard to add one.

---

## Proposed plugin architecture (if pursued)

### Plugin package shape

```
plugins/rtl-sdr/
  meshpoint_plugin.yaml   # manifest: id, version, meshpoint_api range, deps, permissions
  backend/__init__.py     # def register(reg): ...
  frontend/               # js/css served under /plugins/rtl-sdr/
  config_schema.py        # dataclass fragment, namespaced under config.plugins.<id>
  requirements.txt        # pip deps (installed on enable)
  system-deps.txt         # apt packages — DECLARED, installed only by the SSH install step
```

### Contribution API (`meshpoint.plugin_api`, SemVer-versioned)

```python
class PluginRegistry:
    def add_capture_source(self, factory: Callable[[AppConfig], CaptureSource]) -> None
    def add_decoder(self, protocol_id: str, decoder: Decoder, *, try_order: int) -> None
    def add_router(self, router: APIRouter, *, auth: bool = True) -> None
    def add_service(self, svc: Service) -> None          # Service = start()/stop()
    def add_packet_callback(self, cb: Callable[[Packet], None]) -> None
    def add_sidebar_entry(self, entry: SidebarEntry) -> None
    def add_frontend_assets(self, js: list[str], css: list[str]) -> None
    def add_theme(self, theme_id: str, css_path: str, label: str) -> None
    def add_dangerous_action(self, action: DangerousAction) -> None
    def on_startup(self, hook) / on_shutdown(self, hook)
```

`create_app` becomes: build core → `for p in plugin_manager.enabled(): p.register(reg)`
→ apply everything the registry collected. `lifespan` iterates `reg.services`.

### Lifecycle

| Phase | Mechanism |
|---|---|
| Discover | Scan `plugins/` at boot; read manifests |
| Enable/disable | `config.plugins.<id>.enabled` in `local.yaml`; **restart to apply** (no hot reload; update flow already restarts) |
| Install | Drop directory (submodule / tarball / `meshpoint plugin add <url>`) → `pip install -r` deps → restart. System deps require the SSH `install.sh` path. |
| Update | Plugin has its own version; `meshpoint plugin update`, or bundled with core git pull |
| Uninstall | Remove directory + its config namespace + restart |

### Dependency / version management

- Core exposes `meshpoint.plugin_api.__version__` (SemVer). Manifest declares
  `meshpoint_api: ">=1.2,<2"`. Manager refuses incompatible plugins, logs a
  banner line (matching the `PIPELINE/RELAY/MQTT` startup banner style).
- Inter-plugin deps: manifest `requires: [rtl-sdr]`. Manager topo-sorts
  `register()` order; hard-fails on missing/cycle.

### UI integration / discovery

- `GET /api/plugins` → enabled list + asset manifest. `serve_dashboard_root`
  (already rewriting HTML) injects `<script>`/`<link>` for enabled plugins.
- Sidebar router (`frontend/sidebar/router.js`) reads sidebar entries from that
  endpoint instead of hardcoding.
- A "Plugins" card under Settings: list, enable/disable toggle (writes config,
  prompts for restart), shows declared permissions + version compat.

### Configuration & permissions

- Config: third-party keys live under `config.plugins.<id>.*`, never in the core
  dataclass tree.
- Permissions: manifest declares
  `permissions: [radio_tx, shell, network_out, gpio, filesystem_write]`.
  **Disclosure, not enforcement** — in-process Python can't be contained. The
  Plugins UI shows them; enabling a `radio_tx`/`shell` plugin gets an extra
  confirmation (reuse the dangerous-action modal). Real isolation needs a
  subprocess + IPC contract — only justify that for genuinely untrusted code.

---

## Example plugin breakdown

### 1. `themes` — feasible, low value as a "plugin", high value as a directory

- **Effort:** 1–2 days. **Risk:** trivial.
- Make `theme_controller.js` read available themes from a manifest; auto-scan
  `themes/*/theme.css` + `theme.json` (id, label); server lists them.
- Don't build a plugin *framework* for this. A scanned `themes/` folder anyone
  can drop a CSS file into is the right size. Step 1 regardless — proves the
  asset-manifest pattern with zero blast radius.

### 2. `rtl-sdr` — feasible as a vertical slice, blocked by system deps

- **Effort:** 1–2 weeks. **Risk:** medium (touches lifespan, router list,
  frontend, sidebar).
- Cohesive set: `src/audio/` (7 listeners), `{listener,pager,rtl433,dab,adsb}_routes.py`,
  `sdr_registry`, `listener_panel.js` / `dab_panel.js` / `adsb_panel.js` /
  `pager_*.js`, sidebar badges, `capture.rtl_sdr_page_enabled`.
- **Blockers:** needs `rtl_fm`, `ffmpeg`, `redsea`, `rtl_433`, `dump1090`/`nrsc5`
  on `PATH`. "Install plugin ⇒ SDR works" is a lie on a locked-down Pi — apt is
  deliberately excluded from dashboard updates. Best case: "enable plugin ⇒ SDR
  features appear *if binaries present*", ≈ what `rtl_sdr_page_enabled` already does.
- **Recommendation:** first-party in-tree module with a clean `register()` and a
  real enable/disable toggle. Not out-of-tree, not runtime-installed.

### 3. `lorawan` decoder — most interesting architecturally, hardest to do cleanly

- **Effort:** 2–3 weeks incl. the enum/coordinator refactor. **Risk:** high
  (core pipeline path).
- Surface area: `PacketRouter` hardcoded `self._lorawan`; `PipelineCoordinator`
  `_lorawan_keystore`, `_setup_channel_keys` iterating `config.lorawan.devices`;
  `Protocol.LORAWAN` special-cased in `_update_node`/`_store_telemetry`; the
  `Protocol` enum; `lorawan_routes.py` + `lorawan_config_routes.py`;
  `lorawan_panel.js`; `lorawan.css`; config block; `_build_advert_steps` carve-out.
- **Prerequisite:** open up protocol identity — `Protocol.EXTENSION` +
  `protocol_subtype: str`, or migrate to string protocol IDs. Then decoders
  become `reg.add_decoder("lorawan", …)` and coordinator `if protocol == X`
  branches become capability queries (`decoder.produces_node_updates`,
  `decoder.produces_telemetry`).
- Until that refactor, a LoRaWAN "plugin" is just moving coupled code behind a
  thin shim — cosmetic.

---

## Migration roadmap

**Phase 0 — decouple, no behavior change (do this anyway).**
1. `Service` protocol (`start()/stop()`); collect lifespan services in a list;
   shrink `lifespan` from ~40 blocks to a loop.
2. Route registry: `create_app` iterates a list of `(router, auth)` instead of
   60 `include_router` calls.
3. Server-render the frontend asset list from a manifest; keep cache-bust behavior.
- *Risk:* startup-ordering regression. *Mitigation:* 143-file test suite +
  `docs/plans/*-tests/` gate docs; land as one reviewed PR.

**Phase 1 — themes directory.** Auto-scan `themes/`, manifest endpoint,
`theme_controller.js` reads it. Ship one extra theme to prove it.

**Phase 2 — decoder registry + open protocol id.** Enum → `EXTENSION`+subtype or
strings; `PacketRouter` and coordinator branches become registry + capability
checks. Migrate LoRaWAN onto it as the reference decoder (still in-tree).

**Phase 3 — internal `PluginRegistry`, in-tree only.** Convert RTL-SDR and
LoRaWAN to `register()` modules living in `plugins/` inside the repo. Config
namespace `config.plugins.<id>`. Plugins UI card with enable/disable + restart.

**Phase 4 — out-of-tree plugins (only if real external demand).**
`meshpoint plugin add <url>`, pip-dep install on enable, SemVer API contract,
permission disclosure UI. Consider subprocess isolation for untrusted sources.

### Stay core vs. move to plugins

| Stay core | Candidate plugins (in-tree first) |
|---|---|
| Capture pipeline, CaptureCoordinator | RTL-SDR listeners (FM/WFM/DAB/ADS-B/pager audio), `rtl_433` |
| Meshtastic + MeshCore decode, crypto, PKI | LoRaWAN decode |
| Storage, repos, DB schema/migrations | MQTT bridge / Meshradar map-report |
| Auth, config, update/rollback, WebSocket | Reticulum / LXMF |
| Coordinator, relay, TX, duty-cycle (safety-critical) | Home Assistant integration, DAPNET/POCSAG |
| Location/GPS, hardware (fan/LED/button) | Prometheus exporter, webhook engine, extra themes |

---

## Trade-offs

- **Maintainability:** +clearer boundaries long-term; Phase-0 registry work is a
  strict win (the god-function is the real pain). −a full framework is a
  permanent carrying cost on a fork that upstreams incrementally.
- **Performance:** in-process — negligible (ms of discovery at boot).
  Subprocess-isolated — real IPC + memory cost, matters on a Pi.
- **Security:** in-process plugins = arbitrary code with the service user's sudo
  rights. "Install this plugin" ≈ "run this as near-root." Fine for a
  single-operator box; not marketplace-safe. Permission manifests are disclosure
  only unless you pay for subprocess isolation.
- **Developer experience:** +third parties add protocols/sources without touching
  core. −you own a stable public API, its docs, contract tests, deprecation
  policy forever.
- **Backward compatibility:** `Protocol` enum, config schema, DB schema all leak
  into any plugin API. Namespacing config under `plugins.<id>` and opening
  protocol identity are prerequisites, not afterthoughts.

---

## Final recommendation

**Do it partially.**

- **Yes now:** Phase 0 (registry refactor of route/service wiring) + Phase 1
  (themes directory). Low-risk, improve the codebase unconditionally, each a
  clean single PR upstream can accept on its own merits.
- **Yes, deliberately:** Phase 2–3 — decoder registry, open protocol id, an
  *internal* `PluginRegistry` with in-tree `plugins/` modules and enable/disable
  toggles. ~90% of the user-visible benefit ("turn LoRaWAN / RTL-SDR on/off",
  clear module boundaries) without a distribution mechanism or a security
  boundary you can't honor.
- **No, not now:** a true out-of-tree, install-at-runtime, sandboxed plugin
  ecosystem. Because: (1) the fork / one-PR-at-a-time workflow makes a big-bang
  framework prohibitively expensive to carry; (2) in-process Python gives no real
  isolation — "install a plugin" = "trust arbitrary code with sudo"; (3) the
  highest-value example (rtl-sdr) needs apt packages the update path won't touch,
  so "just install it" breaks anyway; (4) a single-device deployment needs
  disable-able modules, not an ecosystem — and feature flags already half-deliver
  that.
