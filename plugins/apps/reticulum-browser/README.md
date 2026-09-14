# Reticulum Browser plugin

A full multi-tab NomadNet browser for Reticulum. Adds a **Reticulum
Browser** page under the sidebar's **Networks** section: node search +
picker, an address bar, back/forward/reload, a raw/rendered view toggle,
favourites, and keyboard shortcuts -- all working across multiple tabs
at once.

## Credit

Feature set and name are inspired by
[**fr33n0w/rBrowser**](https://github.com/fr33n0w/rBrowser) (MIT
licensed). This plugin is **not a code port** of that project -- rBrowser
is a single-file Flask app (a ~200KB `index.html`, a Python backend doing
its own routing/caching), structurally very different from a Meshpoint
sidebar plugin (a small ES6 class reading the reticulum plugin's own
`/api/reticulum/nomad/*` endpoints, no backend of its own). What's here
is a clean-room implementation of the same *feature set*, built fresh
against Meshpoint's own patterns -- the same ones the reticulum plugin's
own Browse tab and the reticulum-dashboard plugin's quick-browse modal
already use (`_splitAddr`/`_followLink` shape, the shared favourites
list, `window.MicronParser` rendering).

(Meshpoint's own reticulum plugin already carries the same kind of credit
for `reticulum_micron.js`, ported from reticulum-meshchat, also MIT.)

## What's here

- **Multi-tab browsing** -- open several nodes at once, each tab keeps
  its own address/history independently; switching tabs never re-fetches,
  it just redisplays what that tab already loaded.
- **Node picker + search**, same shape as the reticulum plugin's own
  Browse tab.
- **Favourites** -- shares the *exact same* `localStorage` list
  (`meshpoint.rtNomadFavourites`) as the reticulum plugin's Browse tab,
  its Peers drawer, and the reticulum-dashboard plugin's quick-browse
  modal. Star a node anywhere, it's starred everywhere.
- **Raw/rendered view toggle** -- see a page's actual Micron source
  instead of the parsed rendering.
- **Keyboard shortcuts** -- `Ctrl/Cmd+T` new tab, `Ctrl/Cmd+W` close tab,
  `Ctrl/Cmd+R` reload, `Alt+←`/`Alt+→` back/forward.

## What's not here (yet)

- **Fingerprint identification of remote hosts** -- rBrowser's exact
  verification model for this wasn't studied closely enough yet to build
  a Meshpoint equivalent honestly. A later addition, not forgotten.
- **A local NomadNet search engine + page cache** -- this is a background
  crawler + index, not a browser-tab feature. It would need its own
  `service`-seam backend (the same plugin capability Reticulum's own LXMF
  service uses) and a real cache schema -- comparable in scope to a whole
  separate plugin, not something to bolt onto this one. Worth its own
  effort later if wanted.
- Form-field submission on interactive `.mu` pages, and `/file/...`
  downloads -- same scope line the reticulum-dashboard plugin's own
  quick-browse modal already draws. The reticulum plugin's own Browse tab
  covers both if you need them.

## Enable it

```yaml
plugins:
  reticulum-browser:
    enabled: true
```

Restart, then Networks → Reticulum Browser in the sidebar. Needs
`plugins.reticulum.enabled: true` too, or there's nothing to browse.

## Layout

```
plugin.toml                              manifest ([sidebar] table, requires = "reticulum")
backend/__init__.py                       register(reg) -- a no-op; no backend routes of its own
frontend/reticulum_browser_panel.js       the page (tabs, nav, favourites, shortcuts)
frontend/reticulum_browser_panel.css      toolbar/tab-strip/page styling
```
