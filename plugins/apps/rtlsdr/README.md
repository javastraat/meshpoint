# RTL-SDR plugin

A staging ground, not a real feature yet. Adds an **RTL-SDR** page under the
sidebar's Radio section (next to the built-in Listener page, which is still
where Radio/DAB+/P2000/Pagers/POCSAG/RTL433/ADS-B/ACARS actually run) with
placeholder text plus a mount point other plugins can inject content into
via the `"hook"` seam.

## Why this exists

The built-in Listener page (`frontend/js/listener_panel.js`) is currently
*both* Radio's own implementation *and* the tabbar host every RTL-SDR
plugin already attaches to via `window.registerListenerPanel`. Splitting
those apart — a neutral host page plus Radio becoming an ordinary plugin
like every other RTL-SDR tab — is a real, fairly large piece of work.
Before committing to it, this plugin proves out a *different*, already-built
seam (`"hook"` — see [Hello World Hook](../hello-world-hook/), the original
reference) against a real, non-trivial plugin instead of a toy example:
[DAB+](../dab/) hooks a small status card into this page
(`plugins/apps/dab/frontend/dab_rtlsdr_hook.js`).

If that works out, the plan is for this page to eventually become the real
RTL-SDR host — Radio's own listener/routes/panel moving out of core into
`plugins/apps/radio/`, and `scripts/install.sh`'s RTL-SDR section (librtlsdr
build, kernel DVB blacklist) moving into this plugin's `setup.sh` (currently
a no-op placeholder). Not done yet — deliberately scoped small first.

## Enable it

```yaml
plugins:
  rtlsdr:
    enabled: true
```

Restart, then Radio → RTL-SDR in the sidebar. Also enable `dab` (see
[`plugins/apps/dab/`](../dab/)) to see its hook render on this page.

## Layout

```
plugin.toml                   manifest ([sidebar] table, [frontend])
setup.sh                      no-op placeholder -- see "Why this exists" above
backend/__init__.py           register(reg) -- a no-op; nothing to register
frontend/rtlsdr_panel.js      the page content (registerSidebarPage) + hook mount point
frontend/rtlsdr_panel.css     styling for the placeholder page and its hook container
```
