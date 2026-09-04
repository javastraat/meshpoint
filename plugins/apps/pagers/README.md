# Pagers plugin

Decodes POCSAG512/1200/2400 pager traffic on 172.45 MHz off the shared
RTL-SDR dongle via `rtl_fm | multimon-ng`, and adds a **Pagers** tab to the
Listener page — start/stop/clear + a live decoded-message log, same shape
as the POCSAG/P2000/RTL433/ACARS tabs (reuses the core `PagerPanel`
component as-is, no custom row renderer needed).

The third and last of the former combined `src/audio/pager_listener.py`
kinds to become its own plugin, after P2000 and POCSAG — that shared core
file is gone now (nothing else needed it). It ships `locked = true` in its
`plugin.toml`, so it won't offer a Delete button on Settings → Plugins
(it's git-tracked, so deleting it wouldn't stick past the next `Update`
anyway), but it is off by default like every other plugin.

## Install

1. Install `multimon-ng` (once, needs sudo — a from-source build, not
   packaged in Debian/Raspberry Pi OS):

   ```sh
   sudo bash /opt/meshpoint/plugins/apps/pagers/setup.sh
   # or, for the summary + a confirmation prompt first:
   sudo meshpoint plugin setup pagers
   ```

   The absolute path matters if you want this passwordless: `config/
   sudoers-meshpoint`'s NOPASSWD grant for plugin setup scripts matches
   the absolute path exactly. `meshpoint plugin setup` always resolves it
   for you.

   Unlike when the P2000/POCSAG siblings were split out (`scripts/
   install.sh` still built `multimon-ng` for Pagers staying core at the
   time), this is now the one that actually does the work — `scripts/
   install.sh` no longer builds `multimon-ng` at all. Idempotent
   regardless: skips if `multimon-ng` is already on `PATH` (e.g. from the
   P2000 or POCSAG plugin's own copy of this same script already having
   run).

2. Enable it in `local.yaml` and restart Meshpoint:

   ```yaml
   plugins:
     pagers:
       enabled: true
   ```

3. Open the dashboard → Listener → **Pagers** → Start.

Shares the one RTL-SDR dongle with the FM / POCSAG / P2000 / RTL433 /
ACARS / DAB+ / ADS-B listeners (only one active at a time; stop the other
one first).

## Layout

```
plugin.toml                 manifest (name, deps, [frontend], meta)
setup.sh                    multimon-ng build
backend/listener.py         rtl_fm|multimon-ng pipeline + POCSAG parse (PagersListener)
backend/routes.py           /api/pagers  status / start / stop / clear
backend/__init__.py         register(reg)
frontend/pagers_panel.js    the Pagers Listener tab (reuses core PagerPanel)
```
