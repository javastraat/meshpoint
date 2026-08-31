# Themes — follow-up TODO

Backlog after the v0.8.1 themes + full frontend colour-tokenization push. See
[plugin-architecture-review.md](plugin-architecture-review.md) — the themes work
was "Spike 1" of that plan.

**Status (2026-08-31): everything below is done and Pi-verified except #3.**
18 themes ship (4 built-in + 14 community incl. `colorblind-safe`); Settings →
Themes has the live builder with Save-to-device + the Installed-themes manager.

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

## Open

- **#3 plugin roadmap Phase 0** (unchanged — still last). The only item left on
  the whole themes track. Deep backend context-switch; do it with undivided
  focus, guarded by the 143-file test suite + `docs/plans/*-tests/`.
