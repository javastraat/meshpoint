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
[![Version](https://img.shields.io/badge/version-0.7.9-orange.svg)](docs/CHANGELOG.md)
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

This is a customized fork of upstream [KMX415/meshpoint](https://github.com/KMX415/meshpoint), tuned for a SenseCap M1 "mega-sniffer" **and** a browser radio receiver. It tracks upstream in full, and on top of everything upstream provides, adds an RTL-SDR listener with a family of decoders (Radio, ACARS, RTL433, ADS-B, DAB+, the three pager protocols), native Reticulum/LXMF messaging, expanded multi-protocol capture, a whole plugin architecture, and a long tail of hardware, UI, and self-update improvements.

**Full writeup:** [docs/WHATS-DIFFERENT.md](docs/WHATS-DIFFERENT.md)

> Because this is a fork, a dashboard **Update** (which runs `git reset --hard origin/main`) will overwrite fork-specific changes unless your `origin` remote points at this fork rather than upstream.

---

## Features

**5 networks simultaneously.** A single Meshpoint captures LoRaWAN (868 MHz), Meshtastic (868 MHz), MeshCore (868 MHz), MeshCore (433 MHz), and Meshtastic (433 MHz) at the same time — all from one device. The onboard SX1302 handles LoRaWAN and Meshtastic 868; USB companion radios extend coverage to MeshCore and 433 MHz bands.

**Native mesh messaging.** Send and receive Meshtastic messages directly from the dashboard. Broadcast to channels, DM individual nodes, or reply in conversations. MeshCore messaging supported through the USB companion. The SX1302 handles TX using the same sync word and encryption as the mesh network: phones and nodes see your Meshpoint as a regular participant.

**LoRaWAN passive sniffing.** Captures LoRaWAN traffic on EU868 channels (867.9 / 868.1 / 868.3 / 868.5 / 868.7 MHz) alongside Meshtastic without interfering. MAC layer fully decoded: Join-Request (JoinEUI, DevEUI, DevNonce), Data Up/Down (DevAddr, FCnt, FPort, payload length), and Rejoin frames. Payload is not decrypted (no session keys). All LoRaWAN traffic is strictly listen-only — never relayed. Accessible from its own dashboard panel with per-device stats.

**DAPNET companion (plugin — `plugins/apps/dapnet/`, `pocsag_companion` sketch).** A separate ESP32 + SX1276/SX1262 board (TTGO LoRa32 or Heltec V3) bridges the real German DAPNET amateur-radio paging network into Meshpoint over USB serial — bidirectional: it both decodes real DAPNET pages (capcode, function, text) and, from its own on-device WiFi dashboard, transmits alpha pages with a licensed operator callsign prefix. The first plugin to use the `capture`/`protocol` seams (see [Plugins](docs/WHATS-DIFFERENT.md#plugins) above) rather than the RTL-SDR listener shape every other plugin uses — a real `CaptureSource` joins the pipeline directly, unconditionally at boot. Enable with `plugins.dapnet.enabled: true` and a `plugins.dapnet.devices` entry (serial port/baud/label/name) in `local.yaml`; decoded traffic then shows up on its own **Networks → DAPNET** page (capcode roster + recent-pages log + stats + a **Settings** tab for the device list and capcode filters), named after the real paging network it talks to rather than the generic POCSAG modulation — the RTL-SDR **POCSAG** plugin's own listener is a completely different, unrelated, passive-only code path. Two configurable capcode filters keep DAPNET's own recurring network housekeeping/time-sync beacons from cluttering things: a **blacklist** (shown live, confirming the link is still alive, but never stored) and an **ignore list** (dropped entirely). The DAPNET sidebar link appears whenever the plugin is enabled, same as any other plugin (no longer gated on a device actually being configured). A topbar chip (callsign/frequency/board, next to Meshtastic/MeshCore/Pager) plus a page-level status card both show live connection state — DAPNET is also the reference for a new generic **Topbar** plugin capability (`window.registerTopbarChip`, see [Plugins](docs/WHATS-DIFFERENT.md#plugins) above), any plugin's own persistent topbar badge. **Configuration → Firmware**'s "POCSAG" card can also build and flash the companion sketch (`plugins/apps/dapnet/pocsag_companion/`) straight from the dashboard — no Arduino IDE, no separate machine — via a self-contained `arduino-cli`/ESP32 toolchain `scripts/install.sh` sets up automatically; board target (TTGO vs Heltec) is a pulldown auto-populated from the sketch's own board defines and auto-selected to match whatever's currently picked in "Device to flash" (any connected USB-serial device, not just a configured companion), and live compiler/flash output streams into a collapsible panel. If the target happens to be a currently-connected DAPNET companion, flashing releases its serial connection first and reconnects it automatically afterward, so capture doesn't need a manual service restart to resume.

**Emergency pager project (internal/experimental — confirmed working on real hardware, but still early).** The SX1302 concentrator's dedicated FSK channel (ch9) is genuinely independent hardware from every LoRa channel above (its own demodulator, own sync word) — not POCSAG, a project-specific framing for a planned Heltec V3-based two-way pager. Enable it with `radio.pager_enabled` in `local.yaml` (or **Configuration → Radio → Pager**, which also lets frequency/sync word be tuned within the ETSI EU868 "sub-band P" high-power window, validated against the concentrator's real hardware before saving). Once on, a **Networks → Pager** page appears (Inbox, Outbox, and an admin-only New Message tab). Every message carries a real `from`/`to` POCSAG-style capcode (JSON envelope, same convention DAPNET's own serial protocol uses) — set this device's own address in **Configuration → Radio → Pager** (`radio.pager_capcode`, required before it will transmit at all, same reasoning as `pocsag_companion.ino` requiring a callsign). "Sent" flips to a green "Acked" badge once the pager confirms receipt — every outgoing message carries an id, and `pager_client.ino` echoes it back as a small ACK envelope the moment it accepts one addressed to it, matched back to the Outbox row over a plain id lookup (no schema change needed, the same `status` field this Outbox row already had just gets a real second value now). A received message matching this device's own capcode (its own transmission echoing back) is still correctly recognized and hidden rather than shown as a real message. The actual device firmware (`extra/pager_client`, Heltec WiFi LoRa32 V3 + RadioLib) is a standalone battery-powered pager, not a USB companion: one PRG button (short press to cycle, long-hold to select — no keyboard on this hardware) drives idle plus a menu tree (Inbox / Outbox / Send / Settings), Send still being the small set of canned messages, listening on one or more capcodes plus the fixed 911/112 emergency broadcasts. Unlike the radio parameters (hardcoded to match the concentrator exactly), the capcodes a specific physical unit answers to are programmed from **Configuration → Firmware**'s Pager card at compile time, not hand-edited into the sketch — see above. WiFi/mDNS/OTA and a small password-gated web dashboard are also built in (optional, best-effort — the pager works standalone with no network at all if unconfigured), ported from `pocsag_companion.ino`'s own: reachable at a per-unit `pager-<capcode>.local`, reflashable over WiFi, a browser can check status or trigger a send without touching the physical button, and the OLED auto-blanks after an idle timeout (settable from the dashboard's "Screen Timeout" card) — a short button press wakes it back up. A physical Heltec V3 has been flashed and confirmed working both directions against the deployed concentrator; the WiFi/OTA/web dashboard section itself is still compile-verified only, not yet tested live. Every screen shares a status bar (this unit's own capcode, small WiFi/new-message icons) and word-wraps message text properly instead of breaking mid-word, plus a "LoRaPager" boot screen — both compile-verified only, not yet confirmed on the real OLED.

**Smart relay (experimental).** Re-broadcast captured Meshtastic packets through the same onboard SX1302, identity-preserving — original sender attribution and packet IDs survive, only the hop counter decrements. No second radio required. Filter by signal strength, packet type, and rate limit; share duty-cycle budget with messaging so relay traffic can never crowd out user TX. Enable via `relay.enabled: true` in `local.yaml`. See [Configuration > Smart Relay](docs/CONFIGURATION.md#smart-relay) for details.

**Full chat UI.** Conversations organized by channel and contact. Signal info (SNR, RSSI) on every received bubble. Duplicate badge shows how many times a relayed message was heard. Channel sidebar with LongFast, custom channels, and DM contacts. Message history persisted in SQLite.

**Radio configuration from the dashboard.** Change region, modem preset, frequency, TX power, and duty cycle without SSH. Add and remove channels with custom PSKs. Toggle TX enable/disable. All settings saved to `local.yaml` and survive restarts.

**Web terminal.** A full shell in the browser (Ops → Terminal, admin only): a real PTY streamed over WebSocket with search, clipboard support, and a one-click catalog of common maintenance commands. Quick fixes without reaching for an SSH client. Off by default (`dashboard.web_terminal_enabled`), toggleable from Settings → System with a confirm dialog — and that toggle itself only appears once `dashboard.web_terminal_toggle: true` is hand-set in `local.yaml` and the service restarted (same filesystem-only opt-in as plugin sources, below), so a compromised admin session can't enable a root shell on a device that was never meant to have one.

**Dashboard authentication.** First visit prompts you to set an admin password; sessions are HttpOnly cookies with failed-login lockout. An optional read-only **viewer** role shares the dashboard without exposing configuration, channel keys, or any write access.

**Node discovery.** Live node cards showing every node your Meshpoint has heard: name, ID, protocol, hardware model, signal strength, battery, and last seen. Click any node to open a detail drawer with metrics history, its most recent packets, and direct message.

**Multi-companion MeshCore capture.** Up to 4 Heltec/T-Beam USB companions running MeshCore firmware can be attached simultaneously, each labeled by band. The dashboard shows a dynamic companion card per device, each with its own live readouts, rename, and send-advert controls — no single "primary" companion required for configuration. Companions are auto-detected on `/dev/ttyACM*`.

**Meshtastic 433 via serial.** A Heltec V3 or any Meshtastic-flashed node on `/dev/ttyUSB0` adds a fifth capture stream. Packets are decoded and displayed in the dashboard the same as 868 MHz Meshtastic packets.

**RTL-SDR broadcast & utility radio listener.** Plug in a cheap RTL-SDR dongle and everything RTL-SDR — a live broadcast radio receiver plus a family of decoders — hooks its own tab into one shared **RTL-SDR** sidebar page (`plugins/apps/rtlsdr/`, a bundled plugin), each an independently-enabled plugin, all off by default. Enable `plugins.rtlsdr.enabled: true` plus whichever of the following you want. Since the dongle can only be tuned to one frequency at a time, only one of them can run at once, regardless of which tab it's on; the SX1302 keeps sniffing LoRa uninterrupted throughout (separate hardware). **Radio** (`plugins/apps/radio/`) is the browser radio receiver — FM broadcast, airband (AM), marine VHF/UHF, PMR446, 2 m / 70 cm ham, and anything else in ~24–1766 MHz. Server-side `rtl_fm` demodulates (a **Mode** selector for WFM / NFM / AM / USB / LSB, plus squelch, gain, and pre-encoder level) and streams MP3 to a browser `<audio>` player. Two selectable radio faces — a **Digital** VFD-style readout with a segmented VU meter, and an **Analogue** slide-rule tuner with a swinging-needle VU gauge — and a real-time Web Audio level meter that dances with the audio. **RDS** on FM (via [`redsea`](https://github.com/windytan/redsea)): station name, scrolling RadioText / now-playing, program type (PTY), and a block-error-rate signal-quality meter. A preset stations picker with category tabs, search, and ★ favorites (Amsterdam FM, PMR446, marine, Schiphol airband, ham). Enable with `plugins.radio.enabled: true` (its own `/api/listener/*` routes are kept unchanged from before it was a plugin). A mini player also appears in the sidebar (in place of the noise-floor graph) whenever Radio or DAB+ is actively tuned — station name, mute, and stop — so playback can be checked and stopped from any page. See [RTL-SDR Radio Listener](#optional-rtl-sdr-radio-listener) for setup. **DAB+** (`plugins/apps/dab/`) was the first decoder onto this shared page, and gets two tabs since it's two pieces — the player (pick a channel/ensemble, e.g. `12C` for the NPO nationals, then a station once welle-cli decodes it; ★ favorites do both steps in one click) and a companion **Config** panel (shows every channel `dab_channel_scan.py` found on your antenna, editable display names, runs the scan itself with live streamed output). **Pagers** and **POCSAG** (`plugins/apps/pagers/`, `plugins/apps/pocsag/`) both run POCSAG512/1200/2400 via a fixed `rtl_fm | multimon-ng` pipeline, just on different bands (172.45 MHz and 439.9875 MHz); **P2000** (`plugins/apps/p2000/`) runs the same `rtl_fm | multimon-ng` shape but decodes FLEX instead, for Dutch emergency dispatch on 169.65 MHz — all three were originally one shared core file split into three plugins one at a time. **ACARS** (`plugins/apps/acars/`) wraps [`acarsdec`](https://github.com/f00b4r0/acarsdec) (with [`libacars`](https://github.com/szpajder/libacars)) to decode aircraft VHF datalink messages on the four European ACARS channels around 131.7 MHz — same Start/Stop and decoded-message log, each row showing flight/tail, message label and text, and an expanded block for recognised standard types. **RTL433** (`plugins/apps/rtl433/`) runs [`rtl_433`](https://github.com/merbanan/rtl_433) directly — a single self-contained decoder covering weather stations, TPMS, remote sensors, and hundreds of other 433/315/868 MHz OOK/FSK devices, far broader than the paging-only protocols above; same Start/Stop and decoded-message log shape, each row showing the device model plus whatever fields it reported. **ADS-B** (`plugins/apps/adsb/`) wraps [`dump1090`](https://github.com/MalcolmRobb/dump1090) for live air traffic tracking — instead of a scrolling message log, it polls dump1090's own embedded webserver for a snapshot of every aircraft currently visible on 1090 MHz and renders a table (ICAO hex, flight, squawk, altitude, speed, track, position, last-heard) that updates in place, the same way dump1090's own map view does — a "Metric units" checkbox (on by default) passes dump1090's own `--metric` flag, and a **Map** button opens a modal with the same aircraft plotted live on an OpenStreetMap (Leaflet) view, each as an arrow rotated to its track heading and colored by squawk (emergency codes 7500/7600/7700 stand out, stale contacts dim). Two or more of these tabs on the page get an automatic small tabbar (only DAB+'s two, so far, need it); a single one just renders directly.

**Band spectrum view.** The concentrator module's onboard SX1261 sweeps the entire region band (EU868: 863–870 MHz in 100 kHz steps) every few minutes — without interrupting packet capture — and the RF Environment page draws the result as a live spectrum chart with every LoRaWAN, Meshtastic, and MeshCore channel position overlaid. See interferers (RFID readers, alarms) sharing your band at a glance. The Hardware page keeps the read-only table of the full 9-slot SX1302 channel plan.

**RF Environment tab.** A full-page view of your radio's health: live noise-floor readout with sparkline, calibration state, and the latest spectral-scan histogram — hardware-scanned when the SX1261 is available, packet-derived fallback otherwise. A **Stray Frames** card also lists RF frames that failed every protocol decoder (time, source, protocol hint, size, RSSI/SNR, expandable raw hex) instead of dropping them silently — an in-memory ring buffer (newest 500, cleared on restart), not yet a persisted table.

**Backup and restore.** Download a timestamped archive of `local.yaml` and the full `data/` directory (SQLite hot snapshot, PKI keys) from Settings, and restore it after an SD failure or bad experiment — the box returns to the snapshot, even after a database wipe. Admin-only; the archive contains all secrets, so store it offline.

**Operator tooling.** Click any packet-feed row for a full decode-metadata modal. KPI status strips on the Dashboard and RF tabs, and live MQTT broker health on the MQTT page. A **Quick Deploy QR** exports public channel parameters for field provisioning straight into the Meshtastic app (default key only — private PSKs never leave the box). Optional **Prometheus `/metrics`** endpoint with packet, node, relay, and system counters — configurable from **Configuration → Metrics** (enable + auth toggle apply immediately, no restart), full metric list and a sample scrape config in `docs/CONFIGURATION.md`. Named, revocable **API keys** scoped only to `/metrics` let unattended scrapers (Home Assistant, Prometheus) authenticate without a browser session — generate and revoke them from the same Metrics page.

**Home Assistant integration** ([`homeassistant/`](homeassistant/)) — a companion HA custom component that polls `/metrics` and exposes Meshpoint's own health (uptime, packet rates, node counts, signal averages, relay stats) as sensors on one device, using the API keys above. Deliberately aggregate-only, no per-node/per-contact entities. Includes an optional self-contained Lovelace card (`www/meshpoint-card.js`, no build step) that groups a device's entities into a status card instead of a plain entity list. See [homeassistant/README.md](homeassistant/README.md) for setup.

**Broadcast cadence controls.** Position and telemetry broadcast intervals are editable from the dashboard with live countdowns (off, or 5 min–24 h), independent of NodeInfo, applied hot without a restart.

**Full packet decoding.** 14 Meshtastic portnums decoded: TEXT, POSITION, NODEINFO, TELEMETRY, ROUTING, ADMIN, WAYPOINT, DETECTION_SENSOR, PAXCOUNTER, STORE_FORWARD, RANGE_TEST, TRACEROUTE, NEIGHBORINFO, and MAP_REPORT. 6 MeshCore message types decoded. Device roles (CLIENT, ROUTER, REPEATER, TRACKER, SENSOR) extracted from NodeInfo.

**Multi-channel decryption.** Configure private channel PSKs from the dashboard or `local.yaml`. The Meshpoint decodes traffic on those channels alongside the default key and routes messages to the correct conversation. Supports any number of channels with AES-128 or AES-256 keys.

**6 frequency regions.** US, EU_868, ANZ, IN, KR, and SG_923. Select during setup or change from Configuration → Radio. MeshCore companion radios configure to match automatically.

**Real-time dashboard.** Live map with node positions, color-coded packet feed with frequency and spreading factor columns, traffic charts, signal analytics, node cards, and a dedicated LoRaWAN devices panel. Accessible from any device on your network.

**GPS and split placement.** USB GPS via `gpsd`, or an on-board GPS wired straight to the Pi's hardware UART (RAK Pi HAT, Pisces P100), drives the Configuration → GPS skyplot and live coordinates. Registered coordinates (wizard pin) always feed [Meshradar](https://meshradar.io) fleet view. Meshtastic POSITION broadcasts are separately configurable: registered pin or live GPS, with approximate (~1.1 km), precise, or hidden privacy. See [Configuration > Location](docs/CONFIGURATION.md#location-gps-source).

**Cloud integration.** Optional WebSocket uplink to [Meshradar](https://meshradar.io) for aggregated multi-site mesh intelligence. Fleet management, city-wide maps, and packet history across all your Meshpoints.

**Dual-protocol MQTT gateway.** Publish captured packets to community MQTT brokers and Home Assistant. Dual-protocol: Meshtastic (protobuf) and MeshCore (JSON) from a single device. Two-gate privacy model ensures private channel data never leaks. Optional JSON publishing, HA auto-discovery, and configurable location precision. An opt-in **"Official map" toggle** additionally publishes the Meshpoint's own identity (name, approximate location, firmware, region) as a public MapReport onto the official Meshtastic map — separate from the packet-relay gateway above, MQTT-only, no LoRa airtime used.

**Auto-detect hardware.** RAK Hotspot V2, SenseCap M1, and Syncrobit Chameleon (SX1302) supported; carrier board may show as generic SX1302/Pi during setup. **Bobcat Miner 300** (Rockchip RK3566 + SX1302 on Armbian) is community-validated with manual SPI/GPIO setup. **COTX X3 Helium Miner** (Pi 4 + custom SX1302-class HAT) is community-validated with a manual concentrator-reset GPIO override — see the [Hardware Matrix](docs/HARDWARE-MATRIX.md#cotx-x3-helium-miner-notes). **Pisces P100** (PoE-powered outdoor Helium miner, repurposed) is likewise community-validated with its own manual reset-GPIO override — see the [Hardware Matrix](docs/HARDWARE-MATRIX.md#pisces-p100-helium-miner-notes). **WisMesh Node** (RAK6421 Pi HAT + WisBlock SX1262, experimental) is documented on `main` and installs from branch `feat/wismesh-hat` until v0.7.6 merges. MeshCore USB companions auto-detected on `/dev/ttyUSB*` and `/dev/ttyACM*`.

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

### Option D: COTX X3 Helium Miner (~$50)

A **COTX X3** Helium miner: standard Raspberry Pi 4 baseboard, a custom
LoRaWAN HAT (SX1302-class concentrator), and a front-panel status
display/button board — repurposed to run Meshpoint instead of its
original Helium firmware. Not auto-detected as its own carrier type
(shows as generic SX1302/Pi during setup); needs one manual systemd
override for the concentrator to survive anything but a full reboot.
That override is a one-time fix, not an ongoing hassle — set it once
and the box restarts normally from then on.

Community-validated (September 2026): concentrator reset is GPIO **22**,
not the RAK V2/SenseCap M1 default of 17/25; front button is GPIO 23,
front LED is GPIO 27 (both wired up via Configuration → Peripherals'
**COTX X3** preset). 

> **Details:** [Hardware Matrix](docs/HARDWARE-MATRIX.md#cotx-x3-helium-miner-notes).

### Option E: Pisces P100 (PoE outdoor, ~$75-100)

A **Pisces P100**: a PoE-powered outdoor LoRaWAN gateway in a sealed
waterproof enclosure, built around a Pi 4 and a custom SX1302-class
concentrator board — repurposed from its original Balena-based Helium
miner firmware. Same "needs a manual reset-GPIO override, once" situation
as the COTX X3, just a different pin and a different underlying board.

Community-validated (September 2026): concentrator reset is GPIO **23**,
found via a systematic sweep (`scripts/test_concentrator_reset.py`) after
every other candidate — including several from the vendor's own real
firmware repos — failed.

> **Details:** [Hardware Matrix](docs/HARDWARE-MATRIX.md#pisces-p100-helium-miner-notes).

### Option F: Build Your Own (~$85)

| Component | Price |
|-----------|-------|
| Raspberry Pi 4 (1GB+) | $35 |
| RAK2287 SX1302 + Pi HAT | ~$20* |
| 915 MHz LoRa antenna | $10 |
| MicroSD card (16GB+) | $10 |
| USB-C power supply (5V 3A) | $10 |

*\*Helium's surplus means RAK2287 concentrators and Pi HATs go for ~$20 combined on eBay.*

**Assembly:** Seat the RAK2287 on the Pi HAT, mount the HAT on the Pi GPIO header, connect the antenna. Always connect the antenna before powering on.

### Option G: WisMesh Node (RAK6421 HAT, experimental)

The [RAK WisMesh Pi Node](https://store.rakwireless.com/products/wismesh-pi-node) is a Pi HAT with a **WisBlock SX1262** LoRa module. Meshpoint drives RF through **meshtasticd** (Portduino), not the SX1302 concentrator path used by Options A–F.

**Status:** User-facing docs are on **`main`** now. The installer, dashboard, and capture bridge are on branch **`feat/wismesh-hat`** until they ship in **v0.7.6**.

> **Guides:** [WisMesh branch overview](docs/plans/WISMESH-BRANCH.md), [Gateway ↔ Node migration](docs/MIGRATE-GATEWAY-TO-NODE.md), [Hardware Matrix](docs/HARDWARE-MATRIX.md#wismesh-node-rak6421-hat-experimental).

### Option H: Bobcat Miner 300 (~$15-40 used, community path)

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

Add an **RTL-SDR dongle** (RTL2832U + R820T/R860 — e.g. RTL-SDR Blog V3/V4, ~€25) to turn Meshpoint into a browser-based broadcast/utility radio receiver, plus a family of other decoders. It is completely independent of the SX1302, so LoRa capture continues uninterrupted. None of this is part of `scripts/install.sh` — every piece is a **plugin**, off by default, and can be set up independently of everything else in this repo.

- **Coverage:** ~24–1766 MHz — FM broadcast (WFM), airband and AM, marine VHF/UHF, PMR446, 2 m / 70 cm ham (NFM), and SSB (USB/LSB).
- **RTL-SDR host page (required first):** the shared **RTL-SDR** sidebar page (`plugins/apps/rtlsdr/`) that every decoder below hooks its own tab into. Run `sudo bash plugins/apps/rtlsdr/setup.sh` (or `sudo meshpoint plugin setup rtlsdr`) — builds `librtlsdr` from source (osmocom upstream, `rtl_fm`/`rtl_test`) and blacklists the kernel's DVB-T driver so it doesn't claim the dongle as a TV tuner first (the #1 "device not found" gotcha; also unloads it immediately if a dongle is already plugged in this boot). Idempotent. Then set `plugins.rtlsdr.enabled: true` in `local.yaml`. Confirm with `rtl_test` (0 samples lost = healthy). See [`plugins/apps/rtlsdr/README.md`](plugins/apps/rtlsdr/README.md).
- **Radio (optional):** the browser radio receiver itself, a **plugin** (`plugins/apps/radio/`). Run `sudo bash plugins/apps/radio/setup.sh` (or `sudo meshpoint plugin setup radio`) — also needs `ffmpeg` (a base package) plus builds [`redsea`](https://github.com/windytan/redsea) from source for RDS (station name, RadioText, program type, signal-quality meter on FM; not packaged in Debian/Raspberry Pi OS, decoded from the wide FM multiplex `rtl_fm` already streams at 171 kHz, `tee`'d to both `redsea` and `ffmpeg` — no second dongle needed). Without `redsea`, everything else still works; the RDS pills simply stay hidden. Then set `plugins.radio.enabled: true` in `local.yaml`. See [`plugins/apps/radio/README.md`](plugins/apps/radio/README.md).
- **Pagers, POCSAG, and P2000 (all optional):** three **plugins** (`plugins/apps/pagers/`, `plugins/apps/pocsag/`, `plugins/apps/p2000/`). Each has its own `setup.sh` building [`multimon-ng`](https://github.com/EliasOenal/multimon-ng) from source (`sudo bash plugins/apps/<id>/setup.sh` or `sudo meshpoint plugin setup <id>`) — idempotent, so whichever of the three you set up first does the real work and the others are no-ops. Then set the matching `plugins.<id>.enabled: true` in `local.yaml`. See each plugin's own README ([`pagers`](plugins/apps/pagers/README.md), [`pocsag`](plugins/apps/pocsag/README.md), [`p2000`](plugins/apps/p2000/README.md)). Since Radio/Pagers/POCSAG/RTL433/ACARS/DAB+/ADS-B/P2000 all use the same dongle, only one can be active at a time; starting one while another is listening returns an error rather than silently stopping it.
- **RTL433 (optional):** a **plugin** (`plugins/apps/rtl433/`) — run `sudo bash plugins/apps/rtl433/setup.sh` (or `sudo meshpoint plugin setup rtl433`), a plain apt install of [`rtl_433`](https://github.com/merbanan/rtl_433), then set `plugins.rtl433.enabled: true` in `local.yaml`. See [`plugins/apps/rtl433/README.md`](plugins/apps/rtl433/README.md).
- **ADS-B (optional):** also a **plugin** (`plugins/apps/adsb/`) — run `sudo bash plugins/apps/adsb/setup.sh` (or `sudo meshpoint plugin setup adsb`), which builds [`dump1090`](https://github.com/MalcolmRobb/dump1090) from source (not packaged in Debian/Raspberry Pi OS), then set `plugins.adsb.enabled: true` in `local.yaml`. See [`plugins/apps/adsb/README.md`](plugins/apps/adsb/README.md).
- **DAB+ (optional):** also a **plugin** (`plugins/apps/dab/`) — run `sudo bash plugins/apps/dab/setup.sh` (or `sudo meshpoint plugin setup dab`), a plain apt install of [`welle.io`](https://github.com/AlbrechtL/welle.io) (`--no-install-recommends`, since only its headless `welle-cli` binary is used, not the GUI app), then set `plugins.dab.enabled: true` in `local.yaml`. See [`plugins/apps/dab/README.md`](plugins/apps/dab/README.md).
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

That's core. The plugin system (opt-in, off by default) adds a lot more on top — full list in [docs/WHATS-DIFFERENT.md](docs/WHATS-DIFFERENT.md):

```
┌─────────────────────────────────────┐
│      Meshpoint plugins (opt-in)     │
├─────────────────────────────────────┤
│ Reticulum/LXMF                      │
│   rnsd + LXMRouter — messaging,     │
│   NomadNet browsing, telemetry      │
├─────────────────────────────────────┤
│ DAPNET  ·  RF Environment companion │
│   own USB-serial ESP32 board, joins │
│   the capture pipeline directly     │
├─────────────────────────────────────┤
│ ACARS  ·  ADS-B  ·  DAB+  ·  RTL433 │
│   share the RTL-SDR dongle above,   │
│   one decoder at a time             │
└─────────────────────────────────────┘
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
meshpoint plugin list    # list discovered app plugins and their enabled/loaded state
meshpoint plugin check [<id>]  # re-run [deps] check probes live (list shows a boot-time snapshot)
meshpoint plugin setup <id>  # show + confirm + run a plugin's apt deps and setup.sh
sudo meshpoint setup     # re-run config wizard
sudo meshpoint reset-password  # recover forgotten admin password
```

---

## Local API

FastAPI server on port 8080 (configurable via `dashboard.port` in `local.yaml`).
Highlights below; see [docs/API-ENDPOINTS.md](docs/API-ENDPOINTS.md) for the
complete route list including config-write, admin-only, and one-off endpoints:

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
| `GET /api/config/meshcore/firmware-check?current_version=...` | Compare a companion's firmware against the latest `meshcore-dev/MeshCore` release (on-demand, cached 5 min) |
| `PUT /api/config/meshcore/companion-name` | Rename one MeshCore companion (label-scoped) |
| `POST /api/config/meshcore/companion-advert` | Send an advert from one specific MeshCore companion (label-scoped) |
| `GET /api/config/serial/firmware-check?current_version=...` | Compare a Meshtastic USB stick's firmware against the latest `meshtastic/firmware` release (on-demand, cached 5 min) |
| `PUT /api/config/serial/identity` | Rename one Meshtastic USB stick's long/short name (label-scoped) |
| `POST /api/config/serial/advert` | Send a NodeInfo broadcast from one specific Meshtastic USB stick (label-scoped) |
| `GET /api/config/serial-ports` | Enumerate connected USB-serial devices with a recommended stable path (by-path/by-id), for the port-picker dropdown |
| `POST /api/messages/send` | Send a Meshtastic or MeshCore message |
| `GET /api/messages/conversations` | Message history by conversation |
| `GET /api/lorawan/devices` | LoRaWAN device list (frame count, RSSI, SF, first/last seen) |
| `GET /api/lorawan/packets` | Recent LoRaWAN packet log (max 1000) |
| `GET /api/lorawan/stats` | LoRaWAN totals: packets, unique devices, by frame type |
| `GET /api/dapnet/capcodes` | DAPNET capcode roster (frame count, last text, first/last seen) — provided by the DAPNET plugin when enabled (see [Plugins](docs/WHATS-DIFFERENT.md#plugins)) |
| `GET /api/dapnet/packets` | Recent DAPNET page log (max 1000) |
| `GET /api/dapnet/stats` | DAPNET totals: pages, unique capcodes, by page type |
| `GET /api/dapnet/status` | Live per-companion connection status — shown on the plugin's own status card and its topbar chip |
| `GET/POST /api/reticulum/...` | Reticulum/LXMF status, peer roster, conversation history, send, announce, contacts (petname address book) — provided by the Reticulum plugin when enabled (see [Plugins](docs/WHATS-DIFFERENT.md#plugins)) |
| `GET/PUT /api/config/reticulum` · `POST /api/config/reticulum/restart-rnsd` | Reticulum plugin's RNode/backbone settings (the page's Settings tab) + trigger an `rnsd` restart |
| `GET /api/{lorawan,meshtastic,meshcore,dapnet}/export/packets.csv` | Download all captured packets as CSV (LoRaWAN adds DevEUI/FCnt/FPort/MIC columns) |
| `GET /api/lorawan/export/devices.csv` · `.../meshtastic/export/nodes.csv` · `.../meshcore/export/contacts.csv` · `.../dapnet/export/capcodes.csv` | Download the device/node/contact/capcode census as CSV |
| `GET /api/listener/status` | RTL-SDR Radio listener state: frequency, mode, RDS (PS/RadioText/PTY/BLER), audio level — provided by the Radio plugin when enabled (see [Plugins](docs/WHATS-DIFFERENT.md#plugins)); kept at `/api/listener/*` from before Radio was a plugin |
| `POST /api/listener/tune` | Tune the RTL-SDR: frequency, mode, squelch, gain, level, optional preset station label |
| `POST /api/listener/stop` | Stop the RTL-SDR listener |
| `GET /api/listener/stream` | Live MP3 audio stream for the browser player |
| `GET/POST /api/{pagers,pocsag,p2000,rtl433,acars,adsb}/...` | Decoder state / start / stop / clear, provided by the Pagers/POCSAG/P2000/RTL433/ACARS/ADS-B plugins when enabled (see [Plugins](docs/WHATS-DIFFERENT.md#plugins)) — none present unless installed, only one RTL-SDR listener runs at a time |
| `GET/POST /api/dab/...` | Tune / stop / status / MP3 stream, plus channel-scan results and a live-streamed scan run, provided by the DAB+ plugin when enabled (see [Plugins](docs/WHATS-DIFFERENT.md#plugins)) — same one-RTL-SDR-listener-at-a-time rule as above |
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
