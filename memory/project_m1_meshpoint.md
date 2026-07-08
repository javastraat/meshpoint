# Project M1 — Sensecap M1 Mega-Sniffer (5 networks)

## What we built

A 5-network passive sniffer on the Sensecap M1 (SX1302 concentrator).
It listens simultaneously to LoRaWAN, Meshtastic, and MeshCore on 433 and 868 MHz.
Meshtastic packets are relayed. LoRaWAN and MeshCore are listen-only.
The codebase lives in `meshpoint_lorawan/`.

---

## Hardware

| Device | Protocol | Band | Interface |
|---|---|---|---|
| Sensecap M1 (SX1302) | LoRaWAN + Meshtastic | 868 MHz | onboard |
| Heltec V3 868 MHz (~€21) | MeshCore | 868 MHz | USB `/dev/ttyACM0` |
| Heltec V3 433 MHz (~€22.75) | MeshCore | 433 MHz | USB `/dev/ttyACM1` |
| Heltec V3 433 MHz (owned) | Meshtastic | 433 MHz | USB `/dev/ttyUSB0` |
| 868 MHz tags | MeshCore | 868 MHz | over-air via Heltec 868 |
| P1 SolarNode | MeshCore | 868 MHz | over-air via Heltec 868 |
| 2nd Heltec V3 433 MHz | TBD / play | 433 MHz | standalone |

### Hardware notes
- Heltec V3: flash with `companion_radio_usb` MeshCore firmware from flasher.meshcore.io
- Heltec V4 USB gotcha: MeshCore enumerates as `303a:0002`, Meshtastic as `303a:1001` — opposite of expected
- Heltec V3 for Meshtastic 433: flash with Meshtastic EU_433 firmware, connect via `serial` source (NOT `meshcore_usb`)

---

## 5 networks at once

| # | Protocol | Band | Source in code |
|---|---|---|---|
| 1 | LoRaWAN | 868 MHz | SX1302 (`concentrator`) |
| 2 | Meshtastic | 868 MHz | SX1302 (`concentrator`) |
| 3 | MeshCore | 868 MHz | Heltec V3 USB (`meshcore_usb` label=868) |
| 4 | MeshCore | 433 MHz | Heltec V3 USB (`meshcore_usb` label=433) |
| 5 | Meshtastic | 433 MHz | Heltec V3 USB (`serial`) |

---

## Architecture

```
SX1302 concentrator (8 ch)
  ├── ch0-ch4  → EU868 LoRaWAN 125 kHz  (867.9 / 868.1 / 868.3 / 868.5 / 868.7 MHz)  syncword 0x34
  ├── ch5-ch7  → disabled (RF1 multi-SF can't reach either protocol without breaking ch8)
  └── ch8      → Meshtastic EU868 250 kHz SF11 (869.525 MHz)            syncword 0x2B

USB companion 1  (Heltec V3 868 MHz)    /dev/ttyACM0  label "868"  → MeshCore protocol
USB companion 2  (Heltec V3 433 MHz)    /dev/ttyACM1  label "433"  → MeshCore protocol
USB companion 3  (Heltec V3 433 MHz)  /dev/ttyUSB0               → Meshtastic serial (protobuf)

CaptureCoordinator (async, shared queue)
  → PacketRouter → LoRaWAN decoder | Meshtastic decoder | MeshCore decoder
  → DatabaseManager
  → RelayManager   (Meshtastic only — LoRaWAN and MeshCore never relayed)
  → WebSocket / REST API / MQTT publisher
```

---

## CRITICAL: MeshCore USB vs Meshtastic serial — two different protocols

**`meshcore_usb` source** — for Heltec/T-Beam running MeshCore firmware:
- Speaks MeshCore serial event format (proprietary)
- Use for: Heltec V3, T-Beam, Wireless Tracker with MeshCore `companion_radio_usb` firmware
- Config key: `capture.meshcore_usb` (list, up to 4)

**`serial` source** — for Heltec V3/any device running Meshtastic firmware:
- Speaks Meshtastic serial protocol (protobuf)
- Use for: Heltec V3, any Meshtastic node connected via USB
- Config key: `capture.serial_port` + `capture.serial_baud`

You CANNOT use `meshcore_usb` for a Meshtastic device — it will read garbage.
You CANNOT use `serial` for a MeshCore device — it will read garbage.

---

## local.yaml (full 5-network config)

```yaml
capture:
  sources:
    - concentrator      # SX1302: LoRaWAN + Meshtastic 868
    - meshcore_usb      # Heltec sticks: MeshCore 868 + 433
    - serial            # Heltec V3: Meshtastic 433
  serial_port: "/dev/ttyUSB0"   # Heltec V3 Meshtastic 433
  serial_baud: 115200
  meshcore_usb:
    - serial_port: "/dev/ttyACM0"
      label: "868"
    - serial_port: "/dev/ttyACM1"
      label: "433"
```

---

## Key technical solutions

### Dual sync word on SX1302

SX1302 has one global syncword register set but the service channel (ch8) has
its own pair of registers that can be overridden independently.

**Solution:**
1. Set `lorawan_public = True` → `lgw_start()` programs ch0–ch7 to LoRaWAN 0x34 (PEAK1=6, PEAK2=8).
2. After `lgw_start()`, call `lgw_reg_w()` on registers 932/933 only (service channel) to set Meshtastic 0x2B (PEAK1=4, PEAK2=22).

**Register IDs:**
- `SX1302_REG_RX_TOP_LORA_SERVICE_FSK_FRAME_SYNCH0_PEAK1_POS = 932`
- `SX1302_REG_RX_TOP_LORA_SERVICE_FSK_FRAME_SYNCH0_PEAK2_POS = 933`

**Formula:** `PEAK = 2 × nibble`
- 0x34 → PEAK1=6, PEAK2=8
- 0x2B → PEAK1=4, PEAK2=22

**Files:** `src/hal/sx1302_signatures.py`, `src/hal/sx1302_wrapper.py`

### EU868 channel plan

RF0 = 868.3 MHz, RF1 = 869.525 MHz

**Correction (superseded the original plan below the line):** ch0-ch7 (multi-SF)
share ONE board-wide syncword register set — `lorawan_public=True` locks all of
them to 0x34 at `lgw_start()`, with no per-channel override. Only ch8 (service
channel) can be set independently via direct register writes. That means a
multi-SF channel can **never** decode Meshtastic (0x2B) regardless of which
frequency it's tuned to — the original plan's ch3/ch4 "Meshtastic 0x2B" row
below was never actually true; those channels only ever listened with 0x34 and
caught nothing, since no LoRaWAN traffic exists at 869.4625/869.5875 MHz.

Fixed plan: RF0 uses its full ±400 kHz IF window (867.9-868.7 MHz) for 5 real
LoRaWAN channels instead of 3, and the dead RF1 multi-SF slots are disabled
instead of pointed at frequencies they could never usefully receive.

| ch | Freq (Hz) | BW | SF | Syncword | Protocol |
|---|---|---|---|---|---|
| 0 | 867_900_000 | 125k | 7-12 | 0x34 | LoRaWAN |
| 1 | 868_100_000 | 125k | 7-12 | 0x34 | LoRaWAN |
| 2 | 868_300_000 | 125k | 7-12 | 0x34 | LoRaWAN |
| 3 | 868_500_000 | 125k | 7-12 | 0x34 | LoRaWAN |
| 4 | 868_700_000 | 125k | 7-12 | 0x34 | LoRaWAN (RF0 IF edge, +400 kHz — unverified in field) |
| 5-7 | — | — | — | — | disabled |
| 8 | 869_525_000 | 250k | SF11 | 0x2B | Meshtastic (service ch, only real Meshtastic path) |

`concentrator_config.py` → `eu868_lorawan()` static method, used by `for_region("EU_868")`.

### Protocol routing by frequency

`concentrator_source.py`:
```python
_MESHTASTIC_EU868_FREQS_HZ = frozenset({869_525_000})
protocol_hint = Protocol.MESHTASTIC if pkt.frequency_hz in _MESHTASTIC_EU868_FREQS_HZ else Protocol.LORAWAN
```

### ch8 (service channel) always on RF1 — bug that was fixed

`_configure_if_channels()` hardcoded `rf_chain = 0` for the single-SF channel.
With RF0=868.3 MHz and ch8=869.525 MHz, ch8 physically belongs to RF1.

Fix in `sx1302_wrapper.py`:
```python
conf.rf_chain = 0 if ch.frequency_hz <= radio_0_freq + 500_000 else 1
center = radio_0_freq if conf.rf_chain == 0 else plan.radio_1_freq_hz
```

---

## LoRaWAN support

### Model types (`src/models/packet.py`)
- `Protocol.LORAWAN`
- `PacketType.LORAWAN_JOIN`, `LORAWAN_DATA`, `LORAWAN_REJOIN`

### LoRaWAN decoder (`src/decode/lorawan_decoder.py`)

| MType | Frame | Fields extracted |
|---|---|---|
| 000 | Join-Request | AppEUI (LSB), DevEUI (LSB), DevNonce, MIC |
| 010/100 | Data Up | DevAddr, FCnt, FPort, FRMPayload (hex, encrypted), MIC |
| 110 | Rejoin | Type 0/1/2 with appropriate EUI/ID fields |

- `source_id` = DevEUI (join) or DevAddr hex (data)
- Payload NOT decrypted (no AppSKey/NwkSKey)

### Relay safety (double protection)
1. `hop_limit = 0` default on all LoRaWAN packets
2. `PacketType.LORAWAN_*` not in `RELAY_WORTHY_TYPES`

LoRaWAN is **never** relayed.

### LoRaWAN isolation from node system (`src/coordinator.py`)
- `_update_node()` early-returns for `Protocol.LORAWAN` — DevAddrs never appear as mesh nodes
- `_store_telemetry()` early-returns for `Protocol.LORAWAN`

### Routing order in PacketRouter
LORAWAN checked **first** before MESHTASTIC to avoid false positives.

---

## Multi USB companion support (MeshCore)

### Config (`src/config.py`)
- `MeshcoreUsbConfig` has `label: str = ""` field
- `CaptureConfig.meshcore_usb` is `list[MeshcoreUsbConfig]` (was single object)
- `_coerce_meshcore_usb()` accepts old dict format OR new list-of-dicts — backward compat
- Source name: `meshcore_usb_{label}` when label set (e.g. `meshcore_usb_868`)

### API endpoints
- `PUT /api/config/capture/meshcore-usb` — edits companion[0] only (backward compat)
- `PUT /api/config/capture/meshcore-companions` — replaces full list atomically (max 4)

### Bug fixed in server.py
`_add_meshcore_usb_source()` and the auto-detect check in `_build_pipeline()` were
still treating `meshcore_usb` as a single object. Fixed to loop over the list.

---

## LoRaWAN UI (dashboard page)

### Backend (`src/api/routes/lorawan_routes.py`)
- `GET /api/lorawan/devices` — one row per DevEUI/DevAddr: frame_count, first_seen, last_seen, RSSI, SNR, freq, SF
- `GET /api/lorawan/packets` — recent packets log (limit param, max 1000)
- `GET /api/lorawan/stats` — totals: total_packets, unique_devices, by_type counts

### Frontend
- `frontend/js/lorawan_panel.js` — `LoRaWANPanel` class, show/hide with auto-refresh (15s)
- `frontend/css/lorawan.css` — panel styles, type badges (Join=green, Data=cyan, Rejoin=amber)
- `index.html` — sidebar nav item + `data-section="lorawan"` section
- `app.js` — `_bootLoRaWANPanel(router)`, `'lorawan'` added to `allowedRoutes`

---

## Files changed / created

| File | Change |
|---|---|
| `src/models/packet.py` | Added `Protocol.LORAWAN`, `PacketType.LORAWAN_*` |
| `src/hal/concentrator_config.py` | Added `eu868_lorawan()`, updated `for_region("EU_868")` |
| `src/hal/sx1302_signatures.py` | Added `lgw_reg_w` ctypes signature |
| `src/hal/sx1302_wrapper.py` | `lorawan_public=True`; `set_syncword()` via reg 932/933; ch8 RF chain fix |
| `src/capture/concentrator_source.py` | Protocol hint by frequency |
| `src/decode/lorawan_decoder.py` | **NEW** — full LoRaWAN MAC frame parser |
| `src/decode/packet_router.py` | Added LoRaWAN decoder, LORAWAN branch first |
| `src/coordinator.py` | LoRaWAN isolation; startswith fix for labelled companions |
| `src/config.py` | `label` on `MeshcoreUsbConfig`; list field; `_coerce_meshcore_usb` |
| `src/capture/meshcore_usb_source.py` | `label` param, named `name` property |
| `src/main.py` | Loop over companion list |
| `src/api/server.py` | Fixed multi-companion bug; added `lorawan_routes` |
| `src/api/routes/lorawan_routes.py` | **NEW** — LoRaWAN API endpoints |
| `src/api/routes/config_enrichment.py` | Full list + primary compat in GET /api/config |
| `src/api/routes/system_config_routes.py` | `CompanionEntry`, `MeshcoreCompanionsUpdate`, new PUT endpoint |
| `frontend/js/lorawan_panel.js` | **NEW** — LoRaWAN dashboard panel |
| `frontend/css/lorawan.css` | **NEW** — LoRaWAN panel styles |
| `frontend/js/configuration/meshcore_card.js` | Dynamic multi-companion USB section |
| `frontend/css/configuration.css` | Companion card styles |
| `frontend/index.html` | LoRaWAN nav + section + CSS/JS links |
| `frontend/js/app.js` | `_bootLoRaWANPanel`, `lorawan` in allowedRoutes |
| `config/local.yaml` | Two MeshCore companions: 868 @ ACM0, 433 @ ACM1 |

---

## MeshCore signal metadata: freq / SF / hops (2026-07-05)

MeshCore packets come from a USB companion radio, not the onboard SX1302, so
their per-packet metadata is different from Meshtastic/LoRaWAN captures.

### Frequency / SF — static per companion, read from handshake
The `meshcore` library's event stream only carries RSSI/SNR per packet, NOT
freq/SF (those are static radio config, not per-packet telemetry). They live on
`self._meshcore.self_info` (keys `radio_freq` / `radio_bw` / `radio_sf`),
populated once at connect-time handshake — the same object the Config > MeshCore
page reads via `get_radio_info()`.

- **Fix:** `_wrap_event()` in `src/capture/meshcore_usb_source.py` now reads
  `self._meshcore.self_info` and passes it to `_extract_signal(payload, radio_info)`,
  which stamps freq/BW/SF instead of the old hardcoded `0.0`/`0`. Downstream
  `_rf_signal_from_payload()` in `src/decode/meshcore_event_adapter.py` was also
  re-zeroing these — fixed to preserve the fallback SignalMetrics.
- **Multi-companion:** value is per-instance (each companion's own `self_info`),
  so an 868 vs 433 stick each report their real channel independently.

### Hops — from path_len, was never read
CONTACT_MSG_RECV / CHANNEL_MSG_RECV events carry `path_len` = real hop count
(verified in the `meshcore` PyPI package `reader.py`; cross-checked against
firmware `MeshCore/src/Packet.h`). ADVERTISEMENT/nodeinfo events do NOT carry
path info — those stay blank by design.

- **Fix:** `_hop_start_from_payload()` in `meshcore_event_adapter.py` converts
  `path_len` → `hop_start` (255 is the firmware's "direct message" sentinel → 0
  hops, not a literal 255). `_build_contact_message` / `_build_channel_message`
  now set it. hop_limit stays 0 so the existing `hop_count` property returns
  path_len unchanged.

### capture_source now carries the companion label
`_wrap_event()` stamps `capture_source=self.name` (was hardcoded
`"meshcore_usb"`), so labelled companions store `meshcore_usb_868` /
`meshcore_usb_433` etc. Only matcher is the coordinator's
`startswith("meshcore_usb")`, which all variants satisfy. (The Meshtastic
`serial` source is still single-instance / unlabelled — would need a list-field
config change to support `meshtastic_usb_*`.)

## Imported-contacts / neighbours workflow (`import_contacts.py` in repo ROOT)

There are TWO import scripts: `meshpoint_lorawan/import_contacts.py` (older,
nodes-only) and the ROOT `import_contacts.py` (newer, imports contacts AND
neighbours, and inserts synthetic `neighbour_advert` packet rows with
`packet_id` prefix `nb:<node>:<ts>` to surface neighbour SNR in panels).

- **Synthetic rows now stamp freq/SF/BW** (defaults 869.618 / SF8 / 62.5 kHz,
  overridable via `--freq/--sf/--bw`) so they display like real captures and
  each re-import doesn't re-blank them. (Still show blank RSSI/FREQ/SF in the
  packet feed — they only carry SNR; cosmetic, not yet addressed.)
- **Canonical refresh order (`importcontacts.sh`): import → repair → backfill.**
  1. `sudo python3 import_contacts.py --freq 869.618 --sf 8 --bw 62.5`
  2. `sudo python3 meshpoint_lorawan/scripts/repair_neighbour_timestamps.py --apply`
  3. `sudo python3 meshpoint_lorawan/scripts/backfill_meshcore_signal.py --apply`

### Timestamp saga (root causes + fixes, 2026-07-05)
The `nb:` synthetic rows and each node's `nodes.last_heard` were landing at
wrong times in BOTH directions. Three distinct causes, all now fixed in the
ROOT `import_contacts.py`:

1. **Past (2024) rows → "777 days since first packet".** Some neighbours report
   a stale/absent `last_advert`; old rows sorted `MIN(timestamp)` to 2024.
2. **Future rows → node pinned to top as "Now".** ROOT CAUSE: the
   `neighbours.json` **generator machine writes Amsterdam local time (CEST,
   UTC+2) in its `generated` field with no timezone marker**. Parsed as UTC it
   is ~2h ahead, so `generated - secs_ago` (and the nodes' own fast RTCs via
   `last_advert`) produced future timestamps.
   FIX: compute `last_heard = now - secs_ago`, anchoring `secs_ago` (a reliable
   RELATIVE measure) to **our own trusted clock**, never the file's skewed
   `generated` field or the node's `last_advert`. Immune to both skews. Fall
   back to `last_advert` only when `secs_ago` is absent; `_clamp_future()` is a
   final safety net.
3. **Sticky poison.** `nodes.last_heard` sorts the node list and the upsert
   only ever RAISED it, so a once-poisoned high value (future / clamp-to-now)
   could never be corrected down.
   FIX: neighbour upsert is now AUTHORITATIVE, floored at real packets:
   `last_heard = MAX(excluded.last_heard, latest real captured packet)`.
   Corrects poisoned highs down to the true time, never regresses a genuine
   live capture. Verified both directions on scratch DBs.

### Repair script (`scripts/repair_neighbour_timestamps.py`) — safety net
Catches `nb:%` rows that are pre-`--cutoff` (default 2026-01-01) OR in the
future (> now + 2min), AND resets any future `nodes.last_heard`. Per node picks
best real date: (1) latest real captured packet, else (2) `nodes.last_heard`
if sane (>= cutoff, not future), else (3) clamp to earliest real packet.
Nothing deleted; idempotent. With the import fixes above it usually finds
nothing to do. Backfill script targets all `protocol='meshcore'` rows with
`frequency_mhz` 0/NULL.

### Files changed (2026-07-05)
| File | Change |
|---|---|
| `src/capture/meshcore_usb_source.py` | freq/SF from `self_info`; `capture_source=self.name`; removed `_EMPTY_SIGNAL` |
| `src/decode/meshcore_event_adapter.py` | preserve freq/SF in `_rf_signal_from_payload`; `_hop_start_from_payload` from `path_len` |
| `import_contacts.py` (root) | neighbour rows stamp freq/SF/BW (`--freq/--sf/--bw`); `last_heard = now - secs_ago` (skew-immune); `_clamp_future()`; AUTHORITATIVE `MAX(excluded, real-packet floor)` upsert |
| `scripts/repair_neighbour_timestamps.py` | **NEW** — fix past AND future `nb:` timestamps + future `nodes.last_heard` |
| `scripts/backfill_meshcore_signal.py` | **NEW** — backfill freq/SF on old meshcore rows |

### RTL-SDR web listener (REBUILT + FULLY WIRED locally — 2026-07-05 evening)
Audio-only browser SDR (rtl_fm -> ffmpeg MP3 -> fan-out), tune-anywhere, no
waterfall, uses the RTL-SDR (separate from SX1302). The first attempt's files
were LOST in the revert (never committed — git log -S confirmed); rebuilt from
scratch and this time the wiring is IN:

- `src/audio/rtl_listener.py` — RtlListener: shell pipeline
  `rtl_fm | ffmpeg -f mp3` in own process group (killpg stop), restart-based
  tuning, per-client asyncio.Queue fan-out (drop-oldest on slow clients),
  10-min idle auto-stop, modes nfm/am/usb/lsb/wfm (wfm = rtl_fm `wbfm` alias,
  32 kHz; others 16 kHz), 64 kbps MP3.
- `src/api/routes/listener_routes.py` — /api/listener: GET status, POST tune,
  POST stop, GET stream (StreamingResponse audio/mpeg). Registered with
  `dependencies=protected`; the HttpOnly session cookie authenticates the
  <audio> element, no token plumbing needed.
- `server.py` — import, `_rtl_listener` global created in lifespan after
  `_init_routes`, stopped first in shutdown, router registered after lorawan.
- `frontend/js/listener_panel.js` + `frontend/css/listener.css` (lsn-*
  classes) — freq/mode/squelch/gain controls, preset buttons (FM 100.0,
  PMR446, 2m 145.5, 433.5, marine ch16, airband AM), <audio> with stream URL
  cache-busted per tune.
- `index.html` (css link + nav "Listener" + section + script tag),
  `app.js` (`listener` in allowedRoutes, `_bootListenerPanel`).

Status: py_compile + node --check pass; NOT yet deployed — the user pushes to
the Pi themselves (never SSH the Pi unprompted). Pi prerequisites verified
earlier: rtl_fm/rtl_test in /usr/local/bin, ffmpeg 7.1.5 with libmp3lame,
dvb_usb_rtl28xxu blacklisted, dongle now permanently on a USB3 port.
OpenWebRX+ remains ruled out (needs Docker — python3-csdr wants python <3.12
on Trixie).

#### RTL-SDR vs MeshCore "name conflict" — SOLVED (2026-07-05 evening)
The reason the listener was parked ("RTL-SDR takes the same name as MeshCore
and kicks it out") turned out to be FALSE as stated but real in effect:
- RTL-SDR (0bda:2838, RTL2838UHIDIR, R820T tuner) creates NO tty at all —
  it can never steal `/dev/ttyUSB0` from the MeshCore CP2102.
- ROOT CAUSE = POWER: hot-plug inrush browns out the M1's internal 4-port
  VIA hub. First incident: CP2102 disconnected/re-enumerated → app's open
  MeshCore serial handle died ("kicked out"). Second test (2026-07-05):
  whole Pi hard-rebooted (uptime 1 min after plug-in).
- RULE: never hot-plug the RTL-SDR; leave it permanently connected (or use a
  powered hub). Once enumerated, `rtl_test` runs clean (0 lost samples @
  2.048 MS/s) while MeshCore capture keeps working — verified live.
- Box is listener-ready: `dvb_usb_rtl28xxu` already blacklisted in
  /etc/modprobe.d, `rtl_fm`/`rtl_test` in /usr/local/bin. `[R82XX] PLL not
  locked!` at startup is harmless init noise.
- Everything self-heals after a reboot: meshpoint.service auto-starts and the
  MeshCore source reconnects on its own.

#### Live device config drift (2026-07-05)
The M1 (`pi@192.168.2.189`, service config at `/opt/meshpoint/config/local.yaml`)
currently runs only TWO sources: `concentrator` + ONE `meshcore_usb` companion
at `/dev/ttyUSB0` (CP2102, label "", auto_detect false). The 5-network
local.yaml above (2× ACM MeshCore + Meshtastic serial) is NOT what is deployed
right now. Repo copy `meshpoint_lorawan/config/local.yaml` is also stale vs
the live one. Consider `/dev/serial/by-id/usb-Silicon_Labs_CP2102_...-if00-port0`
instead of ttyUSB0 for robustness if more USB devices get added.

#### Listener enhancements (2026-07-05 evening → live, working)
Built on the base above; all verified working in the browser (FM audio + meter).

**Presets — data-driven, grouped.** `ListenerPanel.PRESET_GROUPS` (static getter)
renders labelled sections via `_presetsHtml()`; delegated click handler picks up
any `button[data-freq]`. Full precision preserved (no toFixed rounding — PMR
needs 5 decimals). Sections:
- Amsterdam FM Radio (WFM): R1 98.6, R2 92.3, 3FM 96.5, Klassiek 94.3, FunX 96.1,
  Qmusic 100.4, 538 102.4, R10 91.6, Sky 101.5, Joe 103.8, Veronica 95.3,
  100%NL 89.6, SLAM! 98.0, BNR 101.8. (Joe/100%NL/SLAM are nationwide freqs.)
- PMR446 (NFM): all 16 channels 446.00625–446.19375.
- Marine VHF marifoon (NFM): Ch10 156.5, Ch16 156.8, Ch31 ship 156.55 / coast
  161.15, Ch67 156.375, Ch77 156.875.
- Marine UHF on-board (NFM): 10 ch, 457.525–457.575 / 467.525–467.575 (Ch2/4 social).
- Schiphol airband (AM): Tower/Approach+Radar/Ground+Delivery/ATIS+Emergency.
  IMPORTANT: uses the ACTUAL 8.33 kHz carrier freqs (e.g. 118.100), NOT the
  channel-label numbers (118.105).
- Ham & Utility (NFM): 2m 145.5, 70cm 433.5.

**Overmodulation / level control.** rtl_fm PCM runs hot and clips. ffmpeg `-af`
now `volume={self.volume},alimiter=limit=0.9,ebur128`. A live **Level slider**
sets the PRE-ENCODER `volume` (clip fix must be before the MP3 encoder — browser
volume can't undo baked-in clipping); range 0.05–1.5. `DEFAULT_VOLUME = 0.45`
(bake-in default; `MIN/MAX_VOLUME` clamp). Slider applies on release
(`change`, not `input`) only while playing. **Resets to 0.45 on every preset
switch** (`_resetLevel()` — user found a carried-over 0.85 too hot).

**Clean channel switching = stop → tune → listen.** `_tune()` calls
`_stopAudio()` first (drops the old browser stream) before POSTing tune; backend
`tune()` already stop+starts the pipeline; then `_startAudio()` reconnects with a
cache-busted URL. Not gapless (~1-2s) — inherent to one dongle retuning.

**Device-busy race on fast switches — FIXED.** Symptom: "idle — Failed to open
rtlsdr device #0". Cause: `_stop_locked` killpg's the group but `proc.wait()`
reaps the *shell*, which exits before rtl_fm finishes releasing libusb → new
rtl_fm hits a still-busy device. Fix in `tune()`: `_DEVICE_SETTLE_SECS=0.4`
sleep between stop and start when `was_running`, plus `_start_locked_retrying()`
(start → wait `_START_CHECK_SECS=0.4` → if proc died, settle + retry, up to
`_START_RETRIES=3`).

**Layout** reordered to blocks: Listener (audio + meter) → Tuner → Presets.

**Audio-level meter (S-meter v1).** Appended `ebur128` to the ffmpeg filter
(needs `-loglevel info`); `_stderr_loop` parses momentary loudness `M: <LUFS>`
via `_EBUR128_M_RE`, maps [`_LUFS_FLOOR -60`, `_LUFS_CEIL -5`] → 0-100
(`self.audio_level`), exposed in status(), drawn as a gradient bar; panel polls
status at 1 Hz. Genuine errors filtered to `_last_error` only via `_ERROR_RE`
(so ebur128/info noise doesn't pollute the error display). CAVEAT: this is
POST-DEMOD AUDIO level (activity/modulation), **not calibrated RF dBm** — one
dongle held by rtl_fm can't give true RSSI. Calibration (`_LUFS_*`) landed right
first try; nudge if the bar pins or dies.

**SDR options evaluated, rtl_fm kept.** Inspected keenerd/rtlsdr-waterfall &
PLSDR (desktop GUI, waterfall CPU — rejected), pyrtlsdr (library, good for a
future IQ-based scope/S-meter but conflicts with rtl_fm on the one dongle),
rtl_fm_streamer (C fork: FM-stereo + retune-without-restart + GetPowerLevel, but
FM-ONLY so loses AM airband — rejected), SeanoNET/rtlsdr-radio (same
FastAPI+rtl_fm+ffmpeg arch as ours — validates design; borrowable: ICY "now
playing" metadata, and DAB+ via welle-cli). FUTURE ideas: RDS station name
(redsea), DAB+ mode (welle-cli, unlocks NPO Radio 5 which is DAB-only), true
IQ S-meter (pyrtlsdr, time-shared).

#### Display units default → metric (2026-07-05)
`frontend/js/meshpoint_display_units.js`: `DEFAULTS` and the load/save fallbacks
flipped to **Celsius + kilometers** (was fahrenheit/imperial). Browser-local
pref; explicit fahrenheit/imperial still honored, only unset browsers change.

#### Listener "real radio" UI + RDS + Web Audio VU (2026-07-05 late → live, working)
Big session turning the Listener tab into a proper radio face. All in
`frontend/js/listener_panel.js` + `frontend/css/listener.css` unless noted.

**Radio face.** Block order Listener → Tuner → Presets. Listener block = bezel
panel with: LED strip (mode badge `WFM/AM/NFM/USB/LSB` on the LEFT, then ON AIR
green + TUNING amber-blink LEDs), big cyan illuminated frequency (JetBrains
Mono, glow, **3 decimals** e.g. `98.000`), station line under it, segmented VU,
`<audio>` player. Bezel/glow/colors all from existing tokens (`--accent-*`,
`--glow-*`, `--font-mono`). Hint text removed. Native `title=` tooltips on
mode/ON AIR/TUNING/RDS/BLER/PTY (cursor:help).

**Presets** = data-driven `ListenerPanel.PRESET_GROUPS` (static getter),
grouped sections; delegated click sets freq+mode, marks active chip (lit cyan),
resets Level to default, tunes. Full precision preserved. Groups: Amsterdam FM
(WFM, Qmusic 100.4 / Sky 101.5 corrected), PMR446 16ch, Marine VHF, Marine UHF,
Schiphol airband AM (ACTUAL 8.33k carriers not channel labels), Ham & Utility.

**Level control.** ffmpeg `-af volume={v},alimiter=limit=0.9,ebur128`. Live
Level slider = PRE-encoder volume (clip fix must precede the MP3 encoder).
`DEFAULT_VOLUME=0.45`; resets to default on every preset switch.

**Clean switching + device-busy race fix** (`rtl_listener.py`): `_tune()` stops
old browser stream first; backend killpg reaps the shell before rtl_fm releases
libusb → "Failed to open rtlsdr device #0" → fixed with `_DEVICE_SETTLE_SECS`
(0.4) + `_start_locked_retrying()` (retry ≤3).

**RDS (WFM only, redsea).** RDS is on the 57 kHz MPX subcarrier, needs the WIDE
signal, and one dongle can't run two rtl_fm — so WFM switches to a **171 kHz MPX
pipeline teed to both redsea and ffmpeg** (needs `/bin/bash -c` for process
substitution):
`rtl_fm -M fm -s 171000 -F 9 | tee >(redsea -r 171000 -E > /tmp/meshpoint_rds.jsonl) | ffmpeg [MPX->audio]`.
ffmpeg reconstructs mono audio: `lowpass=f=15000,aemphasis=mode=reproduction:type=50fm,...`
(EU 50µs de-emphasis). `_rds_reader` tails the JSON file for `ps`/`radiotext`/
`prog_type`(PTY)/`bler`. **No `-p`** (partial) — only fully-received text, else
the marquee flickered on half-decoded fragments. status() exposes
`rds_ps/rds_rt/rds_pty/rds_bler`. Verified live on SLAM! 98.0 — audio + RDS both
worked first try (MPX rework needed no tuning). Other modes = unchanged narrow
pipeline, no RDS.

**Station line** (`_renderStation`): tags `[RDS][BLER %][PTY]` fixed on the left,
scrolling text to the right. **Marquee** only rebuilds when text CHANGES
(`_stationTextCache` guard) — rebuilding every poll was resetting it to frame 0
so it never scrolled. Prefers RDS PS (+RadioText when it differs from PS) over
preset label. `RDS`/`PTY`/`BLER` pills; BLER = `100 − block error rate`, colored
green≥90 / amber≥70 / red — the real signal-quality meter (RF), unlike the VU.
Station line + VU widened to `width:100%; max-width:720px` to match.

**VU meter = Web Audio (client-side), the important fix.** ebur128 audio_level
(400 ms integrated loudness) barely moved on compressed broadcast FM. Replaced
with a real-time `AnalyserNode` on the `<audio>` element: `_ensureAudioGraph()`
(element→analyser→destination, created ONCE — createMediaElementSource is
one-per-element), `_startVuLoop()` computes instantaneous RMS→dBFS→0-100 at
~60 fps (`(db+50)/47*100`, EMA smoothing). Peak-hold is time-based (~14 seg/s)
so it works at 60 fps or the 2 Hz poll fallback. Server `audio_level` kept only
as fallback (`_vuFromWebAudio` gate). Dances with the music, drops on quiet.

**24-hour time everywhere** (`hour12: false`): `simple_packet_feed.js`,
`meshtastic_panel.js`, `lorawan_panel.js`, `meshcore_panel.js`, `node_drawer.js`,
`node_metrics_chart.js`, `messaging_chat.js`, `messaging_contacts.js`,
`settings/update_panel_controller.js`. (Number `.toLocaleString()` counts left as-is.)

**Deploy note:** user pushes to the Pi themselves; needs `redsea` on PATH
(installed) for RDS. Tunable knobs if needed on-Pi: VU dB map `(db+50)/47`,
smoothing `0.4/0.6`, marquee speed `/22`, de-emphasis type, `_LUFS_*`. Verify
redsea JSON key is `bler` (`-E`) if the quality pill stays hidden.

**Still open (radio):** DAB+ via welle-cli (NPO Radio 5 is DAB-only), true-RF
S-meter via pyrtlsdr (time-shared). Evaluated & rejected: rtl_fm_streamer
(FM-only, loses AM), PLSDR / rtlsdr-waterfall (desktop GUI, waterfall CPU).
rtlsdr-radio validated our arch + suggested ICY metadata / DAB idea.

#### Listener two-skin radio + station presets + theme toggle (2026-07-06 → live)
Big polish pass. All frontend unless noted. The "analog tuning dial" from the
open list got built (as the Analogue skin).

**Two swappable SKINS, one shared controller.** `listener_panel.js` split into a
CONTROLLER (state, tune/stop, status poll, RDS, Web Audio VU, presets) and a
pluggable DISPLAY SKIN implementing { mount, setFreq, setMode, setLeds,
setStation, setRdsQual, setVu, reset }. `DigitalSkin` (VFD readout + segmented
VU) and `AnalogueSkin` (slide-rule dial + swinging-needle VU). A
**Digital | Analogue toggle** in the panel header switches them; choice persists
(localStorage `meshpoint.listenerSkin`). CRITICAL: the `<audio>` element lives in
the SHELL, not a skin — `createMediaElementSource` is one-per-element, so the
Web Audio graph survives skin switches and the VU keeps feeding whichever skin.
Skins query their own elements via `data-*` attrs (no global IDs → no collisions).

**Analogue skin:** full-width slide-rule dial (band scale auto-adapts: FM
87.5-108.5, AIR, 2m, MARINE, 70cm, PMR — `AnalogueSkin.BANDS`), red needle
glides to freq (green when RDS locks, BLER>=80), **cyan preset-flag dots** on the
scale for every preset freq in-band. SVG **VU gauge**: green/yellow/red arc +
ticks + white needle + round-glass dome overlay. Amber "dial-light" theme
(`--accent-amber`). Layout (final): dial on top → row of [VU gauge left | RDS
block right], RDS block stacks tags(RDS/BLER%/PTY) → station text → freq readout.
Whole analogue block capped `max-width:720px` to match the digital skin.

**Web Audio VU (real-time), the key VU fix.** Server ebur128 audio_level (400ms
integrated loudness) barely moved on compressed broadcast FM. Replaced with a
client-side `AnalyserNode` on the `<audio>` element: `_ensureAudioGraph()`
(element→analyser→destination, created ONCE), `_startVuLoop()` computes
instantaneous RMS→dBFS→0-100 at ~60fps (`(db+50)/47*100`, EMA smoothing). Time-
based peak-hold (~14 seg/s) works at 60fps or the 2Hz poll fallback. Server
audio_level kept only as fallback (`_vuFromWebAudio` gate). NOTE: this routes
playback through the AudioContext → causes a macOS Bluetooth "silent until you
re-select the output" quirk. A "Direct audio" bypass toggle was tried and
REVERTED (didn't fix BT; user wanted the nice VU back). Real fix would need
HTTPS for a `setSinkId` output picker — deferred (meshpoint is http on LAN).

**RDS quality + text refinements.** BLER meter: redsea `-E` adds a `bler` field
(block error rate); pill shows `100-bler`% green>=90/amber>=70/red, placed right
after the RDS tag. PTY tag from `prog_type`. RadioText fix: dropped redsea `-p`
(partial) and only read fully-received `ps`/`radiotext` — partial fragments were
flickering half-text and restarting the marquee. Marquee only rebuilds when the
text CHANGES (`_stationTextCache` guard). Native `title=` tooltips on
WFM/ON AIR/TUNING/RDS/BLER/PTY.

**Station presets** (call them that, not "phonebook" — user's naming; was one
long scroll). `PRESET_GROUPS` unchanged; new
rendering: **★ Favorites tab** (first; pin via ☆ star on each chip, stored
localStorage `meshpoint.presetFavs` as `freq|mode` keys) + **category tabs**
(one visible at a time, persists `meshpoint.presetCat`, `'fav'` = favorites) +
**search box** (filters across all categories, grouped for context; tabs dim).
`_repaintPresets()` re-renders tabs+view. **Green "now playing" dot** on both the
tuned category tab (`_tunedCat`) AND the tuned channel chip (`_tunedKey`, marked
in `_btn`, persists across tab/search). Default tuner freq **98.000 + WFM** so a
fresh visitor can hit Tune & Listen and get SLAM! immediately.

**Other:** 24-hour time everywhere (`hour12:false` across ~10 files); 3-decimal
freq readout; frequency default 98/WFM.

#### Topbar theme toggle (2026-07-06)
meshpoint has **3 themes, all dark**: `dark` (default), `high-contrast`,
`sunlight` — `ThemeController` sets `data-theme` on `<html>`, persists, and
themes are CSS-variable overrides in `css/theme_high_contrast.css`. Added a
**theme button in the topbar** (`_registerThemeToggle` in app.js via
`topbar.registerAction`) that cycles them with a per-theme icon (moon/contrast/
sun) + tooltip; in sync with the existing `theme:cycle` command-palette entry.
A 4th **LIGHT** theme is NOT done — it's a medium-large job because the CSS is
dark-first with many hardcoded colors (surfaces, glows, gradients) + dark map
tiles; would need tokenizing colors, a glow/contrast pass, and per-page testing.
The toggle is ready to accept a `light` entry when that work happens.

#### Fork = javastraat/meshpoint; update mechanism repointed (2026-07-06)
This whole tree (`meshpoint_lorawan/`) is a **fork of upstream KMX415/meshpoint**,
substantially diverged. User's fork: **`https://github.com/javastraat/meshpoint`**.
Confirmed against upstream README (WebFetch): upstream has NONE of the RTL-SDR
listener, RDS, radio skins, LoRaWAN sniffing/`/api/lorawan/*`, multi-companion,
theme toggle, or 24h/metric defaults — all of that is this fork's work.

**How the dashboard "Update" works** (Settings → Updates):
- Operates on the git repo at **`/opt/meshpoint`** (NOT /opt/meshcore).
- Apply chain (`src/api/update/apply.py`, all `sudo`): `git fetch origin <branch>`
  → `git checkout -f <branch>` → `git reset --hard origin/<branch>` →
  `sudo bash scripts/apply_finish.sh` (detached; `systemctl restart`).
- **`git reset --hard` WIPES uncommitted local changes in /opt/meshpoint.** So all
  our fork work must live in `origin` (javastraat), or a dashboard Update deletes
  it. Check before Apply: `git -C /opt/meshpoint status --short` (empty = safe).
- "Update available?" = version check reading `version.py` from GitHub raw.
- Watchdog stores pre-update SHA; Rollback = `git reset --hard <sha>` (unlocks
  only after one Apply runs from that page).

**Repointed the 4 hardcoded KMX415 URLs → javastraat** (so update pulls from AND
version-checks against the fork):
| File | What |
|---|---|
| `src/api/update/install_status.py` (`fetch_remote_version_sync`) | version-check raw URL |
| `src/api/routes/update_check.py` | version-check raw URL |
| `src/remote/executors.py` (`GITHUB_REPO`) | remote-executor clone URL |
| `scripts/meshpoint.service` | `Documentation=` link (cosmetic) |
The `origin` remote in `/opt/meshpoint/.git/config` was ALREADY javastraat (set by
install-time clone) — that governs the actual `fetch`/`reset`, not any hardcoded
URL. GOTCHA: origin AND the 2 version-check URLs must both be javastraat or the
"1 commit behind" comparison is wrong. README still has KMX415 badges/clone/links
(cosmetic, left as-is unless asked).

**Git "dubious ownership" error — FIXED two ways.** `/opt/meshpoint` is root-owned
(sudo clone) but the service runs as `meshpoint`, so newer git refused updates:
`fatal: detected dubious ownership`. Manual one-liner that fixes a box:
`sudo git config --system --add safe.directory /opt/meshpoint`. Baked in so it
never recurs: (1) every git invocation in `apply.py` (4) + `install_status.py`
(5 builders) now passes `-c safe.directory=<repo_path>` → the app self-trusts the
repo even before the system config is set; (2) `scripts/install.sh` adds the
`git config --system` line after the chowns (idempotent, guarded on `.git`).

**README additions this session** (`meshpoint_lorawan/README.md`): a "What's
Different in This Fork" section (grouped list of all fork additions), an
"Optional: RTL-SDR Radio Listener" hardware section (dongle, coverage,
rtl-sdr/ffmpeg/redsea deps, DVB-driver blacklist, power/no-hot-plug, antenna),
the RTL-SDR listener feature paragraph, and 4 `/api/listener/*` API rows. The
formerly stale 5-network channel table (`ch0-ch2 LoRaWAN, ch3-ch4 Meshtastic`)
was corrected 2026-07-06 to the real plan: ch0-ch4 LoRaWAN + only ch8 Meshtastic.

#### v0.7.7: dashboard self-update REGRESSION + repair (2026-07-06 afternoon)

**The last update broke Check for updates.** Dashboard showed: `Could not fetch
origin: sudo: a terminal is required to read the password`. ROOT CAUSE = our own
v0.7.6 dubious-ownership fix: adding `-c safe.directory=/opt/meshpoint` to every
`sudo git` call changed the argv, and `/etc/sudoers.d/meshpoint` grants NOPASSWD
on EXACT argv (`/usr/bin/git fetch origin *` etc.) — the leading `-c` matches no
rule → sudo wants a password → no terminal → error. (install_status.py's own
docstring even warned commands must match sudoers.)

**Fixes (all on the Mac working copy, core ones pushed by user):**
| File | Change |
|---|---|
| `config/sudoers-meshpoint` | Added a literal-pinned `-c safe.directory=/opt/meshpoint` variant next to EVERY git rule (fetch/checkout/pull/reset/status/log/rev-list/rev-parse); old lines kept; `visudo -cf` parsed OK |
| `scripts/post_update.sh` | New step 1a: idempotent `git config --system --add safe.directory /opt/meshpoint` (was only in install.sh → upgraded boxes never got it) |
| `src/version.py` | 0.7.6 → **0.7.7** |
| `src/api/update/channels.py` | Catalog trimmed to **Stable (main) + Custom** only (user request: "we only have main or custom"); upstream `rc-077`/`feat/v0.7.7` + `wismesh-node`/`feat/wismesh-hat` rows deleted (branches don't exist on the fork); `CHANNEL_ID_ALIASES` maps ALL retired ids (rc-074..077, wismesh-node) → `"stable"` |
| `frontend/js/settings/update_panel_controller.js` | `UPDATE_CHANNEL_ALIASES` same remap → 'stable' |
| `docs/CHANGELOG.md` | New **v0.7.7 section = full fork feature list** (LoRaWAN sniffing, multi-radio, RTL-SDR listener, UI, scripts, self-update fixes — 23 bullets across 6 subsections) + manual-upgrade note; verified with the real ChangelogParser: stable preview picks v0.7.7 (2026-07-06 late: grew to 31 bullets / 7 subsections — added "Roles and access" + sidebar regroup/modals/date bullets) |
| `tests/` (3 files) | See below |

**Sudoers self-installs — no manual copy needed:** `meshpoint.service`
ExecStartPre copies `config/sudoers-meshpoint` → `/etc/sudoers.d/meshpoint` on
EVERY service start, and post_update.sh step 1 does the same on every apply.

**BOOTSTRAP CATCH:** a v0.7.6 box cannot fetch this fix through the dashboard
(the fetch is what's broken). One manual round on the Pi required:
`cd /opt/meshpoint && sudo git fetch origin main && sudo git reset --hard
origin/main && sudo systemctl restart meshpoint` — the restart installs the new
sudoers, then dashboard Check/Apply works again.

**Channel-removal ripple effects (verified):** `rc_channel()` returns None →
`suggest_active_channel_for_install` no longer auto-advances main boxes to an RC
picker entry (stays stable). `match_channel_for_branch("feat/v0.7.7")` → custom.
Release-notes route: retired ids resolve to the stable channel/preview.
`_RC_CHANNEL_VERSION` + the `tier == "rc"` path in release_notes.py left as
dead-but-harmless legacy.

**Tests (44 pass locally):** upstream-channel expectations rewritten
(rc→custom/stable renames); deleted `test_rc_tier_accepts_retired_channel_id`;
route test `test_retired_rc_ids_normalize_to_stable` loops rc-074/rc-077/
wismesh-node → stable. IMPORTANT FIND: `_FakeGitRunner` in
test_update_install_status.py matched `args[:3] == ["git","fetch","origin"]` —
the v0.7.6 `-c` change had ALREADY silently broken these tests (they were never
run last session). Added `_FakeGitRunner._strip_prefix()` (drops `sudo` + `-c
<val>` pairs) used by the runner and the fetch assertion.
`tests/test_update_routes.py` can't run on the Mac (no fastapi installed) —
fixed statically, runs on Pi/CI only.

**Git state:** user committed+pushed the core fixes themselves: `83e6e85`
"update fix" (sudoers, post_update.sh, version.py) and `05fef20` "update fixes"
(channels.py, update_panel_controller.js). Still uncommitted at session end:
docs/CHANGELOG.md + 3 test files. Suggested commit msg: `fix(update): repair
dashboard self-update broken by safe.directory prefix (v0.7.7)`; suggested
release tag `v0.7.7` "Dashboard self-update repair".

**Open / noted:**
- `use_sudo=True` is hardcoded on every update-code path → a dev instance ON THE
  MAC always fails Check for updates (macOS has no meshpoint sudoers). Offered
  auto-detect (skip sudo when current user owns the repo — also correct on the
  Pi where root owns /opt/meshpoint); NOT implemented yet.
- The Mac working copy is now `/Users/einstein/Software/meshpoint` with the tree
  at repo ROOT (older notes said `meshpoint_lorawan/` — that layout is gone).
- User repeatedly stressed "we are on the Mac, not the Pi": all edits/tests are
  local; never SSH or deploy to the Pi unprompted.

#### Sidebar regroup (2026-07-06, local only — not yet pushed)
New nav shape (user-approved): **Dashboard** ungrouped on top → **Networks**
(LoRaWAN, Meshtastic, MeshCore, Messages, Stats) → **Radio** (Hardware ← renamed
from "Radio" page, route/badge id still `radio`; Listener = the RTL-SDR) →
**Ops** (Terminal, Configuration ▸, Settings ▸). Listener's menu label renamed
**"RTL-SDR"** (route/ids/API stay `listener` — internal name OK per user).
"Status" and "Config" group
headers removed (Config→Configuration stutter). Command palette entry now "Go to
Hardware". `sidebar_controller.js` `_applyIdentity`: `data-requires-section` now
accepts a SPACE-SEPARATED any-of list; Ops header uses
`"terminal configuration.identity settings"` so it survives Terminal being
feature-hidden. Radio page itself keeps its console-style `radio status` strip
(no visible title to rename). Same-day timestamp formatters also fixed this
session: lorawan/meshcore/meshtastic panels' `_fmtTime` shows `Jul 5, 16:19`
for non-today (today stays `HH:MM:SS`); messaging_contacts.js:200 still
time-only (offered, not requested).

#### Viewer-role security lockdown (2026-07-06, committed as `0c1cd41` — verified working, viewers get 403 + toast)
User tested as viewer and found writes NOT blocked (only sidebar hiding was).
Fixed on three layers:
1. **require_admin gates added** (per-route `_claims: SessionClaims =
   Depends(require_admin)`, matching system_config_routes house style):
   `config_routes.py` (PUT transmit/identity/radio/channels/meshcore-channels +
   POST **restart** — was viewer-callable!), `nodeinfo_routes.py` (PUT + POST
   send), `meshcore_config_routes.py` (PUT companion-name), `messages.py`
   (POST send + advert, DELETE conversation + all; **mark-read left open** for
   the unread badge). Already-gated before: mqtt/upstream/device/system_config.
   Listener tune/stop left viewer-accessible by design.
2. **Channel-key redaction:** `GET /api/config` leaked Meshtastic `psk_b64`
   and MeshCore `key_hex` to viewers. `get_config` now takes require_auth
   claims; `_redact_channel_secrets()` blanks both for non-admins (per-request
   dicts, safe to mutate). messages `GET /channels` never leaked (names only).
3. **Frontend route guard:** `Router` gained a `guard` option → disallowed
   route renders new `forbidden` section ("Admin access required" lock card,
   `.forbidden-card` in dashboard.css). `_buildRouteGuard(identity)` in app.js
   maps `configuration/x`→`configuration.x`, `terminal`, `settings/*`→
   `settings`, `settings/dangerous`; everything else (incl. radio/Hardware +
   listener) open to viewers per user. Fails open when no available_sections
   (setup/dev).
Also fixed: **Transmit card stuck "Saving…"** — `_onSubmit` crashed on
`null._relayBurst` (burst/RSSI inputs don't exist in the template) after PUT
transmit succeeded, and PUT `/api/config/relay` doesn't even exist in the
backend; dead call + null lookups removed. Viewer UX verified live by user (2026-07-06): guarded routes show the
"Admin access required" card; on viewer-open pages (Hardware, Messages) admin
buttons stay visible and 403 with a clean toast on click — ACCEPTED as-is,
hiding them is NOT a wanted task.
`_ADMIN_SECTIONS`/`_VIEWER_SECTIONS` in identity_routes.py still stale vs real
tabs (works because ungated nav items aren't checked) — offered sync, not done.

#### Viewer 403 toast + README table fix (2026-07-06 late, committed as `ca41dbf` "message protection")
- **README 5-Network table corrected** (rows 1-2): ch0-ch4 LoRaWAN 0x34 /
  ch8-only Meshtastic 0x2B (was the never-true ch0-ch2/ch3-ch4 plan).
- **Viewer message-send → toast** (user-tested the failed-bubble UX and asked
  for a toast): in `messaging.js` `_onSendMessage`, a **403** now removes the
  optimistic bubble (`MessagingChat.removeMessage(tempId)`, new) and shows
  "Not sent: <detail>" via a `_showToast` helper reusing the global `r-toast`
  element/styles from radio.css (loaded on every page). Non-403 failures keep
  the in-thread `failed:` bubble (real delivery errors are useful history).
- **Bottom-right "meshpoint · vX.Y.Z" build stamp STAYS.** A removal was tried
  (overlaps the scrollbar) but the user reverted it before committing — final
  call: leave the stamp as-is. Don't propose removing it again.
- **Total Packets tile → "24h / total"** (deployed, verified live): user asked
  for total+session; 24h chosen over since-boot (matches Nodes tile grammar,
  survives restarts). `packets_last_24h` added to `get_traffic_summary()` in
  `traffic_monitor.py`; app.js renders `${24h} / ${total}` with a null-guard
  fallback to plain total (mixed-deploy safe); subtitle div added in index.html.
- **CHANGELOG v0.7.7 grew to 32 bullets**: new "Roles and access" subsection
  (viewer lockdown, secret redaction, forbidden page, send toast, login
  no-prefill) + Dashboard/UI bullets (sidebar regroup, inline modals, feed
  dates, packets tile). All verified through ChangelogParser.

#### Viewer denied-nav → in-place toast (2026-07-07)
User request: don't bounce viewers to the forbidden page on in-app admin-link
clicks (page → Back to Dashboard → re-navigate was annoying). `router.js`
`_onHashChange`: guard-rejected route while `_currentRoute` exists →
`history.replaceState` back to the current hash + fire new `onDenied` callback
(no dispatch, no history junk; replaceState doesn't re-fire hashchange so no
loop). app.js passes `onDenied: _toastAdminRequired` (r-toast pill: "Admin
access required — the viewer role is read-only"). Fresh loads / deep links
(no current route) still render the forbidden lock card. Changelog bullet
rewritten accordingly.

#### Web server port now config-driven via src/serve.py launcher (2026-07-08)
The port was set in TWO places and only the systemd unit mattered:
`meshpoint.service` ExecStart hardcoded `uvicorn ... --host 0.0.0.0 --port 8080`,
while `dashboard.host/port` in the YAML (`DashboardConfig`, config.py) was ONLY
used for the startup-banner URL in log_format.py — changing the YAML did nothing.

Fix — YAML is now the single source of truth:
- **`src/serve.py` (NEW)** — launcher: `_bind_address()` reads
  `load_config().dashboard` host/port; on ANY config error falls back to
  `0.0.0.0:8080` with a loud log (a broken local.yaml must never crash-loop the
  server, since the dashboard is also the update/rollback UI). `main()` calls
  `uvicorn.run("src.api.server:create_app", factory=True, host, port)`.
  uvicorn import is INSIDE main() so the module imports on the Mac (no uvicorn
  in the system python; `_bind_address()` unit-testable without it).
- **`scripts/meshpoint.service`** — ExecStart is now
  `/opt/meshpoint/venv/bin/python -m src.serve` (no --host/--port args).
- **`config/default.yaml`** — comment on the `dashboard:` block: bind address
  read by src/serve.py, override in local.yaml, takes effect on restart.
- Pi rollout needs NO manual step: `post_update.sh` step 2 already copies
  scripts/meshpoint.service → /etc/systemd/system + `systemctl daemon-reload`
  when it differs.
- To change the port: set `dashboard: port:` in local.yaml, restart service.
  Verified on Mac: `_bind_address()` returns `('0.0.0.0', 8080)` from YAML.
- **Bind-failure fallback** (added same day): `_can_bind()` pre-probes the
  configured address (SO_REUSEADDR, matching uvicorn, so TIME_WAIT after a
  restart isn't a false conflict); unbindable (port taken / privileged port
  as non-root on Linux / bad host) → loud log + fall back to 0.0.0.0:8080.
  Skipped when config already equals the fallback (let uvicorn error
  normally). NOTE: macOS lets non-root bind <1024, Linux doesn't — probe
  reflects each OS's real rules. Verified: occupied port + bad host → False.
- **Web editor for the port: DECIDED NOT TO BUILD** (2026-07-08, user call —
  low value, port changes are ~once ever, YAML+restart suffices). If ever
  revisited: Settings card (not Configuration), port-only (never host),
  `PUT /api/config/dashboard` via `save_section_to_yaml`, reject <1024,
  countdown-redirect UX to the new port. Don't re-propose unprompted.
- Changelog bullet added under **v0.7.7 → "Dashboard and UI"** (33 bullets now).
  CONVENTION (user-confirmed): ALL ongoing work goes into the v0.7.7 section,
  NOT "Unreleased" — stable tracks main, version.py stays 0.7.7, and the
  dashboard release-notes preview only shows the section matching the version
  (an Unreleased/None section is never displayed). Verified via ChangelogParser.

#### Whole-code inspection findings backlog (2026-07-08, user-requested, prioritized)
Full sweep done: all py compiles, all js parses, auth solid everywhere (incl.
terminal WS admin check + shlex-quoted listener pipeline). Backlog:

| # | Prio | Effort | Finding |
|---|------|--------|---------|
| 1 | ~~P1~~ DONE 2026-07-08 | S | `use_sudo=True` hardcoded in update paths → Check-for-updates always failed on Mac dev. FIXED: `sudo_needed()` + `_git_argv()` in install_status.py; all `use_sudo` params default `None` = auto (stat st_uid vs getuid); apply.py `_capture_head_sha` on auto too. Apply-chain git fetch/reset kept hardcoded sudo (mutates root tree, must match sudoers). Verified on Mac: plain git, full sync_remote payload OK, 13 unittests pass |
| 2 | ~~P1~~ DONE 2026-07-08 | S | `_ADMIN_SECTIONS`/`_VIEWER_SECTIONS` synced (identity_routes.py): both now include lorawan/meshtastic/meshcore/listener in sidebar order. No behavior change (only terminal/configuration.*/settings* are checked); tests only assert membership |
| 3 | P2 | M | HIDDEN FEATURE: `PUT /api/config/relay` (system_config_routes.py:231) fully supports min/max_relay_rssi (RSSI-gated relaying), burst_size, serial port/baud — no UI calls it. Expose on Transmit card. (Old note "PUT /relay doesn't exist" was WRONG — it exists; only the frontend call was broken) |
| 4 | ~~P2~~ DONE 2026-07-08 | S | Dead frontend/js/simple_node_list.js DELETED (nothing referenced it; superseded by node_cards.js) |
| 5 | P2 | M | 8 unused endpoints — wire or prune: /api/analytics/signal/rssi+snr, /api/packets/by-source+count+protocols+types, /api/nodes/map+summary, /api/telemetry/{id}(+history) |
| 6 | P3 | L | Spectrum view: SpectralScanService already scans periodically but discards the histogram (only floor/median → noise pill). Endpoint + canvas = the wishlist "spectral scan overlay" |
| 7 | P3 | M | Meshtastic `serial` source single-instance — needs the list-field treatment meshcore_usb got |
| 8 | P3 | S | `nb:` synthetic rows blank RSSI/FREQ/SF in feed (cosmetic, SNR-only) |
| 9 | P3 | M | Concentrator-channels card on Hardware page (no UI/API shows ch0-ch4 LoRaWAN + ch8 Meshtastic plan) |

Intentional / leave alone: sx1262_spi_source.py (parked per ROADMAP, RAK HAT
coexistence), /api/public/recent_rx unauth (login-page radar blips),
no CORS middleware (same-origin), messages mark-read viewer-open (badge).
Suggested order: 1 → 2 → 4 (one small PR), then 3, then decide 5.

Items 1+2+4 done 2026-07-08 (same session as the port launcher). Changelog:
2 new v0.7.7 bullets (dev-checkout update check → "Self-update system";
section-list sync → "Roles and access"; dead-file delete not changelogged,
not user-facing) — 35 bullets total, verified via ChangelogParser.
Suggested commit msgs: `feat: web server port configurable via dashboard.port
(src/serve.py launcher with bind fallback)` + `fix: update check without sudo
on user-owned repos, sync role section lists, remove dead simple_node_list.js`.
Next up: #3 (relay RSSI-gating UI on Transmit card).

---

## What it does NOT do (intentional)

- LoRaWAN payloads NOT decrypted (need AppSKey/NwkSKey from the network)
- LoRaWAN NOT on the map (no position in LoRaWAN packets)
- LoRaWAN NOT relayed (ever)
- MeshCore NOT relayed (ever — listen only)
- Meshtastic 433 (Heltec V3 serial) packets handled by existing `serial` source —
  they decode and appear in dashboard like any Meshtastic packet

---

## Possible next steps

- Export LoRaWAN captures to CSV / TTN-compatible format
- Add EU433 LoRaWAN channel plan (`eu433_lorawan()`) — needs a 433 concentrator, not the M1
- Spectral scan overlay
- LoRaWAN MIC verification (cosmetic — tells you if a packet is malformed)
- Show 433 Meshtastic nodes separately in the UI (protocol + frequency tag)
