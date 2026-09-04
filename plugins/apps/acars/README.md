# ACARS plugin

Decodes aircraft VHF datalink (ACARS) off the shared RTL-SDR dongle and adds
an **ACARS** tab to the Listener page — same start/stop/clear + live message
log as the RTL433 and Pager tabs. ADS-C position contracts and plain-text POS
reports collapse to a one-line summary with the coordinate linked to
OpenStreetMap; the full decode sits behind a "details" toggle. Airline
telemetry (label H1) stays raw — it's carrier-proprietary.

This is Meshpoint's reference **community plugin**: a listener, its `/api/acars`
routes and its dashboard tab, all under `plugins/apps/acars/`, wired through
`register(reg)` — nothing in core. It ships `locked = true` in its
`plugin.toml`, so unlike a plugin you drop in yourself it won't offer a
Delete button on Settings → Plugins (it's git-tracked, so deleting it
wouldn't stick past the next `Update` anyway).

## Install

1. Build the decoder (once, needs sudo — apt + `make install`):

   ```sh
   sudo bash plugins/apps/acars/setup.sh
   # or, for the apt list + a confirmation prompt first:
   sudo meshpoint plugin setup acars
   ```

   Builds `szpajder/libacars` and `f00b4r0/acarsdec` from source into `/opt`.
   Idempotent — skips if `acarsdec` is already on `PATH`.

2. Enable it in `local.yaml` and restart Meshpoint:

   ```yaml
   plugins:
     acars:
       enabled: true
   ```

3. Open the dashboard → Listener → **ACARS** → Start.

Shares the one RTL-SDR dongle with the FM / Pager / RTL433 / DAB+ / ADS-B
listeners (only one active at a time; stop the other one first).

## Configuration

All optional, under `plugins.acars` in `local.yaml` (restart to apply):

```yaml
plugins:
  acars:
    enabled: true
    freqs: [131.525, 131.725, 131.800, 131.825]  # default: the EU channels above
    gain: 34                                     # default: 34 (not AGC -- airband
                                                   # AGC overloads on strong ground stations)
    device: 0                                    # default: 0 (RTL-SDR device index)
```

An unset or invalid `freqs` (missing key, not a list, all-blank entries) falls
back to the default EU channel set rather than starting acarsdec with no
channels at all.

## Layout

```
plugin.toml                 manifest (name, deps, [frontend], meta)
setup.sh                    acarsdec + libacars build
backend/listener.py         acarsdec subprocess + JSON parse (AcarsListener)
backend/routes.py           /api/acars  status / start / stop / clear
backend/__init__.py         register(reg)
frontend/acars_panel.js     the ACARS Listener tab (reuses core PagerPanel)
frontend/acars_panel.css    acars row styling
```
