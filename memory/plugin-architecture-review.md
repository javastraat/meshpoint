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

---

## Getting started — Spike 1: pluggable themes directory

**Status: implemented 2026-08-31** (not yet live-verified on the Pi). See
`memory/project_m1_meshpoint.md` → "Plugin architecture — Spike 1" for the full
change list. New: `src/api/theme_registry.py`, `src/api/routes/theme_routes.py`,
`frontend/themes/{dark,high-contrast,sunlight,amber-mono,green-crt,light}/`,
`tests/test_theme_registry.py` (9 tests green). Deleted:
`frontend/css/theme_high_contrast.css`. `light` is a v1 (chrome flips, but
hardcoded white overlays / chat+terminal panels / charts / map tiles stay dark —
full polish is the staged light-theme task).

The smallest end-to-end slice that proves "drop a folder ⇒ capability appears"
without touching the pipeline, the `Protocol` enum, or the deployment model.
This is Phase 1; it also establishes the manifest-scan pattern that Phase 3
reuses for sidebar entries and frontend bundles.

| # | Task | File(s) | Notes |
|---|------|---------|-------|
| 1 | Create `frontend/themes/` with three theme folders, each `theme.json` (`{id,label,order,icon}`) + `theme.css` | `frontend/themes/dark/`, `frontend/themes/sunlight/`, `frontend/themes/high-contrast/` | Move the `[data-theme="sunlight"]` / `[data-theme="high-contrast"]` blocks out of `frontend/css/theme_high_contrast.css` verbatim — no visual change. **`dark` gets a folder as a registry entry only** (Option A): its `theme.css` is empty / `/* baseline palette lives in dashboard.css */`, so the picker lists it uniformly with no special-case `'dark'` string. The actual dark palette stays on bare `:root` in `dashboard.css` — a synchronously-loaded stylesheet — because it's the baseline everything renders against and the inline early-set `<script>` in `index.html` (~L1022–1049) exists precisely to avoid a flash. Leave the `@media (prefers-contrast: more)` auto-bump in a base CSS file. |
| 2 | Add `GET /api/themes` that scans `frontend/themes/*/theme.json` and returns the list | new `src/api/routes/theme_routes.py` (~30 lines), register in `src/api/server.py` | Unauthenticated is fine (same exposure as static CSS); sort by `order` then `label`; skip malformed JSON |
| 3 | Serve `frontend/themes/` as static files | `src/api/server.py` static mount | So each `theme.css` is reachable |
| 4 | `theme_controller.js`: fetch `/api/themes` on init, build `valid`/`order` from the response instead of the hardcoded arrays | `frontend/js/theme_controller.js` | Fall back to `['dark']` if the fetch fails; `dark` remains the default selection when nothing is persisted |
| 5 | Inject `<link rel="stylesheet">` per discovered theme at runtime (skip empty `theme.css` like `dark`'s) | `frontend/js/theme_controller.js` (or the `serve_dashboard_root` HTML rewrite) | Drop the per-theme `<link>` lines from `frontend/index.html` |
| 6 | Point the theme picker at the dynamic list | `frontend/js/app.js` — `_registerThemeToggle` (~L244, the `ICONS`/`LABELS` maps) and the `theme:cycle` command-palette entry (~L791) | Drive icon/label/order from the manifest; fallback icon for unrecognized ids; cycle the discovered id list, not the literal `['dark','high-contrast','sunlight']` array |
| 7 | pytest: temp dir with 3 fake `theme.json`, assert `/api/themes` returns them sorted and ignores malformed JSON | `tests/test_theme_routes.py` | Runs on the Mac, no hardware/venv deps |
| 8 | Add a new theme folder as the "does it actually work" demo (→ 4 selectable themes) | `frontend/themes/amber-mono/` | Acceptance test: add folder, restart, theme shows in picker — zero `.js` / `.py` edits |
| 9 | Changelog bullet under the current version section (`docs/CHANGELOG.md`); verify it parses with `ChangelogParser.parse_file` | `docs/CHANGELOG.md` | Per repo convention |

**Definition of done:** adding `frontend/themes/<x>/{theme.json,theme.css}` and
restarting makes `<x>` appear in the picker with no change to any `.js` / `.py`
file.

**Option B (follow-up, not Spike 1) — make `dark` a *real* theme file too.**
Extract the baseline palette out of `dashboard.css` into
`frontend/themes/dark/theme.css` (`:root, [data-theme="dark"] { … }`) so every
theme is genuinely a folder and `dashboard.css` carries no palette. Requires the
server to **inline the active base theme's CSS into `<head>`** via the existing
`serve_dashboard_root` HTML rewrite — otherwise a `<link>`-injected baseline
flashes unstyled on every page load. Worth doing once the plugin model needs
themes shipped fully out-of-tree; overkill for the first slice.

**Why this slice first:** no `apt` / `pip` deps, no out-of-tree code, no security
surface, ~1–2 days, and it lands as a self-contained PR upstream can take on its
own merits.

**Landed (2026-08-31):** Spike 1 shipped, and then the theme dir was split into
built-in (`frontend/themes/`) + **`plugins/themes/`** — the first concrete
`plugins/` directory. `scan_themes(themes_dir, plugin_themes_dir=None)` scans
both, built-in id wins collisions, plugin can't claim `dark`; plugin CSS gets a
dedicated `/plugins/themes` static mount; `dashboard.plugins_dir` config key.
This is the template for how later plugin surfaces (decoders, panels) get
discovered — a `plugins/<kind>/<name>/` folder + a manifest, scanned at boot.

**Next after it proves out:** Phase 0 route/service registry refactor of
`src/api/server.py` (bigger, but the highest-leverage internal win), then Phase 2
decoder registry + opening the `Protocol` enum.

---

## Reference plugin candidate: ACARS (2026-09-02)

The user wants ACARS decoding (aircraft VHF datalink, 131.525/131.725/131.800/
131.825 MHz) and explicitly does NOT want it embedded in core — wants it as a
plugin another operator can install. It's the ideal forcing function: same shape
as 5 existing listeners (`src/audio/{adsb,rtl433,pager,dab,rtl}_listener.py` —
spawn external decoder, parse output, feed pipeline), so the "add a 6th" pain is
concrete. Working standalone today: built `f00b4r0/acarsdec` (NOT the archived
`TLeconte/acarsdec`) + `szpajder/libacars` from source on the Pi, `acarsdec
--output monitor:file -g 34 --rtlsdr 0 <freqs>`.

What an ACARS plugin must provide / what the runtime must accept:
- capture-source class (start/stop/status)      -> Phase 0 service registry
- `/api/acars/*` routes                         -> Phase 0 router registry
- dashboard panel + sidebar + `#/acars` route   -> Phase 3 frontend panel registry
- config schema (freqs/gain/rtl device) + RTL claim via existing `sdr_registry`
- **system deps** (build acarsdec+libacars, apt pkgs) -> NEW: `setup.sh` +
  manifest run once with explicit consent, like `scripts/install.sh`'s opt-in
  arduino-cli / platformio / rnsd sections

**Path decided (2026-09-02):** `plugins/<kind>/<name>/` scheme — `plugins/themes/`
already works this way (`scan_themes`); "app" plugins go under **`plugins/apps/`**.

```
plugins/apps/acars/
  plugin.toml            # name, meshpoint_api, provides=[capture_source,routes,panel], apt=[...], setup="setup.sh"
  backend/__init__.py    # def register(reg): reg.add_capture_source(...); reg.add_router(...); reg.add_config(...)
  backend/listener.py    # ~ copy of adsb_listener.py
  backend/routes.py
  frontend/acars_panel.{js,css}
  setup.sh
```

ACARS needs essentially the whole roadmap (Phase 0 + 2 + 3 + a deps mechanism) —
themes was cheap because a theme is pure CSS with no code/lifecycle/deps; ACARS is
the opposite end (trusted in-process code + subprocess + system packages + panel).

**Agreed sequencing:** Track A (embed ACARS as listener #6) -> Phase 0 / 2 / 3 +
deps mechanism (B1-B4, ~3 wk) -> **B5: extract Track A's code into
`plugins/apps/acars/`** as the reference plugin. Nothing from Track A is wasted;
B5 is move + adapt.

**B1 DONE 2026-09-02 (scoped to the router registry only):**
`src/api/route_registry.py` (new, FastAPI-free — `register_router(router, *,
public=False)`, `registered()`, `reset()`, `RouterSpec` dataclass).
`src/api/server.py`: the 60 hand-wired `app.include_router(...)` calls are now
a module-level `_BUILTIN_ROUTERS: list[tuple]` (each `(router, public_bool)`,
12 public / 48 gated) driven by one loop in `create_app`, followed by a loop
over `route_registry.registered()`. Built-ins deliberately stay a greppable
list in server.py — they do NOT call `register_router`; the registry is purely
the plugin seam. No behaviour change. Tests: `tests/test_route_registry.py`
(5, pure Python, runs on Mac), `tests/test_create_app_routers.py` (CI/Pi only —
needs fastapi; shape + public-count snapshot + known auth-levels + no dup
route + mini-app wiring/plugin-mount check).
**NOT done in B1 (deferred):** the ~280-line `lifespan` dependency graph is
untouched — the listener/service lifecycle seam is B2's job.

**B2 DONE 2026-09-02 (scoped to the listener lifecycle only):**
`src/api/listener_registry.py` (new, FastAPI-free — `register_listener(spec)`,
`plugin_specs()`, `start_all(builtins)`, `stop_all()`, `live()`, `reset()`;
`ListenerSpec(name, build, wire)` where `build` returns a listener or a tuple
and `wire` gets that result). `src/api/server.py`: the 8 hand-constructed
listeners + their 8 `if x is not None: await x.stop()` shutdown blocks are now
a module-level `_BUILTIN_LISTENERS` list (6 specs — pagers is one spec that
builds the 3-tuple) passed to `listener_registry.start_all(_BUILTIN_LISTENERS)`
at lifespan startup and `await listener_registry.stop_all()` at shutdown.
`stop_all` catches per-listener stop errors so one bad stop doesn't abort
shutdown. Built-ins stay a greppable list in server.py — they do NOT call
`register_listener` (same split as `_BUILTIN_ROUTERS` vs `route_registry`).
Listeners are still built idle — their `/start` route starts them on demand.
Nothing outside server.py referenced the old `_rtl_listener …` globals; they're
gone. Tests: `tests/test_listener_registry.py` (7, pure Python, Mac),
`tests/test_create_app_listeners.py` (CI/Pi — needs fastapi: names/shape,
start_all wires all 6 route modules, `/status` routes answer `running:false`,
plugin spec builds after built-ins, listener↔router prefix alignment).
**NOT done in B2 (deferred):** the pipeline → tx_service → broadcaster →
fan/led/button graph in `lifespan` stays hand-wired (it's a real dependency
chain, not repetitive). The `Protocol` enum opening is folded into B5 — ACARS
is a standalone subprocess feed like rtl433 and doesn't tag the pipeline.

**B3 DONE 2026-09-02 (frontend panel registry):**
`frontend/js/listener_panel_registry.js` (new — `window.LISTENER_PANELS` array
+ `window.registerListenerPanel({tab, label, make})`; loaded in index.html just
before `listener_panel.js`). `listener_panel.js`: the 8 hand-wired non-radio
sub-panels (constructor `new`s, `hide()`, `_showActiveTab` if-chain,
`_switchTab` hides, `_mount` tabbar buttons + content divs + mount calls) are
now one `this._subPanels` list `[{tab, label, panel}]` — built from a greppable
`builtins` literal (pager helper for the 5 PagerPanel tabs; dab/adsb/dabconfig
gated on their own class) then `window.LISTENER_PANELS` mapped via `make()` and
appended. New `_subPanel(tab)` finder. `_mount` generates the non-radio tabbar
buttons + `#lsn-tab-<tab>` divs with `.map()`; radio tab stays a bespoke inline
literal + the default branch. `window.dabPanel` still set (found by tab==='dab')
for the sidebar mini-player. No visible change. No JS test framework in the repo
-> `node --check` + manual Pi tab-click verification. Built-ins-first ordering
like B1/B2.

**B4a DONE 2026-09-02 (plugin manifest schema + parser/discovery, not wired):**
`src/plugins/manifest.py` (new, FastAPI-free, stdlib `tomllib`):
`PLUGIN_API_VERSION = 1` (the contract number B1-B3's seams collectively define
-- bump when a seam's observable contract changes), `PluginManifest` frozen
dataclass, `parse_manifest(plugin_dir)`, `discover_plugins(apps_dir)`,
`PluginManifestError(code, message)` with codes
missing/toml/name/version/api/provides/deps/meta. `plugin.toml` schema:
`name` (== folder name, SLUG_RE), `version`, `meshpoint_api` (int >= 1, refused
if > PLUGIN_API_VERSION), `provides` (non-empty subset of
{listener,routes,panel,config}), optional `[deps]` (`apt` = list of pkg names,
`setup` = relative path that must exist), optional `[meta]`
(description/homepage/author strings). `discover_plugins` scans
`plugins/apps/*/plugin.toml`, skips+warns bad ones, returns sorted by name.
Tests: `tests/test_plugin_manifest.py` (17, pure Python, Mac). NOT wired into
`create_app` -- that's B4b (loader + `PluginRegistry` facade + `config.plugins.<id>`
gate). No runtime change, nothing to deploy.

**B4b DONE 2026-09-02 (plugin loader + PluginRegistry facade + config gate):**
`src/plugins/registry.py` (`PluginRegistry` — `.manifest`, `.name`, `.config`
[copy of `config.plugins.<id>`], `add_router(router, public=False)` ->
route_registry, `add_listener(spec)` -> listener_registry; each checked against
`manifest.provides` -> `PluginRegistryError`). `src/plugins/loader.py`
(`load_plugins(apps_dir, plugins_config) -> list[LoadedPlugin]`: discover ->
skip unless `plugins.<id>.enabled` truthy -> `_import_backend` via
`importlib.util.spec_from_file_location(..., submodule_search_locations=[backend/])`
so relative imports work and no `__init__.py` boilerplate needed under
`plugins/apps/` -> call `module.register(reg)`; any failure logged+skipped, one
bad plugin never stops boot). `src/config.py`: `AppConfig.plugins: dict`
(opaque, default `{}`); `_apply_yaml` pops `plugins` before the section loop and
merges per-id so a 2nd YAML adds rather than replaces, and
`_collect_unknown_keys` never sees `plugins.<id>.*`. `src/api/server.py`:
`create_app` does `route_registry.reset(); listener_registry.reset();
_loaded_plugins = load_plugins(Path(plugins_dir)/"apps", config.plugins)` before
the router loop — the resets clear ONLY plugin registrations (built-ins are the
`_BUILTIN_*` literals), so repeat `create_app()` is clean (refines B1's
no-reset note now that plugins register at create_app time, not import time).
`_loaded_plugins` module global kept for a future `/api/plugins` endpoint.
Tests (all pure-Python, pass on Mac): `tests/test_plugin_loader.py` (8),
`tests/test_plugin_registry_facade.py` (6), `tests/test_config_loader.py`
+PluginsNamespaceTest (3). `docs/CONFIGURATION.md` has a `## Plugins` section.
**NOT in B4b:** frontend asset mount/injection (B4c), `setup.sh`/apt consent
CLI (B4d). No plugin ships yet -> deploy is a no-op (loader returns [] with no
`plugins/apps/` dir).

**Track A DONE 2026-09-02:** `src/audio/acars_listener.py` (copy of
rtl433_listener), `src/api/routes/acars_routes.py`, RTL-SDR → ACARS sub-tab
(reuses `PagerPanel` + `_acarsRowHtml`), `scripts/install.sh` section 12,
`tests/test_acars_listener.py`. No config section. The 6 hand-wired `server.py`
spots this touches (import x2, global, lifespan start/stop, include_router) are
exactly what B1 (Phase 0 registry) removes -- B5 will delete them and register
via the plugin's `register()` instead.
