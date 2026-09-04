# RTL433 plugin

Decodes hundreds of 433/315/868 MHz OOK/FSK devices (weather stations, TPMS,
remote sensors, and more) off the shared RTL-SDR dongle via
[`rtl_433`](https://github.com/merbanan/rtl_433), and adds an **RTL433** tab
to the Listener page — start/stop/clear + a live decoded-message log, same
shape as the P2000/Pagers/POCSAG/ACARS tabs. The decoded field set varies
wildly by device model, so each row just shows the model name plus whatever
other keys a given event happens to carry.

Extracted from core into a plugin (was previously always-on, no config
gate); it now ships `locked = true` in its `plugin.toml`, so it won't offer
a Delete button on Settings → Plugins (it's git-tracked, so deleting it
wouldn't stick past the next `Update` anyway), but it is now off by default
like every other plugin.

## Install

1. Install `rtl_433` (once, needs sudo — apt only, no build):

   ```sh
   sudo bash /opt/meshpoint/plugins/apps/rtl433/setup.sh
   # or, for the apt list + a confirmation prompt first:
   sudo meshpoint plugin setup rtl433
   ```

   The absolute path matters if you want this passwordless: `config/
   sudoers-meshpoint`'s NOPASSWD grant for plugin setup scripts matches
   the absolute path exactly. `meshpoint plugin setup` always resolves it
   for you.

   Idempotent — skips the apt install if `rtl_433` is already on `PATH`.

2. Enable it in `local.yaml` and restart Meshpoint:

   ```yaml
   plugins:
     rtl433:
       enabled: true
   ```

3. Open the dashboard → Listener → **RTL433** → Start.

Shares the one RTL-SDR dongle with the FM / Pager / ACARS / DAB+ / ADS-B
listeners (only one active at a time; stop the other one first).

## Layout

```
plugin.toml                 manifest (name, deps, [frontend], meta)
setup.sh                    rtl_433 apt install
backend/listener.py         rtl_433 subprocess + JSON parse (Rtl433Listener)
backend/routes.py           /api/rtl433  status / start / stop / clear
backend/__init__.py         register(reg)
frontend/rtl433_panel.js    the RTL433 Listener tab (reuses core PagerPanel)
```
