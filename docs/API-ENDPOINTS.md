# API Endpoints

Complete reference for every HTTP and WebSocket route the Meshpoint dashboard
server exposes. The README's [Local API](../README.md#local-api) section is a
curated highlights list for a quick skim; this file is the full surface,
including the config-write, admin-only, and one-off routes the README omits.

FastAPI server on port 8080 (`dashboard.port` in `local.yaml`). All routes are
prefixed `/api` unless noted otherwise.

## Access roles

Every route requires at least a logged-in session (`Public` routes are the
only exception). Two authenticated roles exist:

- **Viewer** — read-only dashboard access.
- **Admin** — everything a viewer can do, plus every write/action endpoint below.

A viewer hitting an `Admin` route gets `403 Forbidden`; anyone with no valid
session gets `401 Unauthorized`. See `src/api/auth/dependencies.py` for the
`require_auth`/`require_admin`/`optional_auth` dependencies this table maps to.

---

## Authentication & session

| Method | Path | Role | Description |
|---|---|---|---|
| POST | `/api/auth/setup` | Public | Create the first admin account (only works while unconfigured) |
| POST | `/api/auth/login` | Public | Exchange username/password for a session cookie |
| POST | `/api/auth/logout` | Public | Clear the current session cookie |
| POST | `/api/auth/change_password` | Viewer | Change the caller's own password |
| POST | `/api/auth/logout_all` | Admin | Invalidate every active session (rotates the JWT secret) |
| POST | `/api/auth/setup_viewer` | Admin | Create/update the read-only viewer account |
| POST | `/api/auth/clear_viewer` | Admin | Remove the viewer account |
| GET | `/api/config/auth_settings` | Admin | Read lockout/session-lifetime settings |
| PUT | `/api/config/auth_lockout` | Admin | Set failed-login lockout attempts/cooldown |
| PUT | `/api/config/auth_session_lifetime` | Admin | Set JWT session expiry |
| GET | `/api/identity` | Public | Allowlisted identity fields only — lets `/login`/`/setup` render before a session exists |
| GET | `/setup` | Public | Serves the first-run admin-setup page (HTML, not JSON) |
| GET | `/login` | Public | Serves the login page (HTML, not JSON) |
| GET | `/` | Public\* | Dashboard shell; \*redirects to `/login` or `/setup` server-side if there's no valid session |

---

## Configuration — general

| Method | Path | Role | Description |
|---|---|---|---|
| GET | `/api/config` | Viewer | Radio, TX, channel, and companion configuration (channel PSKs/keys hidden from viewers) |
| GET | `/api/config/export` | Viewer | Quick Deploy export: public channel params + Meshtastic QR URL (no private PSKs) |
| PUT | `/api/config/transmit` | Admin | Update TX settings (power, duty cycle, hop limit) |
| PUT | `/api/config/identity` | Admin | Update node ID, long/short name |
| PUT | `/api/config/radio` | Admin | Change region, preset, frequency |
| PUT | `/api/config/channels` | Admin | Update Meshtastic channel keys |
| PUT | `/api/config/meshcore/channels` | Admin | Update MeshCore channel keys |
| POST | `/api/config/restart` | Admin | Restart the meshpoint service |
| PUT | `/api/config/device` | Admin | Update device name/hardware description |
| PUT | `/api/config/gps` | Admin | Update GPS/location source settings |
| PUT | `/api/config/storage` | Admin | Update data retention settings |
| PUT | `/api/config/relay` | Admin | Update legacy USB-companion relay settings |
| PUT | `/api/config/radio/advanced` | Admin | Concentrator: spectral scan interval, SX1261 SPI path, capture-RAM band spectrum toggle (Configuration → Concentrator; restart to apply) |
| PUT | `/api/config/radio/pager` | Admin | Emergency pager (ch9 FSK): enable, frequency, sync word, own capcode (validated against the channel plan) |
| PUT | `/api/config/dashboard` | Admin | Dashboard-level settings saved to `local.yaml` (e.g. web terminal on/off, only once `dashboard.web_terminal_toggle` is set) |
| GET | `/api/config/lorawan` | Viewer | LoRaWAN device keys (DevEUI → OTAA root keys + optional payload field list) used to decrypt your own devices |
| PUT | `/api/config/lorawan` | Admin | Replace that device list (applies to live decoding) |
| GET | `/api/config/serial-ports` | Viewer | Enumerate connected USB-serial devices for the port-picker dropdown |

## Configuration — capture devices

| Method | Path | Role | Description |
|---|---|---|---|
| PUT | `/api/config/capture/meshcore-usb` | Admin | Legacy single-companion MeshCore USB config |
| PUT | `/api/config/capture/meshcore-companions` | Admin | Replace full MeshCore companion list (max 4) |
| GET | `/api/config/meshcore/firmware-check` | Viewer | Compare a companion's firmware against the latest `meshcore-dev/MeshCore` release (cached 5 min) |
| PUT | `/api/config/meshcore/companion-name` | Admin | Rename one MeshCore companion (label-scoped) |
| POST | `/api/config/meshcore/companion-advert` | Admin | Send an advert from one specific MeshCore companion (label-scoped) |
| PUT | `/api/config/meshcore/companion-radio` | Admin | Set one companion's radio (frequency/bandwidth/SF/CR, from a preset or custom) over its live connection |
| PUT | `/api/config/capture/serial-devices` | Admin | Replace full Meshtastic USB stick list |
| GET | `/api/config/serial/firmware-check` | Viewer | Compare a Meshtastic USB stick's firmware against the latest `meshtastic/firmware` release (cached 5 min) |
| PUT | `/api/config/serial/identity` | Admin | Rename one Meshtastic USB stick's long/short name (label-scoped) |
| POST | `/api/config/serial/advert` | Admin | Send a NodeInfo broadcast from one specific Meshtastic USB stick (label-scoped) |
| PUT | `/api/config/serial/region` | Admin | Set one Meshtastic USB stick's LoRa region over its live serial connection |
| PUT | `/api/config/serial/modem-preset` | Admin | Set one stick's LoRa modem preset |
| PUT | `/api/config/serial/bluetooth` | Admin | Set one stick's Bluetooth config (enabled + pairing) |
| PUT | `/api/config/serial/broadcast-intervals` | Admin | Set one stick's own NodeInfo/telemetry broadcast intervals |
| PUT | `/api/config/rfenv-companion/wifi` | Admin | Set the RF Environment companion's WiFi SSID/password (direct one-off serial session) |
| PUT | `/api/config/rfenv-companion/web-password` | Admin | Set the RF Environment companion's web dashboard password |
| POST | `/api/config/rfenv-companion/reboot` | Admin | Reboot the RF Environment companion |
| PUT | `/api/config/nodeinfo` | Admin | Update NodeInfo broadcast interval |
| POST | `/api/config/nodeinfo/send` | Admin | Send a NodeInfo broadcast now |
| PUT | `/api/config/position` | Admin | Set position broadcast interval |
| PUT | `/api/config/telemetry` | Admin | Set telemetry broadcast interval |
| GET | `/api/device/gps-status` | Viewer | Live GPS fix state (source, satellites, fix quality) |

## Configuration — hardware & services

| Method | Path | Role | Description |
|---|---|---|---|
| PUT | `/api/config/hardware/fan` | Admin | SenseCap M1 fan control settings |
| PUT | `/api/config/hardware/led` | Admin | SenseCap M1 case LED settings |
| PUT | `/api/config/hardware/button` | Admin | SenseCap M1 user button settings |
| GET | `/api/config/mqtt/runtime` | Viewer | Live MQTT broker connection status |
| PUT | `/api/config/mqtt` | Admin | Update MQTT broker settings |
| PUT | `/api/config/upstream` | Admin | Update Meshradar cloud connection settings |
| PUT | `/api/config/repeater-poll` | Admin | Update MeshCore repeater-polling settings |
| PUT | `/api/config/metrics` | Admin | Update Prometheus `/metrics` endpoint settings |
| POST | `/api/config/metrics/api-keys` | Admin | Create a named `/metrics`-only API key (raw key shown once, only its hash is stored) |
| DELETE | `/api/config/metrics/api-keys/{key_id}` | Admin | Revoke one API key |

## Firmware flashing (Configuration → Firmware)

All flash/compile routes stream NDJSON progress. Any connected USB-serial port can be the target; a board in use as a capture source (or an RNode held by `rnsd`) is released first and reconnected afterwards.

| Method | Path | Role | Description |
|---|---|---|---|
| GET | `/api/config/serial/firmware/installed` | Admin | Firmware versions reported by the configured Meshtastic USB sticks |
| GET | `/api/config/serial/firmware/releases` | Admin | Recent `meshtastic/firmware` releases for the version picker |
| GET | `/api/config/serial/firmware/targets` | Admin | Board list, read live from the chosen release's manifest |
| POST | `/api/config/serial/firmware/flash/stream` | Admin | Download (cached) and flash official Meshtastic firmware with `esptool` (optional erase-all) |
| GET | `/api/config/meshcore/firmware/installed` | Admin | Firmware versions reported by the connected MeshCore companions |
| GET | `/api/config/meshcore/firmware/releases` | Admin | Recent MeshCore `companion-` releases for the version picker |
| GET | `/api/config/meshcore/firmware/targets` | Admin | Board list for the chosen release + flavour (USB/BLE) |
| POST | `/api/config/meshcore/firmware/flash/stream` | Admin | Download (cached) and flash official MeshCore companion firmware with `esptool` |
| GET | `/api/rnode/firmware/targets` | Admin | Supported RNode boards (Heltec v2/v3/v4/T114, LilyGO LoRa32; 433–923 MHz) |
| POST | `/api/rnode/firmware/flash/stream` | Admin | Flash RNode firmware + bootstrap EEPROM + set firmware hash via `rnodeconf` (optional EEPROM erase first) |
| GET | `/api/rfenv-companion/firmware/targets` | Admin | RF Environment companion board (single fixed target) |
| POST | `/api/rfenv-companion/firmware/compile/stream` | Admin | Compile `rfenv_companion.ino` for the chosen band (EU868 / 70 cm) with `arduino-cli` |
| POST | `/api/rfenv-companion/firmware/flash/stream` | Admin | Upload the compiled build |
| GET | `/api/pager/firmware/targets` | Admin | Pager board (single fixed target) |
| POST | `/api/pager/firmware/compile/stream` | Admin | Compile `pager_client.ino` for the capcode(s) this unit answers to |
| POST | `/api/pager/firmware/flash/stream` | Admin | Upload the compiled build |
| GET | `/api/reticulum-companion/firmware/targets` | Admin | Heltec V4 Reticulum node (single fixed PlatformIO environment) |
| POST | `/api/reticulum-companion/firmware/compile/stream` | Admin | Write `node_config.h` (WiFi + backbone) and build with PlatformIO |
| POST | `/api/reticulum-companion/firmware/flash/stream` | Admin | Upload the built image |

The POCSAG/DAPNET companion flasher (`/api/pocsag/firmware/*`) is provided by the DAPNET plugin, see below.

## Emergency pager (ch9)

Core feature, enabled with `radio.pager_enabled` (settings: `PUT /api/config/radio/pager` above).

| Method | Path | Role | Description |
|---|---|---|---|
| GET | `/api/pager/status` | Viewer | Config + live state (drives the sidebar/topbar and page header) |
| GET | `/api/pager/messages` | Viewer | Inbox (`direction=in`) or Outbox (`direction=out`), newest first |
| GET | `/api/pager/stats` | Viewer | Totals for the page's stat tiles |
| GET | `/api/pager/export/inbox.csv` | Viewer | All received pager messages as CSV |
| GET | `/api/pager/export/outbox.csv` | Viewer | All sent pager messages (with ack status) as CSV |
| POST | `/api/pager/send` | Admin | Transmit one message on ch9 (needs `radio.pager_capcode`) |

## Plugins & plugin sources

| Method | Path | Role | Description |
|---|---|---|---|
| GET | `/api/plugins` | Viewer | Every discovered plugin with config, load state, dependency verdict and provenance |
| PUT | `/api/plugins/{plugin_id}` | Admin | Enable/disable (`plugins.<id>.enabled`, restart to apply); refuses a hook whose host is off, cascades disables to dependents |
| POST | `/api/plugins/{plugin_id}/check` | Admin | Re-run one plugin's `[deps] check` now |
| POST | `/api/plugins/check-all` | Admin | Re-run every plugin's `[deps] check` concurrently |
| POST | `/api/plugins/{plugin_id}/setup/stream` | Admin | Run the plugin's `setup.sh` (`sudo bash`), streamed |
| DELETE | `/api/plugins/{plugin_id}` | Admin | Delete a community plugin's folder (not built-in or locked ones) |
| GET | `/api/plugin-sources` | Viewer | Configured plugin sources (+ whether `plugin_sources_enabled` is on) |
| POST | `/api/plugin-sources` | Admin | Add a source (needs `plugin_sources_enabled` + `confirm: true`) |
| PATCH | `/api/plugin-sources` | Admin | Change a source's ref — pin to the current commit / unpin |
| DELETE | `/api/plugin-sources` | Admin | Forget a source (installed plugins stay) |
| GET | `/api/plugin-sources/catalog` | Admin | Fetch a source's `repo.json` with installed/update/compatible state per entry |
| GET | `/api/plugin-sources/resolve` | Admin | Resolve a source ref to its current commit (for the update confirm) |
| POST | `/api/plugin-sources/install` | Admin | Install, update or reinstall one plugin/theme from a source (needs `plugin_sources_enabled`) |
| GET | `/plugins/apps/{plugin_id}/{path}` | Viewer | Serve a plugin's declared frontend files (scripts/styles from its `plugin.toml`, no other paths) |

## Themes

| Method | Path | Role | Description |
|---|---|---|---|
| GET | `/api/themes` | Viewer | Available themes (built-in, plugin theme packs, custom) + the server default |
| PUT | `/api/config/dashboard/theme` | Admin | Set the default theme for all browsers (`dashboard.theme`) |
| POST | `/api/themes` | Admin | Save a custom theme from the theme editor |
| DELETE | `/api/themes/{theme_id}` | Admin | Delete a custom theme (locked theme-pack themes can't be deleted) |

---

## Nodes, packets & analytics

| Method | Path | Role | Description |
|---|---|---|---|
| GET | `/api/nodes` | Viewer | All discovered nodes |
| GET | `/api/nodes/count` | Viewer | Total node count |
| GET | `/api/nodes/summary` | Viewer | Whole-network totals (nodes, positions, packets per protocol) |
| GET | `/api/nodes/{node_id}` | Viewer | Single node detail |
| GET | `/api/nodes/{node_id}/metrics_history` | Viewer | A node's telemetry history for drawer charts |
| GET | `/api/packets` | Viewer | Recent packets (paginated) |
| GET | `/api/packets/count` | Viewer | Total packet count |
| GET | `/api/packets/by-source/{source_id}` | Viewer | Recent packets from one node (node-drawer "Recent Packets") |
| GET | `/api/analytics/traffic` | Viewer | Traffic rates and counts |
| GET | `/api/analytics/traffic/timeline` | Viewer | Traffic over time (chart data) |
| GET | `/api/analytics/signal/rssi` | Viewer | RSSI distribution |
| GET | `/api/analytics/signal/snr` | Viewer | SNR distribution |
| GET | `/api/analytics/signal/summary` | Viewer | Best/worst/average signal summary |
| GET | `/api/analytics/topology` | Viewer | Legacy topology analytics (see also `/api/topology/graph`) |
| GET | `/api/stats/summary` | Viewer | Dashboard stats-bar summary |
| GET | `/api/topology/graph` | Viewer | Mesh topology graph: nodes + edges from traceroutes, direct receptions, and neighbour imports |

## Per-protocol data (LoRaWAN / Meshtastic / MeshCore)

| Method | Path | Role | Description |
|---|---|---|---|
| GET | `/api/lorawan/devices` | Viewer | LoRaWAN device list (frame count, RSSI, SF, first/last seen) |
| GET | `/api/lorawan/packets` | Viewer | Recent LoRaWAN packet log (max 1000) |
| GET | `/api/lorawan/stats` | Viewer | LoRaWAN totals: packets, unique devices, by frame type |
| GET | `/api/lorawan/export/packets.csv` | Viewer | Download all LoRaWAN packets as CSV |
| GET | `/api/lorawan/export/devices.csv` | Viewer | Download the LoRaWAN device census as CSV |
| GET | `/api/meshtastic/nodes` | Viewer | Meshtastic node list |
| GET | `/api/meshtastic/packets` | Viewer | Recent Meshtastic packet log |
| GET | `/api/meshtastic/stats` | Viewer | Meshtastic totals |
| GET | `/api/meshtastic/export/packets.csv` | Viewer | Download all Meshtastic packets as CSV |
| GET | `/api/meshtastic/export/nodes.csv` | Viewer | Download the Meshtastic node census as CSV |
| GET | `/api/meshcore/nodes` | Viewer | MeshCore node list |
| GET | `/api/meshcore/packets` | Viewer | Recent MeshCore packet log |
| GET | `/api/meshcore/stats` | Viewer | MeshCore totals |
| GET | `/api/meshcore/repeaters` | Viewer | Known MeshCore repeaters (contact roster) |
| GET | `/api/meshcore/export/packets.csv` | Viewer | Download all MeshCore packets as CSV |
| GET | `/api/meshcore/export/contacts.csv` | Viewer | Download the MeshCore contact census as CSV |

## DAPNET (plugin)

Provided by the **DAPNET** community plugin (install from [meshpoint-plugins](https://github.com/javastraat/meshpoint-plugins), `plugins.dapnet.enabled: true`) — DAPNET/POCSAG amateur-radio paging via a serial-connected companion board. Unlike the RTL-SDR plugins below, DAPNET is a real `CaptureSource` joining the core packet pipeline directly (the `"capture"`/`"protocol"` plugin seams — see `docs/PLUGINS.md`), not an on-demand subprocess listener.

| Method | Path | Role | Description |
|---|---|---|---|
| GET | `/api/dapnet/capcodes` | Viewer | DAPNET capcode roster (frame count, last text, first/last seen) |
| GET | `/api/dapnet/packets` | Viewer | Recent DAPNET page log (max 1000) |
| GET | `/api/dapnet/stats` | Viewer | DAPNET totals: pages, unique capcodes, by page type |
| GET | `/api/dapnet/export/packets.csv` | Viewer | Download all DAPNET pages as CSV |
| GET | `/api/dapnet/export/capcodes.csv` | Viewer | Download the DAPNET capcode roster as CSV |
| GET | `/api/dapnet/settings` | Viewer | Current device list, capcode filters, and status-poll interval |
| PUT | `/api/dapnet/settings` | Admin | Replace the device list and/or blacklist/ignore capcode lists and/or poll interval (capcode lists apply immediately; devices/poll interval need a restart) |
| GET | `/api/dapnet/status` | Viewer | Live per-companion connection status (connected, board, callsign, frequency, hostname, WiFi) — polled by both the plugin's own topbar chip and its page-level status card |
| PUT | `/api/config/dapnet/callsign` | Admin | Set one companion's callsign over its live serial connection (label-scoped) |
| PUT | `/api/config/dapnet/web-password` | Admin | Set one companion's web dashboard password over serial (never cached/logged) |
| POST | `/api/config/dapnet/reset-credentials` | Admin | Reset one companion's callsign + web password to firmware defaults |
| PUT | `/api/config/dapnet/wifi` | Admin | Set one companion's WiFi SSID/password over serial (takes effect on next reboot) |
| POST | `/api/config/dapnet/reboot` | Admin | Reboot one companion |
| POST | `/api/config/dapnet/send` | Admin | Send a page from one companion |
| GET | `/api/pocsag/firmware/targets` | Viewer | Board targets auto-discovered from the companion sketch's `BOARD_*` defines |
| POST | `/api/pocsag/firmware/compile/stream` | Admin | Compile the companion sketch for a chosen board (NDJSON stream) |
| POST | `/api/pocsag/firmware/flash/stream` | Admin | Flash a compiled build to a chosen USB-serial port (NDJSON stream) |

## Reticulum (plugin)

Provided by the **Reticulum** community plugin (install from [meshpoint-plugins](https://github.com/javastraat/meshpoint-plugins), `plugins.reticulum.enabled: true`) — native Reticulum/LXMF messaging: meshpoint's own LXMF delivery destination (attached to a local `rnsd` shared instance) plus the peer roster built from announces. Uses the `"service"` plugin seam for the `LxmfService` lifecycle (see `docs/PLUGINS.md`). Message *history* is the shared `messages` table (`protocol='reticulum'`), read via the Messages endpoints below.

| Method | Path | Role | Description |
|---|---|---|---|
| GET | `/api/reticulum/status` | Viewer | Service state: running, own LXMF address, peer count, and a `node` block (hosting state / page count / requests served / last announce) when a NomadNet node is hosted |
| GET | `/api/reticulum/peers` | Viewer | Known-destinations roster from announces (`lxmf.delivery` / `lxmf.propagation` / `nomadnetwork.node`), newest first; a row gains `petname`/`trusted` when a contact exists for it |
| GET | `/api/reticulum/messages/{destination_hash}` | Viewer | One conversation's message history (from the shared `messages` table) |
| POST | `/api/reticulum/send` | Admin | Send a direct LXMF message (`destination_hash`, `text`) — the Messages page posts here for `protocol='reticulum'` conversations |
| POST | `/api/reticulum/announce` | Admin | Re-send meshpoint's own LXMF delivery announce on demand |
| GET | `/api/reticulum/propagation` | Viewer | Both halves of propagation: `local` (this box's relay, or null) and `client` (outbound node + current/last sync state) |
| POST | `/api/reticulum/propagation/sync` | Admin | Pull messages parked for us on the configured outbound propagation node (400 if none configured); returns once dispatched — poll `GET /propagation` for state |
| POST | `/api/reticulum/propagation/sync/cancel` | Admin | Cancel an in-flight propagation sync |
| GET | `/api/reticulum/telemetry` | Viewer | Telemetry-publish status (collector, interval, last-sent, last-error) or null when not configured |
| POST | `/api/reticulum/telemetry/send` | Admin | Send one telemetry frame (host stats → Sideband `FIELD_TELEMETRY`) to the collector now |
| GET | `/api/reticulum/telemetry/peers` | Viewer | Latest telemetry received from other nodes — one entry per peer (temp, status line, lat/lon), newest first, in-memory |
| GET | `/api/reticulum/contacts` | Viewer | The operator's petname address book — `{hash: {petname, note, trusted, updated}}`, stored in `data/reticulum/contacts.json`, never announced |
| PUT | `/api/reticulum/contacts/{destination_hash}` | Admin | Set a contact (`petname`, optional `note`, `trusted`); an empty `petname` removes it |
| DELETE | `/api/reticulum/contacts/{destination_hash}` | Admin | Forget a contact |
| GET | `/api/reticulum/nomad/nodes` | Viewer | `nomadnetwork.node` peers in the roster (the Browse tab's node list) |
| POST | `/api/reticulum/nomad/page` | Admin | Fetch one NomadNet page over an RNS Link (`destination_hash`, `path`, optional `field_data`) → `{ok, content}` (Micron markup) or `{ok: false, error}` |
| POST | `/api/reticulum/nomad/file` | Admin | Fetch a `/file/...` path → the raw bytes as an attachment, or a 502 |
| GET | `/api/config/reticulum` | Admin | Current `plugins.reticulum.*` — display name, NomadNet timeout, NomadNet-node hosting (enabled/name/pages dir/interval), RNode radio, TCP backbone (the page's Settings tab loads this) |
| PUT | `/api/config/reticulum` | Admin | Save those settings (NomadNet timeout applies immediately; the rest need a restart, and `rnsd` restart for RNode/backbone) |
| POST | `/api/config/reticulum/restart-rnsd` | Admin | Restart the `rnsd` systemd unit so it re-reads its generated config, then restart `meshpoint` itself too (detached) — both are needed, since whichever process has been running longer holds the live RNode/backbone interfaces as a shared RNS instance |
| GET | `/api/reticulum/announces` | Viewer | Recent announces heard, newest first (the Activity tab; in-memory) |
| GET | `/api/reticulum/peers/{destination_hash}/link` | Viewer | Live routing + last-known signal for one peer (the peer drawer) |
| GET | `/api/reticulum/attachments/{attachment_id}` | Viewer | Raw bytes of one image attachment from a message |
| POST | `/api/reticulum/paper` | Admin | Build a Paper Message (a real LXMF message exported as a QR / `lxm://` link, never sent over the air) |
| POST | `/api/reticulum/nomad/fingerprint` | Viewer | Identify our own Reticulum identity to a NomadNet node over its Link |
| GET | `/api/reticulum/nomad/pages` | Admin | Editable `*.mu` files of this box's own hosted NomadNet node (index.mu first) |
| GET/PUT/DELETE | `/api/reticulum/nomad/pages/{name}` | Admin | Read / save / delete one hosted page |
| GET | `/api/reticulum/nomad/sample-page` | Admin | The bundled sample `index.mu` (the "Load sample" button) |
| POST | `/api/reticulum/call/initiate` | Admin | Start a `call.audio` voice call to a peer (used by the reticulum-call plugin's Call tab) |
| POST | `/api/reticulum/call/{call_hash}/hangup` | Admin | Hang up a call |

## Messages (chat)

| Method | Path | Role | Description |
|---|---|---|---|
| POST | `/api/messages/send` | Admin | Send a Meshtastic or MeshCore message |
| POST | `/api/messages/advert` | Admin | Send a MeshCore advert |
| GET | `/api/messages/conversations` | Viewer | Message history by conversation |
| GET | `/api/messages/conversation/{node_id}` | Viewer | Single conversation's messages |
| POST | `/api/messages/conversation/{node_id}/read` | Viewer | Mark a conversation as read |
| DELETE | `/api/messages/conversation/{node_id}` | Admin | Delete one conversation |
| DELETE | `/api/messages/all` | Admin | Delete all messages |
| GET | `/api/messages/channels` | Viewer | Configured channel list for the Messages sidebar |
| GET | `/api/messages/contacts` | Viewer | Known contacts for the Messages sidebar |
| GET | `/api/messages/status` | Viewer | Messaging subsystem status (companion connected, etc.) |

---

## Device & system status

| Method | Path | Role | Description |
|---|---|---|---|
| GET | `/api/device` | Viewer | Device summary |
| GET | `/api/device/status` | Viewer | Device health and uptime |
| GET | `/api/device/metrics` | Viewer | Live CPU/RAM/disk/temp/load-average stats-bar data |
| GET | `/api/device/thermals` | Viewer | CPU temperature + fan duty history (6 h in-memory, requires fan control) |
| GET | `/api/device/update-check` | Viewer | Cached result of the last periodic update check |
| GET | `/api/device/spectrum` | Viewer | Latest band sweep (median/peak per 100 kHz step) from the SX1261, the RF Environment companion, or the SX1302 capture RAM (then `units: "db_rel"` plus a `calibration` block) |
| POST | `/api/device/spectrum/sweep` | Admin | Trigger an on-demand band sweep |
| POST | `/api/device/spectrum/calibrate` | Admin | Capture-RAM spectrum only: run a calibration sweep and save its median shape as the baseline |
| DELETE | `/api/device/spectrum/calibrate` | Admin | Capture-RAM spectrum only: forget the baseline |
| GET | `/api/sdr/status` | Viewer | Who holds the shared RTL-SDR dongle right now (works whichever RTL-SDR plugins are installed; drives the sidebar badge) |
| GET | `/api/rf/status` | Viewer | RF Environment tab data: noise floor, calibration, latest scan histogram |
| GET | `/api/rf/stray-frames` | Viewer | Frames that failed every protocol decoder (in-memory ring buffer, newest 500) |
| GET | `/metrics` | Public\* | Prometheus scrape endpoint (opt-in via `metrics.enabled`; \*auth is config-driven via `metrics.require_auth`, defaults to on) |

---

## RTL-SDR listeners (Radio and friends)

Nothing RTL-SDR-related is built in by default anymore -- Radio, Pagers, POCSAG, P2000, RTL433, ADS-B, ACARS and DAB+ are all opt-in plugins (`plugins.rtlsdr.enabled: true` plus whichever of these you want; see their own `plugins/apps/*/README.md`). Only one of them holds the RTL-SDR dongle at a time regardless of which are installed.

The routes below are provided by the **Radio** plugin (`plugins/apps/radio/`) and kept at their original `/api/listener/*` prefix from before Radio was extracted out of core.

| Method | Path | Role | Description |
|---|---|---|---|
| GET | `/api/listener/status` | Viewer | RTL-SDR listener state: frequency, mode, RDS (PS/RadioText/PTY/BLER), audio level |
| POST | `/api/listener/tune` | Admin | Tune the RTL-SDR: frequency, mode, squelch, gain, level, optional preset station label |
| POST | `/api/listener/stop` | Admin | Stop the RTL-SDR listener |
| GET | `/api/listener/stream` | Viewer | Live MP3 audio stream for the browser player |

The decoder plugins each mount their own prefix — `/api/pagers`, `/api/pocsag`, `/api/p2000`, `/api/rtl433`, `/api/acars` (`status` · `start` · `stop` · `clear`), `/api/adsb` (`status` · `start` · `stop`, aircraft snapshot instead of a message log) and `/api/dab` (tune / stop / status / MP3 stream, scan results, live-streamed channel scan). `GET .../status` is Viewer, the rest Admin. From plugin version 1.2.0 each of them, DAB+ included, also has `PUT .../keep-running` (Admin) to switch its 10-minute idle auto-stop off, saved to `plugins.<id>.keep_running`. See each plugin's README in meshpoint-plugins.

## Other plugins

Mounted only when the plugin is installed and enabled; see each plugin's README in [meshpoint-plugins](https://github.com/javastraat/meshpoint-plugins) for the exact routes.

| Prefix | Plugin |
|---|---|
| `/api/bluetooth-scanner/...` | Bluetooth Scanner: start/stop a BLE scan, live device table |
| `/api/offline-map/...` | Offline Maps: tile downloader builds and downloads |
| `/api/oled-display/...` | OLED Display: settings and status of the I2C status screen |
| `/api/raspberry-network/...` | Raspberry Network: WiFi scan and switch |

`reticulum-browser`, `reticulum-call` and `reticulum-dashboard` add no routes of their own; they use the Reticulum plugin's routes above.

---

## Self-update system

| Method | Path | Role | Description |
|---|---|---|---|
| GET | `/api/update/badge` | Admin | Sidebar "update available" badge state |
| PUT | `/api/update/check-settings` | Admin | Enable/disable and set interval for periodic update checks |
| GET | `/api/update/channels` | Admin | Available update channels (Stable/RC) |
| GET | `/api/update/branches` | Admin | Branches on this install's resolved repo, for the custom-branch picker |
| GET | `/api/update/install_status` | Admin | Progress of an in-flight install/apply |
| POST | `/api/update/check` | Admin | Check GitHub for a newer version now |
| GET | `/api/update/release_notes` | Admin | Parsed changelog for the installed/available version |
| POST | `/api/update/apply` | Admin | Apply an update (`git pull` + restart) |
| POST | `/api/update/apply/stream` | Admin | Same as `apply`, streamed progress (SSE-style) |
| POST | `/api/update/rollback` | Admin | Roll back to the previous version |
| POST | `/api/update/rollback/stream` | Admin | Same as `rollback`, streamed progress |

## Backup & restore

| Method | Path | Role | Description |
|---|---|---|---|
| GET | `/api/system/backup/status` | Admin | Last backup/restore timestamps and state |
| GET | `/api/system/backup/download` | Admin | Download config + data backup archive |
| POST | `/api/system/backup/restore` | Admin | Restore a backup archive |

## Terminal (PTY in the browser)

| Method | Path | Role | Description |
|---|---|---|---|
| GET | `/api/terminal/commands` | Admin | Quick-command catalog for the Terminal tab |
| GET | `/api/terminal/status` | Admin | Whether a PTY session is currently active |
| WS | `/api/terminal/ws` | Admin | Live PTY stream; manually role-checked before the connection is accepted |

## Debug / operator actions

| Method | Path | Role | Description |
|---|---|---|---|
| GET | `/api/dangerous/actions` | Admin | List of available one-off maintenance actions |
| POST | `/api/dangerous/invoke` | Admin | Run one of those actions |

---

## Public, unauthenticated

| Method | Path | Description |
|---|---|---|
| GET | `/api/public/recent_rx` | Deliberately scrubbed + IP rate-limited public radar feed — no session required by design |
| GET | `/setup` | First-run page to create the admin account (only while unconfigured) |
| GET | `/login` | Login page |
| GET | `/` | The dashboard itself (redirects to `/login` or `/setup` without a session) |

## WebSocket

| Path | Role | Description |
|---|---|---|
| `/ws` | Viewer/Admin | Real-time packet + message stream for the dashboard. Requires a valid session; closes with 4401 otherwise |
| `/api/terminal/ws` | Admin | PTY stream for the Terminal tab (see above) |

---

*Core routes re-audited against `src/api/routes/*.py` and `src/api/server.py` on 2026-10-03 (all 183 core routes listed), plugin routes against meshpoint-plugins. If you add a new route, add a row here — nothing enforces this file staying in sync automatically.*
