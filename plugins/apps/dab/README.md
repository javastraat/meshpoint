# DAB+ plugin

Live DAB/DAB+ digital radio off the shared RTL-SDR dongle via
[`welle-cli`](https://github.com/AlbrechtL/welle.io) (the headless webserver
mode of the welle.io project). Unlike every other RTL-SDR plugin, its UI
doesn't live on the built-in Listener page — it renders on the
[RTL-SDR Plugins](../rtlsdr/) page instead, via the `"hook"` seam
(`plugin.toml`'s `[hook] host = "rtlsdr"`), first to move off ahead of
Radio itself (see [`plugins/apps/rtlsdr/README.md`](../rtlsdr/README.md)
for why). Two pieces, shown as switchable tabs on that page (each hook
registration carries its own `label` — see `docs/PLUGINS.md`'s hook seam
docs for how `mountPageHooks()` turns that into a small tabbar
automatically once more than one hook shares a host):

- **The player** — pick a channel (Favorites, a scanned-channel tab, or
  Manual), tune it, and welle-cli progressively decodes the ensemble's
  station list as it locks. Styled like the Radio tab's Digital skin (LEDs,
  VFD-style readout, VU meter, native `<audio>` controls) so it reads as
  the same instrument family, with a station list below since DAB+ carries
  several stations per channel rather than one per frequency.
- **Config** — shows what `dab_channel_scan.py` found on this antenna
  (read from its JSON output), lets an admin set a friendlier per-channel
  display name, and runs the scan itself with live streamed output instead
  of CLI-only over SSH.

Extracted from core into a plugin (was previously always-on, no config
gate); it now ships `locked = true` in its `plugin.toml`, so it won't offer
a Delete button on Settings → Plugins (it's git-tracked, so deleting it
wouldn't stick past the next `Update` anyway), but it is now off by default
like every other plugin.

## Install

1. Install `welle.io` (once, needs sudo — apt only, no build):

   ```sh
   sudo bash /opt/meshpoint/plugins/apps/dab/setup.sh
   # or, for the apt list + a confirmation prompt first:
   sudo meshpoint plugin setup dab
   ```

   The absolute path matters if you want this passwordless: `config/
   sudoers-meshpoint`'s NOPASSWD grant for plugin setup scripts matches
   the absolute path exactly. `meshpoint plugin setup` always resolves it
   for you.

   `--no-install-recommends` skips the Qt/QML GUI dependency chain that
   only the `welle.io` GUI app needs (~87 MB installed otherwise) —
   `welle-cli`, the headless binary this plugin actually drives, has no
   GUI dependencies. Idempotent — skips the apt install if `welle-cli` is
   already on `PATH`.

2. Enable it (and [`rtlsdr`](../rtlsdr/), its host page) in `local.yaml`
   and restart Meshpoint:

   ```yaml
   plugins:
     rtlsdr:
       enabled: true
     dab:
       enabled: true
   ```

3. Open the dashboard → Radio → **RTL-SDR Plugins** and run a scan (Config,
   below the player) or pick a channel from Favorites/Manual in the player
   itself to find stations at this antenna.

Shares the one RTL-SDR dongle with the FM / Pager / RTL433 / ACARS / ADS-B
listeners (only one active at a time; stop the other one first) — both
live playback (`dab`) and a running scan (`dab_scan`) claim it as distinct
owner names, so a busy message can say which DAB+ activity is holding it.

## Layout

```
plugin.toml                    manifest (name, deps, [frontend], [hook], meta)
setup.sh                       welle.io apt install
dab_channel_scan.py            standalone Band III channel scanner (also runnable
                                directly over SSH, see its own docstring)
backend/listener.py            welle-cli subprocess + /mux.json poll + MP3 stream proxy (DabListener)
backend/routes.py              /api/dab  status / tune / stop / stream / scan-results / scan
backend/__init__.py            register(reg)
frontend/dab_panel.js          the player (channel picker, station list, playback) -- hooks into rtlsdr
frontend/dab_config_panel.js   Config (scan results, renaming, run-scan panel) -- hooks into rtlsdr
frontend/dab_panel.css         styling for both
```
