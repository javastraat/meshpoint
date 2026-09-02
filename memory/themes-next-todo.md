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
  4. **B6 — Plugins management page (user asked 2026-09-02, NOT started).**
     A Settings sub-page (sibling of Settings -> Themes) that lists every
     discovered plugin (built-in + community) and toggles each on/off.
     Sketch / open questions:
     - `GET /api/plugins` (new route module) -> per plugin:
       `{id, version, source, provides, description, homepage, enabled,
       loaded, apt, setup, deps_ok}`. `loaded` = in `server._loaded_plugins`
       this run; `deps_ok` = best-effort (e.g. `shutil.which` for a known
       binary?) or just surface `apt`/`setup` so the user knows to run it.
     - `PUT /api/plugins/{id}` `{enabled: bool}` (admin + audited) -> writes
       `plugins.<id>.enabled` into `local.yaml`. Needs the yaml-patch helper
       (`src/config.py save_section_to_yaml`, as `theme_routes` uses for
       `dashboard.theme`) -- but `plugins` is an opaque dict, not a dataclass
       section, so check `save_section_to_yaml` handles a plain-dict section
       or add a small `save_plugin_enabled(id, bool)`.
     - **Restart required**: plugins load once in `create_app`, so a toggle
       can't take effect live (unlike theme default). Page must show a
       "restart to apply" banner; maybe reuse the Settings -> Updates restart
       affordance, or just tell the user.
     - Frontend: `frontend/js/settings/plugins.js` + a nav entry; card per
       plugin (name, source badge builtin/community, version, provides chips,
       description, enable toggle, "needs setup.sh" hint when apt/setup set
       and not loaded despite enabled).
     - `_loaded_plugins` is already kept as a module global in server.py for
       exactly this.
  5. **B4d — deps-consent CLI (`meshpoint plugin setup <id>`).** NOT started,
     optional/low-priority. Reads a plugin's `[deps]`, prints the apt packages
     + `setup.sh` it would run, asks Y/n, then runs it (`sudo` needed for the
     apt/`make install`). Pairs with `meshpoint plugins list` (reuse B6's
     `GET /api/plugins` logic, or a shared `discover_plugins` call). Lower
     priority because B5 shipped `plugins/apps/acars/setup.sh` as a plain
     `sudo bash plugins/apps/acars/setup.sh` — the CLI is just nicer UX + a
     confirmation gate, not required.
  6. **B7 — plugin config schema.** `plugins.<id>` is opaque today; ACARS
     hardcodes `_FREQUENCIES`/`_GAIN` in `backend/listener.py`. Let a plugin
     declare a config schema (in `plugin.toml` or `register`) so B6's page can
     render a settings form and `config.plugins.<id>` gets defaulted/validated.
     Also: wire up `provides = ["config"]` (declared in `KNOWN_PROVIDES`, no
     `PluginRegistry.add_config` yet) or drop it. Do after B6.
  7. **B8 — community plugin uninstall.** "Remove" button on B6's page for
     community plugins → delete `plugins/apps/<id>/`, mirroring
     `theme_store.delete_theme`; built-ins locked like the locked theme pack.

  **Full remaining-work list + unfinished capability surface + docs debt:**
  see the "Plugin system — remaining work" section in
  [plugin-architecture-review.md](plugin-architecture-review.md).
  Not planned unless real external demand: out-of-tree `plugin add <url>`,
  pip deps, subprocess isolation, public SemVer contract (Phase 4 in that doc).
