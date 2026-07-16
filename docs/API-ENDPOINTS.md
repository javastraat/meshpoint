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
| PUT | `/api/config/radio/advanced` | Admin | Advanced radio tuning (spreading factor, bandwidth, etc.) |
| GET | `/api/config/serial-ports` | Viewer | Enumerate connected USB-serial devices for the port-picker dropdown |

## Configuration — capture devices

| Method | Path | Role | Description |
|---|---|---|---|
| PUT | `/api/config/capture/meshcore-usb` | Admin | Legacy single-companion MeshCore USB config |
| PUT | `/api/config/capture/meshcore-companions` | Admin | Replace full MeshCore companion list (max 4) |
| GET | `/api/config/meshcore/firmware-check` | Viewer | Compare a companion's firmware against the latest `meshcore-dev/MeshCore` release (cached 5 min) |
| PUT | `/api/config/meshcore/companion-name` | Admin | Rename one MeshCore companion (label-scoped) |
| POST | `/api/config/meshcore/companion-advert` | Admin | Send an advert from one specific MeshCore companion (label-scoped) |
| PUT | `/api/config/capture/serial-devices` | Admin | Replace full Meshtastic USB stick list |
| GET | `/api/config/serial/firmware-check` | Viewer | Compare a Meshtastic USB stick's firmware against the latest `meshtastic/firmware` release (cached 5 min) |
| PUT | `/api/config/serial/identity` | Admin | Rename one Meshtastic USB stick's long/short name (label-scoped) |
| POST | `/api/config/serial/advert` | Admin | Send a NodeInfo broadcast from one specific Meshtastic USB stick (label-scoped) |
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
| GET | `/api/device/spectrum` | Viewer | Latest band sweep from the SX1302 spectral scanner (median/peak per 100 kHz step) |
| POST | `/api/device/spectrum/sweep` | Admin | Trigger an on-demand band sweep |
| GET | `/api/rf/status` | Viewer | RF Environment tab data: noise floor, calibration, latest scan histogram |
| GET | `/api/rf/stray-frames` | Viewer | Frames that failed every protocol decoder (in-memory ring buffer, newest 500) |
| GET | `/metrics` | Public\* | Prometheus scrape endpoint (opt-in via `metrics.enabled`; \*auth is config-driven via `metrics.require_auth`, defaults to on) |

---

## RTL-SDR listeners (Radio tab and friends)

Only one of Radio / P2000 / Pagers / POCSAG / RTL433 / DAB+ may hold the RTL-SDR dongle at a time.

| Method | Path | Role | Description |
|---|---|---|---|
| GET | `/api/listener/status` | Viewer | RTL-SDR listener state: frequency, mode, RDS (PS/RadioText/PTY/BLER), audio level |
| POST | `/api/listener/tune` | Admin | Tune the RTL-SDR: frequency, mode, squelch, gain, level, optional preset station label |
| POST | `/api/listener/stop` | Admin | Stop the RTL-SDR listener |
| GET | `/api/listener/stream` | Viewer | Live MP3 audio stream for the browser player |
| GET | `/api/p2000/status` · `/api/pagers/status` · `/api/pocsag/status` · `/api/rtl433/status` | Viewer | Decoder state: running, frequency, decoded messages |
| POST | `/api/p2000/start` · `/api/pagers/start` · `/api/pocsag/start` · `/api/rtl433/start` | Admin | Start the given decoder |
| POST | `/api/p2000/stop` · `/api/pagers/stop` · `/api/pocsag/stop` · `/api/rtl433/stop` | Admin | Stop the given decoder |
| GET | `/api/dab/status` | Viewer | DAB+ listener state: channel, ensemble label, SNR, decoded station list (sid, name, DLS text) |
| POST | `/api/dab/tune` | Admin | Tune to a DAB+ channel/ensemble (e.g. `12C`) |
| POST | `/api/dab/stop` | Admin | Stop the DAB+ listener |
| GET | `/api/dab/stream/{sid}` | Viewer | Live MP3 audio stream for one DAB+ station, proxied from welle-cli |

---

## Self-update system

| Method | Path | Role | Description |
|---|---|---|---|
| GET | `/api/update/badge` | Admin | Sidebar "update available" badge state |
| PUT | `/api/update/check-settings` | Admin | Enable/disable and set interval for periodic update checks |
| GET | `/api/update/channels` | Admin | Available update channels (Stable/RC) |
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

## WebSocket

| Path | Role | Description |
|---|---|---|
| `/ws` | Viewer/Admin | Real-time packet + message stream for the dashboard. Requires a valid session; closes with 4401 otherwise |
| `/api/terminal/ws` | Admin | PTY stream for the Terminal tab (see above) |

---

*Generated from a full route audit of `src/api/routes/*.py` and `src/api/server.py`. If you add a new route, add a row here — nothing enforces this file staying in sync automatically.*
