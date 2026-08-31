# Themes — follow-up TODO

Backlog after the v0.8.1 themes + full frontend colour-tokenization push
(drop-in `frontend/themes/<id>/`, `GET /api/themes`, `meshpoint:themechange`
event, 6 shipped themes incl. the first light mode). See
[plugin-architecture-review.md](plugin-architecture-review.md) — the themes
work was "Spike 1" of that plan.

Ranked roughly by bang-for-buck. Not started unless noted.

| # | Item | What it is | Effort | Notes / why |
|---|------|-----------|--------|-------------|
| 1 | **In-dashboard theme editor** | Settings panel: ~25 colour swatches live-previewing on the page; "Download theme.css" button; stretch = "Save as new theme" writes the folder server-side | ~2–3 d | Cashes in the "easy to make themes" story — no text editor needed. Strong community/Discord hook. One PR. |
| 2 | ~~**Community theme pack**~~ **DONE 2026-08-31** | Shipped `nord`, `solarized-dark`, `gruvbox-dark` (`frontend/themes/`). `tokyo-night` skipped for now (terminal already uses that palette). | — | 9 themes total in the picker. |
| 3 | **Plugin roadmap Phase 0** | Collapse `src/api/server.py`'s ~2,100-line `create_app` / `lifespan` into route + service **registries** (iterate a list instead of ~60 hand-wired `include_router` + global service wiring) | ~1 wk | The real architectural win the themes work warmed up for. Unlocks capture-sources / decoders / panels as modules (Phase 2–3). Less flashy, most leverage. No behaviour change — reviewed single PR; 143-file test suite + `docs/plans/*-tests/` gate it. |
| 4 | **Server-side theme persistence** | Theme choice is in `localStorage` (per-browser). Persist per-user like the other display prefs (`MeshpointDisplayForm` / `/api/config` display block) | ~½ d | Theme follows you across devices. Small. |
| 5 | **Chart categorical palette** | `meshpoint:themechange` re-themes charts, but axis-title / series colours are still hardcoded hex. Give charts a 6-colour colour-blind-safe categorical palette, theme-tuned, driven from `ChartTheme.ink()` | ~1 d | Last "functional but not polished" spot in light mode (RF spectrum, node metrics, thermals, repeater trends). |
| 6 | **Light theme visual polish pass** | With the app running: walk each page in `light`, tighten anything still slightly off (contrast on faint chips, a few `--sunken`/`--bg-inset` shades). Charts (#5) are the biggest remaining gap. | ~2–3 h | Needs eyes-on; can't be done blind. |

## Order (agreed 2026-08-31)

1. ~~#2 community theme pack~~ — **done** (nord / solarized-dark / gruvbox-dark)
2. **#4 server-side theme persistence** — small, and it's the plumbing #5-editor needs
3. **#5 chart categorical palette** — before #6 so the polish pass isn't also "fix all charts"
4. **#6 light theme polish pass** — quick, eyes-on, once charts are handled
5. **#1 in-dashboard theme editor** — the flagship; builds on #4's persistence
6. **#3 plugin roadmap Phase 0** — last; it's a context switch (deep backend), give it undivided focus

Steps 2–4 are ~2 days of easy wins that make light mode genuinely finished.
#5 is the fun one. #6 is the deep architecture work.
