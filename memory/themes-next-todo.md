# Themes — follow-up TODO

Backlog after the v0.8.1 themes + full frontend colour-tokenization push. See
[plugin-architecture-review.md](plugin-architecture-review.md) — the themes work
was "Spike 1" of that plan.

**Status (2026-09-01): everything below is done and Pi-verified except #3.**
18 themes ship (4 built-in + 14 bundled community incl. `colorblind-safe`).
Settings → Themes has the live builder with Save-to-device + the Installed-themes
manager (badges: Built-in / Community = locked/shipped / Custom = your saves,
only Custom is deletable). Topbar theme button: quick-click cycles, press-and-hold
opens a full picker popover.

Original backlog table, ranked by bang-for-buck:

| # | Item | What it is | Effort | Notes / why |
|---|------|-----------|--------|-------------|
| 1 | ~~**In-dashboard theme editor**~~ **DONE 2026-08-31 (download-only)** | New **Settings → Themes** sub-page. Default-theme picker moved here from Settings → System. Builder: pick a base theme, ~30 colour/opacity swatches (Base/Accents/Sidebar/Surfaces) live-previewing on the whole dashboard (`data-theme`=base + inline `setProperty` for diffs, `meshpoint:themechange` for charts/term), "Download theme.css" (self-contained: every token differing from dark baseline) + "Download theme.json". Reverts on route-leave. `frontend/js/settings/theme_editor.js` + `css/theme_editor.css`; `_bootThemeEditor` in app.js. | done | Stretch "Save as new theme" server-side deferred — download-only shipped as one PR. `--msg-*`/`--term-*` left to hand-edit (noted in the UI). |
| 2 | ~~**Community theme pack**~~ **DONE 2026-08-31** | Shipped `nord`, `solarized-dark`, `gruvbox-dark` (`frontend/themes/`). `tokyo-night` skipped for now (terminal already uses that palette). | — | 9 themes total in the picker. |
| 3 | **Plugin roadmap Phase 0** | Collapse `src/api/server.py`'s ~2,100-line `create_app` / `lifespan` into route + service **registries** (iterate a list instead of ~60 hand-wired `include_router` + global service wiring) | ~1 wk | The real architectural win the themes work warmed up for. Unlocks capture-sources / decoders / panels as modules (Phase 2–3). Less flashy, most leverage. No behaviour change — reviewed single PR; 143-file test suite + `docs/plans/*-tests/` gate it. |
| 4 | ~~**Server-side theme persistence**~~ **DONE 2026-08-31** | `dashboard.theme` in local.yaml = the default for browsers with no localStorage choice. Server stamps `data-theme` on `<html>` (no flash). Admin control at Settings→System; `PUT /api/config/dashboard/theme`. | — | Not per-*user* (single-operator box) but per-*browser* override + a server seed, which is the useful part. |
| 5 | ~~**Chart categorical palette**~~ **DONE 2026-08-31** | `meshpoint:themechange` re-themes charts, but axis-title / series colours are still hardcoded hex. Give charts a 6-colour colour-blind-safe categorical palette, theme-tuned, driven from `ChartTheme.ink()` | ~1 d | Last "functional but not polished" spot in light mode (RF spectrum, node metrics, thermals, repeater trends). |
| 6 | ~~**Light theme visual polish pass**~~ **DONE 2026-08-31** | With the app running: walk each page in `light`, tighten anything still slightly off (contrast on faint chips, a few `--sunken`/`--bg-inset` shades). Charts (#5) are the biggest remaining gap. | ~2–3 h | Needs eyes-on; can't be done blind. |

## Order (agreed 2026-08-31)

1. ~~#2 community theme pack~~ — **done** (nord / solarized-dark / gruvbox-dark)
2. ~~#4 server-side theme persistence~~ — **done**
3. ~~#5 chart categorical palette~~ — **done**
4. ~~#6 light theme polish pass~~ — **done, all pages verified**
5. ~~#1 in-dashboard theme editor~~ — **done** (download-only; Settings → Themes)
6. **#3 plugin roadmap Phase 0** — last; it's a context switch (deep backend), give it undivided focus

## Also done (2026-08-31)

- **Theme dir split**: built-ins in `frontend/themes/`, extras/community in
  `plugins/themes/` (first `plugins/` dir). `scan_themes` reads both, stamps
  `source: builtin|plugin`, sorts `(source_rank, order, label)` so built-ins
  always precede plugin themes — `order` collisions across the two sets no
  longer matter. Settings → Themes selectors group them in `Built-in` /
  `Community` `<optgroup>`s. `dashboard.plugins_dir` key; `/plugins/themes`
  mount. `order` is built-in-only now; plugin themes sort by normalised label.
  `theme.json` gained optional `author`/`homepage`/`description`.

Theme dir split + source tier Pi-verified working 2026-08-31.

- **Builder "Save to device" + "Installed themes" manager** (2026-08-31,
  Pi-verified: save / overwrite / delete all working): `POST /api/themes` writes
  `plugins/themes/<id>/` (admin+audit, no restart), `DELETE /api/themes/{id}`
  removes community themes. `src/api/theme_store.py` + `tests/test_theme_store.py`.
  Guards: slug regex, 64KiB, `@import` ban, built-in ids protected.

- **Community theme pack + a11y theme** (2026-08-31): 8 more dark palettes in
  `plugins/themes/` (dracula, catppuccin-mocha, rose-pine, everforest-dark,
  one-dark, kanagawa, github-dark, ayu-mirage) + `colorblind-safe` (Okabe-Ito
  accents, neutral high-contrast base). Own CSS, palette values only, credited.
  18 themes total. `high-contrast` stays the low-vision pick; charts already
  CB-safe fork-wide.

- **Hold-for-picker on the topbar theme button** (2026-09-01): ~450ms hold →
  popover listing all themes; quick click still cycles. `app.js` + `topbar.css`.

- **Locked theme pack** (2026-09-01): bundled `plugins/themes/` manifests carry
  `"locked": true`; `theme_store` won't overwrite/delete a locked folder;
  Installed-themes manager splits Community (locked, no delete) vs Custom (your
  saves, deletable). `scan_themes` adds `locked: bool` to plugin entries.

## Open

- **#3 plugin roadmap Phase 0** — still the big backend item. Now has a concrete
  driver: **ACARS** (see [plugin-architecture-review.md](plugin-architecture-review.md)).
  Agreed plan 2026-09-02:
  1. ~~**Track A** — embed ACARS as listener #6~~ **DONE 2026-09-02**:
     `src/audio/acars_listener.py` (copy of rtl433_listener), `acars_routes.py`,
     RTL-SDR → ACARS sub-tab (reuses `PagerPanel`), `install.sh` section 12
     (builds `f00b4r0/acarsdec` + `szpajder/libacars`), `tests/test_acars_listener.py`.
     No config section (matches rtl433/adsb). Not Pi-verified yet.
  2. **B1-B4** — Phase 0 (server.py route/service registry) -> Phase 2
     (capture-source registry + lifecycle, open `Protocol` enum) -> Phase 3
     (frontend panel registry) -> plugin manifest + `setup.sh`/deps mechanism.
     ~3 wk. Guarded by the 143-file suite + `docs/plans/*-tests/`.
     - ~~**B1** — router registry~~ **DONE + Pi-verified 2026-09-02**, scoped to
       routers only: `src/api/route_registry.py` + `_BUILTIN_ROUTERS` data list
       + loop in `create_app`. `lifespan` left alone (that's B2). Tests:
       `test_route_registry.py` (Mac), `test_create_app_routers.py` (CI/Pi).
       Deployed — no 404 on any sidebar page.
     - ~~**B2** — listener registry~~ **DONE 2026-09-02**, scoped to the 8
       RTL-SDR listeners only: `src/api/listener_registry.py` + `_BUILTIN_LISTENERS`
       list in server.py, `start_all()`/`stop_all()` in lifespan. The
       pipeline/tx/broadcaster/fan/led/button graph stays hand-wired (not
       repetitive). `Protocol` enum opening folded into B5. Tests:
       `test_listener_registry.py` (Mac), `test_create_app_listeners.py` (CI/Pi).
       Deployed + Pi-verified 2026-09-02 — FM radio, DAB+, ADS-B, P2000,
       Pagers, RTL433 all start with live data (pager trio = tuple spec, OK).
     - ~~**B3** — frontend panel registry~~ **DONE 2026-09-02**:
       `frontend/js/listener_panel_registry.js` (`window.registerListenerPanel`)
       + `listener_panel.js` collapsed to one `_subPanels` list. No JS tests in
       repo -> `node --check` + manual Pi verification. Deployed + Pi-verified
       2026-09-02 (P2000, DAB+, RTL433, ADS-B tabs — all 3 panel classes).
     - **B4** — `plugin.toml` manifest + loader + deps mechanism. Split:
       - ~~**B4a** — manifest schema + `src/plugins/manifest.py` parser +
         `discover_plugins()`~~ **DONE 2026-09-02**, pure Python, 17 tests,
         not wired in yet (no runtime change).
       - ~~**B4b** — loader + `PluginRegistry` facade + `config.plugins.<id>`
         gate~~ **DONE 2026-09-02**: `src/plugins/loader.py` + `registry.py`,
         `AppConfig.plugins: dict`, wired into `create_app` (with
         route_registry/listener_registry `.reset()` first). **Two tiers**
         (user): built-in `src/plugins/apps/<id>/` (loads unless
         `enabled: false`) + community `plugins/apps/<id>/` (opt-in
         `enabled: true`); built-in wins id collisions; `manifest.source`.
         ~24 pure-Python tests. `docs/CONFIGURATION.md` `## Plugins`. No plugin
         ships yet -> deploy is a no-op.
       - ~~**B4c** — serve + inject panel-plugin frontends~~ **DONE 2026-09-02**:
         `plugin.toml` `[frontend]` table, `src/plugins/assets.py`
         (`inject_plugin_assets` at the `<!-- meshpoint:plugin-panels -->`
         marker in index.html + `resolve_plugin_asset`), scoped
         `GET /plugins/apps/{id}/{path}` route in server.py (declared files
         only, both tiers, no traversal). 17 new pure-Python tests. Deploy
         no-op until a plugin exists.
       - **B4d** (optional, not started) — `setup.sh` / apt consent CLI
         (`meshpoint plugin setup <name>`), never auto-run. Lower priority now
         that B5 shipped `plugins/apps/acars/setup.sh` as a plain `sudo bash`
         script.
  3. ~~**B5** — extract ACARS into `plugins/apps/acars/`~~ **DONE 2026-09-02**.
     Community tier, opt-in `plugins.acars.enabled: true` + `setup.sh`. Removed
     from core: acars_listener.py, acars_routes.py, test_acars_listener.py,
     server.py wiring (routers 60->59, listeners 6->5), listener_panel.js
     `_acars*` + tab entry, listener.css acars rules, install.sh §12. CI runs
     `plugins/` now. `PluginRegistry.add_listener(name,build,wire)`.
     **Plugin roadmap B1-B5 complete.** ⚠️ deploy = behaviour change for ACARS
     users (must enable + run setup.sh).
  4. ~~**B6 — Plugins management page**~~ **DONE** (this note was stale —
     confirmed built 2026-10-11 while reviewing the backlog). Settings →
     Plugins exists: `GET /api/plugins` (`src/api/routes/plugin_routes.py:275`)
     lists every discovered plugin, built-in + community, with
     enabled/loaded/`restart_required`/deps/source/install info; `PUT
     /api/plugins/{id}` (`:291`) toggles `enabled` via `save_section_to_yaml`,
     refuses enabling with an off dependency, cascades disable to dependents
     (`:241`). Restart-required banner wired both ends (`:211` backend,
     `index.html:1080 data-restart-status` frontend). Frontend:
     `frontend/js/settings/plugins_panel_controller.js` (1714 lines) + nav
     entry `#/settings/plugins` (`index.html:337`) + panel markup
     (`index.html:1070-1099`). Also went beyond the original sketch:
     `/api/plugins/{id}/check` + `/check-all` (live re-run of `[deps]`
     check) and streamed setup (`/setup/stream`).
  5. ~~**B4d — deps-consent CLI**~~ **DONE** (also stale — confirmed built).
     `meshpoint plugin setup <id>` is `run_plugin_setup()`
     (`src/cli/plugin_command.py:164`): prints the manifest's apt/setup
     info, confirms via `_confirm()` (`:203`), runs `sudo bash setup.sh`
     (`:208`). `meshpoint plugin list`/`plugin check` also exist (`:25`/`:49`).
  6. **B7 — plugin config schema. Still open, confirmed not built** (no
     `config_schema` field anywhere in `PluginManifest`,
     `src/plugins/manifest.py:170-184`). `plugins.<id>` stays opaque today;
     ACARS hardcodes `_FREQUENCIES`/`_GAIN` in `backend/listener.py`.
     **Full design scoped 2026-10-11** (plan-mode session, not yet
     implemented — written here since the plan file itself is ephemeral):
     <br>• New `[config.<field>]` table in `plugin.toml`, read
     unconditionally (NOT gated behind a `provides` entry — `"config"` was
     briefly in `KNOWN_PROVIDES`, removed by `02e77123` since nothing ever
     implemented it, confirming the table shouldn't need a capability at
     all). One sub-table per field: `type` (`string`/`int`/`float`/`bool`/
     `select`/`float_list` — `float_list` added specifically for ACARS's
     frequency list rather than a generic nested scheme), `label`,
     `default` (mandatory — every field always has a value to fall back
     to), optional `hint`/`min`/`max`/`options` (`select` requires
     non-empty `options`). Field names `^[a-z][a-z0-9_]{0,38}$` (underscore,
     deliberately unlike the hyphen `_SLUG_RE`/`_ROUTE_RE` used everywhere
     else in this file, since a field name becomes a Python dict/kwarg
     key). <br>• New frozen `ConfigFieldSpec` dataclass + trailing
     `PluginManifest.config_schema: tuple[...] = ()` field (safe addition —
     all ~18 existing manifests have no `[config]` table, so every one
     parses to `()`, zero behavior change) + `_parse_config_schema()` in
     `src/plugins/manifest.py`, mirroring `_parse_sidebar`/`_parse_hook`'s
     style. Parse-time (author-facing) validation: unknown `type`, missing
     `default`/`label`, `select` without `options` or `default` not in
     `options`, `min > max`, numeric `default` outside its own `min`/`max`,
     `float_list` default not a list of numbers, or a `bool` sneaking into
     a numeric/select/string default (`isinstance(True, int)` is `True` in
     Python — needs an explicit `not isinstance(x, bool)` guard, same
     pattern the existing `meshpoint_api` check already uses) — all raise
     `PluginManifestError("config", ...)`, same as a bad `[sidebar]` today.
     <br>• New `src/plugins/config_schema.py` (FastAPI-free, like the rest
     of `src/plugins/`): `default_config(schema, raw) -> dict` fills ONLY
     missing keys from their field defaults (a present-but-invalid
     existing value is deliberately left alone — no silent config mutation
     as a side effect of booting); `validate_config_update(schema,
     submitted) -> (valid_values, errors)` is the one real enforcement
     point, used only by the new write route — coerces numeric strings,
     excludes `bool` from numeric coercion, checks `min`/`max`
     (per-element for `float_list`), checks `select` membership, collects
     every field's error rather than failing fast. `loader.py` gets one
     line (`conf = default_config(manifest.config_schema, conf)` before
     `PluginRegistry(manifest, conf)`) so a plugin's `register()` can
     always assume every declared field is present. <br>• `plugin_routes.py`:
     `_describe()` gains always-present `config_schema`/`config` keys
     (empty for schema-less plugins); new `PUT /api/plugins/{id}/config`
     (body `{"values": {...}}`) — 404 unknown plugin, 400 "nothing to
     configure" if schema empty, 400 listing any submitted key not in the
     schema (checked before validation, not folded into it), 400 with
     per-field errors from `validate_config_update`, else read-modify-write
     `_config.plugins.get(id, {})` exactly like the existing
     `_save_enabled()` does, `save_section_to_yaml`, audited as
     `config.plugin_config_update` (values logged directly — RF gain/
     frequency/device-index, nothing sensitive). Response
     `restart_required = plugin_id in loaded_names` (not an unconditional
     `true` like the enable/disable PUT — config is baked into a plugin's
     closures once at `register()` time, so a currently-disabled plugin has
     nothing running to go stale; noted as a conservative default since a
     `"service"`-type plugin reading live `AppConfig` instead of a snapshot
     wouldn't technically need one, but the manifest has no way to signal
     that distinction today). <br>• Frontend
     (`plugins_panel_controller.js`): a `.plugin-row__cfg` "Settings"
     button per row (only when `config_schema.length`), a new
     `this._expandedConfig` `Set` (mirroring the existing
     `this._collapsedGroups` fold state — expansion state lives in the Set,
     not the DOM, so it survives the full re-render `refresh()` already
     does after any save), pushed into `_render()`'s existing row-building
     loop as a `<tr class="plugin-row__config-row"><td colspan="4">`
     containing a `.cfg-form` built field-by-field from `config_schema`
     (reusing `configuration.css`'s already-global `.cfg-field` family —
     new CSS for the row/button chrome itself goes in `settings.css`
     alongside the other `.plugin-row__*` rules, not `configuration.css`).
     <br>• Tests: extend `tests/test_plugin_manifest.py` (pure Python,
     existing `_write_plugin()` helper) for every parse-time check above;
     new `tests/test_plugin_config_schema.py` (pure Python) for
     `default_config`/`validate_config_update`; extend
     `tests/test_plugin_routes.py` (FastAPI `TestClient`, needs the
     throwaway-venv approach already established this session) for the new
     PUT route's happy/validation/404/empty-schema paths and `GET`'s new
     keys. <br>• Also update `docs/PLUGINS.md` ("Your plugin's own config"
     + the "Current limitations" bullet about no plugin-contributed
     settings UI — note what's now possible vs. still true: no seam inside
     the core *Configuration* page itself, only Settings → Plugins).
     <br>• Explicitly out of scope / follow-up, separate repo: porting
     ACARS's actual `plugin.toml` to a real `[config]` table (its current
     `gain`/`device`/`freqs` Python defaults are all **strings**, e.g.
     `_DEFAULT_GAIN = "34"` — a `float`-typed schema field would hand
     `reg.config["gain"]` a Python `float`, cosmetically changing the
     `acarsdec` argv string; harmless almost certainly, but the porting
     author should double-check, not assume it's a no-op). <br>Ask to
     resume when ready to build.
  7. ~~**B8 — community plugin uninstall**~~ **DONE** (also stale — confirmed
     built). `DELETE /api/plugins/{id}` (`plugin_routes.py:590`) deletes a
     community plugin's folder, refuses built-ins/`locked` plugins, cleans
     up its `plugins.<id>` config key (`:627 remove_subsection_key`),
     reports `restart_required: true`.

  **Full remaining-work list + unfinished capability surface + docs debt:**
  see the "Plugin system — remaining work" section in
  [plugin-architecture-review.md](plugin-architecture-review.md).
  Not planned unless real external demand: out-of-tree `plugin add <url>`,
  pip deps, subprocess isolation, public SemVer contract (Phase 4 in that doc).
