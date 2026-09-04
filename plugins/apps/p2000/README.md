# P2000 plugin

Decodes Dutch emergency dispatch traffic (P2000, FLEX on 169.65 MHz) off the
shared RTL-SDR dongle via `rtl_fm | multimon-ng`, and adds a **P2000** tab to
the Listener page — start/stop/clear + a live decoded-message log, same
shape as the Pagers/POCSAG/RTL433/ACARS tabs (reuses the core `PagerPanel`
component as-is, no custom row renderer needed).

Split out of `src/audio/pager_listener.py` (which still covers the generic
Pagers/POCSAG kinds, both POCSAG-family and still core, not yet plugins) --
P2000 is FLEX-only and the kind people most often want standalone. It ships
`locked = true` in its `plugin.toml`, so it won't offer a Delete button on
Settings → Plugins (it's git-tracked, so deleting it wouldn't stick past the
next `Update` anyway), but it is off by default like every other plugin.

## Install

1. Install `multimon-ng` (once, needs sudo — a from-source build, not
   packaged in Debian/Raspberry Pi OS):

   ```sh
   sudo bash /opt/meshpoint/plugins/apps/p2000/setup.sh
   # or, for the summary + a confirmation prompt first:
   sudo meshpoint plugin setup p2000
   ```

   The absolute path matters if you want this passwordless: `config/
   sudoers-meshpoint`'s NOPASSWD grant for plugin setup scripts matches
   the absolute path exactly. `meshpoint plugin setup` always resolves it
   for you.

   **Note:** Pagers and POCSAG (still core, not plugins yet) use this
   exact same `multimon-ng` binary, and `scripts/install.sh` already
   builds it unconditionally as part of RTL-SDR setup — so on a normal
   Pi install this script is usually a no-op (idempotent: skips if
   `multimon-ng` is already on `PATH`). It stays self-contained anyway so
   the P2000 plugin doesn't silently depend on Pagers/POCSAG staying core.

2. Enable it in `local.yaml` and restart Meshpoint:

   ```yaml
   plugins:
     p2000:
       enabled: true
   ```

3. Open the dashboard → Listener → **P2000** → Start.

Shares the one RTL-SDR dongle with the FM / Pagers / POCSAG / RTL433 /
ACARS / DAB+ / ADS-B listeners (only one active at a time; stop the other
one first).

## Layout

```
plugin.toml                 manifest (name, deps, [frontend], meta)
setup.sh                    multimon-ng build (usually a no-op, see above)
backend/listener.py         rtl_fm|multimon-ng pipeline + FLEX parse (P2000Listener)
backend/routes.py           /api/p2000  status / start / stop / clear
backend/__init__.py         register(reg)
frontend/p2000_panel.js     the P2000 Listener tab (reuses core PagerPanel)
```
