# DAPNET plugin

DAPNET/POCSAG amateur-radio paging via a serial-connected companion board
(`pocsag_companion/`, an ESP32 + SX1276/SX1262 sketch — TTGO LoRa32 or
Heltec V3). Bidirectional: it both decodes real DAPNET pages (capcode,
function, text) and, from its own on-device WiFi dashboard or this
plugin's Send tab, transmits alpha pages with a licensed operator
callsign prefix.

Unlike every RTL-SDR plugin (ACARS, RTL433, Radio, ...), this one isn't
listener-shaped at all — it's the reference for the `"capture"`/`"protocol"`
plugin seams (see `docs/PLUGINS.md`): a real `CaptureSource` joins the
core packet pipeline directly, unconditionally at boot, and it owns
decode + classification for its own protocol identity
(`OpenProtocol("dapnet")`, not a member of the closed core `Protocol`
enum). It ships `locked = true` in its `plugin.toml`, so unlike a plugin
you drop in yourself it won't offer a Delete button on Settings →
Plugins (it's git-tracked, so deleting it wouldn't stick past the next
`Update` anyway).

## Install

1. Run setup once (checks for the shared `arduino-cli`/ESP32 toolchain
   `scripts/install.sh` already sets up — needed only for the
   Configuration → Firmware compile/flash card below, nothing else to
   build for capture/decode itself):

   ```sh
   sudo bash /opt/meshpoint/plugins/apps/dapnet/setup.sh
   # or, for a confirmation prompt first:
   sudo meshpoint plugin setup dapnet
   ```

2. Enable it and configure at least one companion device in `local.yaml`:

   ```yaml
   plugins:
     dapnet:
       enabled: true
       devices:
         - serial_port: "/dev/ttyUSB2"
           serial_baud: 115200
           label: "ttgo"
           name: "Attic POCSAG"
   ```

3. Restart Meshpoint. Decoded traffic shows up on **Networks → DAPNET**.

## Configuration

Everything lives under `plugins.dapnet` — device connection info and
capcode filters, previously two separate core config sections, are now
one opaque shape like every other plugin's:

```yaml
plugins:
  dapnet:
    enabled: true
    status_poll_interval_s: 60                 # 10-3600, default 60
    blacklist_capcodes: [200, 208, 216, 224]   # shown live, never stored
    ignore_capcodes: [4512, 4520]              # neither shown nor stored
    devices:
      - serial_port: "/dev/ttyUSB2"
        serial_baud: 115200
        label: "ttgo"
        name: "Attic POCSAG"
```

`devices`/`status_poll_interval_s` changes need a service restart
(`DapnetSerialSource` reads both once, at construction); the two
capcode-filter lists take effect immediately, and saving either also
purges any already-stored pages for a newly-added capcode. All of it is
also editable from the DAPNET page's own **Settings** tab, which is the
same PUT under the hood (`GET`/`PUT /api/dapnet/settings`).

## No topbar chip

The old core version of this page had a small topbar badge
(callsign/frequency/board). This plugin doesn't get an equivalent — no
generic "plugin owns a topbar chip" seam exists yet, and building one
for a single caller risked guessing its shape wrong. A **status card**
at the top of the DAPNET page shows the same info instead — a real,
acknowledged trade-off (glance-from-anywhere becomes click-into-the-page),
the same reasoning already applied to the RTL-SDR family's sidebar "in
use" badge before it was later rebuilt properly as a generic seam.
Revisit building a real topbar-chip registry if a second plugin ever
wants one too.

## Layout

```
plugin.toml                        manifest (capture/protocol/routes/sidebar, [frontend], meta)
setup.sh                           arduino-cli/ESP32 toolchain check
pocsag_companion/                  the companion's own Arduino sketch
backend/listener.py                DapnetSerialSource (threaded pyserial reader)
backend/decode.py                  adapt_event() -- JSON page -> Packet
backend/state.py                   devices/capcode-filter state, tier() classification
backend/routes.py                  /api/dapnet/{packets,capcodes,stats,export/*}
backend/config_routes.py           /api/config/dapnet/* -- live serial commands (callsign, wifi, ...)
backend/firmware_routes.py         /api/pocsag/firmware/* -- compile/flash the companion sketch
backend/settings_routes.py         GET/PUT /api/dapnet/settings, GET /api/dapnet/status
backend/__init__.py                register(reg)
frontend/dapnet_panel.js           the DAPNET page (Recent Pages / Capcodes / Send / Settings tabs)
frontend/dapnet_settings_tab.js    the Settings tab (device CRUD, capcode filters, live commands)
frontend/dapnet_status_card.js     the status card replacing the old topbar chip
frontend/dapnet_packet_format.js   registers DAPNET's id/type-label/summary quirks with core's
                                    protocol_format_registry.js
frontend/dapnet_panel.css          empty on purpose -- reuses core's lorawan.css/configuration.css
```
