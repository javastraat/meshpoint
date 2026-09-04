# POCSAG plugin

Decodes POCSAG512/1200/2400 pager traffic on 439.9875 MHz off the shared
RTL-SDR dongle via `rtl_fm | multimon-ng`, and adds a **POCSAG** tab to the
Listener page — start/stop/clear + a live decoded-message log, same shape
as the Pagers/P2000/RTL433/ACARS tabs (reuses the core `PagerPanel`
component as-is, no custom row renderer needed).

Split out of `src/audio/pager_listener.py` (which still covers the
"pagers" kind — the same POCSAG-family decoders, just on 172.45 MHz
instead — still core, not yet a plugin), the second of the three former
pager kinds to become its own plugin (after P2000). It ships `locked =
true` in its `plugin.toml`, so it won't offer a Delete button on Settings
→ Plugins (it's git-tracked, so deleting it wouldn't stick past the next
`Update` anyway), but it is off by default like every other plugin.

## Install

1. Install `multimon-ng` (once, needs sudo — a from-source build, not
   packaged in Debian/Raspberry Pi OS):

   ```sh
   sudo bash /opt/meshpoint/plugins/apps/pocsag/setup.sh
   # or, for the summary + a confirmation prompt first:
   sudo meshpoint plugin setup pocsag
   ```

   The absolute path matters if you want this passwordless: `config/
   sudoers-meshpoint`'s NOPASSWD grant for plugin setup scripts matches
   the absolute path exactly. `meshpoint plugin setup` always resolves it
   for you.

   **Note:** Pagers (still core, not a plugin yet) uses this exact same
   `multimon-ng` binary, and `scripts/install.sh` already builds it
   unconditionally as part of RTL-SDR setup — so on a normal Pi install
   this script is usually a no-op (idempotent: skips if `multimon-ng` is
   already on `PATH`). It stays self-contained anyway so the POCSAG
   plugin doesn't silently depend on Pagers staying core.

2. Enable it in `local.yaml` and restart Meshpoint:

   ```yaml
   plugins:
     pocsag:
       enabled: true
   ```

3. Open the dashboard → Listener → **POCSAG** → Start.

Shares the one RTL-SDR dongle with the FM / Pagers / P2000 / RTL433 /
ACARS / DAB+ / ADS-B listeners (only one active at a time; stop the other
one first).

## Layout

```
plugin.toml                  manifest (name, deps, [frontend], meta)
setup.sh                     multimon-ng build (usually a no-op, see above)
backend/listener.py          rtl_fm|multimon-ng pipeline + POCSAG parse (PocsagListener)
backend/routes.py            /api/pocsag  status / start / stop / clear
backend/__init__.py          register(reg)
frontend/pocsag_panel.js     the POCSAG Listener tab (reuses core PagerPanel)
```
