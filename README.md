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
[![Version](https://img.shields.io/badge/version-0.7.6-orange.svg)](docs/CHANGELOG.md)

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

A Raspberry Pi-based Meshtastic base station that sends and receives messages through an SX1302/SX1303 concentrator. The concentrator receives on 8 channels simultaneously (SF7-SF12) and transmits natively with up to 27 dBm output. Phones and nodes see it as a regular participant on the mesh.

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

## Features

**5 networks simultaneously.** A single Meshpoint captures LoRaWAN (868 MHz), Meshtastic (868 MHz), MeshCore (868 MHz), MeshCore (433 MHz), and Meshtastic (433 MHz) at the same time — all from one device. The onboard SX1302 handles LoRaWAN and Meshtastic 868; USB companion radios extend coverage to MeshCore and 433 MHz bands.

**Native mesh messaging.** Send and receive Meshtastic messages directly from the dashboard. Broadcast to channels, DM individual nodes, or reply in conversations. MeshCore messaging supported through the USB companion. The SX1302 handles TX using the same sync word and encryption as the mesh network: phones and nodes see your Meshpoint as a regular participant.

**LoRaWAN passive sniffing.** Captures LoRaWAN traffic on EU868 channels (867.9 / 868.1 / 868.3 / 868.5 / 868.7 MHz) alongside Meshtastic without interfering. MAC layer fully decoded: Join-Request (JoinEUI, DevEUI, DevNonce), Data Up/Down (DevAddr, FCnt, FPort, payload length), and Rejoin frames. Payload is not decrypted (no session keys). All LoRaWAN traffic is strictly listen-only — never relayed. Accessible from its own dashboard panel with per-device stats.

**Smart relay (experimental).** Re-broadcast captured Meshtastic packets through the same onboard SX1302, identity-preserving — original sender attribution and packet IDs survive, only the hop counter decrements. No second radio required. Filter by signal strength, packet type, and rate limit; share duty-cycle budget with messaging so relay traffic can never crowd out user TX. Enable via `relay.enabled: true` in `local.yaml`. See [Configuration > Smart Relay](docs/CONFIGURATION.md#smart-relay) for details.

**Full chat UI.** Conversations organized by channel and contact. Signal info (SNR, RSSI) on every received bubble. Duplicate badge shows how many times a relayed message was heard. Channel sidebar with LongFast, custom channels, and DM contacts. Message history persisted in SQLite.

**Radio configuration from the dashboard.** Change region, modem preset, frequency, TX power, and duty cycle without SSH. Add and remove channels with custom PSKs. Toggle TX enable/disable. All settings saved to `local.yaml` and survive restarts.

**Node discovery.** Live node cards showing every node your Meshpoint has heard: name, ID, protocol, hardware model, signal strength, battery, and last seen. Click any node to open a detail drawer with signal history and direct message.

**Multi-companion MeshCore capture.** Up to 4 Heltec/T-Beam USB companions running MeshCore firmware can be attached simultaneously, each labeled by band. The dashboard shows a dynamic companion card per device. Companions are auto-detected on `/dev/ttyACM*`.

**Meshtastic 433 via serial.** A Heltec V3 or any Meshtastic-flashed node on `/dev/ttyUSB0` adds a fifth capture stream. Packets are decoded and displayed in the dashboard the same as 868 MHz Meshtastic packets.

**RTL-SDR broadcast & utility radio listener.** Plug in a cheap RTL-SDR dongle and listen to real radio from the browser — FM broadcast, airband (AM), marine VHF/UHF, PMR446, 2 m / 70 cm ham, and anything else in ~24–1766 MHz. Server-side `rtl_fm` demodulates (a **Mode** selector for WFM / NFM / AM / USB / LSB, plus squelch, gain, and pre-encoder level) and streams MP3 to a browser `<audio>` player, while the SX1302 keeps sniffing LoRa uninterrupted (separate hardware). Two selectable radio faces — a **Digital** VFD-style readout with a segmented VU meter, and an **Analogue** slide-rule tuner with a swinging-needle VU gauge — and a real-time Web Audio level meter that dances with the audio. **RDS** on FM (via [`redsea`](https://github.com/windytan/redsea)): station name, scrolling RadioText / now-playing, program type (PTY), and a block-error-rate signal-quality meter. A phonebook-style preset picker with category tabs, search, and ★ favorites (Amsterdam FM, PMR446, marine, Schiphol airband, ham). See [RTL-SDR Radio Listener](#optional-rtl-sdr-radio-listener) for setup.

**Full packet decoding.** 14 Meshtastic portnums decoded: TEXT, POSITION, NODEINFO, TELEMETRY, ROUTING, ADMIN, WAYPOINT, DETECTION_SENSOR, PAXCOUNTER, STORE_FORWARD, RANGE_TEST, TRACEROUTE, NEIGHBORINFO, and MAP_REPORT. 6 MeshCore message types decoded. Device roles (CLIENT, ROUTER, REPEATER, TRACKER, SENSOR) extracted from NodeInfo.

**Multi-channel decryption.** Configure private channel PSKs from the dashboard or `local.yaml`. The Meshpoint decodes traffic on those channels alongside the default key and routes messages to the correct conversation. Supports any number of channels with AES-128 or AES-256 keys.

**6 frequency regions.** US, EU_868, ANZ, IN, KR, and SG_923. Select during setup or change from the Radio settings page. MeshCore companion radios configure to match automatically.

**Real-time dashboard.** Live map with node positions, color-coded packet feed with frequency and spreading factor columns, traffic charts, signal analytics, node cards, and a dedicated LoRaWAN devices panel. Accessible from any device on your network.

**GPS and split placement.** USB GPS via `gpsd` drives the Configuration → GPS skyplot. Registered coordinates (wizard pin) always feed [Meshradar](https://meshradar.io) fleet view. Meshtastic POSITION broadcasts are separately configurable: registered pin or live GPS, with approximate (~1.1 km), precise, or hidden privacy. See [Configuration > Location](docs/CONFIGURATION.md#location-gps-source).

**Cloud integration.** Optional WebSocket uplink to [Meshradar](https://meshradar.io) for aggregated multi-site mesh intelligence. Fleet management, city-wide maps, and packet history across all your Meshpoints.

**Dual-protocol MQTT gateway.** Publish captured packets to community MQTT brokers and Home Assistant. Dual-protocol: Meshtastic (protobuf) and MeshCore (JSON) from a single device. Two-gate privacy model ensures private channel data never leaks. Optional JSON publishing, HA auto-discovery, and configurable location precision.

**Auto-detect hardware.** RAK Hotspot V2, SenseCap M1, and Syncrobit Chameleon (SX1302) supported. MeshCore USB companions auto-detected on `/dev/ttyUSB*` and `/dev/ttyACM*`.

---

## Hardware

> **Requirements:** Raspberry Pi 4 or Compute Module 4, **64-bit** Raspberry Pi OS or Raspbian Lite, Python 3.12+. Pi 3, Pi 5 (unvalidated), x86, and 32-bit OS are not supported.

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

### Optional: MeshCore USB Companions

Add one or more Heltec V3/V4 or T-Beam nodes running [MeshCore USB companion firmware](https://flasher.meshcore.co.uk/) to monitor MeshCore traffic alongside Meshtastic. Up to 4 companions can be attached simultaneously, each labeled by band. The setup wizard auto-detects each device.

**Flashing note:** Heltec V4 USB enumerates as `303a:0002` under MeshCore firmware and `303a:1001` under Meshtastic — the opposite of what you might expect.

### Optional: Meshtastic 433 MHz via USB Serial

A Heltec V3 (or any Meshtastic node) flashed with **Meshtastic EU_433** firmware and connected via USB adds a fifth capture stream at 433 MHz. Use the `serial` source in `local.yaml` — not `meshcore_usb`. These two sources speak different protocols and are not interchangeable.

### Optional: RTL-SDR Radio Listener

Add an **RTL-SDR dongle** (RTL2832U + R820T/R860 — e.g. RTL-SDR Blog V3/V4, ~€25) to turn Meshpoint into a browser-based broadcast/utility radio receiver. It is completely independent of the SX1302, so LoRa capture continues uninterrupted.

- **Coverage:** ~24–1766 MHz — FM broadcast (WFM), airband and AM, marine VHF/UHF, PMR446, 2 m / 70 cm ham (NFM), and SSB (USB/LSB).
- **Requirements:** the `rtl-sdr` package (provides `rtl_fm` / `rtl_test`) and `ffmpeg`. For **RDS** on FM (station name, RadioText, program type, signal-quality meter), also install [`redsea`](https://github.com/windytan/redsea). RDS is decoded from the wide FM multiplex, so `rtl_fm` runs at 171 kHz and the stream is `tee`'d to both `redsea` and `ffmpeg` — no second dongle needed.
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
| 1 | LoRaWAN | 868 MHz | SX1302 concentrator (ch0–ch2, syncword 0x34) |
| 2 | Meshtastic | 868 MHz | SX1302 concentrator (ch3–ch4 + ch8, syncword 0x2B) |
| 3 | MeshCore | 868 MHz | Heltec V3 USB companion (`/dev/ttyACM0`) |
| 4 | MeshCore | 433 MHz | Heltec V3 USB companion (`/dev/ttyACM1`) |
| 5 | Meshtastic | 433 MHz | Heltec V3 USB serial (`/dev/ttyUSB0`) |

LoRaWAN and MeshCore are **listen-only** and are never relayed. Only Meshtastic traffic is eligible for relay and messaging.

---

## Install

```bash
sudo apt update && sudo apt install -y git
sudo git clone https://github.com/KMX415/meshpoint.git /opt/meshpoint
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
│ (serial) │    │ /ttyUSB0 │    └─────────────────────────┘
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
meshpoint report         # full operational report (traffic, signal, system)
meshpoint restart        # restart the service
meshpoint meshcore-radio # configure MeshCore companion radio frequency
sudo meshpoint setup     # re-run config wizard
sudo meshpoint reset-password  # recover forgotten admin password
```

---

## Local API

FastAPI server on port 8080:

| Endpoint | Description |
|----------|-------------|
| `GET /api/nodes` | All discovered nodes |
| `GET /api/nodes/map` | Nodes with GPS for map display |
| `GET /api/packets` | Recent packets (paginated) |
| `GET /api/analytics/traffic` | Traffic rates and counts |
| `GET /api/analytics/signal/rssi` | RSSI distribution |
| `GET /api/device/status` | Device health and uptime |
| `GET /api/config` | Radio, TX, channel, and companion configuration |
| `PUT /api/config/transmit` | Update TX settings |
| `PUT /api/config/identity` | Update node ID, long/short name |
| `PUT /api/config/radio` | Change region, preset, frequency |
| `PUT /api/config/capture/meshcore-companions` | Replace full MeshCore companion list (max 4) |
| `POST /api/messages/send` | Send a Meshtastic or MeshCore message |
| `GET /api/messages/conversations` | Message history by conversation |
| `GET /api/lorawan/devices` | LoRaWAN device list (frame count, RSSI, SF, first/last seen) |
| `GET /api/lorawan/packets` | Recent LoRaWAN packet log (max 1000) |
| `GET /api/lorawan/stats` | LoRaWAN totals: packets, unique devices, by frame type |
| `GET /api/listener/status` | RTL-SDR listener state: frequency, mode, RDS (PS/RadioText/PTY/BLER), audio level |
| `POST /api/listener/tune` | Tune the RTL-SDR: frequency, mode, squelch, gain, level |
| `POST /api/listener/stop` | Stop the RTL-SDR listener |
| `GET /api/listener/stream` | Live MP3 audio stream for the browser player |
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
- **[Hardware Matrix](docs/HARDWARE-MATRIX.md):** all supported hardware, companion radios, antennas, what's not supported
- **[Configuration Guide](docs/CONFIGURATION.md):** all config options, private channels, relay, upstream, MQTT, radio tuning
- **[Radio Config Explained](docs/RADIO-CONFIG-EXPLAINED.md):** the "why" behind region, spreading factor, bandwidth, custom slots
- **[MQTT and Meshradar](docs/MQTT-AND-MESHRADAR.md):** the two cloud paths side-by-side, what data flows where, privacy posture
- **[Network Watchdog](docs/NETWORK-WATCHDOG.md):** how the WiFi auto-recovery service works, default thresholds

**When something goes wrong**
- **[FAQ](docs/FAQ.md):** quick answers to common questions
- **[Common Errors](docs/COMMON-ERRORS.md):** searchable catalog of error messages with cause and fix
- **[Troubleshooting](docs/TROUBLESHOOTING.md):** longer diagnostic flows, recovery from corrupted installs

**Project**
- **[Changelog](docs/CHANGELOG.md):** version history and release notes
- **[GitHub Issues](https://github.com/KMX415/meshpoint/issues)** and **[Discussions](https://github.com/KMX415/meshpoint/discussions)** for bugs and questions
- **[Discord](https://discord.gg/BnhSeFXVY8)** for real-time community support

---

## Community

- **Discord:** [discord.gg/BnhSeFXVY8](https://discord.gg/BnhSeFXVY8)
- **Website:** [meshradar.io](https://meshradar.io)
- **Issues:** [GitHub Issues](https://github.com/KMX415/meshpoint/issues)

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
