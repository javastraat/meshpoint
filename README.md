<p align="center">
  <img src="MP_logo.png" width="280" alt="Meshpoint Logo">
</p>

<h1 align="center">Meshpoint</h1>

<p align="center"><strong>Open-source Meshtastic base station with native TX/RX, 8-channel concentrator, and browser-based messaging.</strong><br>Runs on Raspberry Pi 4 + SX1302/SX1303. Supports US915, EU868, ANZ915, IN865, KR920, and SG923.</p>

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-green.svg)](https://www.python.org/)
[![Platform: Raspberry Pi](https://img.shields.io/badge/platform-Raspberry%20Pi%204-red.svg)](https://www.raspberrypi.com/)
[![Discord](https://img.shields.io/badge/Discord-Join-5865F2?logo=discord&logoColor=white)](https://discord.gg/BnhSeFXVY8)
[![GitHub stars](https://img.shields.io/github/stars/KMX415/meshpoint?style=flat&color=yellow)](https://github.com/KMX415/meshpoint/stargazers)
[![GitHub issues](https://img.shields.io/github/issues/KMX415/meshpoint)](https://github.com/KMX415/meshpoint/issues)
[![Last commit](https://img.shields.io/github/last-commit/KMX415/meshpoint)](https://github.com/KMX415/meshpoint/commits/main)
[![Version](https://img.shields.io/badge/version-0.7.7-orange.svg)](docs/CHANGELOG.md)
[![CI](https://github.com/javastraat/meshpoint/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/javastraat/meshpoint/actions/workflows/ci.yml)

### Meshradar Cloud Dashboard
![Meshradar Cloud Dashboard](Meshradar414.png)

### Local Dashboard
![Local Dashboard](Meshpoint61.png)

### Messaging
![Messaging](MessagingUI.png)

### Startup Log
![Startup Log](MP%20Log.png)

---

## What Is This?

A Raspberry Pi-based Meshtastic base station that sends and receives messages through an SX1302/SX1303 concentrator. The concentrator decodes SF7 through SF12 in parallel on one tuned frequency (eight demod chains). It transmits natively with up to 27 dBm output. Phones and nodes see it as a regular participant on the mesh.

Everything is managed from a browser dashboard: full chat with channels and DMs, node discovery, radio configuration, and live packet feed. Also supports MeshCore traffic through USB companions and passively sniffs LoRaWAN traffic. Optionally syncs upstream to [Meshradar](https://meshradar.io) for aggregated multi-site mesh intelligence.

### Standard Node vs Meshpoint

| | Standard Node | Meshpoint |
|---|---|---|
| **Radio** | Single transceiver | SX1302 concentrator (RX + TX) |
| **Role** | Participant | Observer + participant |
| **Packet visibility** | Own traffic | Everything in range |
| **Messaging** | Phone app only | Full chat from any browser |
| **Storage** | None | SQLite with retention |
| **Dashboard** | None | Real-time web UI with radio config |

---

## What's Different in This Fork

This is a customized fork of upstream [KMX415/meshpoint](https://github.com/KMX415/meshpoint), tuned for a SenseCap M1 "mega-sniffer" **and** a browser radio receiver. It tracks upstream (their v0.7.7 — backup/restore, RF Environment, Quick Deploy QR, Prometheus metrics — is merged in full), and on top of everything upstream provides, this version adds:

**RTL-SDR broadcast & utility radio listener** (entirely new)
- Browser radio receiver on a cheap RTL-SDR dongle — FM broadcast, airband (AM), marine VHF/UHF, PMR446, 2 m / 70 cm ham, SSB (~24–1766 MHz), independent of the SX1302 so LoRa capture keeps running.
- Modes **WFM / NFM / AM / USB / LSB**, with squelch, gain, and pre-encoder level controls.
- Two switchable radio faces — **Digital** (VFD readout + segmented VU) and **Analogue** (slide-rule dial + swinging-needle VU gauge under glass), persisted per browser.
- Real-time **Web Audio VU meter** that follows the audio.
- **RDS** on FM (via `redsea`): station name, scrolling RadioText / now-playing, program type (PTY), and a block-error-rate signal-quality meter.
- **Preset stations picker** — category tabs, search across all presets, ★ favorites, and green "now playing" dots on the tuned channel and its category.
- New `/api/listener/*` endpoints.
- **DAB+ tab** via [`welle-cli`](https://github.com/AlbrechtL/welle.io) — pick a channel/ensemble (e.g. `12C` for the NPO nationals), then a station once it's decoded; ★ favorites jump straight to a channel + station in one click. New `/api/dab/*` endpoints.

**Expanded multi-protocol capture**
- **LoRaWAN passive sniffing** — full MAC decoder (Join / Data / Rejoin), a dedicated LoRaWAN dashboard panel, and `/api/lorawan/*` endpoints, using the SX1302 "dual sync-word" trick (ch0–ch7 on LoRaWAN 0x34, ch8 on Meshtastic 0x2B).
- **EU868 5-channel LoRaWAN plan** (867.9 / 868.1 / 868.3 / 868.5 / 868.7 MHz) across RF0's full IF window — the 3 mandatory uplinks plus 2 extra TTN channels.
- **Up to 4 MeshCore USB companions** plus a Meshtastic-433 serial source → 5 networks captured at once.
- **MeshCore per-packet metadata** — frequency/SF read from the companion's radio config, hop count decoded from the MeshCore `path_len`, and each companion's packets labeled by source.
- **Up to 40 MeshCore user channels** (slots 1–40, slot 0 stays Public) — raised from 7.

**Hardware page & spectrum**
- **Band spectrum card** — the concentrator module's onboard SX1261 companion chip (not a USB radio) sweeps the whole region band (100 kHz steps, EU868: 863–870 MHz) and draws a live spectrum chart with median + peak level and the LoRaWAN / Meshtastic / MeshCore channel positions overlaid; "Sweep now" button, hover readout, `GET /api/device/spectrum`. Requires `radio.sx1261_spi_path` (e.g. `/dev/spidev0.1`) in `local.yaml`; cadence via `radio.spectrum_sweep_interval_seconds`.
- **RF Environment works on the SenseCap M1** — upstream marks spectral scan unavailable on the M1; this fork's `sx1261_spi_path` support powers upstream's RF Environment tab with live hardware scans here (and its histogram's endless-page-growth bug is fixed).
- **Concentrator channels card** — read-only table of all 9 SX1302 slots (frequency, BW, SF, sync word, protocol, RF chain, state), derived from the same channel-plan code the radio runs.
- **Unified protocol cards** — "Meshtastic Configuration" (radio settings + channel list in one card) and a matching MeshCore Companion layout, which also shows the companion's firmware version alongside its frequency/bandwidth/SF/TX power readouts.
- **Node drawer recent packets** — every node shows its last 15 packets (time, type, RSSI/SNR).
- **SNR distribution chart** on Stats next to the RSSI histogram; signal stats ignore implausible near-field readings (> −20 dBm).
- **Relay tuning from the dashboard** — burst size and the min/max RSSI relay window are editable on Configuration → Transmit.
- **Temperature-driven PWM fan control** (opt-in, SenseCap M1 only) — the onboard fan ramps speed with CPU temperature instead of running flat-out or not at all; `fan:` in `local.yaml`.
- **Thermals card** — 6 h of CPU temperature + fan duty history as two stacked charts on the Hardware page (`GET /api/device/thermals`); shown only when fan control is enabled.
- **Status LED** (opt-in, SenseCap M1 only) — the case LED becomes a glanceable health light: steady on = all capture sources healthy, brief flicker = packet captured, 1 Hz blink = a source is down, dark = service not running; `led:` in `local.yaml`.
- **User button** (opt-in, SenseCap M1 only) — short press adverts on every TX-capable radio (Meshtastic 868 + 433, MeshCore), long press (3 s) restarts the service; LED feedback for every gesture; `button:` in `local.yaml`.
- **Configuration → Peripherals page** — edit the fan, status LED, and user button settings above from the dashboard instead of hand-editing `local.yaml`.
- **CSV export** — an Export button on each protocol page (LoRaWAN / Meshtastic / MeshCore) downloads the active tab's dataset: all captured packets, or the full device/node/contact census. Streamed straight from the database (so "all packets" really is all), UTF-8 with a BOM so Excel handles the emoji, and LoRaWAN packet exports flatten DevEUI/FCnt/FPort/MIC into their own columns for coverage analysis.
- **MeshCore repeater monitoring** (opt-in) — MeshCore nodes advertise identity only, so Meshpoint can actively poll repeaters you operate (`req_status`/`req_telemetry`, like the phone app) for battery, uptime, airtime, packet counters, noise floor and LPP sensors. A dedicated **Repeaters** page shows a Health / Sensors / History card row plus a Trends chart of the voltage/temperature/humidity/pressure history, and its neighbour count opens a modal listing each one (freshest-first, names resolved against the known roster). Each poll also feeds the reported neighbours into the roster (placeholder nodes, `nb:`-tagged packets — same convention `scripts/import_contacts.py`'s manual import uses, just live), so the Health card can show a **Farthest neighbour** distance/SNR/name per repeater, measured from that repeater's own position rather than Meshpoint's (a repeater can be a remote site). Configured from the dashboard at **Configuration → Repeater Poll** (enable/interval, add/rename/remove repeaters) — no more hand-editing `repeater_poll:` in `local.yaml`.

**Roles, config & self-update**
- **Viewer role locked down server-side** — all write endpoints require admin; channel PSKs/keys are redacted for viewers; admin-only links show a toast instead of navigating away.
- **Web server port from config** — `dashboard.host`/`dashboard.port` in `local.yaml` via a launcher that falls back to `0.0.0.0:8080` if the config is broken or the port unbindable.
- **Self-update against this fork** — version checks and the apply chain point at `javastraat/meshpoint`, sudoers/safe.directory repairs are self-installing, update checks work on dev checkouts (sudo only when the repo is root-owned), "Check for updates" lists the incoming commit messages so you can see what an Apply brings, a **Latest commits** list shows the last five commits on the channel's GitHub branch (date, SHA, message), and the release-notes preview groups its bullets under the changelog's category headings.
- **Automatic update checks** (on by default) — a background task periodically re-checks for updates using the same git-fetch logic as the manual button, and an "Update available" pill appears under the device status at the top of the sidebar the moment one's found; click it to jump straight to Settings → Updates. Interval and on/off are editable from that same page; `update_check:` in `local.yaml`.

**Contacts / neighbours tooling**
- `import_contacts.py` imports a MeshCore contacts/neighbours list into the node DB, with clock-skew-immune timestamps (`now − secs_ago`) and freq/SF stamping.
- `scripts/repair_neighbour_timestamps.py` + `scripts/backfill_meshcore_signal.py` fix bad past/future timestamps and backfill freq/SF on old rows.
- `scripts/edit_contact.py` interactively looks up and corrects a node's stored name/GPS in the database (e.g. a stale fix on a node whose real location you know) — shows the current values, confirms before editing, and confirms again before writing.

**UI / UX**
- **Mesh topology graph + map** — a Topology page draws the mesh as a force-directed graph: Meshtastic traceroute chains, direct receptions by this box, and MeshCore neighbour SNR become nodes and edges you can drag, zoom, and filter. A Graph|Map switch projects the same network onto real map tiles, an "all positions" layer shows every positioned-but-unlinked node as a faint scouting dot, and with repeater polling enabled the graph refreshes itself — each poll fetches the repeater's own neighbour list (`fetch_all_neighbours`), so every polled repeater becomes a live star. `GET /api/topology/graph`.
- **Incoming-message notifications** — corner toast with sender + snippet (click jumps to the conversation) and an optional soft notification sound; independent per-browser toggles in Settings → System.
- **Topbar theme toggle** (cycles the dark / high-contrast / sunlight themes with a per-theme icon).
- **24-hour time** across the whole dashboard.
- **Metric defaults** (Celsius + kilometers) for a fresh browser.

> Because this is a fork, a dashboard **Update** (which runs `git reset --hard origin/main`) will overwrite these changes unless your `origin` remote points at this fork rather than upstream.

---

## Features

**5 networks simultaneously.** A single Meshpoint captures LoRaWAN (868 MHz), Meshtastic (868 MHz), MeshCore (868 MHz), MeshCore (433 MHz), and Meshtastic (433 MHz) at the same time — all from one device. The onboard SX1302 handles LoRaWAN and Meshtastic 868; USB companion radios extend coverage to MeshCore and 433 MHz bands.

**Native mesh messaging.** Send and receive Meshtastic messages directly from the dashboard. Broadcast to channels, DM individual nodes, or reply in conversations. MeshCore messaging supported through the USB companion. The SX1302 handles TX using the same sync word and encryption as the mesh network: phones and nodes see your Meshpoint as a regular participant.

**LoRaWAN passive sniffing.** Captures LoRaWAN traffic on EU868 channels (867.9 / 868.1 / 868.3 / 868.5 / 868.7 MHz) alongside Meshtastic without interfering. MAC layer fully decoded: Join-Request (JoinEUI, DevEUI, DevNonce), Data Up/Down (DevAddr, FCnt, FPort, payload length), and Rejoin frames. Payload is not decrypted (no session keys). All LoRaWAN traffic is strictly listen-only — never relayed. Accessible from its own dashboard panel with per-device stats.

**Smart relay (experimental).** Re-broadcast captured Meshtastic packets through the same onboard SX1302, identity-preserving — original sender attribution and packet IDs survive, only the hop counter decrements. No second radio required. Filter by signal strength, packet type, and rate limit; share duty-cycle budget with messaging so relay traffic can never crowd out user TX. Enable via `relay.enabled: true` in `local.yaml`. See [Configuration > Smart Relay](docs/CONFIGURATION.md#smart-relay) for details.

**Full chat UI.** Conversations organized by channel and contact. Signal info (SNR, RSSI) on every received bubble. Duplicate badge shows how many times a relayed message was heard. Channel sidebar with LongFast, custom channels, and DM contacts. Message history persisted in SQLite.

**Radio configuration from the dashboard.** Change region, modem preset, frequency, TX power, and duty cycle without SSH. Add and remove channels with custom PSKs. Toggle TX enable/disable. All settings saved to `local.yaml` and survive restarts.

**Web terminal.** A full shell in the browser (Ops → Terminal, admin only): a real PTY streamed over WebSocket with search, clipboard support, and a one-click catalog of common maintenance commands. Quick fixes without reaching for an SSH client.

**Dashboard authentication.** First visit prompts you to set an admin password; sessions are HttpOnly cookies with failed-login lockout. An optional read-only **viewer** role shares the dashboard without exposing configuration, channel keys, or any write access.

**Node discovery.** Live node cards showing every node your Meshpoint has heard: name, ID, protocol, hardware model, signal strength, battery, and last seen. Click any node to open a detail drawer with metrics history, its most recent packets, and direct message.

**Multi-companion MeshCore capture.** Up to 4 Heltec/T-Beam USB companions running MeshCore firmware can be attached simultaneously, each labeled by band. The dashboard shows a dynamic companion card per device. Companions are auto-detected on `/dev/ttyACM*`.

**Meshtastic 433 via serial.** A Heltec V3 or any Meshtastic-flashed node on `/dev/ttyUSB0` adds a fifth capture stream. Packets are decoded and displayed in the dashboard the same as 868 MHz Meshtastic packets.

**RTL-SDR broadcast & utility radio listener.** Plug in a cheap RTL-SDR dongle and listen to real radio from the browser — FM broadcast, airband (AM), marine VHF/UHF, PMR446, 2 m / 70 cm ham, and anything else in ~24–1766 MHz. Server-side `rtl_fm` demodulates (a **Mode** selector for WFM / NFM / AM / USB / LSB, plus squelch, gain, and pre-encoder level) and streams MP3 to a browser `<audio>` player, while the SX1302 keeps sniffing LoRa uninterrupted (separate hardware). Two selectable radio faces — a **Digital** VFD-style readout with a segmented VU meter, and an **Analogue** slide-rule tuner with a swinging-needle VU gauge — and a real-time Web Audio level meter that dances with the audio. **RDS** on FM (via [`redsea`](https://github.com/windytan/redsea)): station name, scrolling RadioText / now-playing, program type (PTY), and a block-error-rate signal-quality meter. A preset stations picker with category tabs, search, and ★ favorites (Amsterdam FM, PMR446, marine, Schiphol airband, ham). Four more tabs alongside Radio decode live signals instead of streaming audio — **P2000** (Dutch emergency dispatch, FLEX), **Pagers** (POCSAG512/1200/2400 on 172.45 MHz), and **POCSAG** (the same POCSAG512/1200/2400 decoders on a separate 439.9875 MHz band) each run a fixed `rtl_fm | multimon-ng` pipeline, while **RTL433** runs [`rtl_433`](https://github.com/merbanan/rtl_433) directly — a single self-contained decoder covering weather stations, TPMS, remote sensors, and hundreds of other 433/315/868 MHz OOK/FSK devices, far broader than the paging-only protocols above. All four have their own Start/Stop and a live decoded-message log; since the dongle can only be tuned to one frequency at a time, only one of Radio/P2000/Pagers/POCSAG/RTL433/DAB+ can run at once. A sixth tab, **DAB+**, wraps [`welle-cli`](https://github.com/AlbrechtL/welle.io) (welle.io's DAB/DAB+ decoder) for browser playback of Dutch DAB+ multiplexes — unlike the flat preset lists above, a DAB+ ensemble carries several stations at once, so it's a two-level pick: choose a channel (e.g. `12C` for the NPO nationals), wait for welle-cli to decode the station list, then pick a station; ★ favorites (channel + station together) do both steps in one click. A mini player also appears in the sidebar (in place of the noise-floor graph) whenever Radio or DAB+ is actively tuned — station name, mute, and stop — so playback can be checked and stopped from any page. See [RTL-SDR Radio Listener](#optional-rtl-sdr-radio-listener) for setup.

**Band spectrum view.** The concentrator module's onboard SX1261 sweeps the entire region band (EU868: 863–870 MHz in 100 kHz steps) every few minutes — without interrupting packet capture — and the RF Environment page draws the result as a live spectrum chart with every LoRaWAN, Meshtastic, and MeshCore channel position overlaid. See interferers (RFID readers, alarms) sharing your band at a glance. The Hardware page keeps the read-only table of the full 9-slot SX1302 channel plan.

**RF Environment tab.** A full-page view of your radio's health: live noise-floor readout with sparkline, calibration state, and the latest spectral-scan histogram — hardware-scanned when the SX1261 is available, packet-derived fallback otherwise. A **Stray Frames** card also lists RF frames that failed every protocol decoder (time, source, protocol hint, size, RSSI/SNR, expandable raw hex) instead of dropping them silently — an in-memory ring buffer (newest 500, cleared on restart), not yet a persisted table.

**Backup and restore.** Download a timestamped archive of `local.yaml` and the full `data/` directory (SQLite hot snapshot, PKI keys) from Settings, and restore it after an SD failure or bad experiment — the box returns to the snapshot, even after a database wipe. Admin-only; the archive contains all secrets, so store it offline.

**Operator tooling.** Click any packet-feed row for a full decode-metadata modal. KPI status strips on the Dashboard and RF tabs, and live MQTT broker health on the MQTT page. A **Quick Deploy QR** exports public channel parameters for field provisioning straight into the Meshtastic app (default key only — private PSKs never leave the box). Optional **Prometheus `/metrics`** endpoint with packet, node, relay, and system counters — configurable from **Configuration → Metrics** (enable + auth toggle apply immediately, no restart), full metric list and a sample scrape config in `docs/CONFIGURATION.md`.

**Broadcast cadence controls.** Position and telemetry broadcast intervals are editable from the dashboard with live countdowns (off, or 5 min–24 h), independent of NodeInfo, applied hot without a restart.

**Full packet decoding.** 14 Meshtastic portnums decoded: TEXT, POSITION, NODEINFO, TELEMETRY, ROUTING, ADMIN, WAYPOINT, DETECTION_SENSOR, PAXCOUNTER, STORE_FORWARD, RANGE_TEST, TRACEROUTE, NEIGHBORINFO, and MAP_REPORT. 6 MeshCore message types decoded. Device roles (CLIENT, ROUTER, REPEATER, TRACKER, SENSOR) extracted from NodeInfo.

**Multi-channel decryption.** Configure private channel PSKs from the dashboard or `local.yaml`. The Meshpoint decodes traffic on those channels alongside the default key and routes messages to the correct conversation. Supports any number of channels with AES-128 or AES-256 keys.

**6 frequency regions.** US, EU_868, ANZ, IN, KR, and SG_923. Select during setup or change from Configuration → Radio. MeshCore companion radios configure to match automatically.

**Real-time dashboard.** Live map with node positions, color-coded packet feed with frequency and spreading factor columns, traffic charts, signal analytics, node cards, and a dedicated LoRaWAN devices panel. Accessible from any device on your network.

**GPS and split placement.** USB GPS via `gpsd` drives the Configuration → GPS skyplot. Registered coordinates (wizard pin) always feed [Meshradar](https://meshradar.io) fleet view. Meshtastic POSITION broadcasts are separately configurable: registered pin or live GPS, with approximate (~1.1 km), precise, or hidden privacy. See [Configuration > Location](docs/CONFIGURATION.md#location-gps-source).

**Cloud integration.** Optional WebSocket uplink to [Meshradar](https://meshradar.io) for aggregated multi-site mesh intelligence. Fleet management, city-wide maps, and packet history across all your Meshpoints.

**Dual-protocol MQTT gateway.** Publish captured packets to community MQTT brokers and Home Assistant. Dual-protocol: Meshtastic (protobuf) and MeshCore (JSON) from a single device. Two-gate privacy model ensures private channel data never leaks. Optional JSON publishing, HA auto-discovery, and configurable location precision.

**Auto-detect hardware.** RAK Hotspot V2, SenseCap M1, and Syncrobit Chameleon (SX1302) supported; carrier board may show as generic SX1302/Pi during setup. **Bobcat Miner 300** (Rockchip RK3566 + SX1302 on Armbian) is community-validated with manual SPI/GPIO setup. **WisMesh Node** (RAK6421 Pi HAT + WisBlock SX1262, experimental) is documented on `main` and installs from branch `feat/wismesh-hat` until v0.7.6 merges. MeshCore USB companions auto-detected on `/dev/ttyUSB*` and `/dev/ttyACM*`.

---

## Hardware

> **Requirements:** Raspberry Pi 4 or Compute Module 4, **64-bit** Raspberry Pi OS or Raspbian Lite, Python 3.12+. **Bobcat Miner 300** uses Rockchip RK3566 + community Armbian (see below). Pi 3, Pi 5 (unvalidated), x86, and 32-bit OS are not supported.

### Option A: RAK Hotspot V2 (~$60, recommended)

The easiest path. RAK/MNTD Hotspot V2 miners (model **RAK7248**) include a Pi 4, RAK2287 (SX1302), Pi HAT, metal enclosure, antenna, and power supply: everything you need. Helium's IoT network didn't pan out, so these are all over eBay for $40-70.

[Find on eBay ($30-80)](https://www.ebay.com/sch/i.html?_nkw=RAK%20Hotspot%20V2%20%2F%20MNTD&_sacat=0&_from=R40&rt=nc&_udlo=30&_udhi=80)

<img src="rak7248.png" width="360" alt="RAK7248 Hotspot V2">

Remove the black tape covering the SD card slot and carefully remove SD. Flash a new card with Raspberry Pi OS 64-bit, run the install script, and you have a Meshpoint in a nice aluminum enclosure.

### Option B: SenseCap M1 (~$40-60)

Another Helium-era miner with identical compatibility. The SenseCap M1 includes a Pi 4, Seeed WM1303 concentrator (SX1303), carrier board, metal enclosure, and antenna. Some units ship with a 64GB SD card included.

[Find on eBay ($30-60)](https://www.ebay.com/sch/i.html?_nkw=SenseCap%20M1&_sacat=0&_from=R40&rt=nc&_udlo=30&_udhi=60)

<img src="docs/sensecap-m1.png" width="360" alt="SenseCap M1">

Remove the 2 screws on the back panel (the side without the Ethernet/antenna ports) to access the SD card: it may be held in place by kapton tape. Flash with Raspberry Pi OS 64-bit and run the install script. USB-C power connects to the carrier board, not the Pi directly.

### Option C: Syncrobit Chameleon (CM4 eMMC, SX1302)

Retired **Syncrobit Chameleon** LoRa miners bundle a **Compute Module 4** (onboard
eMMC), an **SX1302** concentrator, enclosure, and antenna. Many units support
**PoE**. There is no microSD slot: you flash **64-bit** Raspberry Pi OS or
Raspbian Lite to eMMC once over USB using a CM4 carrier board and Raspberry Pi `usbboot`, then run the same
`install.sh` + `meshpoint setup` flow as a RAK V2.

> **Step-by-step:** [Syncrobit Chameleon guide](docs/SYNCROBIT-CHAMELEON.md) and [Hardware Matrix](docs/HARDWARE-MATRIX.md).

### Option D: Build Your Own (~$85)

| Component | Price |
|-----------|-------|
| Raspberry Pi 4 (1GB+) | $35 |
| RAK2287 SX1302 + Pi HAT | ~$20* |
| 915 MHz LoRa antenna | $10 |
| MicroSD card (16GB+) | $10 |
| USB-C power supply (5V 3A) | $10 |

*\*Helium's surplus means RAK2287 concentrators and Pi HATs go for ~$20 combined on eBay.*

**Assembly:** Seat the RAK2287 on the Pi HAT, mount the HAT on the Pi GPIO header, connect the antenna. Always connect the antenna before powering on.

### Option E: WisMesh Node (RAK6421 HAT, experimental)

The [RAK WisMesh Pi Node](https://store.rakwireless.com/products/wismesh-pi-node) is a Pi HAT with a **WisBlock SX1262** LoRa module. Meshpoint drives RF through **meshtasticd** (Portduino), not the SX1302 concentrator path used by Options A–D.

**Status:** User-facing docs are on **`main`** now. The installer, dashboard, and capture bridge are on branch **`feat/wismesh-hat`** until they ship in **v0.7.6**.

> **Guides:** [WisMesh branch overview](docs/plans/WISMESH-BRANCH.md), [Gateway ↔ Node migration](docs/MIGRATE-GATEWAY-TO-NODE.md), [Hardware Matrix](docs/HARDWARE-MATRIX.md#wismesh-node-rak6421-hat-experimental).

### Option F: Bobcat Miner 300 (~$15-40 used, community path)

Retired **Bobcat Miner 300** units (models **G290** / **G295** reported) bundle a
**Rockchip RK3566** host, **64 GB eMMC**, and an onboard **SX1302** concentrator.
They are not Raspberry Pis: you flash **[Bobcat-Armbian](https://github.com/sicXnull/Bobcat-Armbian)**,
pin the vendor kernel (do not run a generic `apt upgrade`), enable the `spi5-m1`
overlay, then install Meshpoint with concentrator SPI on `/dev/spidev5.0` and a
small systemd drop-in for GPIO reset and SPI symlinks.

Community-validated (July 2026): Meshtastic TX/RX on G295; upgrade from v0.7.3.x
to v0.7.4+ reported smooth when `install.sh` skips `apt-get upgrade`. MeshCore
USB companion may need a **powered hub** (onboard micro-USB is for flashing;
OTG not confirmed on G295).

> **Step-by-step:** [Bobcat Miner 300 guide](docs/BOBCAT-300.md) and [Hardware Matrix](docs/HARDWARE-MATRIX.md).

### Optional: MeshCore USB Companion

Add one or more Heltec V3/V4 or T-Beam nodes running [MeshCore USB companion firmware](https://flasher.meshcore.co.uk/) to monitor MeshCore traffic alongside Meshtastic. Up to 4 companions can be attached simultaneously, each labeled by band. The setup wizard auto-detects each device.

**Flashing note:** Heltec V4 USB enumerates as `303a:0002` under MeshCore firmware and `303a:1001` under Meshtastic — the opposite of what you might expect.

### Optional: Meshtastic 433 MHz via USB Serial

A Heltec V3 (or any Meshtastic node) flashed with **Meshtastic EU_433** firmware and connected via USB adds a fifth capture stream at 433 MHz. Use the `serial` source in `local.yaml` — not `meshcore_usb`. These two sources speak different protocols and are not interchangeable.

More than one Meshtastic USB stick can be captured at once (e.g. one 433 MHz, one 868 MHz): use the `capture.serial` list instead of the single `serial_port`/`serial_baud` fields, each entry with its own `label` — same shape as the MeshCore companion list. Edit it from Configuration → Serial in the dashboard instead of hand-editing `local.yaml`. See [CONFIGURATION.md](docs/CONFIGURATION.md#capture-sources).

### Optional: RTL-SDR Radio Listener

Add an **RTL-SDR dongle** (RTL2832U + R820T/R860 — e.g. RTL-SDR Blog V3/V4, ~€25) to turn Meshpoint into a browser-based broadcast/utility radio receiver. It is completely independent of the SX1302, so LoRa capture continues uninterrupted.

- **Coverage:** ~24–1766 MHz — FM broadcast (WFM), airband and AM, marine VHF/UHF, PMR446, 2 m / 70 cm ham (NFM), and SSB (USB/LSB).
- **Requirements:** the `rtl-sdr` package (provides `rtl_fm` / `rtl_test`) and `ffmpeg`:
  ```bash
  sudo apt update && sudo apt install -y rtl-sdr ffmpeg
  ```
- **RDS (optional):** for station name, RadioText, program type, and the signal-quality meter on FM, also install [`redsea`](https://github.com/windytan/redsea). It is not packaged in Debian/Raspberry Pi OS, so build it from source (a couple of minutes on a Pi 4):
  ```bash
  sudo apt install -y git build-essential meson ninja-build libliquid-dev libsndfile1-dev
  git clone https://github.com/windytan/redsea.git
  cd redsea && meson setup build && cd build && ninja
  sudo ninja install    # puts `redsea` on PATH
  ```
  RDS is decoded from the wide FM multiplex, so `rtl_fm` runs at 171 kHz and the stream is `tee`'d to both `redsea` and `ffmpeg` — no second dongle needed. Without `redsea` installed, everything else works; the RDS pills simply stay hidden.
- **P2000 / Pagers / POCSAG (optional):** for the dashboard's P2000 (Dutch emergency dispatch, FLEX), Pagers, and POCSAG tabs (all POCSAG-family decoders, on different bands), also install [`multimon-ng`](https://github.com/EliasOenal/multimon-ng) — not packaged in Debian/Raspberry Pi OS either, so build from source:
  ```bash
  sudo apt install -y cmake libpulse-dev libx11-dev
  git clone https://github.com/EliasOenal/multimon-ng.git
  cd multimon-ng && cmake -S . -B build && cmake --build build --parallel 4
  sudo cmake --install build
  ```
  Both `redsea` and `multimon-ng` are installed automatically by `scripts/install.sh` on a fresh Pi setup — this is only needed for a manual/non-installer setup. Since P2000/Pagers/POCSAG/RTL433/DAB+ use the same dongle as the Radio tab, only one of the six can be active at a time; starting one while another is listening returns an error rather than silently stopping it.
- **RTL433 (optional):** for the dashboard's RTL433 tab — a generic OOK/FSK decoder covering weather stations, TPMS, remote sensors, and hundreds of other 433/315/868 MHz devices, much broader than the paging-only P2000/Pagers/POCSAG decoders above — also install [`rtl_433`](https://github.com/merbanan/rtl_433):
  ```bash
  sudo apt install -y --no-install-recommends rtl-433
  ```
  Installed automatically by `scripts/install.sh` on a fresh Pi setup (the Raspberry Pi OS package is small and current enough that a from-source build wasn't warranted, unlike redsea/multimon-ng above) — manual install only needed for a non-installer setup.
- **DAB+ (optional):** for the dashboard's DAB+ tab, install [`welle.io`](https://github.com/AlbrechtL/welle.io) — the Debian/Raspberry Pi OS package ships both the GUI app and the headless `welle-cli` binary Meshpoint actually uses:
  ```bash
  sudo apt install -y --no-install-recommends welle.io
  ```
  Installed automatically by `scripts/install.sh` on a fresh Pi setup (same rationale as RTL433 above — the apt package is small and current enough, no from-source build needed) — manual install only needed for a non-installer setup. Confirm with `which welle-cli` after installing.
- **Blacklist the DVB-T driver** so the kernel doesn't claim the dongle as a TV tuner (the #1 "device not found" gotcha):
  ```bash
  echo 'blacklist dvb_usb_rtl28xxu' | sudo tee /etc/modprobe.d/rtl-sdr-blacklist.conf
  sudo modprobe -r dvb_usb_rtl28xxu   # or reboot
  ```
  Confirm with `rtl_test` (0 samples lost = healthy).
- **Power:** the dongle draws ~300 mA. On a Pi already running the concentrator and USB companions, use a solid supply (or a powered hub) and **avoid hot-plugging** — inrush current can brown out the internal USB hub and drop your MeshCore/serial companions. Leave it permanently connected.
- **Antenna:** give it its own wideband antenna (don't share the tuned LoRa antennas). A broadcast-FM band-pass/notch filter helps if strong local stations cause overload.

Open the **Listener** tab in the dashboard, pick a preset (or type a frequency + mode) and hit **Tune & Listen**. Switch between the Digital and Analogue faces with the toggle in the panel header.

> **Full step-by-step guide:** See the [Onboarding Guide](docs/ONBOARDING.md) for detailed instructions covering SD flashing, Chameleon eMMC recovery, assembly, installation, MeshCore setup, and troubleshooting for all hardware options.

---

## 5-Network Capture

A fully-equipped Meshpoint captures all of these simultaneously from one device:

| # | Protocol | Band | Source |
|---|---|---|---|
| 1 | LoRaWAN | 868 MHz | SX1302 concentrator (ch0–ch4, syncword 0x34) |
| 2 | Meshtastic | 868 MHz | SX1302 concentrator (ch8 service channel, syncword 0x2B) |
| 3 | MeshCore | 868 MHz | Heltec V3 USB companion (`/dev/ttyACM0`) |
| 4 | MeshCore | 433 MHz | Heltec V3 USB companion (`/dev/ttyACM1`) |
| 5 | Meshtastic | 433 MHz | Heltec V3 USB serial (`/dev/ttyUSB0`) |

LoRaWAN and MeshCore are **listen-only** and are never relayed. Only Meshtastic traffic is eligible for relay and messaging.

---

## Install

```bash
sudo apt update && sudo apt install -y git
sudo git clone https://github.com/javastraat/meshpoint.git /opt/meshpoint
cd /opt/meshpoint && sudo bash scripts/install.sh
```

This builds the SX1302 HAL with Meshtastic patches, sets up a Python venv, and installs the systemd service.

```bash
sudo meshpoint setup    # interactive config wizard
meshpoint status        # verify everything is running
```

Open `http://<pi-ip>:8080` for the local dashboard. On first visit you'll be prompted to set an admin password at `/setup` (8-character minimum). If you forget the password, recover via SSH with `sudo meshpoint reset-password`.

> **First time?** The [Onboarding Guide](docs/ONBOARDING.md) walks through everything from flashing the SD card to verifying your first captured packets.

---

## Architecture

```
                                ┌─────────────────────────┐
                                │    Meshradar Cloud       │
                                │    (meshradar.io)        │
                                └────────────┬────────────┘
                                             │ WebSocket
                                             │
┌──────────┐    ┌──────────┐    ┌────────────┴────────────┐
│LoRaWAN + │    │ SX1302/  │    │    Meshpoint (Pi 4)      │
│Meshtastic│◀──▶│ SX1303   │◀──▶│                          │
│ 868 MHz  │    │ ch0–ch8  │    │  CaptureCoordinator      │
└──────────┘    └──────────┘    │    ├── PacketRouter       │
                                │    │     ├── LoRaWAN      │
┌──────────┐    ┌──────────┐    │    │     ├── Meshtastic   │
│MeshCore  │    │ Heltec   │    │    │     └── MeshCore     │
│ 868 MHz  │◀──▶│ USB ×1-4 │◀──▶│    ├── DatabaseManager   │
│ 433 MHz  │    │(ACM0-3)  │    │    ├── RelayManager      │
└──────────┘    └──────────┘    │    └── WebSocket / API   │
                                │                           │
┌──────────┐    ┌──────────┐    │         Dashboard        │
│Meshtastic│    │ Heltec   │    │         (port 8080)       │
│ 433 MHz  │◀──▶│   V3     │◀──▶│                          │
│ (serial) │    │ /ttyUSB0 │    │  RtlListener             │
└──────────┘    └──────────┘    │   (rtl_fm → ffmpeg MP3   │
                                │    → browser audio)      │
┌──────────┐    ┌──────────┐    │                          │
│Broadcast │    │ RTL-SDR  │───▶│                          │
│FM·air·PMR│───▶│  dongle  │    └─────────────────────────┘
│24–1766MHz│    │  (USB)   │
└──────────┘    └──────────┘
```

---

## Configuration

All configuration lives in `config/local.yaml`. Below is the full 5-network example:

```yaml
capture:
  sources:
    - concentrator      # SX1302: LoRaWAN + Meshtastic 868
    - meshcore_usb      # Heltec companions: MeshCore 868 + 433
    - serial            # Heltec V3: Meshtastic 433

  # Meshtastic 433 — Heltec V3 running Meshtastic EU_433 firmware
  serial_port: "/dev/ttyUSB0"
  serial_baud: 115200

  # MeshCore companions — up to 4, each with a label
  meshcore_usb:
    - serial_port: "/dev/ttyACM0"
      label: "868"
    - serial_port: "/dev/ttyACM1"
      label: "433"
```

> **Important:** `meshcore_usb` and `serial` speak different protocols. A Meshtastic device must use `serial`; a MeshCore device must use `meshcore_usb`. Mixing them produces garbage reads.

See [docs/CONFIGURATION.md](docs/CONFIGURATION.md) for all options: relay, MQTT, upstream, GPS, channels, and radio tuning.

---

## CLI

```bash
meshpoint status         # service status + config summary
meshpoint logs           # tail the service journal
meshpoint report         # full operational report (asks for admin login; sudo skips the prompt)
meshpoint restart        # restart the service
meshpoint meshcore-radio # configure MeshCore companion radio frequency
sudo meshpoint setup     # re-run config wizard
sudo meshpoint reset-password  # recover forgotten admin password
```

---

## Local API

FastAPI server on port 8080 (configurable via `dashboard.port` in `local.yaml`):

| Endpoint | Description |
|----------|-------------|
| `GET /api/nodes` | All discovered nodes |
| `GET /api/nodes/summary` | Whole-network totals (nodes, positions, packets per protocol) |
| `GET /api/packets` | Recent packets (paginated) |
| `GET /api/analytics/traffic` | Traffic rates and counts |
| `GET /api/analytics/signal/rssi` | RSSI distribution |
| `GET /api/device/status` | Device health and uptime |
| `GET /api/config` | Radio, TX, channel, and companion configuration |
| `PUT /api/config/transmit` | Update TX settings |
| `PUT /api/config/identity` | Update node ID, long/short name |
| `PUT /api/config/radio` | Change region, preset, frequency |
| `PUT /api/config/position` | Set position broadcast interval (admin) |
| `PUT /api/config/telemetry` | Set telemetry broadcast interval (admin) |
| `PUT /api/config/capture/meshcore-companions` | Replace full MeshCore companion list (max 4) |
| `POST /api/messages/send` | Send a Meshtastic or MeshCore message |
| `GET /api/messages/conversations` | Message history by conversation |
| `GET /api/lorawan/devices` | LoRaWAN device list (frame count, RSSI, SF, first/last seen) |
| `GET /api/lorawan/packets` | Recent LoRaWAN packet log (max 1000) |
| `GET /api/lorawan/stats` | LoRaWAN totals: packets, unique devices, by frame type |
| `GET /api/{lorawan,meshtastic,meshcore}/export/packets.csv` | Download all captured packets as CSV (LoRaWAN adds DevEUI/FCnt/FPort/MIC columns) |
| `GET /api/lorawan/export/devices.csv` · `.../meshtastic/export/nodes.csv` · `.../meshcore/export/contacts.csv` | Download the device/node/contact census as CSV |
| `GET /api/listener/status` | RTL-SDR listener state: frequency, mode, RDS (PS/RadioText/PTY/BLER), audio level |
| `POST /api/listener/tune` | Tune the RTL-SDR: frequency, mode, squelch, gain, level, optional preset station label |
| `POST /api/listener/stop` | Stop the RTL-SDR listener |
| `GET /api/listener/stream` | Live MP3 audio stream for the browser player |
| `GET /api/{p2000,pagers,pocsag,rtl433}/status` | Decoder state: running, frequency, decoded messages |
| `POST /api/{p2000,pagers,pocsag,rtl433}/start` · `.../stop` | Start/stop the P2000, Pagers, POCSAG, or RTL433 decoder (only one of Radio/P2000/Pagers/POCSAG/RTL433/DAB+ may run at a time) |
| `GET /api/dab/status` | DAB+ listener state: channel, ensemble label, SNR, decoded station list (sid, name, DLS text) |
| `POST /api/dab/tune` | Tune to a DAB+ channel/ensemble (e.g. `12C`) |
| `POST /api/dab/stop` | Stop the DAB+ listener |
| `GET /api/dab/stream/{sid}` | Live MP3 audio stream for one DAB+ station, proxied from welle-cli |
| `GET /api/device/spectrum` | Latest band sweep from the SX1302 spectral scanner (median/peak per 100 kHz step) |
| `POST /api/device/spectrum/sweep` | Trigger an on-demand band sweep (admin) |
| `GET /api/topology/graph` | Mesh topology graph: nodes + edges from traceroutes, direct receptions, and neighbour imports |
| `GET /api/device/thermals` | CPU temperature + fan duty history (6 h in-memory, requires fan control enabled) |
| `GET /api/rf/status` | RF Environment tab data: noise floor, calibration, latest scan histogram |
| `GET /api/rf/stray-frames` | Frames that failed every protocol decoder (in-memory ring buffer, newest 500) |
| `GET /api/config/export` | Quick Deploy export: public channel params + Meshtastic QR URL (no private PSKs) |
| `GET /api/system/backup/download` | Download config + data backup archive (admin) |
| `POST /api/system/backup/restore` | Restore a backup archive (admin) |
| `GET /metrics` | Prometheus scrape endpoint (opt-in via `metrics.enabled`) |
| `WS /ws` | Real-time packet + message stream |

---

## Updating

```bash
cd /opt/meshpoint
sudo git fetch origin
sudo git checkout main
sudo git pull origin main
sudo bash scripts/install.sh
sudo systemctl restart meshpoint
```

`install.sh` is idempotent on existing installs. After every update, hard-refresh each open dashboard tab (Ctrl+Shift+R / Cmd+Shift+R) so the browser loads the new frontend.

**From the dashboard (v0.7.4+):** sign in as admin, open Settings → Updates, pick **Stable (main)**, then **Check for updates** and **Apply**.

See [docs/COMMON-ERRORS.md](docs/COMMON-ERRORS.md#upgrades) if the service fails to start after pulling.

---

## Troubleshooting

**Chip version 0x00:** Concentrator not responding. Check that the concentrator module is seated, SPI is enabled (`raspi-config` → Interface Options → SPI), and try a full power cycle (unplug for 10+ seconds). Normal chip versions are `0x10` (SX1302) and `0x12` (SX1303).

**No packets:** Verify antenna is connected and frequency matches your region. Check `meshpoint logs` for `lgw_receive returned N packet(s)`.

**MeshCore companion not detected:** Verify the device is flashed with `companion_radio_usb` MeshCore firmware (not Meshtastic). Check `dmesg | grep tty` to confirm the port. Heltec V4 enumerates as `303a:0002` under MeshCore firmware.

**Heltec V3 433 showing garbage:** Make sure it is flashed with Meshtastic EU_433 firmware and that the config uses `serial` source — not `meshcore_usb`.

**Upstream 401:** Bad API key. Get a free one at [meshradar.io](https://meshradar.io) and re-run `sudo meshpoint setup`.

---

## Support and documentation

**Setup and configuration**
- **[Onboarding Guide](docs/ONBOARDING.md):** step-by-step from empty Pi to running Meshpoint
- **[Hardware Matrix](docs/HARDWARE-MATRIX.md):** RAK V2 vs SenseCap M1 vs Chameleon vs Bobcat vs DIY, WisMesh Node (experimental), MeshCore companion radios, antennas, what's not supported
- **[Bobcat Miner 300](docs/BOBCAT-300.md):** Rockchip RK3566 + Armbian repurposing (manual SPI/GPIO)
- **[WisMesh Node (experimental)](docs/plans/WISMESH-BRANCH.md):** RAK6421 HAT, meshtasticd, branch install until v0.7.6
- **[Gateway ↔ Node migration](docs/MIGRATE-GATEWAY-TO-NODE.md):** switch between concentrator Gateway and WisMesh Node platforms
- **[Configuration Guide](docs/CONFIGURATION.md):** all config options, private channels, relay, upstream, MQTT, radio tuning
- **[Radio Config Explained](docs/RADIO-CONFIG-EXPLAINED.md):** the "why" behind region, spreading factor, bandwidth, custom slots
- **[MQTT and Meshradar](docs/MQTT-AND-MESHRADAR.md):** the two cloud paths side-by-side, what data flows where, privacy posture
- **[Home Assistant cookbook](docs/HOME-ASSISTANT-COOKBOOK.md):** copy-paste REST sensors, alerts, and broadcast automations for LAN integrations
- **[Network Watchdog](docs/NETWORK-WATCHDOG.md):** how the WiFi auto-recovery service works, default thresholds, re-enabling auto-reboot

**When something goes wrong**
- **[FAQ](docs/FAQ.md):** quick answers to common questions
- **[Common Errors](docs/COMMON-ERRORS.md):** searchable catalog of error messages with cause and fix
- **[Troubleshooting](docs/TROUBLESHOOTING.md):** longer diagnostic flows, recovery from corrupted installs

**Project**
- **[Contributor PR roadmap](docs/plans/master-pr-roadmap.md):** ordered queue for diagnostics, intelligence, and field-ops PRs
- **[Changelog](docs/CHANGELOG.md):** version history and release notes
- **[GitHub Issues](https://github.com/javastraat/meshpoint/issues)** for bugs in this fork; **[upstream Discussions](https://github.com/KMX415/meshpoint/discussions)** for general Meshpoint questions
- **[Discord](https://discord.gg/BnhSeFXVY8)** for real-time community support

---

## Community

- **Discord:** [discord.gg/BnhSeFXVY8](https://discord.gg/BnhSeFXVY8)
- **Website:** [meshradar.io](https://meshradar.io)
- **Issues:** [GitHub Issues](https://github.com/javastraat/meshpoint/issues)

---

## Contributing

Meshpoint is still early alpha. Pull requests are welcome, but please keep changes small and reviewable.

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines, workflow, and PR expectations.

AI-assisted contributions are allowed, but contributors should review and understand all code before submitting.

---

## License

AGPL-3.0: see [LICENSE](LICENSE). All source code, including HAL bindings, protocol decoders, and packet builders, is published in this repository under the same license.

---

*Built for the mesh community by [Meshradar](https://meshradar.io).*
