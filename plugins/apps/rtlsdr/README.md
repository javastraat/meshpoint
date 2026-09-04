# RTL-SDR plugin

The shared RTL-SDR host page. Adds an **RTL-SDR** page under the sidebar's
Radio section that every RTL-SDR plugin hooks its own tab into.

## Why this exists

The old built-in Listener page (`frontend/js/listener_panel.js`, deleted)
used to be *both* Radio's own implementation *and* the tabbar host every
other RTL-SDR plugin attached to via `window.registerListenerPanel`. Every
RTL-SDR plugin has since migrated off it onto this page instead, one at a
time (via `"hook"`, not `"panel"` — see [Hello World Hook](../hello-world-hook/)
for the seam's own minimal reference). Radio itself was the last to move;
the built-in Listener page is gone entirely now, and nothing RTL-SDR-related
is built into core anymore.

**[DAB+](../dab/) moved first** — not a toy test, a real migration: it
dropped `"panel"` from its `provides`. Both its player and its Config
panel hook into this page as their own labeled tabs
(`window.mountPageHooks()` builds a small internal tabbar automatically
once a host has more than one hook — see `docs/PLUGINS.md`). Moved
wholesale rather than duplicated deliberately — DAB+'s player looks up
its `<audio>` element by a hardcoded id, not scoped to its own mounted
root, so two live instances at once (old tab + new hook) would have
fought over it.

DAB+ moving first also surfaced two real bugs in the hook mechanism
itself (fixed, not DAB+-specific, before anything else migrated):
`mountPageHooks()` used to hand every hook the same container element
directly, so a second hook's `mount()` silently erased the first's
content; and nothing ever called a mounted hook's `show()`, so any hook
depending on that lifecycle for data loading (like DAB+'s Config panel)
never did anything. Both fixed generically, and the automatic tabbar
(built in response to DAB+'s two-tab needs) is what every subsequent
plugin's tab renders through too.

**P2000, Pagers, POCSAG, RTL433, ACARS and ADS-B followed once the
mechanism was proven** — six single-hook migrations, mechanical copies of
the same pattern (drop `"panel"`, add `"hook"` with `host = "rtlsdr"`,
swap `registerListenerPanel` for `registerPageHook`).

**[Radio](../radio/) moved last** — the biggest of the migrations, since
it carries the most UI (VU meter, Digital/Analogue skin switch, tuner,
presets, RDS). Same pattern as the other six, plus converting every
internal DOM lookup from `document.getElementById`/`document.querySelector`
to `this._root.querySelector(...)`, since a hooked panel no longer owns the
whole document the way the old built-in page did. With Radio gone, the
built-in Listener page had nothing left on it and was deleted outright,
along with `frontend/js/listener_panel.js`,
`frontend/js/listener_panel_registry.js` (the now-fully-dead
`window.registerListenerPanel`/`window.LISTENER_PANELS` seam), and
`frontend/sidebar/listener_badge.js` (the sidebar badge showing which
RTL-SDR listener held the dongle — a real, acknowledged feature loss with
no replacement yet; a future fix could extend `sidebar_plugin_registry.js`'s
link-building with an optional badge slot for any plugin sidebar page).
`scripts/install.sh`'s old RTL-SDR section (librtlsdr build, kernel DVB
blacklist) moved into this plugin's own `setup.sh`.

This page's own sidebar icon (`icon = "usb"` in `plugin.toml`) is an exact
copy of the old built-in Listener page's own USB-dongle glyph, inherited
now that this is the only RTL-SDR-labeled sidebar entry left.

## Enable it

```yaml
plugins:
  rtlsdr:
    enabled: true
```

Run `sudo bash plugins/apps/rtlsdr/setup.sh` (or
`sudo meshpoint plugin setup rtlsdr`) first — builds `librtlsdr` from
source and blacklists the kernel's DVB-T driver so it doesn't claim the
dongle as a TV tuner. Then restart and find **RTL-SDR** in the sidebar's
Radio section. Enable whichever RTL-SDR plugins you want alongside it —
each shows up as its own tab here once enabled (see each plugin's own
README): [`radio`](../radio/), [`dab`](../dab/), [`p2000`](../p2000/),
[`pagers`](../pagers/), [`pocsag`](../pocsag/), [`rtl433`](../rtl433/),
[`acars`](../acars/), [`adsb`](../adsb/). With none enabled, the page is
just the placeholder text.

## Layout

```
plugin.toml                   manifest ([sidebar] table, [frontend])
setup.sh                      builds librtlsdr from source, blacklists the kernel DVB-T stack
backend/__init__.py           register(reg) -- a no-op; nothing to register
frontend/rtlsdr_panel.js      the page content (registerSidebarPage) + hook mount point
frontend/rtlsdr_panel.css     styling for the placeholder page and its hook container
```
