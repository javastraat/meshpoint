# Configuration Guide

All settings live in `config/default.yaml` with user overrides in `config/local.yaml`. The service merges both files at startup: anything in `local.yaml` overrides the default. You only need to add the settings you want to change.

Edit your local config:

```bash
sudo nano /opt/meshpoint/config/local.yaml
```

Restart after any config change: `sudo systemctl restart meshpoint`

### Backup and restore

**Download backup (healthy Pi):** **Settings → System → Download backup** writes a timestamped `.tar.gz` to your browser. Save it on your PC or NAS, not only on the Pi. The archive is not encrypted and contains API keys, channel PSKs, PKI private material, and your full local database.

**Restore** replaces `config/local.yaml` and resets the live `data/` tree to match the archive. Anything that happened on the Pi after that backup (including **Clear database**) is discarded. Upload staging folders (`data/restore-incoming/`) and prior `data/pre-restore-stash-*` folders are left untouched.

**Fresh SD or wiped install (typical user flow):**

1. Install Meshpoint (`git clone` + `scripts/install.sh` on the new card).
2. Run **`sudo meshpoint setup`** once and paste a valid Meshradar API key so the service can start (the dashboard does not load on a blank install without this step).
3. Open the dashboard, complete **`/setup`** for the admin password.
4. **Settings → System → Restore backup** and upload your saved `.tar.gz`.
5. After restart, sign in with your **pre-disaster** dashboard password. Confirm nodes and packets, then check upstream logs for `connected to wss://api.meshradar.io`.

**Important:** Restore puts back the API key from the backup. If you deleted that key on [meshradar.io](https://meshradar.io) after taking the backup, local data will still restore but upstream will log `HTTP 403` until you generate a new key for the same `device_id` and update it via `sudo meshpoint setup` or `upstream.auth_token` in `config/local.yaml` (there is no dashboard field for the API key yet).

Full walkthrough: [TROUBLESHOOTING.md](TROUBLESHOOTING.md#disaster-recovery-with-a-saved-backup-recommended). SSH-only restore: `sudo bash /opt/meshpoint/scripts/restore_finish.sh /path/to/backup.tar.gz`.

---

## Radio

```yaml
radio:
  region: "US"                 # US, EU_868, ANZ, IN, KR, SG_923
  frequency_mhz: 906.875       # override within region's band limits
  spreading_factor: 11         # 7-12. 11=LongFast, 9=MediumFast, 7=ShortFast/Turbo
  bandwidth_khz: 250.0         # 125, 250, or 500
  coding_rate: "4/5"           # 4/5, 4/6, 4/7, 4/8
  sync_word: 0x2B              # 0x2B = Meshtastic. Don't change unless you know why.
  preamble_length: 16          # 16 = Meshtastic standard
  tx_power_dbm: 22             # SX1302 concentrator output power
  spectral_scan_interval_seconds: 60   # noise floor sampler cadence (0 disables)
  sx1261_spi_path: ""          # SX1261 SPI device for spectral scan (empty = disabled)
  spectrum_sweep_interval_seconds: 300 # band-sweep cadence for the spectrum card (0 = on-demand only)
  pager_enabled: false         # emergency pager project (EU868 only): enables the concentrator's
                                # dedicated FSK channel (ch9). No real Heltec V3 firmware deployed
                                # yet -- received frames are JSON envelopes, {"from":<capcode>,
                                # "to":<capcode>,"text":"..."}. Editable from Configuration ->
                                # Radio (Pager) or here directly.
  pager_frequency_mhz: 869.4625  # must stay in the ETSI EU868 "sub-band P" window
                                  # (869.40-869.65 MHz) and close to RF1's real anchor frequency
  pager_sync_word: 0x946437      # up to pager_sync_word_size bytes
  pager_sync_word_size: 3        # 1-8 bytes
  pager_rf_chain: 1              # NOT exposed in the UI -- see src/config.py's comment
                                  # before changing; wrong chain + the above frequency
                                  # range produces an IF offset the hardware will reject
  pager_capcode: 0               # this device's own POCSAG-style capcode -- the "from" on
                                  # every message it sends, and required (nonzero) before
                                  # it will transmit at all. 0 = unset.
```

The region sets the base frequency, spreading factor, and bandwidth automatically. You only need `region` in most cases. Override `frequency_mhz`, `spreading_factor`, or `bandwidth_khz` individually to tune for non-default presets (MediumFast, ShortFast, etc.) or custom frequency slots.

### Region Defaults and Band Limits

| Region | Default frequency | Allowed band |
|---|---|---|
| `US` | 906.875 MHz | 902.0 - 928.0 MHz |
| `EU_868` | 869.525 MHz | 863.0 - 870.0 MHz |
| `ANZ` | 919.875 MHz | 915.0 - 928.0 MHz |
| `IN` | 865.875 MHz | 865.0 - 867.0 MHz |
| `KR` | 922.875 MHz | 920.0 - 923.0 MHz |
| `SG_923` | 917.875 MHz | 917.0 - 925.0 MHz |

If `frequency_mhz` falls outside the region's band limits, the service will reject it at startup. Omit `frequency_mhz` entirely to tune to the region default.

### Spectral Scan (Noise Floor)

The dashboard's sidebar shows a live noise-floor reading. There are two ways the service can produce that number; which one applies depends on your concentrator hardware.

**Which radio does the scanning:** the SX1261 is a small companion chip **on the concentrator module itself** (e.g. inside the WM1302 on the SenseCap M1), sitting next to the SX1302 on a second SPI chip-select. It only measures RF power — it decodes nothing — which is why spectral scans and band sweeps run while the SX1302 keeps capturing packets. External radios (MeshCore USB companions, the RTL-SDR) are not involved in scanning at all.

**Hardware capability matrix:**

| Carrier board | SX1261 reachable from Pi? | Spectral scan supported? |
|---|---|---|
| Semtech SX1302CXXXGW1 reference kit | yes (own SPI line) | yes |
| SenseCap M1 | yes — `/dev/spidev0.1` (verified in the field) | yes |
| **RAK2287** | **no — confirmed absent, not just unreachable.** [RAK's own datasheet](https://docs.rakwireless.com/product-categories/wislink/rak2287/datasheet/) lists the module as "one SX1302 chip and two SX1250 chips," makes zero mention of an SX1261/LBT anywhere, and documents a single `HOST_CSN` pin — there is no second chip-select for the Pi to even reach. `/dev/spidev0.1` existing as a device node on the Pi is just the SoC's SPI0 bus exposing its normal CE0/CE1 pair; on RAK2287 only CE0 is wired to anything. **Don't set `sx1261_spi_path` on this board — it will crash the whole concentrator (see the warning below) for a chip that isn't there.** | no — hardware limitation, not fixable in config |
| RAK5146 / some off-the-shelf concentrators | unverified — often no (SX1261, where present, is commonly wired behind the SX1302's SPI router rather than directly to the Pi) | try `/dev/spidev0.1` only if you're prepared to recover from a crash; fall back if the SX1261 status errors below appear |
| Custom carriers with SX1261 on a dedicated CE line | yes | yes, after configuring `sx1261_spi_path` |

**Default behaviour (works everywhere):** `sx1261_spi_path` is empty, so the service skips the SX1261 init entirely and derives the noise floor from packet metadata — specifically a rolling minimum of `RSSI − SNR` across recently-decoded frames. This is a *loose upper bound* on the true noise floor (it tracks the quietest signal we managed to demodulate), but on a normally-operating link it converges to within a few dB of the real ambient floor and is good enough to spot RF interference, broken antennas, or unusually noisy bands.

**Opting in to true spectral scan:** if you have a board that exposes the SX1261 directly to the Pi (the Semtech reference kit is the common case), add this to `config/local.yaml`:

```yaml
radio:
  sx1261_spi_path: "/dev/spidev0.1"
  spectral_scan_interval_seconds: 60
```

When enabled, every `spectral_scan_interval_seconds` (default 60, minimum 5) the SX1261 samples ambient channel power on the radio's frequency for roughly 50 ms and the service reports the 10th-percentile reading as the noise floor. At 60 s cadence that is ~0.08% of receive time. If you set `spectral_scan_interval_seconds: 0`, scanning is disabled entirely and the packet-derived fallback is used.

**⚠️ Detecting an unsupported board — this is not a soft failure.** If you set `sx1261_spi_path` on a carrier where the SX1261 isn't directly reachable, `libloragw` logs lines like:

```
ERROR: sx1261_check_status: SX1261 status is not as expected: got:0x00 expected:0x22
ERROR: failed to patch sx1261 radio for LBT/Spectral Scan
```

…and `lgw_start()` refuses to bring up the concentrator **at all** — not just spectral scan. This is real, unmodified Semtech HAL behavior (`loragw_hal.c`): an enabled-but-unreachable SX1261 aborts the whole `lgw_start()` call, which takes down RX, TX, and native relay along with it. The service crashes on startup (`RuntimeError: lgw_start() failed`) and stays down until you fix the config — this is a real device outage, not spectral scan quietly falling back.

If this happens, recover immediately:

```bash
sudo sed -i 's#sx1261_spi_path:.*#sx1261_spi_path: ""#' /opt/meshpoint/config/local.yaml
sudo systemctl restart meshpoint
sudo systemctl status meshpoint --no-pager
```

(or edit `config/local.yaml` directly and set `sx1261_spi_path: ""` if `sed` doesn't match the line cleanly). Only try a non-empty `sx1261_spi_path` on hardware you're prepared to remotely recover — many RAK2287/RAK5146 revisions route the SX1261 behind the SX1302's internal SPI router rather than a Pi-visible chip-select, so `/dev/spidev0.1` existing as a device node is not proof the chip is actually reachable there.

If your `libloragw` build does not expose the spectral scan symbols at all (older HAL revisions), the service logs a single info line at startup and falls back automatically.

**Band spectrum sweep.** With spectral scan enabled, the service also sweeps the whole region band (one scan per 100 kHz step; EU868 = 71 points in a few seconds) every `spectrum_sweep_interval_seconds` (default 300) and draws the result as the **Band Spectrum** card on the RF Environment page — median and peak level per step with the channel positions overlaid. Set it to `0` to disable automatic sweeps; the card's "Sweep now" button (admin) still works. A full sweep costs roughly 4 s of scan time per interval (~1% of receive time at the default cadence).

### RF Environment companion — for boards with no SX1261 (extra/rfenv_companion)

RAK2287 (see the capability matrix above) has **no SX1261 at all** — no config change makes a real hardware spectral scan possible on that board. `extra/rfenv_companion` is a Heltec V3 with its own independent SX1262 radio and antenna that samples real ambient RSSI and reports a histogram back to Meshpoint over USB serial, so the RF Environment page's histogram and noise-floor card can show real hardware-measured data again even on hardware that will never grow a working SX1261.

```yaml
capture:
  sources:
    - rfenv_companion
  rfenv_companion:
    - serial_port: "/dev/ttyUSB3"
      serial_baud: 115200
      label: "rfenv"
      name: "RF Env companion"
      nb_scan: 512          # RSSI samples per scan; lower than the real
                             # HAL's 1024 default since this board
                             # physically retunes+samples over a serial
                             # round-trip, not near-instant in-silicon
```

Only ever active when the real HAL-backed spectral scan is unavailable (`_build_spectral_scan_service` returned `None`) — it's a fallback, not a competitor to real hardware when the SX1261 genuinely works (e.g. SenseCap M1). Polls on the same `radio.spectral_scan_interval_seconds` cadence as the real scan (reused as-is, no separate interval to configure) and the same `radio.frequency_mhz` anchor frequency. Implemented by `RfEnvCompanionScanService` (`src/api/telemetry/rfenv_companion_scan_service.py`), which exposes the exact same interface `rf_routes.py` already expects from the real `SpectralScanService` — so the RF Environment page needs zero changes to render it; the message field just adds a note that the histogram came from the companion, not the concentrator's own hardware.

Flash `extra/rfenv_companion/rfenv_companion.ino` (RadioLib 7.7.1, same board/pins already proven by `extra/pager_client`) — WiFi/secrets are entirely optional (see below), it's always polled directly over the USB serial connection regardless. The board's own OLED has four screens, each opening with a one-line header naming itself after the matching RF Environment dashboard card, all working independent of any USB/Meshpoint connection: **STATUS** (last poll time), **LIVE SCAN** (continuous per-frequency RSSI bars across the board's own EU868-default band constant), **BAND SPECTRUM** (a fresh discrete sweep — median line + p95/peak dots — the on-device equivalent of the dashboard's Band Spectrum card), and **CHANNEL HISTOGRAM** (hold the PRG button, from any of the three screens above, to run the exact same single-frequency histogram scan Meshpoint itself requests, with floor/median shown right on-device). Short-press cycles STATUS → LIVE SCAN → BAND SPECTRUM → STATUS; the hold gesture works from any of those three. The panel auto-blanks after 5s of no button activity (burn-in protection, same pattern as `extra/pager_client`/`extra/pocsag_companion`) and wakes on the next press.

**Also powers the Band Spectrum card**, the same fallback way — `spectrum_routes.init_routes()` gets the companion whenever the real service is unavailable, same precedence as the histogram wiring above. The companion sweeps the *same* frequency list Meshpoint's own `_sweep_frequencies_hz(config)` already computes for the real HAL sweep (region/band logic stays Python-side, one source of truth), via a `{"cmd":"sweep",...}` serial command, on the same `radio.spectrum_sweep_interval_seconds` cadence and "Sweep now" button as the real feature — no new config keys. Per-point sample count is intentionally small (16, firmware-clamped to 16-32) since this board physically retunes+samples each point over a slow serial round-trip rather than the real HAL's near-instant in-silicon scan; a 71-point EU868 sweep takes a few seconds, matching the real feature's own budget. **Known limitation**: the firmware caps a sweep at 128 points (`SWEEP_MAX_POINTS`) for time/memory safety — wide-band regions like US915 (~260 points at the default 100 kHz step) get a truncated sweep rather than the full band; EU868 (~71 points) is unaffected.

**Configuration → Firmware** has a Compile/Flash card for this board (`src/api/routes/rfenv_companion_firmware_routes.py`, `rfenv_companion_firmware_card.js`) — same `arduino-cli` streaming mechanism as the Pager/POCSAG cards: single board (no picker, matching the Pager card's own simplicity), a **Band picker** (868 MHz / 70cm, see below), device-to-flash picker, Compile/Flash/Show-output. If the selected port is the currently-configured companion, the live `RfEnvCompanionScanService` is released before flashing and reconnected afterward (same pattern as the POCSAG card's own release/reconnect logic).

**Band picker — a second, standalone 70cm handheld scanner.** The sketch has one compile-time choice, a `BAND SELECT` block (`#define BAND_EU868` / `#define BAND_70CM`, exactly one uncommented) near the top of `rfenv_companion.ino`, same source-level-toggle-plus-regex-rewrite mechanism as the POCSAG card's own board picker. `BAND_EU868` (default) is what this section is otherwise about — feeding a Meshpoint box's own RF Environment page. `BAND_70CM` derives `DEFAULT_FREQ_MHZ`/`BAND_START_MHZ`/`BAND_END_MHZ` for the 430-440 MHz amateur 70cm band instead, for a **second, physically distinct** Heltec V3 (its own antenna/RF matching network built for that band) used purely as a standalone handheld RF scanner — it can never usefully feed a 868/915-band Meshpoint's own RF Environment page, since that page reflects the concentrator's own operating band. The `{"cmd":"status"}` reply's `band` field (`"eu868"`/`"70cm"`) reports which one a given board was built for.

**Optional WiFi/mDNS/OTA/web dashboard — a second, independent way to use this board's own standalone-scanner data — LIVE-CONFIRMED on real hardware.** Ported from `extra/pocsag_companion`'s own WiFi/OTA/web-dashboard mechanism (not its paging-specific content — no callsign, no page-send form). Copy `extra/rfenv_companion/secrets.h.example` to `secrets.h` (gitignored) and fill in `WIFI_SSID`/`WIFI_PASSWORD`/`OTA_PASSWORD`/`WEB_PASSWORD` — leave `WIFI_SSID` blank/placeholder and the board skips WiFi entirely, running USB-serial/OLED-only exactly as before; **a board used purely as a Meshpoint companion needs nothing here filled in**. A board already flashed with placeholder credentials can also be provisioned without ever touching `secrets.h` or recompiling: `{"cmd":"set_wifi","ssid":"...","password":"..."}` / `{"cmd":"set_web_password","password":"..."}` over the same USB-serial connection Meshpoint already polls (writes to NVS, same as the web UI's own WiFi Credentials card), paired with `{"cmd":"reboot"}` to apply it — mirrors `pocsag_companion.ino`'s own identical commands, since USB serial keeps working regardless of WiFi state while the web UI obviously doesn't until WiFi is up.

**These same commands are also reachable from Meshpoint's own dashboard**, not just by hand over a raw serial terminal — Configuration → Firmware's RF Environment companion card gains a **Live Device Commands** section with WiFi SSID/password and web-dashboard-password fields. Unlike the equivalent POCSAG/DAPNET live-command cards, this one does **not** require the target board to already be Meshpoint's configured companion: every Save/Reboot is a one-off command sent straight to whatever port is currently selected in the "Device to flash" picker just above it (`src/api/routes/rfenv_companion_config_routes.py`, `PUT /api/config/rfenv-companion/wifi` / `/web-password`, `POST /api/config/rfenv-companion/reboot`, each opening its own short-lived serial connection to `port` — Meshpoint never caches or persists the password itself). That's deliberate: the main use case is provisioning a brand-new board's WiFi right after flashing it, before it's ever registered as a companion at all. If the selected port *is* the currently-configured companion's own port, the live `RfEnvCompanionScanService` is briefly released first (same release/reconnect pattern the Flash button already uses) so the one-off connection doesn't collide with it. Saving WiFi offers an immediate "Reboot now?" follow-up, same two-step flow POCSAG's own card uses, since new credentials only take effect on the companion's next reboot.

Once connected: reachable at `http://rfenv-companion-eu868.local` (or `-70cm.local` for that band — band-suffixed so two boards on the same LAN don't collide under the same name), a password-gated single-page dashboard (Status / Channel Histogram / Band Spectrum / WiFi Credentials cards, styled with the same dark palette the real Meshpoint dashboard and the other companion firmwares already share) with "Scan now"/"Sweep now" buttons — useful e.g. carrying this board as a portable scanner and checking it from a phone/laptop browser instead of the 128x64 OLED. The Channel Histogram's "Scan now" takes a frequency input (pre-filled with a sensible per-band default — the shared Meshtastic/MeshCore-area anchor for EU868, DAPNET's real 439.9875 MHz for 70cm — freely editable), unlike the OLED's own button-triggered scan which is always locked to whatever Meshpoint last requested. ArduinoOTA lets firmware updates go out over WiFi afterward instead of needing USB. WiFi-triggered scans/sweeps never touch the radio directly from the web server's own thread — they stage a request (`queueWebScan()`/`queueWebSweep()`) that `loop()` picks up and runs itself, same cross-thread-safety discipline (`stateMutex`) `pocsag_companion.ino`/`pager_client.ino` already established for their own web dashboards.

A config-editor UI for `capture.rfenv_companion` itself (a Configuration card + persisted `PUT` route, matching the POCSAG companion's own device-list card) is not yet built — adding/removing a device is still YAML-hand-edit only.

### Reticulum companion — standalone LoRa↔internet bridge (extra/heltec_v4_reticulum_bron)

A Heltec V4 running `microReticulum_Firmware` (a fork of RNode_Firmware with the [microReticulum](https://github.com/attermann/microReticulum) stack embedded) as a fully self-contained [Reticulum](https://reticulum.network/) transport node — not a Meshpoint capture source or companion in the `capture.*` sense, and no USB-serial link to Meshpoint once flashed. It bridges local LoRa (869.463 MHz / SF8 / BW125 / CR5, the network's standard parameters) to a Reticulum TCP backbone over WiFi, entirely independently. See `extra/heltec_v4_reticulum_bron/BUILD-INSTRUCTIES.md` for the underlying firmware/architecture background.

**Configuration → Firmware** has a Provision+Flash card for this board (`src/api/routes/reticulum_companion_firmware_routes.py`, `reticulum_companion_firmware_card.js`) — unlike every other Firmware card, this one wraps **PlatformIO** (`pio`), not `arduino-cli`: the firmware's own `platformio.ini` uses per-environment `custom_variant`/littlefs/symlinked `lib_deps` config arduino-cli's `boards.txt` system can't express. Single fixed board/environment (`heltec_wifi_lora_32_V4-local-udp`) — no board picker, even though `platformio.ini` itself defines 32 environments across ESP32 and nRF52 targets.

WiFi SSID/password and the Reticulum backbone host/port (default `node.reticulumnet.nl:4242`, the public testnet) are this firmware's only run-time-configurable settings, and they're compile-time `#define`s in `node_config.h` — there's no serial/NVS provisioning path like the other companions' `set_wifi` commands. So the card's "Compile" button also provisions: it writes `node_config.h` from the form before every build (mirrors `extra/heltec_v4_reticulum_bron/microReticulum_Firmware/flash-node.sh`'s own manual version of the same thing). `node_config.h` is gitignored (same reasoning as the other companions' `secrets.h`) — see `node_config.h.example` for the template. Both SSID and password are capped at 32 characters: this firmware's own `Remote.h` copies them into fixed 32-byte buffers (`strncpy(wr_ssid, NODE_WIFI_SSID, 32)`), tighter than WPA2's real 63-character allowance, and a longer value would silently truncate on the device rather than error — both the route and the card enforce this length upfront instead. An empty password is valid (open network); the firmware's own `wifi_remote_start_sta()` handles it.

Requires the PlatformIO toolchain, installed via `scripts/install.sh`'s separate opt-in prompt (`--skip-platformio` to skip non-interactively) — a second, independent toolchain from arduino-cli's, since this is the only companion firmware in this repo that needs it. Installed self-contained under `/opt/platformio` (its own venv; `PLATFORMIO_CORE_DIR` is set in `meshpoint.service`, same `--no-create-home` `meshpoint` service-user reasoning as arduino-cli's own `XDG_CACHE_HOME`/`/opt/arduino-cli`). Unlike arduino-cli's board core, PlatformIO downloads its ESP32 platform/toolchain lazily on first `pio run`, not during `install.sh` — so that step itself is quick, and the real multi-hundred-MB download happens the first time the card is actually used.

### Reticulum (native LXMF messaging)

Separate from the standalone companion above — this is meshpoint's own [Reticulum](https://reticulum.network/)/[LXMF](https://github.com/markqvist/LXMF) client, built into the dashboard as the **Reticulum** sidebar page (Peers, Messages, Send). Off by default:

```yaml
reticulum:
  enabled: false                              # opt-in
  display_name: "Meshpoint"
  reticulum_config_dir: "data/reticulum/rns_config"
  identity_path: "data/reticulum/identity"
  lxmf_storage_dir: "data/reticulum/lxmf"
  rnode_serial_port: ""                       # stable /dev/serial/by-id/... path, blank = no RNode
  rnode_frequency_hz: 869463000
  rnode_bandwidth_hz: 125000
  rnode_tx_power: 20
  rnode_spreading_factor: 8
  rnode_coding_rate: 5
  backbone_host: "node.reticulumnet.nl"
  backbone_port: 4242
```

**Configuration → Reticulum** now edits `enabled`/`display_name`/`rnode_*`/`backbone_*` directly from the dashboard (`rnode_serial_port` is a dropdown drawing from the same USB-device enumeration every other companion's port picker uses) — hand-editing `local.yaml` is no longer required for these. Saving there only updates `local.yaml`; the RNode/backbone fields still need `rnsd` itself to restart before they take effect (see below), which the card's own "Restart rnsd" button does directly, without restarting meshpoint.

**Why `enabled` defaults to `false`**: meshpoint's own `RNS.Reticulum()` call attaches to a locally-running `rnsd` shared instance as a client rather than opening a radio interface itself — but if `rnsd` isn't already running when meshpoint starts, `RNS.Reticulum()` falls back to opening whatever interfaces are configured in `reticulum_config_dir` directly, which would then fight `rnsd` for them once it starts. Only turn this on once `rnsd` (see below) is reliably running before meshpoint does.

**`rnsd` itself** runs as its own opt-in systemd service (`scripts/rnsd.service`, installed via `install.sh`'s own prompt, or manually: `sudo systemctl enable --now rnsd`) — deliberately **not** a dependency of `meshpoint.service` (ordering only, `After=rnsd.service`, no `Wants=`/`Requires=`), so Reticulum being off has zero effect on meshpoint's core service. Its own interfaces config gets regenerated from the `reticulum.rnode_*`/`backbone_*` keys above on every `rnsd` start (`scripts/write_rnsd_config.py`, run as `rnsd.service`'s own `ExecStartPre`) — written into `reticulum_config_dir`, the **same directory** meshpoint's own client uses. That's not just tidiness: the shared-instance RPC channel authenticates per-configdir, so meshpoint and `rnsd` sharing one directory is what makes the client/master split actually work reliably.

`rnode_serial_port` needs a physical RNode already flashed and plugged in — see the RNode firmware card below if you need to flash one. Leaving it blank still gives you a working Reticulum node over the `backbone_host`/`backbone_port` TCP link alone, no LoRa hardware required.

**Configuration → Firmware** also has a card for flashing real [RNode firmware](https://github.com/markqvist/RNode_Firmware) onto a board to use as `rnode_serial_port` above — 13 supported boards (Heltec LoRa32 v2/v3/v4, Heltec T114, LilyGO LoRa32 v1.0/v2.0/v2.1, LilyGO LoRa T3S3, LilyGO T-Beam, LilyGO T-Beam Supreme, LilyGO T-Deck, LilyGO T-Echo, RAK4631), each with its own band/model variants. Wraps `rnodeconf` (bundled with the `rns` pip package, already a meshpoint dependency — no separate install) server-side rather than the browser-side Web Serial flasher some other Reticulum tools use, since the board is physically on the Pi, not necessarily the machine your browser is on. One command (`rnodeconf --autoinstall`) flashes the firmware, provisions the EEPROM, and sets the firmware hash together — firmware itself is fetched live from the internet by `rnodeconf`, not vendored in this repo, so the Pi needs internet access at flash time.

### Standard Meshtastic Presets

To match a Meshtastic preset, set `spreading_factor` and `bandwidth_khz` together:

| Preset | SF | BW (kHz) |
|---|---|---|
| ShortTurbo | 7 | 500 |
| ShortFast | 7 | 250 |
| ShortSlow | 8 | 250 |
| MediumFast | 9 | 250 |
| MediumSlow | 10 | 250 |
| LongFast (default) | 11 | 250 |
| LongModerate | 11 | 125 |
| LongSlow | 12 | 125 |

**One preset per Meshpoint.** The dashboard preset (LongFast, MediumFast, etc.)
sets a single frequency, bandwidth, and default spreading factor for TX. The
concentrator still demodulates **SF7-SF12 in parallel on that frequency**, so
you can hear nodes using different spreading factors on the same channel plan.
You cannot listen to multiple modem presets or multiple frequencies at once on
one concentrator (multi-preset IF chains are backlog).

### Custom presets (Configuration → Radio)

The dashboard's **Configuration → Radio** card includes a **Custom**
chip alongside the named preset buttons. Selecting Custom reveals
inputs for spreading factor (5-12), bandwidth (125 / 250 / 500 kHz),
and coding rate (4/5, 4/6, 4/7, 4/8). Use it for combinations that
don't appear in the named-preset table above (for example
SF11 / BW125 / CR4/8 for an extra-resilient long-range link, or
SF7 / BW500 / CR4/5 to mirror the deprecated ShortTurbo).

When `current_preset` in the radio configuration is empty (because
the saved SF / BW / CR doesn't match any named preset), the card
opens on Custom automatically and pre-fills the three inputs from
the values in `local.yaml` so you can see exactly what you're on.

Modem changes always require a service restart; the dashboard
prompts you when one is needed. Off-spec combinations (anything
not in the named table) may be silently dropped by neighboring
nodes, so set the same Custom values on the receiving side too.

### Changing Region

```yaml
radio:
  region: "EU_868"
```

To also update your MeshCore companion radio:

```bash
meshpoint meshcore-radio EU
```

Or enter a custom frequency: `meshpoint meshcore-radio custom`

See the [Onboarding Guide](ONBOARDING.md#changing-meshcore-radio-frequency) for full details.

---

## Capture Sources

```yaml
capture:
  sources:
    - concentrator             # SX1302/SX1303 LoRa concentrator (RAK2287, etc.)
    - meshcore_usb             # optional MeshCore USB companion node
    # - serial                 # optional plain Meshtastic USB node as a capture source
    # - mock                   # optional synthetic packets for development
  concentrator_spi_device: "/dev/spidev0.0"  # Bobcat 300: "/dev/spidev5.0"
  meshcore_usb:
    auto_detect: true          # scans /dev/ttyUSB* and /dev/ttyACM*
    serial_port: null          # or set explicitly: "/dev/ttyACM0"
    baud_rate: 115200
```

The setup wizard configures sources automatically. To add or remove a MeshCore companion later, edit `sources` and restart.

**Available source types:**

| Source | Purpose |
|---|---|
| `concentrator` | SX1302/SX1303 LoRa concentrator (RAK2287, RAK7248, SenseCap M1) |
| `meshcore_usb` | MeshCore USB companion node (Heltec V4, T-Beam, RAK4631 with MeshCore firmware) |
| `serial` | Plain Meshtastic node over USB serial. Used when you don't have a concentrator. |
| `mock` | Synthetic packet generator for development. Not for production. |

When running both Meshtastic concentrator capture and a MeshCore USB companion, pin `meshcore_usb.serial_port` explicitly. Auto-detect can grab the wrong device when multiple Espressif boards are attached.

**Pinning by a stable path, not `/dev/ttyUSBn`.** Linux assigns `ttyUSB0`/`ttyUSB1`/etc. in whatever order devices are detected — unplugging and replugging (or a reboot) can renumber them, silently pointing a pinned config at the wrong physical device. Both the Configuration → MeshCore and → Serial cards' "Pinned serial port" field suggest currently-connected devices via a dropdown (`GET /api/config/serial-ports`), preferring `/dev/serial/by-path/usb-...` (identifies by physical USB port) over `/dev/serial/by-id/usb-...` (identifies by the device's own vendor+serial number) over the raw `/dev/ttyUSBn` path. by-path is the default recommendation because by-id can silently collide: cheap CP210x clone boards (common on Heltec V3/V4) often ship with an identical, unprogrammed factory-default serial number, so two such boards can produce the *same* by-id name — Linux keeps only one symlink, and the second device gets none at all. by-path avoids this since it's keyed on which physical hub port the device is plugged into instead. The trade-off: moving a device to a different USB port makes it look like a new device to Meshpoint (you'd need to re-pin it), rather than automatically following the board — a reasonable cost for a fixed Pi deployment where ports don't move around casually. You can still type a path manually (e.g. for a device that isn't currently plugged in).

**Multiple Meshtastic USB sticks.** A single stick uses the `serial_port` / `serial_baud` fields above. To capture from more than one at once (e.g. one on 433 MHz, one on 868 MHz), use the `serial` list instead — same shape as `meshcore_usb`'s companion list:

```yaml
capture:
  sources:
    - serial
  serial:
    - serial_port: "/dev/ttyUSB0"
      label: "433"
    - serial_port: "/dev/ttyUSB1"
      label: "868"
```

Each entry's `label` tags its captured packets' `capture_source` as `serial_433` / `serial_868` so the packet feed and drawer can tell them apart, the same way labelled MeshCore companions do. When `capture.serial` is set, the top-level `serial_port` / `serial_baud` fields are ignored.

Configuration → Serial in the dashboard edits this list without hand-editing `local.yaml` — same add/remove/label UI as Configuration → MeshCore's companion editor, minus auto-detect (an empty port already means "let meshtastic-python auto-detect").

### Serial Device Identity (v0.7.7+)

Each Meshtastic USB stick's own long/short name can be renamed from
the dashboard, per device — useful since these sticks have no
Bluetooth, so the official Meshtastic app's usual rename path isn't
available without unplugging the stick into a laptop.

- **Configuration → Serial → (each device's own) Long name / Short
  name** edits the inputs, ticks "Send advert after save" (default
  on), and clicks **Save Name**. The Meshpoint sends an admin
  `setOwner` message to *that* stick over its own serial connection,
  persists the values to `local.yaml` under that device's own
  `capture.serial` entry, and optionally sends a NodeInfo broadcast
  from that same stick so neighbors pick up the new name immediately.
- Unlike MeshCore's per-companion rename, there's no live
  reconnect-hook to re-apply this if the stick is later swapped for a
  factory-default replacement (`SerialCaptureSource` has no
  auto-reconnect loop) — the persisted values are applied once, at
  the **next service restart**. The rename itself still takes effect
  immediately on the currently connected stick; only the
  swap-a-different-stick-in-later case needs a restart.

### POCSAG Companion / DAPNET (Networks tab)

`Configuration → POCSAG` edits the USB connection list for
`extra/pocsag_companion` boards (TTGO LoRa32, Heltec V3) — same
shape as `capture.serial` above, minus any identity/advert fields:
this board isn't a mesh node, so it has nothing to rename. Callsign,
screen timeout, and every other on-device setting stay on the
board's own WiFi web dashboard (`pocsag-companion.local`), not here.

```yaml
capture:
  sources:
    - pocsag_serial
  pocsag_serial:
    - serial_port: "/dev/ttyUSB2"
      serial_baud: 115200
      label: "ttgo"
      name: "Attic POCSAG"
```

`capture.pocsag_serial` persists via `PUT
/api/config/capture/pocsag-serial-devices`, and the shared port-picker
(`GET /api/config/serial-ports`) flags a port already pinned by a
POCSAG entry, same as it does for Serial/MeshCore. Adding
`pocsag_serial` to `sources` spins up one `DapnetSerialSource` per
configured device (`src/capture/dapnet_source.py`), reading
newline-delimited JSON pages off the board's serial connection —
decoded traffic shows up on the **Networks → DAPNET** dashboard page
(named for the real DAPNET paging network the companion talks to, not
the generic POCSAG modulation — see `frontend/js/dapnet_panel.js`).
The Networks sidebar link only appears once `pocsag_serial` is in
`capture.sources` (a new `data-requires-source` sidebar-hiding
mechanism, independent of the existing role-based
`data-requires-section` gating).

**Topbar status chip.** `DapnetSerialSource` sends a one-shot
`{"cmd":"status"}` query right after connecting; the companion (a
recent-enough build of `extra/pocsag_companion.ino`) replies
`{"type":"status","board":"ttgo"|"heltec","callsign":"...","freq":439.9875,
"hostname":"pocsag-companion","wifi_ip":"192.168.x.x"}`, cached and
exposed via `GET /api/config`'s `dapnet_status` array (one entry per
configured companion — distinct from the `dapnet` key above, which is
the saved blacklist/ignore config, not live status). Shows as a small
topbar badge (callsign, frequency, board), same visual style as the
Meshtastic USB chip, hidden entirely when no POCSAG companion is
configured. Older companion firmware without the `"cmd"` handler
simply never replies — the chip then just shows `----` for
callsign/board rather than failing.

`hostname`/`wifi_ip` are only shown on the Configuration → POCSAG
readout tiles (a "Web UI" link straight to the companion's own web
dashboard), not the topbar chip, which stays compact.

**Periodic status poll (live TX count/uptime).** The status query no
longer fires only once -- it repeats every `dapnet.status_poll_interval_s`
seconds (default 60), still strictly request/response (never an
unsolicited device push), which is what makes genuinely live fields
like `tx_count`/`last_tx_ok`/`uptime_ms` meaningful instead of frozen
at whatever they were at connect time. Edit the interval from
Configuration → POCSAG's "DAPNET settings" card (10-3600s); unlike the
two capcode lists in that same card, changing it needs a service
restart (`DapnetSerialSource` only reads it once, at construction).

```yaml
dapnet:
  status_poll_interval_s: 60   # 10-3600
```

TX Count, Last TX (Never/OK/Failed), and Uptime show up as three more
readout tiles alongside Callsign/Frequency/Hardware/Web UI. Uptime
wraps to a small number every ~49.7 days (ESP32 `millis()` overflow)
-- a real device limitation, not a display bug, if it ever shows a
suspiciously small value on a long-running companion.

A **WiFi SSID** tile sits next to Web UI, sourced from the same
periodic status reply -- lets you confirm which network the companion
is actually connected to right on this page, without needing to open
its own web dashboard's Connection card.

**Setting the callsign from the dashboard.** Each connected device's
readout tile on `Configuration → POCSAG` also has a "Set callsign"
field — saving it sends `{"cmd":"set_callsign","callsign":"..."}` over
the same serial connection and waits for the companion's reply (same
validation the on-device web dashboard's own Callsign card already
enforces: non-empty, ≤8 chars, not `N0CALL`, must contain a digit).
Nothing is persisted on the Meshpoint side — the callsign lives
entirely in the companion's own NVS — but a successful save updates
the cached status immediately, so the readout tile and topbar chip
reflect it without waiting for another status query (which only ever
happens once, at connect). Requires a companion running a firmware
build with the `set_callsign` command (added alongside the status
query above); older builds will just time out after 5s with "No reply
from companion".

**Setting the web dashboard password from the dashboard.** The same
row also has a "Set web dashboard password" field, sending
`{"cmd":"set_web_password","password":"..."}` the same way. Unlike the
callsign, this value is handled as a real secret end to end: the
companion's reply never echoes it back, Meshpoint never caches,
persists, or logs it anywhere (not in `local.yaml`, not in the status
cache, not in an audit-log entry), and the companion's own serial
console log — which otherwise echoes every incoming command
verbatim — specifically redacts this one. `WEB_PASSWORD` (the
`secrets.h` compile-time default) becomes a runtime value the first
time this is set, persisted in NVS and surviving reboots; until then,
`checkAuth()` still compares against the `secrets.h` default. The
companion's own "Clear Settings" button resets it back to that
default, same as it already does for the callsign.

**Resetting callsign + password from the dashboard.** A "Reset
Callsign & Password" button sends `{"cmd":"reset_credentials"}` —
clears the callsign back to empty and the web password back to the
`secrets.h` default, without touching screen timeout (deliberately
narrower than the companion's own "Clear Settings" button, which
resets all three). Guarded by a browser confirmation dialog since it's
destructive — TX is blocked again immediately until a new callsign is
set. A successful reset also clears the readout tile's cached
callsign right away, rather than waiting for the next status poll.

**Setting WiFi credentials + reboot from the dashboard.** A separate
"Save WiFi Credentials" field pair sends
`{"cmd":"set_wifi","ssid":"...","password":"..."}` — this is the
piece that lets a brand-new companion be configured entirely through
Meshpoint, without ever hand-editing `secrets.h` before the first
flash or opening the companion's own web dashboard: USB serial keeps
working regardless of WiFi state, so a board with blank or wrong WiFi
credentials is still fully reachable for this. Deliberately its own
separate action from callsign/password/reset above — changing WiFi
takes the companion off its current network until it reboots with the
new credentials, a bigger consequence than any of those.

Saving does **not** reconnect by itself — `setupWifiNtpOta()` only
ever runs once, at boot — so a successful save offers a confirm-modal
"reboot now?" prompt, which (if accepted) sends a second command,
`{"cmd":"reboot"}`, over the same serial connection. The password
field is handled exactly like the web password: never cached,
persisted, or logged by Meshpoint, and the companion's reply only ever
echoes the SSID back (not sensitive), never the password.

**Not yet confirmed on real hardware**: whether Meshpoint's own serial
connection survives the companion's reboot. Both current boards use a
separate USB-UART bridge chip, which typically stays enumerated
through an ESP32 reset — but if a board ever used the chip's native
USB instead, it would re-enumerate and could need a Meshpoint
**service restart** to reconnect (`DapnetSerialSource` has no
reconnect loop, matching `SerialCaptureSource`'s own documented
limitation). If the reboot command times out or the readout tile goes
stale afterward, that's the mechanism to check first.

**Verifying it worked: the companion's own web dashboard.** Open
`pocsag-companion.local` (or its IP) directly — the login screen now
shows the saved callsign + hostname before you even enter the
password (via a new unauthenticated `GET /api/whoami`, nothing
sensitive), so you can confirm you're looking at the right physical
board when more than one is on the network. Once logged in, two new
cards close the loop on the WiFi feature above: **Hardware** (chip
model/revision/cores/frequency, flash size, free heap, sketch
space, SDK version) and **Connection** (SSID, IP, gateway, subnet,
DNS, MAC, RSSI, hostname) — the latter is the actual way to confirm a
serial-set WiFi credential resolved correctly, rather than assuming.
This is a `extra/pocsag_companion.ino`-only change; nothing on the
Meshpoint side reads this data.

**DAPNET capcode filters** (`Configuration → POCSAG`'s second card,
`dapnet:` config section) — two independent, immediately-applied
tiers (no restart needed) for decoded pages, keyed on capcode:

```yaml
dapnet:
  blacklist_capcodes: [200, 208, 216, 224]   # shown live, never stored
  ignore_capcodes: [4512, 4520]              # neither shown nor stored
```

- `blacklist_capcodes` (defaults to DAPNET's own confirmed real
  network housekeeping/time-sync beacon capcodes) still broadcast to
  the live DAPNET page over the dashboard WebSocket — useful to
  confirm the decoder/network are still alive — but are never written
  to the `packets` table, and never touch relay/MQTT/stats.
- `ignore_capcodes` are dropped entirely: not shown, not stored, not
  counted anywhere. Pure noise.
- Anything not on either list is treated like every other protocol:
  stored, broadcast live, and included in `/api/dapnet/stats`.

```yaml
capture:
  serial:
    - label: "433"
      long_name: "Field Node 433"    # optional, this stick only
      short_name: "F433"             # optional, max 4 characters
    - label: "868"
      long_name: "Field Node 868"    # optional, independent of the 433 one
```

Leaving a device's `long_name`/`short_name` unset (the default) keeps
whatever identity is already on the stick's own flash.

Validation (shared between the dashboard and the connect-time
apply): long name max 36 characters, short name max 4 characters —
same ceilings as the dashboard's own concentrator Identity route.
Both must be non-empty if provided; meshtastic-python's own
`setOwner()` call would otherwise abort the whole request process on
an empty name, so Meshpoint validates and rejects before ever
reaching that call.

---

## Location (GPS) source

```yaml
location:
  source: "static"           # static | gpsd | uart
  gpsd_host: "127.0.0.1"     # gpsd TCP host (only when source=gpsd)
  gpsd_port: 2947            # gpsd TCP port
  update_interval_seconds: 5 # how often the coordinator polls the source
  min_fix_quality: 1         # minimum NMEA fix quality (1=2D, 3=3D)
```

`location.source` selects where the Meshpoint reads **live GPS fixes**
(for the Configuration → GPS skyplot and optional mesh POSITION
broadcasts). The setup wizard always writes static lat/lon/alt under
`device.*` as the **registered Meshradar fleet pin** (see
[Device Identity](#device-identity)); live gpsd does **not** overwrite
those values. Source changes require a service restart; registered
coordinates and mesh position settings hot-reload from the dashboard.

| Source | Behavior |
|---|---|
| `static` (default) | No live GPS hardware. Registered coordinates live in `device.*` only. Skyplot shows the static pin. |
| `gpsd` | Reads live fixes from the system `gpsd` daemon over TCP (`127.0.0.1:2947`). Recommended for any USB GPS receiver (u-blox 7, u-blox 8, VFAN puck, generic CDC ACM sticks). Skyplot and stats update from the live fix. |
| `uart` | Reserved for direct-serial reads from a Pi HAT GPS (e.g. RAK 7248). Currently a placeholder; falls back to static and surfaces an explanatory error in the dashboard. |

### Mesh position broadcasts (LoRa / Meshtastic app map)

When native TX is enabled (`transmit.enabled: true`), the Meshpoint can
send periodic Meshtastic POSITION packets. That is **separate** from
the Meshradar fleet pin in `device.*`.

Configure on **Configuration → GPS → Mesh position broadcasts**, or in
yaml. Set **Position broadcast interval** on the same GPS page (or
`transmit.position.interval_minutes` in yaml). Default is **15 minutes**.
Use **0** to pause POSITION packets without disabling TX.

```yaml
transmit:
  position:
    interval_minutes: 15
    startup_delay_seconds: 180
    coordinate_source: "static"       # static | live
    location_precision: "approximate"  # exact | approximate | none (live only)
```

| Setting | Values | Meaning |
|---|---|---|
| `coordinate_source` | `static` (default) | Broadcast the registered pin from `device.latitude/longitude`. |
| | `live` | Broadcast the live gpsd/UART fix. Requires `location.source` other than `static`. |
| `location_precision` | `approximate` (default for live) | Round to ~2 decimal places before POSITION TX (about **0.7 mi** / **1.1 km**; the dashboard label follows Settings → Meshpoint distance units). |
| | `exact` | Full precision from the live fix. |
| | `none` | Skip POSITION broadcasts when using live (privacy: no position on mesh). |

When `coordinate_source: static`, coordinates are sent at full wizard
precision regardless of `location_precision`.

### Mesh telemetry broadcasts (LoRa / device health)

When native TX is enabled, the Meshpoint can send periodic Meshtastic
`device_metrics` telemetry (`TELEMETRY_APP`). That is **separate** from
NodeInfo and POSITION.

Configure on **Configuration → Radio → Telemetry broadcast interval**, or in
yaml:

```yaml
transmit:
  telemetry:
    interval_minutes: 30
    startup_delay_seconds: 120
```

Default is **30 minutes**. Use **0** to pause telemetry broadcasts.

### Using gpsd (USB GPS receivers)

`scripts/install.sh` installs `gpsd` and `gpsd-clients`, configures
`/etc/default/gpsd` for **USB hotplug** (`USBAUTO="true"`,
`DEVICES=""`, `GPSD_OPTIONS="-n"`), and enables `gpsd.socket`. As
of v0.7.5 this happens on every fresh install **and** every
upgrade re-run.

To enable live GPS:

1. Plug in a USB GPS receiver. udev rules shipped with `gpsd`
   recognize u-blox VIDs (`0x1546`) and auto-attach the device.
   The MeshCore USB auto-detect path (`UsbPortClassifier`) skips
   any port classified as `gps_known`, so a u-blox stick will
   never be probed as a MeshCore companion.
2. Open the dashboard at **Configuration → GPS**. Set **Registered
   coordinates** (Meshradar fleet pin). Switch **Source** to **gpsd**
   for live skyplot data. Optionally set **Mesh position broadcasts**
   to **Live GPS** with **Approximate** or **Precise** privacy, then
   click **Save**. Changing the GPS source type requires a service
   restart; coordinate and mesh-position edits hot-reload.
3. Watch the **GPS** card. The skyplot animates, satellite dots
   render at their azimuth/elevation, and the fix-mode lamp flips
   from grey (no fix) → amber (2D) → green (3D) as the receiver
   acquires.

For headless / yaml-only setup add the section above to
`local.yaml` and restart the service. Verify with `cgps` (shipped
in `gpsd-clients`) or `gpsmon`.

### Receiver compatibility

| Receiver | Protocol | Tested |
|---|---|---|
| u-blox 7 USB stick | USB CDC ACM, NMEA + UBX | yes (RAK V2 .141) |
| u-blox 8 USB stick | USB CDC ACM, NMEA + UBX | yes |
| VFAN ublox 7 USB puck | USB CDC ACM, NMEA + UBX | yes |
| RAK 7248 onboard u-blox via UART (`/dev/ttyAMA0`) | NMEA over UART | placeholder (`source: uart`, not yet wired) |

Other USB receivers should work as long as `gpsd` recognizes the
device's VID. If `cgps` shows data but the dashboard does not,
check `journalctl -u meshpoint | grep -i gpsd` for connection
errors and confirm `source: gpsd` in `local.yaml`.

### Privacy

Three independent surfaces:

| Surface | Config | Notes |
|---|---|---|
| **Meshradar cloud** | `device.latitude/longitude` | Always the registered pin. Live GPS never moves the fleet marker. |
| **LoRa mesh (POSITION)** | `transmit.position.coordinate_source` + `location_precision` | Choose registered pin or live GPS; approximate / precise / hidden on live. |
| **MQTT** | `mqtt.location_precision` | Applies to position fields in MQTT publishes only (`exact` / `approximate` / `none`). |

To run a mobile Meshpoint without leaking live coordinates on the mesh,
use **Live GPS** with **Hidden** mesh privacy, or keep mesh source on
**Registered pin**. To keep Meshradar on your home pin while testing
gpsd outdoors, leave registered coordinates at home and use live mesh
POSITION only if you intend to advertise on the LoRa map.

---

## Primary Channel Name

The primary (channel 0) name is used to compute the Meshtastic channel hash on transmitted packets. It must match the primary channel name on your mesh for outgoing messages to be heard.

```yaml
meshtastic:
  primary_channel_name: "LongFast"
```

The default is `LongFast` (Meshtastic's standard public channel). Change it only if your mesh uses a custom primary channel name. You can also edit this from the dashboard: open the **Radio** tab, edit **Channel 0**, and save. The Radio and Messages tabs reflect the same value.

### Quick Deploy (QR export)

**Configuration → Channels → Quick Deploy** exports public channel parameters for field radios:

- QR code and `https://meshtastic.org/e/#…` URL (Meshtastic app compatible)
- Downloadable JSON via `GET /api/config/export`

**Private channel keys are never exported.** The QR uses the standard Meshtastic default PSK only (`AQ==`), matching a public primary channel deployment. Scan with the Meshtastic mobile app (Android in-app scanner; iOS camera).

---

## Private Channel Monitoring

By default, the Meshpoint decrypts traffic on the standard Meshtastic default key (`AQ==`). To also decode packets on your private channels, add the channel keys to `local.yaml`:

```yaml
meshtastic:
  channel_keys:
    MyChannel: "base64encodedPSK=="
    AnotherChannel: "anotherBase64PSK=="
```

**Finding your channel's PSK:** Open the Meshtastic app, go to the channel settings, and copy the pre-shared key (base64 format).

**Channel name must match exactly** what's configured on your Meshtastic node (case-sensitive).

The Meshpoint tries each configured key when decoding a packet. Packets matching any configured key will be fully decoded. Packets on channels with unknown keys will continue to show as ENCRYPTED.

To change the default Meshtastic key (if your primary channel uses a non-default PSK):

```yaml
meshtastic:
  default_key_b64: "yourPrimaryKeyBase64=="
```

### MeshCore Keys

MeshCore uses its own default channel key, configurable separately:

```yaml
meshcore:
  default_key_b64: null              # leave null to use the MeshCore built-in default
  channel_keys: 
    SomeChannelName: "32-BytePSK"      # Meshcore Channel Name with 32-Byte Hex PSK. One channel per line            
```
Any Channels listed in the YAML will show in the UI. Changes made in the UI will be written to the YAML config file and pushed to the USB Companion device. Additionally, all channels will be pushed to the USB Companion device upon Meshpoint startup. Up to 40 user channels (slots 1–40) can be configured; slot 0 is always Public.

### MeshCore Companion Identity (v0.7.5+, per-companion since v0.7.7)

Each USB companion's advert name is what neighbors see in their
contact list and on the mesh. The dashboard owns the rename path,
independently per companion:

- **Configuration → MeshCore → USB capture sources → (each
  companion's own) Companion name** edits the input, ticks "Send
  advert after save" (default on), and clicks **Save Name**. The
  Meshpoint sends `CMD_SET_ADVERT_NAME` to *that* companion (via
  its own `meshcore.commands.set_name`), persists the cleaned name
  to `local.yaml` under that companion's own `capture.meshcore_usb`
  entry, and optionally fires an advert from that same companion so
  neighbors pick up the new name immediately.
- Each companion's configured name is **re-applied on every USB
  reconnect for that specific device**. Hot-swapping a
  freshly-flashed companion, or replacing a failed unit, lands the
  new device on your configured name without a manual re-save.

```yaml
capture:
  meshcore_usb:
    - label: "868"
      companion_name: "Mesh Lab East"   # optional, this companion only
    - label: "433"
      companion_name: "Mesh Lab West"   # optional, independent of the 868 one
```

Leaving a companion's `companion_name` unset (the default) keeps the
v0.7.4 behavior for that device: the Meshpoint trusts whatever name
is on its flash. Set it once from the dashboard per companion;
further reboots / unplug / replug events re-apply automatically.

The older mesh-wide `meshcore.companion_name` field (pre-v0.7.7,
singular) still works as a fallback for the *first* configured
companion only, so existing `local.yaml` files keep working
unchanged — but new setups should use the per-companion field above.

Validation (shared between the dashboard and the on-connect
re-apply path): the name is stripped of leading/trailing
whitespace, must not be empty, and must fit in **32 UTF-8 bytes**
(conservative cap matching the companion firmware's accepted
range). 4-byte unicode codepoints (some emoji) count toward that
limit.

---

## Smart Relay

> **Status: experimental — native onboard relay added in v0.7.4.** When `transmit.enabled: true` the Meshpoint now relays through its own SX1302 concentrator using identity-preserving re-broadcast (original `source_id` and `packet_id` survive, only `hop_limit` is decremented). No second radio required. **Hardware validation is still in progress** — please report results in Discord or via a Github issue.

### Native onboard relay (preferred)

Set both `transmit` and `relay` to enabled. The same SX1302 that handles outgoing messages re-broadcasts captured packets, sharing duty-cycle accounting so relay traffic can never crowd out user TX:

```yaml
transmit:
  enabled: true
  # ... see Transmit (Native Messaging) below for the full block

relay:
  enabled: true
  max_relay_per_minute: 20
  burst_size: 5
  min_relay_rssi: -110.0
  max_relay_rssi: -50.0
  # serial_port intentionally omitted — native path is used
```

Encrypted packets (no key match locally) and MeshCore packets are intentionally skipped on the native path to avoid emitting garbage on the air.

### Legacy USB-companion relay

The original v0.7.0–v0.7.3 path is preserved for setups that already have a second Meshtastic radio attached. Only used when `transmit.enabled: false` and `relay.serial_port` is set:

```yaml
relay:
  enabled: true
  serial_port: "/dev/ttyACM1"  # relay radio serial port
  serial_baud: 115200
  max_relay_per_minute: 20     # token-bucket rate limit
  burst_size: 5                # max burst before throttle
  min_relay_rssi: -110.0       # ignore weak packets
  max_relay_rssi: -50.0        # ignore local packets (too strong)
```

The relay path is independent from RX: transmission never blocks packet reception. Packets are deduplicated by ID, rate-limited, and filtered by signal strength before relay.

---

## Transmit (Native Messaging)

Enable the Meshpoint to send messages directly through the onboard SX1302 concentrator (Meshtastic) and the MeshCore USB companion (MeshCore). This powers the Messages tab on the local dashboard.

```yaml
transmit:
  enabled: false               # opt-in
  node_id: null                # auto-generated 4-byte Meshtastic node ID
  tx_power_dbm: 14             # conservative default (dBm)
  # max_duty_cycle_percent omitted: auto-derives from radio.region
  long_name: "Meshpoint"
  short_name: "MPNT"
  hop_limit: 3
```

**`enabled`**: must be `true` to send from the Messages tab. Disabled by default.

**`node_id`**: leave as `null` to auto-generate. Once set, do not change it: your node identity is what other nodes see and cache in their contact lists.

**`tx_power_dbm`**: 14 dBm is conservative and compliant in most regions. Raise carefully; check your regional ISM band limits before increasing.

**`max_duty_cycle_percent`**: airtime limit as a percent of wall clock. Omit (or set to `null`) to auto-derive from `radio.region`: 10% in US/ANZ/KR/SG_923, 1% in EU_868/IN. Set explicitly in `local.yaml` to override (e.g. `25.0`). See `RADIO-CONFIG-EXPLAINED.md` for the full table and rationale.

**`long_name` / `short_name`**: shown to other nodes (long name in node lists, short name on compact displays). Match your naming convention.

**`hop_limit`**: initial hop count on outgoing Meshtastic messages. 3 is typical; higher values mean more relays and more airtime.

MeshCore transmission uses the USB companion node: configure its serial port under `capture.meshcore_usb` (see Capture Sources above). The companion handles encryption and RF timing; the Meshpoint sends serial commands.

---

## Upstream (Cloud)

```yaml
upstream:
  enabled: true
  url: "wss://api.meshradar.io"
  reconnect_interval_seconds: 10
  buffer_max_size: 5000        # local buffer during disconnects
  auth_token: null             # set by setup wizard
```

When enabled, the Meshpoint connects to [Meshradar](https://meshradar.io) via WebSocket and relays captured packets for aggregated mesh intelligence. The connection auto-reconnects with backoff and buffers packets locally during outages.

### Running Offline

To run the Meshpoint without sending anything to the cloud, set:

```yaml
upstream:
  enabled: false
```

When `enabled: false` the Meshpoint never opens an upstream connection and never transmits any packet, heartbeat, or telemetry to meshradar.io. All capture, decoding, dashboard, MQTT, and storage features still work.

No API key is required when running offline: `validate_activation()` skips the token check entirely whenever `upstream.enabled` is `false`. The setup wizard's `[4/8] API key` step now asks up front whether to upstream to meshradar.io — answering no writes `upstream.enabled: false` directly, with no key prompt.

---

## Storage

```yaml
storage:
  database_path: "data/concentrator.db"
  max_packets_retained: 100000
  max_telemetry_retained: 100000
  cleanup_interval_seconds: 3600
```

Packets and telemetry are stored in a local SQLite database. Old rows are pruned automatically once each table exceeds its cap (oldest-first) — `max_packets_retained` covers raw captured RF packets, `max_telemetry_retained` covers battery/voltage/temperature history (feeds the node drawer and Repeater Trends charts). Messages (DM/channel chat history) and the node roster are never auto-pruned. Both editable from Settings → Storage.

### Prometheus metrics (`/metrics`)

Optional Prometheus text scrape endpoint for LAN monitoring. **Off by default** — enabling does not change packet capture, relay, or dashboard behaviour.

```yaml
metrics:
  enabled: false
  require_auth: true    # when false, /metrics is open on the LAN (use firewall rules)
  api_keys: []           # managed from Configuration -> Metrics, not hand-edited
```

When `metrics.enabled: true`, Prometheus (or any scraper) can poll:

```text
http://<pi-ip>:8080/metrics
```

Exposed series include packet counts, node totals, RSSI/SNR averages, noise floor, relay stats, per-channel duty estimates (ToA), SX1302 CRC counters, and process uptime. Labels use protocol/channel/reason only — never PSKs, tokens, or node secrets.

**Example `prometheus.yml` scrape job (auth disabled):**

```yaml
scrape_configs:
  - job_name: meshpoint
    scrape_interval: 30s
    static_configs:
      - targets: ["192.168.1.50:8080"]
    metrics_path: /metrics
```

**API keys (for `require_auth: true`).** A logged-in browser session or a session Bearer JWT both work, but neither suits an unattended scraper — sessions are short-lived and expire. Instead, generate a named key from **Configuration → Metrics → API keys**: give it a label (e.g. "Home Assistant"), click *Generate key*, and copy the raw value shown — it's never shown again, only its hash is stored. Revoke a key any time from the same panel; revocation takes effect immediately, no restart.

Each key is scoped to a small, fixed set of read-only status routes — **not** "any dashboard API route": `/metrics` itself, plus `GET /api/device/metrics` (host CPU/RAM/disk/temp/fan) and `GET /api/stats/summary` (richer stats-page data: best signal ever, farthest contact, role/hardware-model distribution). It cannot reach anything that mutates config, controls the mesh, or reads message/node content. The [Home Assistant integration](../homeassistant/README.md) uses all three with one key.

Send it as a standard bearer token:

```
Authorization: Bearer <key>
```

Example Home Assistant `configuration.yaml` `rest` sensor using a key:

```yaml
rest:
  - resource: http://192.168.1.50:8080/metrics
    scan_interval: 60
    headers:
      Authorization: !secret meshpoint_metrics_key   # "Bearer <key>"
    sensor:
      - name: "Meshpoint Nodes Total"
        value_template: "{{ (value | regex_findall('meshpoint_nodes_total (\\d+)'))[0] }}"
```

(`secrets.yaml`: `meshpoint_metrics_key: "Bearer <key>"`.)

---

## Dashboard

```yaml
dashboard:
  host: "0.0.0.0"             # listen on all interfaces
  port: 8080
  static_dir: "frontend"
  plugins_dir: "plugins"     # extra/community themes: <plugins_dir>/themes/<id>/
  theme: "dark"              # default theme for browsers that haven't picked one
```

Access at `http://<pi-ip>:8080`. Bind to `127.0.0.1` to restrict to local access only.

Changes to `host`/`port`/`static_dir`/`plugins_dir` take effect on service restart. If the configured address can't be used (config typo, port already taken, privileged port), the server logs the problem and falls back to `0.0.0.0:8080` so the dashboard stays reachable.

**`theme`** — the default dashboard theme, one of the installed theme ids. Built-ins ship in `frontend/themes/` (`dark`, `light`, `high-contrast`, `sunlight`); the bundled extras in `plugins/themes/` are `solarized-dark`, `nord`, `gruvbox-dark`, `amber-mono`, `green-crt`, `dracula`, `catppuccin-mocha`, `rose-pine`, `everforest-dark`, `one-dark`, `kanagawa`, `github-dark`, `ayu-mirage`, `colorblind-safe`. It's what a browser shows when nobody has picked a theme via the topbar toggle; a per-browser choice made there overrides it locally. Editable at **Settings → Themes → Default theme** (admin only) or with `PUT /api/config/dashboard/theme` — applies live, no restart.

**`plugins_dir`** — where drop-in themes are read from (`<plugins_dir>/themes/<id>/`, each a `theme.json` + `theme.css`). Resolved from the working directory like `static_dir` (so `/opt/meshpoint/plugins/` on the Pi). A built-in theme id always wins an id collision with a plugin theme, and a plugin folder can't claim `dark`. The builder at **Settings → Themes** can write a theme here directly (**Save to device**, admin-only, no restart — reload the dashboard to pick it up) and the **Installed themes** list on that page deletes community themes; **Download theme.css / theme.json** still works for sharing or a pull request, and you can always hand-drop a folder and restart. Saved `theme.css` can't contain `@import` (a remote import leaks every dashboard visitor's IP) and is capped at 64 KiB.

`theme.json` fields:

| key | | |
|---|---|---|
| `id` | required | short slug; must match the folder name |
| `label` | required | display name in the picker |
| `icon` | optional | a keyword from `frontend/js/theme_glyphs.js` — `moon` `sun` `day` `contrast` `monitor` `terminal` `palette` `circle` `snowflake` `leaf` `flower` `wave` `droplet` `sparkles` `atom` `mountain` `eye` (unknown → `moon`) |
| `order` | built-ins only | integer curation sequence; **ignored for `plugins/themes/`** — those sort alphabetically by label in a separate "Community" group, always below the built-ins |
| `author` | optional | credit shown in the theme builder |
| `homepage` | optional | URL shown as a `↗` link next to the credit |
| `description` | optional | one line shown under "Start from" in the builder |

### RF Environment tab

Open **RF Environment** in the sidebar for a full-page noise-floor sparkline, calibration state, and the latest SX1302 spectral-scan histogram. Data comes from `GET /api/rf/status` (same sources as the sidebar telemetry rail).

- **Live scan** — hardware spectral scan on the tuned channel (`radio.spectral_scan_interval_seconds` > 0 and SX1261/HAL support present)
- **RF Environment companion** — real ambient RSSI from a Heltec V3 board (`extra/rfenv_companion`), automatically used instead of packet fallback on boards with no SX1261 (see below)
- **Packet fallback** — rolling minimum of `RSSI − SNR` when scan is disabled and no companion is configured
- Set `radio.spectral_scan_interval_seconds: 0` in **Configuration → Radio** to disable hardware scan; the tab shows a clear message and uses packet fallback only

---

## Fan Control (SenseCap M1)

```yaml
fan:
  enabled: false        # opt-in -- this hardware doesn't exist on RAK V2/Chameleon/DIY
  gpio_pin: 13           # confirmed via scripts/test_gpio_hardware.py fan-scan
  min_temp_c: 45.0        # ramp starts here
  max_temp_c: 65.0        # 100% duty at/above this
  min_duty: 0.35          # floor once ramping -- most small fans stall below this
  hysteresis_c: 5.0       # fan stays on until temp drops this far below min_temp_c
  poll_interval_s: 10.0
```

Temperature-driven PWM control for the SenseCap M1's onboard fan, reading CPU temperature from the Pi's thermal zone. GPIO 13 is a hardware-PWM-capable pin on the Pi 4 (BCM2711 PWM1), confirmed live as this board's fan pin with `scripts/test_gpio_hardware.py`; the onboard LED (GPIO 22) and user button (GPIO 27) were confirmed the same way.

Disabled by default: this fan/GPIO wiring is specific to the SenseCap M1 carrier board, not other supported hardware. Duty ramps linearly between `min_temp_c` and `max_temp_c`; below `min_temp_c - hysteresis_c` the fan turns fully off. If either dependency below is missing, a clear error is logged at startup and the fan is simply not driven rather than the app failing to start.

Requires `gpiozero` and `lgpio` in the Meshpoint **venv** specifically (both in `requirements.txt`, but a venv doesn't share Raspberry Pi OS's system-wide packages, so an existing install needs these added by hand — see `docs/TROUBLESHOOTING.md` for the full command chain, since `lgpio` builds a C extension and needs `python3-dev`/`swig`/`liblgpio-dev` first). Without `lgpio` (or `RPi.GPIO`/`pigpio`), gpiozero falls back to a pure-Python pin factory that refuses PWM on this board's repurposed GPIO13 (`PinPWMUnsupported`), even though it's a real PWM-capable pin on the Pi 4 SoC.

**`fan.enabled: false` does not hide CPU temperature.** The Radio/Hardware page's Thermals chart always shows a CPU temperature history — reading the SoC's own thermal zone has nothing to do with whether a PWM fan is physically wired up. With `fan.enabled: false` (RAK V2/Chameleon/DIY), a lightweight `CpuTempSampler` (`src/hardware/fan_control.py`) samples temperature on the same cadence a real `FanController` would, without touching GPIO at all; the chart's fan-duty panel simply doesn't render since there's no fan to report on. Only actual PWM driving (and the stat-bar Fan card) require `fan.enabled: true` on a board that has the hardware.

---

## Status LED (SenseCap M1)

```yaml
led:
  enabled: false        # opt-in -- same rationale as fan:
  gpio_pin: 22           # confirmed via scripts/test_gpio_hardware.py led
  activity_blink: true   # brief off-dip per captured packet
```

Drives the M1's onboard case LED as a glanceable status light with four states: **steady on** = service running and every configured capture source healthy (concentrator, MeshCore companions, Meshtastic USB sticks); **brief off-flicker** = a packet was just captured (set `activity_blink: false` for a calm steady light); **1 Hz blink** = one or more configured capture sources are down; **dark** = the service isn't running (when the process dies the kernel releases the GPIO line, so no watchdog is needed).

Plain on/off GPIO — no PWM involved, so unlike the fan it works even without `lgpio` (gpiozero's fallback pin factory handles simple output pins fine). Same venv note as the fan applies for `gpiozero` itself.

---

## User Button (SenseCap M1)

```yaml
button:
  enabled: false          # opt-in -- same rationale as fan:/led:
  gpio_pin: 27             # confirmed via scripts/test_gpio_hardware.py button-scan
  hold_time_s: 3.0         # hold this long to restart the service
  advert_cooldown_s: 30.0  # ignore further advert presses for this long
```

Gives the M1's case button two gestures. **Short press** announces this box on every TX-capable radio — the concentrator's Meshtastic NodeInfo, the MeshCore companion's advert, and each Meshtastic USB stick's own NodeInfo — serialized ~2 s apart, because the two 868 MHz signals overlap outright (Meshtastic 869.525/BW250 contains MeshCore 869.618/BW62.5) and simultaneous TX would jam both. LoRaWAN is deliberately excluded: the box is a pure listener there. A 30 s cooldown stops accidental advert spam. **Hold 3 s** restarts the meshpoint service — the recovery action you need exactly when the dashboard is unreachable; the required sudoers rule already ships and self-installs.

The status LED (when enabled) narrates: double-blink = advert sent, one long dark blink = press ignored (cooldown), fast blink while holding = restart warning, then the normal restart story (dark → steady) plays out. With the LED disabled the button still works, just silently. Booting with the button held (e.g. held straight through the restart it triggered) does nothing — a release must be seen first.

---

## Repeater Polling (MeshCore)

```yaml
repeater_poll:
  enabled: false
  interval_minutes: 30
  repeaters:
    - key: da0b77f13bc7        # public-key prefix (12 hex, == node_id)
      password: "your-password" # the repeater's login password
      # name: "PD2EMC"          # optional label; the real advertised
                                # name is used automatically otherwise
```

MeshCore nodes advertise identity only — no battery/uptime like Meshtastic broadcasts — so a repeater's stats have to be *asked for*. When enabled, Meshpoint periodically queries each listed repeater via the companion's `req_status`/`req_telemetry` (the same calls `meshcore-cli` and the phone app make) and shows the results on a **Repeaters** page (Radio group in the sidebar, only visible when polling is configured): battery, uptime, airtime, packet counters, noise floor, and LPP sensors (temperature/humidity/pressure). The charted fields (voltage, temperature, humidity, uptime) also land in the telemetry table, so they flow into the node drawer chart and CSV export.

This is **active two-way RF on a schedule** — the most chatty thing Meshpoint does — so it's off by default, polls sequentially with gaps, and only targets repeaters you have the login `password` for (required for `req_status`). Passwords stay in `local.yaml` and are never exposed by the API. Poll cadence is `interval_minutes` (floored at 5 in the dashboard; the raw config value has no floor); the first poll runs ~45 s after startup once the contact roster has loaded.

Edit all of this from **Configuration → Repeater Poll** — enable/disable, interval, and add/rename/remove repeaters (up to 8) without hand-editing `local.yaml`. Existing passwords are never sent back to the browser (the form only knows a password is *set*, not what it is); leave the password field blank when editing a repeater to keep its current password, or type a new one to replace it. Changes require a restart to take effect, same as the fan/LED/button peripherals.

Each poll also asks the repeater for its own neighbour list (`req_neighbours`) and writes it into the database — a placeholder node per reported pubkey (never overwrites an already-known name/role/position) plus a synthetic packet tagged `nb:<repeater_key>:<node_id>:<timestamp>`, the same convention `scripts/import_contacts.py`'s manual `neighbours.json` import uses, just live. `last_heard` only ever moves forward relative to a genuinely-captured packet — a stale secondhand report can never un-freshen a node heard more recently some other way — and none of this counts toward `packet_count` (Meshpoint's own radio didn't receive it). The Health card gains a **Farthest neighbour** stat per repeater, distance measured from *that repeater's own position* (not Meshpoint's — a repeater can be a remote site with its own local RF picture). These `nb:`-tagged rows are deliberately excluded from the Stats page's "Farthest Direct Signal", which reports only what Meshpoint's own antenna heard directly.

---

## Automatic Update Checks

```yaml
update_check:
  enabled: true          # on by default -- a read-only network check
  interval_minutes: 60    # floored at 5 -- each check is a real `git fetch`
```

Periodically checks GitHub for a newer version in the background, reusing the *exact same* `git fetch` + commits-behind logic as the "Check for updates" button on Settings → Updates — the sidebar badge and the button always agree on whether an update is available, since it's the same check, just run on a timer versus on demand. Server-side and config-driven, not per-browser: every client sees the same state, and it survives restarts.

When an update is found, an "Update available" pill appears right under the device name/status at the top of the sidebar — visible on any page, no need to expand Settings first. Click it to jump straight to Settings → Updates. Clicking "Check for updates" manually also refreshes this pill immediately, as long as you're checking your actual installed channel (not a different channel/custom branch from the picker — that wouldn't reflect what's really installed, so it's excluded from updating the pill). Edit both fields from Settings → Updates directly; changes require a restart to take effect, same as the fan/LED/button peripherals.

---

## Prometheus Metrics

```yaml
metrics:
  enabled: false        # off by default
  require_auth: true    # gate the endpoint behind a valid dashboard session
```

Exposes a `/metrics` endpoint in standard Prometheus text format (uptime, packet counts by protocol, RSSI/SNR averages, node counts). Purely passive — Meshpoint never sends this anywhere; a Prometheus server you run elsewhere would *scrape* (periodically fetch) this URL on its own schedule.

`require_auth` gates the endpoint behind the browser's session cookie, a session `Authorization: Bearer <jwt>` header, **or** a named API key generated from Configuration → Metrics — those are the long-lived credential for unattended scrapers (Home Assistant, Prometheus) that a login session can't provide. Each key is scoped to `/metrics`, `/api/device/metrics`, and `/api/stats/summary` — a small fixed allowlist, not general dashboard access — and is revocable individually. Turning `require_auth` off instead makes the endpoint fully open to anyone who can reach it on the network; it only ever exposes aggregate stats, never credentials or channel keys. See [Prometheus metrics (`/metrics`)](#prometheus-metrics-metrics) above for the API key workflow and an example Home Assistant sensor.

Edit both fields, and manage API keys, from **Configuration → Metrics**. Unlike most config pages, changes here apply immediately — `metrics_routes.py` reads the config fresh on every request, so no restart is needed.

### Available metrics

| Metric | Type | Description |
|---|---|---|
| `meshpoint_uptime_seconds` | gauge | Seconds since the metrics collector started |
| `meshpoint_info{version,region}` | gauge | Build info (always `1`) |
| `meshpoint_packets_session_total` | counter | Decoded packets since last heartbeat reset |
| `meshpoint_packets_per_minute` | gauge | Session packet rate |
| `meshpoint_protocol_packets_session_total{protocol}` | counter | Session packets by protocol (`meshtastic`/`meshcore`/`lorawan`) |
| `meshpoint_rssi_average_dbm` | gauge | Average RSSI over session samples |
| `meshpoint_snr_average_db` | gauge | Average SNR over session samples |
| `meshpoint_packets_direct_session_total` | counter | Direct (0-hop) packets in session |
| `meshpoint_packets_relayed_session_total` | counter | Relayed (1+ hop) packets in session |
| `meshpoint_packets_database_total` | counter | Total packets stored in SQLite |
| `meshpoint_packets_last_hour` | gauge | Packets received in the last hour |
| `meshpoint_packets_last_minute` | gauge | Packets received in the last minute |
| `meshpoint_rssi_recent_average_dbm` | gauge | Average RSSI over the 200 most recent packets |
| `meshpoint_snr_recent_average_db` | gauge | Average SNR over the 200 most recent packets |
| `meshpoint_nodes_total` | gauge | Known nodes in the local database |
| `meshpoint_nodes_active_24h` | gauge | Nodes heard in the last 24 hours |
| `meshpoint_noise_floor_dbm{source}` | gauge | Estimated noise floor (dBm) |
| `meshpoint_noise_floor_stale` | gauge | `1` when the noise-floor estimate is stale |
| `meshpoint_relay_enabled` | gauge | `1` when experimental relay is enabled |
| `meshpoint_relay_relayed_total` | counter | Packets relayed since process start |
| `meshpoint_relay_rejected_total{reason}` | counter | Packets rejected by relay filters, broken down by reason |
| `meshpoint_relay_rate_per_minute` | gauge | Current relay rate |
| `meshpoint_relay_rate_remaining` | gauge | Remaining relay capacity in the current window |
| `meshpoint_relay_duty_usage_percent` | gauge | Aggregate relay duty usage (ToA estimate) |
| `meshpoint_relay_duty_channel_usage_percent{channel}` | gauge | Per-channel relay duty usage (ToA estimate) |
| `meshpoint_rx_crc_bad_total` | counter | SX1302 CRC_BAD frames since concentrator start |
| `meshpoint_rx_no_crc_total` | counter | SX1302 NO_CRC frames since concentrator start |

Any metric backed by a component that isn't running (e.g. no relay configured, no concentrator) is simply omitted from the response rather than reported as zero.

### Connecting a Prometheus server

Add a scrape job to your Prometheus server's own `prometheus.yml` (not Meshpoint's config) — alongside its default self-scrape job:

```yaml
scrape_configs:
  - job_name: "prometheus"
    static_configs:
      - targets: ["localhost:9090"]
        labels:
          app: "prometheus"

  - job_name: "meshpoint"
    scrape_interval: 30s
    static_configs:
      - targets: ["192.168.2.189:8080"]   # your Pi's IP:port
        labels:
          app: "meshpoint"
```

Then reload Prometheus to pick up the change — either `curl -X POST http://localhost:9090/-/reload` (only works if Prometheus was started with `--web.enable-lifecycle`) or a plain service restart (`systemctl restart prometheus`, or the equivalent for however it's run). Check **Status → Targets** in the Prometheus UI for the `meshpoint` job showing `UP`, then query e.g. `meshpoint_nodes_total` or `rate(meshpoint_packets_database_total[5m])` to confirm data is flowing.

If you leave `require_auth: true`, Prometheus needs to authenticate on every scrape — either the `Authorization: Bearer <session-jwt>` header, or nothing works and every scrape 401s. Since dashboard session tokens expire, this isn't practical for an unattended scrape config in most setups; `require_auth: false` is the realistic choice for actually running this, and the endpoint never exposes credentials or channel keys regardless.

---

## Plugins

App plugins are out-of-core features (an extra listener + its API routes + a
dashboard tab) that live in `plugins/apps/<id>/` and are loaded at startup — but
**only if you explicitly enable them**. An in-process plugin runs with the same
privileges as the Meshpoint service, so installing one is equivalent to running
its code on your device; loading is opt-in, never automatic.

```yaml
plugins:
  acars:                 # <id> = the plugin's folder name under plugins/apps/
    enabled: true        # default false — the loader skips a plugin that isn't
                         # enabled here (it's still listed in the logs as
                         # "found but not enabled")
    # everything else under plugins.<id> is the plugin's own config —
    # frequencies, gain, RTL device, etc. Meshpoint stores it verbatim and
    # hands it to the plugin; it is never checked against the core schema, so
    # a typo here won't show up in the "unknown config key" warning.
    freqs: [131.525, 131.725, 131.800, 131.825]
    gain: 34
```

A plugin folder holds a `plugin.toml` manifest (`name`, `version`,
`meshpoint_api`, `provides`, optional `[deps]` for apt packages / a `setup.sh`
build script, optional `[meta]`). A manifest that targets a newer `meshpoint_api`
than this build supports, or is otherwise invalid, is logged and skipped rather
than loaded. Any system dependencies a plugin needs (`[deps]`) are **not**
installed automatically — run the plugin's setup step yourself first.

## Device Identity

```yaml
device:
  device_name: "My Meshpoint"
  latitude: 40.7128
  longitude: -74.0060
  altitude: 25
```

Set during the setup wizard. The coordinates are used for map placement on the local dashboard and the Meshradar cloud dashboard, and as the reference point for "farthest direct node" distance.

### Updating Location

Three options:

1. **Configuration → GPS** in the dashboard (recommended). Edit lat/lon/alt for `source: static`, or switch to `source: gpsd` to consume live fixes from a USB GPS receiver. See [Location (GPS) source](#location-gps-source) above.

2. Edit `local.yaml` directly (fastest for headless tweaks):

   ```bash
   sudo nano /opt/meshpoint/config/local.yaml
   # change device.latitude / device.longitude / device.altitude
   sudo systemctl restart meshpoint
   ```

3. Re-run the setup wizard and press Enter through steps you want to keep:

   ```bash
   sudo /opt/meshpoint/venv/bin/python -m src.cli setup
   sudo systemctl restart meshpoint
   ```

**Tip**: in Google Maps, right-click any location and click the coordinates at the top of the menu to copy them in decimal format (e.g. `40.7128, -74.0060`).

---

## MQTT Feed

Publish captured packets to community MQTT brokers (meshmap.net, NHmesh.live, etc.) and Home Assistant. The Meshpoint acts as a dual-protocol MQTT gateway: both Meshtastic and MeshCore traffic can be published from a single device.

### Privacy: Two-Gate Safety Model

MQTT publishing uses two independent safety gates to prevent accidental exposure of private data:

**Gate 1: Global kill switch.** MQTT is off by default. You must explicitly set `mqtt.enabled: true` to activate publishing. Nothing is ever sent to any MQTT broker unless you opt in.

**Gate 2: Channel allowlist.** Only packets from channels listed in `publish_channels` are published. The default list contains only `LongFast` (the standard Meshtastic public channel). Private channels, custom PSK channels, and encrypted packets are never published unless you deliberately add that channel name to the list.

Both gates must pass for any packet to leave the device via MQTT. Encrypted packets (those the Meshpoint could not decrypt) are always blocked regardless of channel configuration.

This two-gate approach is informed by active community discussion around MQTT privacy, including the need for explicit opt-in controls ([meshtastic/firmware#5507](https://github.com/meshtastic/firmware/issues/5507)), concerns about private channel data leaking via MQTT gateways ([meshtastic/firmware#5404](https://github.com/meshtastic/firmware/issues/5404)), and the broader push for user-controlled MQTT publishing ([meshtastic/firmware#3549](https://github.com/meshtastic/firmware/issues/3549)).

### Basic Setup

```yaml
mqtt:
  enabled: true
  broker: "mqtt.meshtastic.org"
  port: 1883
  username: "meshdev"
  password: "large4cats"
  region: "US"
  publish_channels:
    - "LongFast"
```

This publishes standard Meshtastic and MeshCore traffic to the community broker. Your Meshpoint appears on community maps (meshmap.net, Liam Cottle, NHmesh) with a unique gateway ID that integrates natively with the Meshtastic ecosystem.

### Configuration Options

```yaml
mqtt:
  enabled: false                 # Gate 1: must be true to publish
  broker: "mqtt.meshtastic.org"  # broker hostname
  port: 1883                     # broker port
  username: "meshdev"            # broker credentials
  password: "large4cats"
  topic_root: "msh"             # MQTT topic prefix
  region: "US"                   # used in topic path
  publish_channels:              # Gate 2: only these channels are published
    - "LongFast"
  publish_json: false            # also publish JSON on /json/ topic
  location_precision: "exact"    # exact | approximate | none
  homeassistant_discovery: false # publish HA auto-discovery configs
  map_reporting_enabled: false            # publish to the official Meshtastic map (opt-in)
  map_report_interval_seconds: 3600       # minimum 3600 (Meshtastic's own minimum)
  map_report_position_precision: 14       # 12 (least precise) - 15 (most precise)
```

### Transport TLS (not yet available)

Configuration → MQTT does **not** expose TLS/mqtts settings yet. The publisher
uses plain TCP; port **8883** alone does not enable encryption.

**Planned:** ship broker TLS (`tls_enabled`, optional CA file) in the same
update as **Meshtastic PKI** (see `ROADMAP.md` in the private repo). Until
then:

- Public Meshtastic MQTT: `mqtt.meshtastic.org` on port **1883** (default).
- Private TLS brokers: wait for that release, or terminate TLS on a local
  reverse proxy in front of a plain MQTT listener.

This is separate from **packet privacy**: undecrypted LoRa packets are never
published to MQTT regardless of transport settings.

### Location Precision

Control how much location detail leaves the device via MQTT:

| Value | Behavior |
|---|---|
| `exact` | Full GPS coordinates (default) |
| `approximate` | Rounded to ~2 decimal places (about 0.7 mi / 1.1 km; Configuration → MQTT and GPS labels follow Settings → Meshpoint distance units) |
| `none` | Location stripped entirely from MQTT messages |

Full-precision location data is always available on the [Meshradar](https://meshradar.io) dashboard regardless of this setting.

### Official Meshtastic Map

The MQTT gateway above republishes packets *heard from other nodes*. This is separate: it publishes the Meshpoint's *own* identity onto the official Meshtastic map (a public, unencrypted MQTT `MapReport`, no LoRa airtime used). Off by default; requires `mqtt.enabled: true` and configured `device.latitude`/`device.longitude`/`transmit.node_id`.

```yaml
mqtt:
  enabled: true
  map_reporting_enabled: true
  map_report_interval_seconds: 3600   # minimum 3600, matching Meshtastic's own minimum
  map_report_position_precision: 14   # 12 (least precise) - 15 (most precise)
```

See [MQTT-AND-MESHRADAR.md](MQTT-AND-MESHRADAR.md#official-meshtastic-map) for details.

### Home Assistant Integration

Enable JSON publishing and HA auto-discovery to automatically create sensors in Home Assistant for battery level, temperature, and GPS position of mesh nodes:

```yaml
mqtt:
  enabled: true
  publish_json: true
  homeassistant_discovery: true
```

HA sensors appear as `sensor.meshpoint_<node_id>_battery`, `sensor.meshpoint_<node_id>_temperature`, and `device_tracker.meshpoint_<node_id>`.

### Publishing Private Channels

If you want to publish traffic from a private channel (for example, to feed it into your own HA instance on a local broker), add the channel name to `publish_channels` and point the broker to your local MQTT server:

```yaml
mqtt:
  enabled: true
  broker: "192.168.1.100"        # your local broker
  username: ""
  password: ""
  publish_channels:
    - "LongFast"
    - "MyPrivateChannel"         # explicitly opted in
```

Never add private channel names when publishing to a public broker.

---

## Full Default Config

See [config/default.yaml](../config/default.yaml) for all available settings and their defaults.

---

## Quick Reference: All Sections

A flat overview of every top-level section in `local.yaml`. Use this as a checklist when assembling a custom config.

```yaml
device:                # name, location (mostly wizard-managed)
  device_id: null
  device_name: "My Meshpoint"
  latitude: null
  longitude: null
  altitude: null

radio:                 # LoRa physical layer
  region: "US"
  frequency_mhz: 906.875
  spreading_factor: 11
  bandwidth_khz: 250.0
  coding_rate: "4/5"
  sync_word: 0x2B
  preamble_length: 16
  tx_power_dbm: 22
  spectral_scan_interval_seconds: 60   # noise floor sampler; 0 disables
  sx1261_spi_path: ""                  # SX1261 SPI device for hardware spectral scan (empty = packet fallback)
  spectrum_sweep_interval_seconds: 300 # band-sweep cadence for the spectrum card; 0 = on-demand only
  pager_enabled: false                 # emergency pager project (EU868 only); off by default
  pager_frequency_mhz: 869.4625
  pager_sync_word: 0x946437
  pager_sync_word_size: 3
  pager_rf_chain: 1                    # not exposed in the UI, see src/config.py
  pager_capcode: 0                     # this device's own POCSAG-style capcode; 0 = unset

meshtastic:            # Meshtastic protocol settings
  primary_channel_name: "LongFast"
  default_key_b64: "1PG7OiApB1nwvP+rz05pAQ=="
  channel_keys: {}
  decode_timeout_ms: 100

meshcore:              # MeshCore protocol settings
  default_key_b64: null
  channel_keys: {}
  companion_name: null  # Legacy, pre-v0.7.7: fallback name for the FIRST companion only.
                        # New setups should use capture.meshcore_usb[i].companion_name below.

capture:               # what packet sources to read from
  sources:
    - concentrator
    - meshcore_usb
    # - serial           # optional: Meshtastic node on USB (e.g. 433 MHz)
  rtl_sdr_page_enabled: true  # shows/hides the RTL-SDR sidebar page; UI-only, no dongle required
  meshcore_usb:          # list — up to 4 companions, each with a label
    - serial_port: null  # null + auto_detect finds /dev/ttyACM*
      baud_rate: 115200
      auto_detect: true
      label: ""
      companion_name: null  # Optional, per-companion. When set, re-applied on every USB reconnect.
  serial_port: "/dev/ttyUSB0"   # single-stick `serial` source (legacy)
  serial_baud: 115200
  serial: []             # OR: list of devices for multiple Meshtastic USB sticks
    # - serial_port: "/dev/ttyUSB0"
    #   label: "433"
    # - serial_port: "/dev/ttyUSB1"
    #   label: "868"

location:              # GPS / location source
  source: "static"            # static | gpsd | uart
  gpsd_host: "127.0.0.1"
  gpsd_port: 2947
  update_interval_seconds: 5
  min_fix_quality: 1

transmit:              # native messaging TX (Meshtastic via SX1302, MeshCore via USB)
  enabled: false
  node_id: null
  tx_power_dbm: 14
  # max_duty_cycle_percent omitted: auto-derives from radio.region
  long_name: "Meshpoint"
  short_name: "MPNT"
  hop_limit: 3
  position:
    interval_minutes: 15
    coordinate_source: "static"      # static | live
    location_precision: "approximate"  # exact | approximate | none (live only)
  telemetry:
    interval_minutes: 30
    startup_delay_seconds: 120

relay:                 # experimental: re-broadcast captured packets via USB radio
  enabled: false
  serial_port: "/dev/ttyACM1"
  serial_baud: 115200
  max_relay_per_minute: 20
  burst_size: 5
  min_relay_rssi: -110.0
  max_relay_rssi: -50.0

upstream:              # cloud (Meshradar) connection
  enabled: true
  url: "wss://api.meshradar.io"
  reconnect_interval_seconds: 10
  buffer_max_size: 5000
  auth_token: null     # required at startup, set by setup wizard

mqtt:                  # MQTT publishing (off by default)
  enabled: false
  broker: "mqtt.meshtastic.org"
  port: 1883
  username: "meshdev"
  password: "large4cats"
  topic_root: "msh"
  region: "US"
  publish_channels:
    - "LongFast"
  publish_json: false
  location_precision: "exact"
  homeassistant_discovery: false

storage:               # local SQLite packet store
  database_path: "data/concentrator.db"
  max_packets_retained: 100000
  max_telemetry_retained: 100000
  cleanup_interval_seconds: 3600

metrics:               # Prometheus /metrics scrape (off by default)
  enabled: false
  require_auth: true

dashboard:             # local web UI
  host: "0.0.0.0"
  port: 8080
  static_dir: "frontend"
```

You only need to put the keys you want to override into `local.yaml`. Every key omitted from `local.yaml` falls back to the value in `config/default.yaml`.
