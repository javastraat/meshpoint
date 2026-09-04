# ADS-B plugin

Live air traffic tracking off the shared RTL-SDR dongle via
[`dump1090`](https://github.com/MalcolmRobb/dump1090), and adds an **ADS-B**
tab to the Listener page. Unlike the P2000/Pagers/POCSAG/RTL433/ACARS tabs
(each a scrolling decoded-message log), dump1090 hands back a full snapshot
of currently-tracked aircraft on every poll of its own `/data.json`, so this
renders as a table keyed by ICAO hex that updates in place — a "Metric
units" checkbox (on by default) passes dump1090's own `--metric` flag, and a
**Map** button opens a modal with the same aircraft plotted live on an
OpenStreetMap (Leaflet) view, each as an arrow rotated to its track heading
and colored by squawk (emergency codes 7500/7600/7700 stand out, stale
contacts dim, trailing its last couple of minutes of positions). Clicking
any aircraft row, or a plane marker on the map, opens a **flight detail**
modal — the tracked ADS-B fields plus, best-effort, registration/aircraft
type/operator and route (origin–destination airport) from
[hexdb.io](https://hexdb.io) and a real photo of the airframe from
[planespotters.net](https://www.planespotters.net), both free public
lookups queried straight from the browser.

Extracted from core into a plugin (was previously always-on, no config
gate); it now ships `locked = true` in its `plugin.toml`, so it won't offer
a Delete button on Settings → Plugins (it's git-tracked, so deleting it
wouldn't stick past the next `Update` anyway), but it is now off by default
like every other plugin.

## Install

1. Build `dump1090` (once, needs sudo — a from-source build, `dump1090`
   isn't packaged in Debian/Raspberry Pi OS):

   ```sh
   sudo bash /opt/meshpoint/plugins/apps/adsb/setup.sh
   # or, for the apt/build summary + a confirmation prompt first:
   sudo meshpoint plugin setup adsb
   ```

   The absolute path matters if you want this passwordless: `config/
   sudoers-meshpoint`'s NOPASSWD grant for plugin setup scripts matches
   the absolute path exactly. `meshpoint plugin setup` always resolves it
   for you.

   Builds `MalcolmRobb/dump1090` from source into `/opt/dump1090`.
   Idempotent — skips if `dump1090` is already on `PATH`.

2. Enable it in `local.yaml` and restart Meshpoint:

   ```yaml
   plugins:
     adsb:
       enabled: true
   ```

3. Open the dashboard → Listener → **ADS-B** → Start.

Shares the one RTL-SDR dongle with the FM / Pager / RTL433 / ACARS / DAB+
listeners (only one active at a time; stop the other one first).

## Layout

```
plugin.toml                     manifest (name, deps, [frontend], meta)
setup.sh                        dump1090 build (from source)
backend/listener.py             dump1090 subprocess + /data.json poll (AdsbListener)
backend/routes.py               /api/adsb  status / start / stop
backend/__init__.py             register(reg)
frontend/adsb_panel.js          the ADS-B Listener tab (aircraft table)
frontend/adsb_map_modal.js      live Leaflet map of tracked aircraft
frontend/adsb_flight_modal.js   per-aircraft detail modal (hexdb.io + planespotters.net)
frontend/adsb_panel.css         table/map/marker styling
```
