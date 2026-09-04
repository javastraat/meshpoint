# RTL-SDR plugin

The future RTL-SDR host page, under construction. Adds an **RTL-SDR
Plugins** page under the sidebar's Radio section (next to the built-in
Listener page, labeled just "RTL-SDR" — deliberately a different label,
since the two looked confusingly identical in the sidebar when this first
shipped) with placeholder text plus a mount point other plugins inject
content into via the `"hook"` seam.

## Why this exists

The built-in Listener page (`frontend/js/listener_panel.js`) is currently
*both* Radio's own implementation *and* the tabbar host every other
RTL-SDR plugin attaches to via `window.registerListenerPanel`. The plan is
for RTL-SDR plugins to migrate off it one at a time, onto this page instead
(via `"hook"`, not `"panel"` — see [Hello World Hook](../hello-world-hook/)
for the seam's own minimal reference), ending with Radio itself becoming
an ordinary plugin here too and the built-in Listener page going away
entirely.

**[DAB+](../dab/) is the first to move** — not a toy test, a real
migration: it dropped `"panel"` from its `provides` and no longer appears
on the Listener page's tabbar at all. Both its player
(`plugins/apps/dab/frontend/dab_panel.js`) and its Config panel
(`dab_config_panel.js`) hook into this page instead, stacked one below the
other. Moved wholesale rather than duplicated deliberately — DAB+'s player
looks up its `<audio>` element by a hardcoded id (`document.
getElementById('dab-audio')`, not scoped to its own mounted root), so two
live instances at once (old tab + new hook) would have fought over it.

Once every RTL-SDR plugin (and Radio) has migrated, `scripts/install.sh`'s
RTL-SDR section (librtlsdr build, kernel DVB blacklist) moves into this
plugin's `setup.sh` (currently a no-op placeholder), and the built-in
Listener page is deleted.

## Enable it

```yaml
plugins:
  rtlsdr:
    enabled: true
```

Restart, then Radio → RTL-SDR Plugins in the sidebar (not "RTL-SDR" —
that's the built-in Listener page). Also enable `dab` (see
[`plugins/apps/dab/`](../dab/)) to get the DAB+ player and Config panel on
this page — without it enabled, the page is just the placeholder text.

## Layout

```
plugin.toml                   manifest ([sidebar] table, [frontend])
setup.sh                      no-op placeholder -- see "Why this exists" above
backend/__init__.py           register(reg) -- a no-op; nothing to register
frontend/rtlsdr_panel.js      the page content (registerSidebarPage) + hook mount point
frontend/rtlsdr_panel.css     styling for the placeholder page and its hook container
```
