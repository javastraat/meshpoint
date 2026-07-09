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
| 3 | ~~P2~~ DONE 2026-07-08 | M | Relay burst + RSSI window exposed on Transmit card. GET /api/config relay dicts (both `transmit.relay` and top-level `relay` in config_routes.py) now include burst_size/min_relay_rssi/max_relay_rssi; transmit_card.js adds 3 inputs + `_collectRelayFilters()` (client-validates numbers + max>min), saves via PUT /api/config/transmit (enable/rate, unchanged) THEN PUT /api/config/relay (filters only, skipped when all blank); backend 400 detail surfaces via panel toast. relay serial_port/baud intentionally NOT exposed (SX1262 legacy, confusing on Transmit). Values apply on restart (existing signalRestart toast). User confirmed the card renders live with correct values (screenshot 2026-07-08); Save path not explicitly exercised yet |
| 4 | ~~P2~~ DONE 2026-07-08 | S | Dead frontend/js/simple_node_list.js DELETED (nothing referenced it; superseded by node_cards.js) |
| 5 | ~~P2~~ DONE 2026-07-08 | M | Of the 8 unused endpoints only 2 carried NEW data (verified: /api/stats/summary already embeds rssi_distribution + protocol/type dists — the old "wire 5" plan would have re-plotted duplicates). WIRED: `/api/analytics/signal/snr` → SNR histogram card on Stats next to RSSI (purple #a855f7, clone of _updateRssiHist, fetched via Promise.all in refresh(), NOT part of session/all-time toggle — last-500-packets only); `/api/packets/by-source/{id}` → "Recent Packets" collapsible section in node drawer (last 15: time · type · RSSI/SNR; source_id==node_id, both 8-hex no `!`). KEPT for later inspection per user (NOT pruned): /api/packets/count+protocols+types, /api/nodes/map+summary, /api/telemetry/{id}(+history) — all duplicate data already on screen via other endpoints. SNR chart browser-verified (screenshot 2026-07-08: renders next to RSSI, bimodal far/near clusters; drawer packets not yet checked). NOTE spotted in screenshot: "Best RSSI −4 dBm" is implausible — likely one synthetic/self-report outlier; candidate small fix: filter RSSI > −20 dBm from best/avg tiles |
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
#3 done later same day (relay UI, changelog bullet under "Dashboard and UI",
36 bullets total). #5 done same day (SNR chart + node-drawer recent packets,
2 more bullets → 38). Remaining open: #6 spectrum view, #7 multi Meshtastic
USB, #8 nb: blank RSSI cosmetic, #9 concentrator-channels card.

---

## What it does NOT do (intentional)

- LoRaWAN payloads NOT decrypted (need AppSKey/NwkSKey from the network)
- LoRaWAN NOT on the map (no position in LoRaWAN packets)
- LoRaWAN NOT relayed (ever)
- MeshCore NOT relayed (ever — listen only)
- Meshtastic 433 (Heltec V3 serial) packets handled by existing `serial` source —
  they decode and appear in dashboard like any Meshtastic packet

---

## CURRENT TO-DO LIST v2 (2026-07-08 15:22 — supersedes T-list below)

All of T1-T4, T6 DONE (see entries below). Fresh numbering:

| # | Prio | Effort | Task |
|---|------|--------|------|
| N1 | P3 | M | Multiple Meshtastic USB sticks — list-field treatment for `serial` source (config list + labels + meshtastic_usb_<label>), like meshcore_usb. Do when 2nd stick wanted (spare Heltec V3 433 "TBD/play" is candidate) |
| N2 | DONE 2026-07-08 | S-M | Endpoint housekeeping done via live diagnosis (user ran stdlib diag script on Pi, all comparisons byte-identical). PRUNED 4: packets/protocols+types, nodes/map (+ orphans: telemetry.py router whole file, TelemetryRepository.get_latest_for_node, NodeRepository.get_with_position, NetworkMapper's get_map_data/get_all_nodes/get_nodes_with_position/get_node_count). **KEPT 2 — double-check saved us: `meshpoint report` CLI (report_command.py) uses /api/packets/count AND /api/nodes/summary** (frontend-only grep missed CLI consumers; remember to grep src/cli too when auditing endpoints). BONUS BUG FIXED: network summary totals were computed over get_all(LIMIT 500) → Stats page + CLI report under-reported (500 vs real 1445 nodes); now `NodeRepository.get_network_totals()` whole-table SQL aggregates (COUNT/SUM CASE/GROUP BY, COALESCE for empty table; SQL validated via stdlib sqlite3 on Mac). nodes.py no longer takes network_mapper (server call updated); NetworkMapper slimmed to get_network_summary→get_network_totals (stats_routes still uses it). README API table: nodes/map row → nodes/summary. 2 changelog bullets (45 total) |

Wishlist: W1 LoRaWAN CSV/TTN export (S-M, best value) · W2 LoRaWAN MIC verify (S) · W3 433-node UI tags (S-M) · W4 light theme (L) · W5 DAB+ welle-cli (M-L) · W6 pyrtlsdr true-RF S-meter (M-L).

Watch: RFID plateau 865.6-867.6 (identified, only interesting if it changes); noise pill should read a few dB lower post-percentile-fix.

**CLI report/status auth fix (2026-07-08 ~16:00, found via N2):** `meshpoint report`
had been broken since API auth landed — unauthenticated `_get` swallowed 401s
into "service is not running" (user hit it right after N2 restored the CLI's
endpoints). NEW `src/cli/api_client.py` (CliApiClient: cookie jar session,
`get()` raising ServiceDown vs AuthRequired vs ApiError, `login_interactive()`
→ POST /api/auth/login). report_command: tries status → ServiceDown = real
"not running"; AuthRequired = prompt admin login, retry; per-section fetches
degrade to {}. status_command: 401/403 → "running (admin login required for
details — use 'meshpoint report')", stays non-interactive; explicit
`import urllib.error` added. Rejected alternative: localhost auth bypass
(would gut the viewer-role model). Changelog bullet (46). LIVE-VERIFIED on Pi
2026-07-08 16:03: report login flow + full render OK; status shows the new
"running (admin login required)" line. Full CLI smoke test (read-only script:
version/status/logs executed, all 9 --help parsed, all cli module imports) —
ALL PASS. Report data also live-confirmed the N2 uncap (Total nodes 1449, was
capped 500) AND the near-field ceiling (RSSI range max -21.0, was -4).
setup/restart/stop/meshcore-radio/reset-password intentionally untested
beyond parse+import (state-changing).
FOLLOW-UP (~16:45, user challenged "shell = admin anyway"): **sudo fast-path**
— `CliApiClient.login_local_root()` reads `web_auth.jwt_secret` +
`session_version` from local.yaml (path from CONCENTRATOR_CONFIG, cwd is
/opt/meshpoint via the bash wrapper) and mints a 10-min admin Bearer token
(sub=cli-local-root; dependencies.py accepts `Authorization: Bearer`).
report tries it silently before the interactive prompt; prompt now tips
"sudo meshpoint report". Trust model = reset-password (read the key ⇒ own
the dashboard anyway); NO server-side change/bypass. Mac-tested with a
stubbed HS256 signer (claims match verify()'s required set incl. sv);
graceful False → interactive fallback when secret unreadable/absent.
Pi-verify: `sudo meshpoint report` (no prompt) AND plain `meshpoint report`
as pi (prompt appears — local.yaml is meshpoint-owned; if it turns out
world-readable, plain also skips, which is equivalent-security).
LIVE RESULT: plain `pi` run skipped the prompt → local.yaml IS pi-readable
(user theorized "because sudo ran before" — corrected: CLI stores NOTHING
between runs, token is per-invocation in-memory; `chmod 640 local.yaml`
restores the prompt for non-root if ever wanted).
REPORT ENRICHMENT (same session, user asked for more info): new PROTOCOLS
section (LoRaWAN pkts+unique devices from /api/lorawan/stats + 867.9-868.7
x5ch from config.concentrator; Meshtastic pkts/nodes/freq/SF/TX; MeshCore
pkts/nodes/freq/SF via companion) + CAPTURE SOURCES section (SX1302 n/9
channels on, companions from capture.meshcore_usb [key is meshcore_usb NOT
meshcore_companions] with port+connected+name, last band sweep from
/api/device/spectrum). RADIO CONFIG renamed MESHTASTIC TX, slimmed (region/
preset/CR/BW + TX/power/hop/duty; freq+SF moved to PROTOCOLS, meshcore line
moved to SOURCES). Noise floor line SKIPPED — no REST endpoint exists (WS
emitter only); candidate tiny future task if wanted. Render path fully
Mac-tested with fake ReportData (pure functions — nice testability trick).
LIVE-VERIFIED on Pi 2026-07-08 ~16:50: all three sections render with real
data (23 LoRaWAN devices, companions by name, sweep timestamp correct UTC).
FOLLOW-UP (user: "meshtastic has a TX section, meshcore doesn't"): new
MESHCORE section after MESHTASTIC TX — companion state+name, radio
freq/BW/SF from cfg.meshcore.radio, TX power, channel list ("5: Public,
TechInc, ..." — Public prepended, names from mc.channel_keys). Mac
render-tested; LIVE-VERIFIED on Pi ~17:00 (exact match with test render). ALSO answered why MeshCore nodes lack per-node device stats:
protocol asymmetry — MeshCore adverts carry identity only (no broadcast
battery/telemetry like Meshtastic); metrics are request/response and mostly
encrypted. Our meshcore _decode_telemetry is a raw-hex stub too. Candidate
wishlist W7: active repeater status polling via companion (like the phone
app does) → would give MeshCore nodes drawer metrics; not yet added/sized.

## SESSION BOOTSTRAP — check this every time you read this file

There is a local working-conventions file at the repo root that the coding
assistant auto-loads at session start (its standard, well-known filename —
all caps, `.md`). It is intentionally **untracked and must never be
committed or `git add`-ed** (public repo). If it does not exist on the
machine you are running on, CREATE it now with exactly this content, AND
append its filename to `.git/info/exclude` (the local-only ignore file —
never committed, invisible on GitHub) as a mechanical guard so even
`git add -A` cannot pick it up. Do both, so every machine behaves the same:

```markdown
# Working conventions for this repo

- **After every change-set (code, changelog, docs), end your final message with a
  ready-to-use git commit one-liner** in a code block, unprompted. Style:
  lowercase, `fix:`/`feat:`/`docs:` prefix, one line, describes the user-visible
  effect, covers all files in the set. The user commits incrementally with these.
- **Session context lives in `memory/project_m1_meshpoint.md`** — read it at the
  start of a session to know where we left off, and update it after completing
  work (status, root causes, decisions, verification evidence).
- **Every feature/fix gets a bullet in `docs/CHANGELOG.md`** under the current
  version section (v0.7.7 while it lasts — NOT "Unreleased"; the dashboard's
  release-notes preview only shows the section matching `src/version.py`).
  Verify edits parse: `ChangelogParser.parse_file(Path('docs/CHANGELOG.md'))`.
- Larger features also go in README's "What's Different in This Fork" section
  and, when config keys change, `docs/CONFIGURATION.md`.
- **Development happens on the Mac; the device is a Raspberry Pi (SenseCap M1)
  deployed by the user.** Never SSH to the Pi or deploy unprompted. The Mac has
  no venv with fastapi/aiosqlite — test logic with stubs
  (`sys.modules['aiosqlite'] = types.ModuleType('aiosqlite')`) and provide
  snippets the user runs on the Pi for live verification.
- This file stays untracked: never commit it, never `git add -A` it.
```

**Updates page: incoming commits (2026-07-08 ~17:15, user request):** when
Check finds drift, the panel now lists the incoming commit subjects. Backend:
`list_incoming_commits()` in install_status.py (`git log --oneline
HEAD..origin/<branch>`, limit 10, same argv shape as _revision_count fallback
→ already sudoers-whitelisted; auto use_sudo); wired into
build_install_status_payload as `incoming_commits` (only fetched when
behind>0). Frontend: `<ul data-update-incoming>` after sync hint in
index.html; `_renderIncoming()` in update_panel_controller.js (DOM-built,
subjects textContent-escaped, "… and N more" row past limit, hidden when
up-to-date/no data); `.update-incoming` styles in settings.css. Verified:
13 unittests pass, parse/limit/failure unit-tested with fake runner, live
payload key present (empty at behind=0). LIVE-VERIFIED on Pi 2026-07-08
~17:20 (recursively: the first listed incoming commit was the feature's own
commit 610b3cb). README self-update bullet also mentions it.

**Docs completeness sweep (2026-07-08 evening, user request "is everything documented"):**
- MeshCore 7→40 channel raise (commit 1785f5e) had NO changelog bullet and no
  README mention — added both (changelog under "Configuration and server",
  49 bullets, parser-verified; README under "Expanded multi-protocol capture").
- EU868 plan commit 89a6ba7 + revert 273cca3 net out to docstring/comment
  improvements only — plan byte-identical, nothing to document.
- **Updates page "What's new" shows a FLAT list by design:** it's the
  release-notes preview rendered from docs/CHANGELOG.md by ChangelogParser
  (src/api/update/release_notes.py). Parser only matches `### vX.Y.Z` section
  headers (`_HEADER_RE` = exactly 3 hashes) and `- **headline.** detail`
  bullets; our `#### Category` subsection lines are silently skipped, so the
  dashboard preview loses the categories. Candidate feature: carry a
  `category` field per bullet + group headers in update_panel_controller.js
  — offered, not built.
- README gaps fixed: rtl-sdr/ffmpeg apt install + redsea build-from-source
  commands added to the RTL-SDR section (previously named as requirements
  with no install steps anywhere in the repo); Features grew "Web terminal"
  (upstream KMX415 feature, was totally undocumented) and "Dashboard
  authentication" (admin+viewer) bullets.
- COMMON-ERRORS.md: new Upgrades entry for the v0.7.6 "sudo: a terminal is
  required" Check-for-updates failure + manual bootstrap fix.
- HARDWARE-MATRIX.md: new RTL-SDR dongle section (software/driver/power/
  antenna table, links to README setup).
- Verified clean: CONFIGURATION.md covers all fork config keys (dashboard
  host/port, sx1261_spi_path, spectrum_sweep_interval_seconds, relay
  burst/RSSI, meshcore_usb list); no docs reference the 4 removed endpoints
  or stale channel plans; FAQ has no stale info.
- RESOLVED (user approved): all functional clone URLs repointed to
  javastraat/meshpoint (README install + ONBOARDING + TROUBLESHOOTING +
  SYNCROBIT-CHAMELEON + COMMON-ERRORS recovery), issue links → fork issues,
  Discussions links stay upstream (forks have no Discussions), version badge
  0.7.6→0.7.7. **Badges (stars/issues/last-commit) deliberately stay on
  KMX415 per user ("show the badges from the forked repository not ours") —
  don't repoint them again.** README line 53 fork-intro upstream link stays.

**Release-notes preview grouped by category (2026-07-08 evening, user request):**
The Updates "What's new" panel showed a flat list because ChangelogParser
ignored `#### Category` lines. Built: `_CATEGORY_RE` + `category: str | None`
field on ChangelogBullet (parse_text tracks current #### per section, resets
on each ###); `format_bullet_for_preview` emits it; frontend
release_notes_view.js `_renderBullets()` interleaves
`<li class="update-release-notes__category">` header rows when the category
changes (sections without categories render flat as before, None-safe);
`.update-release-notes__category` style in settings.css (eyebrow-cyan,
uppercase, underline). 3 new parser tests (attach/reset/preview-dict) — 23
pass on Mac; JS node --check OK; real CHANGELOG yields all 11 v0.7.7
categories in order. Changelog bullet under "Self-update system" (50 total,
parser-verified); README self-update fork bullet mentions grouping.
LIVE-VERIFIED on Pi 2026-07-08 evening (user screenshot): category headers
render (LORAWAN SNIFFING / MULTI-RADIO CAPTURE / RTL-SDR WEB LISTENER, eyebrow
style). Screenshot ALSO exposed a pre-existing upstream CSS bug: the `›`
bullet marker rendered on its own line above each headline. Root cause:
upstream commit 2e3c7cf made `.update-release-notes__bullet`
`flex-direction: column` (headline stacked over detail) and added the 14px
gutter + `position: relative`, but left the `::before` chevron as a flex
item → it became the first stacked row. FIX (settings.css): `::before` now
`position: absolute; left: 2px; top: 0` inside the gutter. Changelog: folded
into the existing "Release notes grouped by category" bullet (same page, no
separate bullet); still 50 bullets, parser-verified. Chevron fix
LIVE-VERIFIED on Pi 2026-07-08 evening (second user screenshot: marker
inline left of every headline, all categories + stacked detail correct).

**UPSTREAM v0.7.7 MERGE (2026-07-09, branch `merge/upstream-v0.7.7`, commit c6ca07a — NOT yet on main):**
Upstream KMX415 released their own v0.7.7 (39 commits); user keeps a local
clone at `/Users/einstein/Software/meshpoint-original`; added as git remote
`upstream` (local path). Merged into the fork with 12 conflicted files, all
resolved:
- **Upstream brings:** Settings backup/restore (tar.gz of config+data,
  systemd-run transient units, new sudoers restore rules — `install.sh`
  needed on upgrade), RF Environment tab (rf.css/rf_tab.js, /api/rf/status,
  reuses OUR SpectralScanService instance), packet detail modal, Quick
  Deploy QR (vendored qrcode.js, /api/config/export — public PSK only,
  verified), Prometheus /metrics (disabled by default, own auth),
  position/telemetry broadcast cadence controls, channel-hash rebuild fix
  (#89), operator status strips + MQTT health, Bobcat Miner 300 docs +
  HOME-ASSISTANT-COOKBOOK, CI on feat/**.
- **Fork decisions kept:** channel picker stays Stable+Custom (upstream's
  new rc-078/wismesh ids alias→stable, tests rewritten); EU868 LoRaWAN plan
  kept (upstream test_eu868_longfast_uses_preset asserted radio_0=869.525 —
  PRE-EXISTING failure on the fork, never noticed via targeted runs; now
  asserts fork plan 868.3/869.525); README badges stay KMX415 per user.
- **Fork lockdown extended to upstream code:** their PUT /api/config/position
  + /api/config/telemetry had NO admin gate → added require_admin (viewer
  lockdown); `rf` added to _ADMIN_SECTIONS/_VIEWER_SECTIONS. backup_routes
  were already admin-gated upstream; rf GET viewer-open (fine).
- **Version collision:** upstream also calls their release v0.7.7. CHANGELOG
  v0.7.7 sections COMBINED: fork intro (mentions merged upstream features +
  install.sh note) + our 11 categories + their 4 (Backup and restore / Mesh
  broadcast cadence / Dashboard and operator tools / Docs). 60 bullets, 15
  categories, parser-verified. RF tab bullet corrected: scan DOES work on
  the M1 on this fork via sx1261_spi_path.
- **Verification (Mac):** every src/*.py compiles, every frontend/*.js
  parses, 49 test modules pass (incl. rewritten channel/plan tests), 28
  modules skip on missing Mac deps (jwt/bcrypt/aiosqlite/Crypto/fastapi —
  pre-existing), test_terminal_session_manager hangs on Mac PTY
  (pre-existing, untouched by upstream). README API table +5 upstream
  endpoint rows. Sudoers merged: restore rules + our safe.directory
  variants coexist. index.html auto-merged: our sidebar regroup intact, RF
  link landed in upstream's telemetry rail.
- **DEPLOYED 2026-07-09:** merged to main (`cca3a90`), pushed via SSH (user
  added ~/.ssh/id_rsa.pub to GitHub after a PAT rejection — the .netrc
  "Database-Server" classic token lacks `workflow` scope and the merge
  touches .github/workflows/ci.yml; SSH remote is now the push path).
  Dashboard Apply on the Pi worked; NO install.sh needed (fork's
  ExecStartPre self-installs the new restore sudoers on service start).
  **Backup download LIVE-VERIFIED** (Device PD2EMC, ~34 MB archive, disk
  9.4%; user stored a backup). GOTCHA that cost debugging time: after the
  apply the backup buttons were dead with NO console errors — STALE CACHED
  app.js; plain reload wasn't enough, needed DevTools-open "Empty Cache and
  Hard Reload". After any dashboard update, stale JS = first suspect for
  "new feature dead, no errors" (candidate wishlist: cache-busting ?v= on
  script tags).
- **FULL PI VERIFICATION 2026-07-09 morning — ALL GREEN (screenshots):**
  backup download (34MB archive stored) · Quick Deploy QR (LongFast/EU_868/
  869.525/hop3) · RF Environment tab (LIVE SCAN badge, -84 dBm, 28 scans 0
  failed — proves fork's sx1261_spi_path beats upstream's "unavailable on
  M1" claim) · broadcast cadence editors (telemetry 30m + position 15m,
  live countdowns) · release-notes categories (all 15 headings) · packet
  detail modal (rendered a MESHCORE packet incl. fork companion freq/SF
  metadata) · Band Spectrum card coexists with RF tab on the shared scan
  service (the riskiest merge spot — confirmed) · regression sweep:
  LoRaWAN page (117 pkts/23 devices/16 joins), RTL-SDR listener (SLAM!
  RDS+VU), Hardware cards (concentrator 6/9 on), MeshCore (1331 contacts,
  companions live), Meshtastic feed — all working. Operator status strip
  visible on Dashboard. MQTT broker-health strip verified too (LAN broker
  192.168.2.26:1883 connected, publishing, 0 drops). NOT tested (fine):
  restore upload flow, viewer 403 on new broadcast PUTs.
  **CI NOW GREEN (2026-07-09, commit 9f99c81):** the merge brought
  upstream's .github/workflows/ci.yml (ruff + pytest on every push to
  main/feat/**) — the fork's FIRST-EVER CI immediately exposed latent debt
  (3 pushes to green): (1) 3 unused imports in lorawan_routes.py (ruff);
  (2) 36 test failures, none merge bugs: fork route tests written BEFORE
  the 2026-07-06 viewer lockdown called APIs unauthenticated (fixed with
  `app.dependency_overrides[require_admin/require_auth] = lambda:
  SessionClaims("test-admin", ROLE_ADMIN, 1)` in the _build_app builders —
  THE pattern for fork route tests now; also added explicit
  401-without-admin gate tests), stale test_meshcore_usb tests predating
  the list-based multi-companion config (rewritten against
  _coerce_meshcore_usb), upstream's broadcast/channel-hash tests hitting
  our new admin gates (same override fix); (3) meshcore channels yaml-save
  test now expects private_channels alongside channel_keys. Final: ruff
  clean + 960 tests / 68 subtests green on ubuntu. CI = the only place the
  fastapi/aiosqlite tests run (Mac can't); check the Actions tab after
  pushes. Chart.js on the RF tab loads from CDN (index.html) — offline
  dashboards skip the histogram; vendoring = candidate task.

**Chart.js vendored locally (2026-07-09, "easy" candidate task picked up):**
Same rationale/pattern as `frontend/vendor/xterm/` and `frontend/vendor/qrcode/`
(both already document "vendored so it works with no outbound CDN access").
Pulled `chart.js@4.4.4` UMD bundle (`dist/chart.umd.min.js`, 205749 bytes,
`window.Chart = An` confirmed at tail of file — matches both consumers'
`window.Chart`/`new Chart(...)` usage) into NEW
`frontend/vendor/chartjs/chart.umd.min.js` + README (same table/license/refresh
format as the other two vendor READMEs). `index.html` script tag repointed
from the jsdelivr CDN URL to `vendor/chartjs/chart.umd.min.js`. Used by
`node_metrics_chart.js` (node drawer) and `rf_tab.js` (RF Environment
histogram) — both already read the global, no JS changes needed. Verified:
`node --check` on the vendored file, no leftover CDN references in
index.html, changelog bullet added under "Dashboard and operator tools"
(folded next to the existing RF histogram sizing fix). NOT yet Pi-verified
(no CDN egress needed now, so nothing to newly test beyond "does the page
still load the charts" — low risk, same file that was already loading fine
from the CDN).
  MESSAGING INCIDENT (same morning, NOT a merge bug): MeshCore channel
  sends timed out AND incoming channel msgs stopped reaching chats, while
  adverts still hit the packet feed. Logs: repeated "get_contacts: 0
  contacts parsed", "auto message fetching restarted", "health probe
  missed (1/2)". DIAGNOSIS: companion's COMMAND channel wedged while its
  push-event stream kept working — sends (commands) unacked, channel-msg
  auto-FETCH (command-based) dead, adverts (push) fine. Merge ruled out by
  diff: meshcore chat routing + tx client untouched (only Meshtastic hash
  lookup was refactored into ChannelHashResolver). FIX: Pi reboot → full
  round-trip verified (send + HA bot reply in chat, -37 dBm). RECOVERY
  DRILL for next time: (1) systemctl restart meshpoint, (2) RST button on
  the Heltec (NOT USB replug — inrush), (3) only then suspect software.
  Note: user runs a MeshCore HA bot ("light on/off/help") on this channel.
  RF CURIOSITY: sweep shows a NEW strong flat block ~863.6–864.2 MHz at
  ~-60 dBm (SRD audio sub-band — wireless mics/audio links nearby);
  RFID plateau still present but quieter (~-80). Watch list.
  NOTE: full `unittest discover` HANGS on Mac (terminal PTY tests) — run
  per-module with `timeout 60` instead.
- **NEVER put Co-Authored-By/AI trailers in commit messages (user: "never
  ever").**

**Post-merge polish round (2026-07-09 afternoon, all user-requested):**
- RF Environment moved from telemetry-rail link into the Radio sidebar group
  (Hardware · RF Environment · RTL-SDR) + palette entry; rail is status-only
  again (dead .telemetry-rail__rf-* CSS left in place).
- Band Spectrum card moved Hardware → RF Environment page: rf_tab.js hosts
  it (`#rf-band-spectrum` grid-span div + minimal fetch api adapter), card's
  auto-refresh gating generalized to closest('[data-section]'), Hardware
  slot/mount removed. GOTCHA THAT BIT: card lifecycle is mount() THEN
  render(config) — render triggers first load + unhide; forgot render →
  invisible card. Also: card now stays visible with "no sweep yet"
  placeholder (10s retry while empty) instead of hiding on fetch failure;
  hides only when endpoint says available:false.
- RF tab histogram page-growth fixed earlier same day (fixed-height
  .rf-histogram-wrap — Chart.js maintainAspectRatio:false needs it).
- Meshtastic Configuration card: computed SF/BW/CR/Sync/Preamble tiles →
  normal r-readout-row entries in the two-col grid; channels block got
  dashed-divider separation (.r-mt-channels). User-verified, matches
  MeshCore companion card.
- **Update history built then REPLACED (2026-07-09):** the apply/rollback
  action log (`history.py`, `GET /api/update/history`, "Recent updates" list)
  shipped in 50eed38 but the user saw a single sparse "apply … → …" row and
  wanted **the last 5 commits on GitHub with their messages** instead
  ("not what we installed but whats on git commited"). REMOVED entirely
  (module, endpoint, 4 route appends, test_update_history.py, 2 route tests;
  leftover data/update_history.json on the Pi is inert). REPLACED with
  `list_branch_commits(repo_path, ref)` in install_status.py — `git log -n 5
  --format=%h%x09%ct%x09%s origin/<branch>` (matches existing `git log *`
  sudoers rules, both safe.directory forms) → `remote_commits` in
  build_install_status_payload (keyed off version_branch = compare_branch or
  install branch). Freshness = as of last fetch (Check for updates / apply
  both fetch). Frontend: same .update-history CSS block, title "Latest
  commits", data-update-commits[-list] attrs, `_renderRemoteCommits()` called
  from _loadInstallStatus + _checkForUpdates (date + cyan code SHA + subject;
  --failed modifier dropped, __what code style added). 5 new unit tests in
  test_update_install_status.py (18 pass on Mac); live-verified on the Mac
  repo (5 real origin/main commits render from the function). Changelog
  bullet rewritten in place (still 63), README fork bullet reworded.
- Changelog now 63 bullets, parser-verified. All pushed by user
  incrementally; CI green through the round.

## OLD LIST (superseded, kept for the DONE details)

User has been committing incrementally with the suggested one-liners (verified
in git log: 6825153 webport, 3181804 fallback, 0118767 fixes 1/2/4, 1d700a9
relay card, 8c8893c SNR+drawer). Tree clean apart from this memory file.

| # | Prio | Effort | Task |
|---|------|--------|------|
| T1 | CLOSED 2026-07-08 no-change | S | RESOLVED BY DESIGN: user screenshot of MeshCore feed shows nb: neighbour_advert rows now display SF8 (the 2026-07-05 stamp/backfill fix worked; old "blank FREQ/SF" note predated it). Only RSSI shows `--` — correct: neighbour reports carry SNR only, no RSSI exists to show. No code change; do not re-open |
| T2 | DONE 2026-07-08 | S | ROOT CAUSE FOUND via read-only DB query on Pi: all 16 outliers (RSSI -4..-18) were REAL near-field readings — meshcore nodeinfo adverts from 2 desk nodes (3dbda079a456, b9c1b47f8ab6) during Jul 5-6 flashing sessions, not a decoder bug. FIX: `RSSI_NEAR_FIELD_CEILING_DBM = -20.0` in signal_analyzer.py filters rssi >= -20 from get_signal_summary + get_rssi_distribution (also kills 0.0 placeholders); stats_routes.py `_get_best_signal` SQL now `rssi < -20`. SNR untouched. Unit-tested with stubbed aiosqlite (Mac has no aiosqlite — stub `sys.modules['aiosqlite']` trick). Changelog bullet under Dashboard and UI (39 total). FOLLOW-UP same day: session-view path (stats_reporter.py record_packet, was `rssi < 0`) now uses the shared constant too — unit-tested; farthest-direct `rssi < 0` at :109 intentionally left (node >0.1mi can't be near-field). USER-VERIFIED live: Best RSSI tile went −4 → −22 dBm, histogram edge now −30 |
| T3 | DONE 2026-07-08 | check | Drawer "Recent Packets" browser-verified on BOTH protocols (Meshtastic Kalmma HQ 15 rows + MeshCore ORDVRP2 6 rows, 12-hex id match confirmed). Caught+fixed: RSSI showed raw float (-94.39999389648438) — now toFixed(1) on RSSI+SNR matching drawer Signal style. Changelog: folded into the existing recent-packets bullet (no separate bullet — fix to an unreleased feature) |
| T4 | DONE 2026-07-08 | M | Concentrator Channels card on Hardware page. NO new endpoint — GET /api/config enriched with `concentrator` key: `_concentrator_status()` in config_routes.py rebuilds the plan via the SAME `ConcentratorChannelPlan.from_radio_config()` call the capture source makes (hardware-free), serializes 9 channels (ch/freq/BW/SF 0=multi/syncword 0x34 vs 0x2B per wrapper truth/rf_chain same rule as wrapper/enabled) + radio_0/1_mhz + `active` ('concentrator' in capture.sources; card hides when absent). Frontend: NEW radio_concentrator_card.js (RadioConcentratorCard, reuses ch-table classes, disabled rows dimmed, link to configuration/radio), slot after r-card-config in radio_settings.js, script tag in index.html. Plan logic Mac-verified against real config (exact 9-row table); fastapi route + card render need Pi verification after deploy. FOLLOW-UPS same session (user requests): (1) "Radio Configuration" card renamed **"Meshtastic Configuration"** and now embeds the Meshtastic channel table (`_renderChannels` in radio_config_card.js, ch-table markup + masked PSK + edit link); standalone Channels card removed — RadioChannels class DELETED (radio_channels.js rm'd, script tag removed; radio_channels.CSS KEPT — ch-table styles used by merged table + concentrator card). (2) Concentrator card's "Region & frequency settings" link removed (plan layout is fixed in software). NOTE user asked "hardcoded or from settings?" — answered: card reads GET /api/config, computed from live radio settings via same from_radio_config call as the source; only plan LOGIC is code. (3) Hardware card polish round (user-directed): Meshtastic channel table made IDENTICAL to MeshCore's (plain `ch-table`, # + Name only, `--locked` rows, disabled shown as "(off)" suffix; PSK/hash/state columns dropped — hash on edit page, on-count in label line); MeshCore Companion top tiles → same `r-readout-grid` label/value rows as Meshtastic card; NodeInfo Broadcast card moved BELOW companion; then concentrator moved 1 up (final order: concentrator, config/meshtastic, companion, nodeinfo) |
| T5 | DONE 2026-07-09 | M | **Multiple Meshtastic USB sticks** — list-field treatment for `serial` source, same shape as MeshCore's `meshcore_usb` list. `config.py`: new `SerialDeviceConfig` (serial_port/serial_baud/label) + `CaptureConfig.serial: list[...]` (default `[]`) + `_coerce_serial_devices()`, popped in `_apply_yaml` before the generic merge (mirrors `_coerce_meshcore_usb`). Legacy top-level `capture.serial_port`/`serial_baud` scalars are UNTOUCHED and still work for single-stick installs — the list is purely additive/opt-in, zero migration needed. `serial_source.py`: added `label` param, `name` property → `serial_<label>` (was hardcoded `"serial"`), `capture_source=self.name` in `_packet_to_raw_capture` (was hardcoded `"serial"`, same bug class as the pre-fix MeshCore source). `main.py`/`server.py` `_add_serial_source()` now loops `config.capture.serial` (falling back to a single-item list built from the legacy scalars when empty) instead of adding exactly one source. REAL BUG CAUGHT BEFORE IT SHIPPED: read the actual installed `meshtastic-python` source (`mesh_interface.py`) and confirmed every `SerialInterface` publishes received packets on ONE process-wide pypubsub topic (`"meshtastic.receive"`) via `pub.sendMessage(topic, packet=asDict, interface=self)` — with 2+ `SerialCaptureSource` instances, each instance's `_on_receive` callback would fire for EVERY stick's packets (cross-attribution/duplication), not just its own, since the old code ignored the `interface` arg entirely. Fixed with an identity guard: `if not self._running or interface is not self._interface: return`. This is exactly the kind of bug that would only surface live with two sticks plugged in, not in code review. Tests: `test_config_loader.py` (+`SerialDeviceConfigTest`, 6 cases: defaults, coercion, YAML pop/merge, legacy-scalar-unaffected), NEW `test_serial_source.py` (naming + the pubsub guard verified directly: same-interface accepted, different-interface ignored, not-running ignored), NEW `test_multi_serial_pipeline.py` (main.py `_add_serial_source` loop, legacy-fallback + multi-device — Mac-runnable) + `test_multi_serial_pipeline_server.py` (same for server.py, CI-only like test_update_routes.py since server.py needs fastapi). 21 tests pass on Mac; py_compile clean on all 4 touched src files. Docs: CONFIGURATION.md (`capture.serial` example + full-config listing), README (433 MHz section), CHANGELOG (folded into "Multi-radio capture" category, 65 bullets, parser-verified). NOT yet Pi-verified live with two Meshtastic sticks (no second stick confirmed connected this session) — logic + pubsub fix verified by unit test with a fake interface object, not real hardware.
| T6 | DONE 2026-07-08 | L | **Band spectrum card** built. Backend: SpectralScanService grew SWEEP MODE (spectral_scan_service.py) — sweep_frequencies_hz list scanned sequentially (~50ms each, one-at-a-time with noise scans), envelope stored as `latest_sweep` dict (points: freq_mhz/floor/median/p95_dbm); auto every `radio.spectrum_sweep_interval_seconds` (NEW config field, default 300, 0=on-demand only, in default.yaml) + `request_sweep()` wakes loop early via asyncio.Event in `_sleep_until_next`. Sweep freqs from region band via NEW `ConcentratorChannelPlan.band_limits_hz()` accessor, 100 kHz steps (EU868 = 71 pts, ~few s/sweep) computed in server.py `_sweep_frequencies_hz()`. NEW spectrum_routes.py: GET /api/device/spectrum (viewer-open) + POST /sweep (admin); init_routes(service) in lifespan after start (listener pattern, None-safe → available:false → card hides). Frontend: NEW radio_spectrum_card.js — canvas envelope (median cyan filled + p95 purple thin, legend), channel markers dashed (LoRaWAN blue L0-L4 / Meshtastic green MT / MeshCore amber MC from config.concentrator+meshcore), hover tooltip nearest point, admin Sweep-now btn (polls until new generated_at), **fullscreen ⛶ btn** (requestFullscreen on card, :fullscreen CSS grows canvas to ~100vh — user-requested for small screens), 60s auto-refresh gated on radio section active. Slot between concentrator and meshtastic cards. CSS appended to radio_cards.css (spectrum-* classes). Mac-verified: syntax all pass + sweep loop unit test with FAKE wrapper (immediate first sweep, on-demand refresh, clean stop; NOTE SpectralScanResult needs nb_scan arg in fakes). Pi-verify after deploy: real sweep timing, route, card render. **DEPLOYED + LIVE-VERIFIED 2026-07-08 afternoon**: card renders (71 pts, 1.77s sweeps). Pi needed `radio.sx1261_spi_path: \"/dev/spidev0.1\"` in local.yaml (was empty → spectral scan disabled since forever; noise pill had silently been packet-derived). LIVE DATA EXPOSED A REAL HAL BUG: p95 < median / floor > median at some points → **M1's libloragw returns histogram levels DESCENDING**, percentile() walked assuming ascending (also means the noise pill floor was computed from the wrong histogram end all along). FIXED in sx1302_spectral_scan.py: `sorted(zip(levels, counts))` before the walk + fallback `max(levels)`; Mac-tested with descending fixture (floor -88 <= median -84 <= p95 -84 ✓). Changelog bullet added (43). Curiosity RESOLVED (3 consecutive sweeps): the raised-median plateau spans ~865.6-867.5 MHz = exactly the ETSI UHF **RFID band** (EN 302 208, 865.6-867.6, up to 2W ERP) — a real nearby RFID reader (shop/warehouse/logistics), not a scan artifact. Peaks to -75 dBm. First real-world catch by the spectrum card. POLISH per user after seeing it live: fullscreen ⛶ button AND header stats subtitle (pts/duration/time) REMOVED — "in the tile it's ok enough"; header is now just title + Sweep now. Don't re-add. PERCENTILE FIX USER-VERIFIED live (screenshot: peak >= median everywhere, p95 spike at 866.4 behaving correctly). README updated same day: "What's Different in This Fork" grew 2 new groups — "Hardware page & spectrum" (6 bullets: spectrum card+sx1261_spi_path note, concentrator card, unified cards, drawer packets, SNR chart+near-field filter, relay tuning UI) and "Roles, config & self-update" (viewer lockdown, dashboard.port launcher, fork self-update); API table +2 spectrum rows |
| T7 | P3 | — | Later inspection: 6 kept duplicate endpoints (packets/count+protocols+types, nodes/map+summary, telemetry/*) |
| T9 | DONE 2026-07-09 | M | **Serial Meshtastic capture crash + silent packet loss, found LIVE the moment the user actually plugged in their 433 MHz stick and enabled [[T5]] for real** (`serial_source: Serial capture started on /dev/ttyUSB1` in the boot log, then an immediate `Pipeline error: TypeError: object of type 'MeshPacket' has no len()`). All three bugs pre-existing in `serial_source.py`, untouched by the T5 change itself — this was simply the FIRST time this exact code path had ever executed live on this box (previously only `concentrator`+`meshcore_usb` were configured). Root-caused by reading the ACTUAL installed `meshtastic-python` source (not guessing) and cross-checking against a real `MeshPacket` protobuf built with `meshtastic.protobuf.mesh_pb2` under `/opt/homebrew/bin/python3.11` (the Mac's default `python3` is 3.14 with no `meshtastic` package at all — needed the other interpreter for this verification). Three findings: (1) `packet.get("raw", b"")` is ALWAYS the actual protobuf `MeshPacket` object (`mesh_interface.py` literally does `asDict["raw"] = meshPacket` — no such "raw" field exists on the message itself), never bytes, so the old `if not raw_bytes` truthiness check never fell through to `_reconstruct_raw()` — a protobuf object is truthy, so it flowed downstream as if it were bytes and crashed on `len()` in `meshtastic_decoder.py`. (2) `_reconstruct_raw()`'s payload read `packet.get("encoded", b"")` and hex-decoded it — verified via `MessageToDict()` on a real MeshPacket that the actual field name is `encrypted` (matches the protobuf descriptor field list) and the encoding is **base64**, never hex; `"encoded"` never matched any real key so the payload was silently always empty even when the fallback did fire. (3) DEEPER FINDING, more important than the crash: the fallback was gated `if not raw_bytes and "decoded" in packet`, but `encrypted`/`decoded` are the SAME protobuf `oneof` (verified via `MeshPacket.DESCRIPTOR.oneofs`) — mutually exclusive. A packet the connected stick's OWN key COULDN'T decrypt (traffic on a channel it isn't configured for — exactly what a passive multi-channel sniffer most wants to catch) has `encrypted` set and NO `decoded` key at all, so the gate silently DROPPED it entirely, never even attempting reconstruction, before Meshpoint's own decoder/`channel_keys` ever got a chance. Fixed by removing the `"decoded"` precondition — `_reconstruct_raw()` already defaults every field it reads via `.get(key, default)`, so it's safe unconditionally (confirmed it now NEVER returns empty bytes, even for a near-empty dict — the trailing `if not raw_bytes: return None` guard is effectively unreachable now, left in place, harmless). All three fixes verified TWICE: once with unit tests using a `_FakeMeshPacket` sentinel (non-bytes/non-str, matches the type-check without needing the real protobuf lib under the test runner's python3.14), and once end-to-end against the REAL `meshtastic.protobuf` library for both scenarios (encrypted-only/foreign-channel packet → now captured correctly with real ciphertext in the payload tail; locally-decoded packet on the stick's own channel → the exact scenario from the user's log → no crash, valid header-only frame as intentionally documented in the method's own docstring). 11 tests pass in `test_serial_source.py` (5 new/rewritten this round). Changelog bullet added under "Multi-radio capture" (67 bullets, parser-verified). NOT yet re-verified live on the Pi after this fix — user needs to redeploy and re-check the boot log / packet feed for the 433 stick.

**Added a TEMPORARY debug log** in `_packet_to_raw_capture` (marked "TEMPORARY DEBUG (remove once confirmed)") logging packet dict keys + rxRssi/rssi/rxSnr/snr at INFO level, to check whether the identical `-100 dBm / 0.0 dB` shown on every reconstructed packet in the drawer is a real characteristic or a 4th bug. **RESULT (user ran it live):** `keys=['decoded', 'from', 'fromId', 'hopLimit', 'id', 'priority', 'raw', 'to', 'toId']` — no rxRssi/rssi/rxSnr/snr keys at all. CONFIRMED: this specific class of reconstructed packet (one the connected radio's own key DID decrypt locally — `decoded` present, `encrypted` absent per the oneof) genuinely doesn't carry signal telemetry in this dict shape; `-100/0.0` is the code's fallback, working as designed, not a new bug. Also revealed a DEEPER finding worth a future look: since `decoded` IS present for these packets (meaning the stick successfully decrypted them itself), `_reconstruct_raw()` currently still produces a HEADER-ONLY frame (ignores `packet["decoded"]` entirely) and Meshpoint's own decoder then correctly fails to decrypt an empty payload → shows "Type: unknown / No matching key" even though the ACTUAL decoded content (portnum, payload) was sitting right there in the dict. Not fixed this round (real feature work, not a bug fix — would need a second code path that builds a Packet directly from `packet["decoded"]` instead of forcing everything through raw-frame-reconstruction+re-decrypt); flagged to the user as a candidate follow-up, not yet actioned. Debug log line still in place pending explicit removal.

**FOLLOW-UP BUG same evening, found by the user noticing the MeshCore topbar chip went to "No companion" (red)** after they correctly added `label: '868'` to their previously-unlabelled MeshCore companion (my own suggestion, to get the band-tag chip). Root-caused precisely: `_find_meshcore_source()` in `src/api/server.py` (used by `_build_tx_service` to bind `MeshCoreTxClient` to the live capture source, AND by the startup advert-send block) did an EXACT match `src.name == "meshcore_usb"` — the moment the companion's `.name` became `"meshcore_usb_868"`, this returned `None` silently. No crash, no log error: `meshcore_tx.set_source()` never ran → `tx_svc.meshcore_enabled` (`"MC=False"` in the boot banner, confirmed by diffing against the FIRST successful boot's log which showed `MC=True` and a `MeshCore TX client bound to live capture source` line that was now simply absent) → `/api/config`'s `mc_status["connected"]` stayed `False` forever → topbar stuck red. **MeshCore receive/capture was never affected** — that path already correctly used `startswith("meshcore_usb")` in `coordinator.py` from the earlier multi-companion work; this was a SEPARATE, missed call site, same bug class, never triggered before because nobody had ever labelled a MeshCore companion on this box until this session. Fixed: `src.name == "meshcore_usb"` → `src.name.startswith("meshcore_usb")` (picks the first match with multiple companions, consistent with the existing "companion[0] is primary" convention elsewhere e.g. the backward-compat single-companion PUT endpoint). New `tests/test_find_meshcore_source.py` (4 cases: unlabelled/labelled/multi-companion-picks-first/absent) — CI-only (fastapi import, same pattern as `test_multi_serial_pipeline_server.py`). py_compile clean. Changelog bullet added under "Multi-radio capture" (68 bullets, parser-verified). NOT yet re-verified live — user needs to redeploy/restart and confirm the topbar goes green + `MC=True` + advert-sent log line reappears. |
| T8 | DONE 2026-07-09 | S | **Band tag on node UI** (requested as a prerequisite check before plugging in the 2nd 433 MHz Meshtastic stick to verify [[T5]]). Sizing this up surfaced a real pre-existing gap worth flagging: `serial_source.py`'s `_packet_to_raw_capture` hardcodes `frequency_mhz=906.875` (a US915 placeholder) on EVERY Meshtastic-serial-captured packet regardless of the stick's actual EU_433/EU_868 firmware — meshtastic-python doesn't expose real per-packet frequency, so whoever wrote this originally just baked in a static number. NOT fixed this session (separate, harder problem — would need reading region/channel config off the interface, akin to how MeshCore's `self_info` fix worked); explicitly NOT used as the tagging signal for that reason. Built instead on `capture_source` (config-driven via the T5 `label` field, immune to the frequency bug). Backend: `node_repository.py` `get_all_with_signal()` join gained `p.capture_source AS latest_capture_source` (one more column on the existing latest-packet subquery, threaded through `_enrich_row`); `get_by_id`/`GET /api/nodes/{id}` deliberately left untouched since the drawer's `open()` merges `{...node, ...detail}` and the enriched list-view object already carries the field through. Frontend: `_bandLabel(captureSource)` helper (duplicated in `node_cards.js` and `node_drawer.js`, matching the existing `_roleName` duplication convention in this repo) maps `*_433`→"433 MHz", `*_868`→"868 MHz", bare `concentrator`→"868 MHz" (fixed EU868 service-channel plan), else no badge. Chip added to node_cards.js `_buildMeta()` (new `.nc-chip--band` CSS, purple accent) and a "Band" row in node_drawer.js's info section. NOTE: only the main Node Discovery flow (`GET /api/nodes` → node_cards.js → drawer) carries this; the per-protocol Meshtastic/MeshCore tabs use separate `/api/meshtastic/nodes` / `/api/meshcore/nodes` endpoints that were not touched (scope decision, not an oversight). Tests: new `test_get_all_with_signal_reports_latest_capture_source` in `test_node_repository.py` (inserts a node + packet with `capture_source="serial_433"`, asserts the enriched row carries it) — CI-only (aiosqlite, same as the rest of that file, unrunnable on Mac). py_compile + `node --check` clean. Changelog bullet added under "Multi-radio capture" (66 bullets, parser-verified). NOT yet Pi-verified live (no second 433 stick plugged in yet this session).

| T10 | DONE 2026-07-09 | M | **Real region/frequency/SF/BW/coding-rate for `serial` Meshtastic capture + a topbar badge per USB stick** — user's follow-up after [[T8]]'s band tag and [[T9]]'s crash fix: they noticed the packet feed still showed `906.9 MHz` for every packet from the 433 stick and asked for both a topbar badge (like MeshCore's) and the frequency fixed. Root cause (same class as [[T8]]'s flagged-not-fixed gap, now actually fixed): `serial_source.py` never did a connect-time handshake at all. FIX mirrors MeshCore's `self_info` pattern exactly: verified `meshtastic-python`'s `StreamInterface.__init__` already calls `waitForConfig()` SYNCHRONOUSLY before `SerialInterface(...)` returns (confirmed by reading `stream_interface.py`), so `interface.localNode.localConfig.lora` + `interface.getShortName()/getLongName()` are populated immediately after connect, no extra async wait needed. New `SerialCaptureSource._read_radio_info()` (static method) reads region (protobuf enum → string via `RegionCode.Name()`), channel_num, and EITHER the named modem preset (`use_preset=True` → `ModemPreset.Name()` → looked up in the EXISTING `src.radio.presets.get_preset()` table, reused rather than reinvented — this also surfaced that `LONG_FAST`'s real coding rate is `4/5`, not the `SignalMetrics` dataclass's generic `4/8` default, ALSO silently wrong before this fix) OR the raw custom `spread_factor`/`bandwidth`/`coding_rate` fields when `use_preset=False` (`coding_rate` is stored as just the denominator, e.g. `6` means `4/6`). New `_default_frequency_mhz(region, channel_num)` + `_REGION_DEFAULT_MHZ` dict (mirrors `concentrator_config.py`'s `_REGION_DEFAULTS_HZ` — same US/EU_868/ANZ/IN/KR/SG_923 values in MHz instead of Hz — plus a NEW `EU_433: 433.875` entry the concentrator table never needed, since the M1's SX1302 is 868-only hardware; 433.875 is the documented EU_433 LongFast default, supplied by the user from their own research and cross-checked). CRITICAL SAFETY RULE self-imposed: frequency is ONLY reported when `channel_num == 0` (the firmware's hash-derived default channel) — a non-zero (custom) channel_num returns `0.0` (this codebase's established "unknown" sentinel, matching the pre-fix MeshCore convention) rather than guessing, since replicating Meshtastic firmware's channel-hash formula wasn't verifiable from the Python library alone. `_packet_to_raw_capture` now uses all of these (falling back to LongFast defaults only if the handshake didn't populate a field) instead of the old unconditional `906.875`/`11`/`250.0` triple-hardcode. API: new `_find_serial_sources()` in `server.py` (returns ALL serial sources in order — unlike MeshCore's single "TX-bound primary", every serial device is passive-capture-only with no TX to bind, so there's no single "the" device) wired into `config_routes.init_routes(serial_sources=...)`; new `_serial_status_entry()` reuses `_default_frequency_mhz` so the badge and captured packets can never disagree. Frontend: NEW `topbar_serial_chip.js` (`TopbarSerialChip`, one small cyan badge per configured device — connected lamp/label/region/freq, DOM-built not innerHTML) + `#topbar-serial-group` container in index.html + CSS in topbar.css, wired into `topbar_controller.js` alongside the existing Meshtastic/MeshCore chips. Backfill: NEW `scripts/backfill_serial_meshtastic_signal.py` (mirrors the existing `backfill_meshcore_signal.py` pattern exactly — dry-run by default, `--capture-source`/`--freq`/`--sf`/`--bw`/`--apply` flags) to correct old rows still carrying the `906.875` marker; verified end-to-end against a scratch sqlite DB matching the real schema (fixed the `serial_433` row, correctly left an unrelated `concentrator` row untouched). Tests: NEW `test_serial_radio_handshake.py` (6 cases: LongFast preset parse, custom-config parse, frequency-only-when-channel-0, broken-interface-doesn't-raise) — run for real against `/opt/homebrew/bin/python3.11` (has the real `meshtastic` package; bare Mac `python3` is 3.14 without it) since `meshtastic>=2.3.0` is a declared dependency so CI has it too; NEW `test_find_serial_sources.py` + `test_serial_status_entry.py` (CI-only, fastapi-gated, same convention as `test_find_meshcore_source.py`). All verified end-to-end against the REAL protobuf library before considering done (not just mocks) — same rigor as [[T9]]. Changelog bullet added under "Multi-radio capture" (69 bullets, parser-verified). **LIVE-VERIFIED 2026-07-09 evening:** user ran the backfill dry-run (68 rows matched exactly, time range sane) then `--apply`; packet feed confirmed both fresh AND backfilled `serial_433` rows now show `433.9 MHz` (was `906.9`), matching the MeshCore feed's `869.6` for comparison; the repeating `!06f4` "unknown" packet (the undecryptable-by-design one from [[T9]]) now correctly shows the right frequency too, still opaque content-wise as expected. Topbar badge font-size was initially too small vs the other two chips (0.62rem vs 0.7rem, plus a missing brand-divider/glow) — fixed to match exactly (padding, font-size, brand border-right divider, 7px lamp dot) per user screenshot feedback. |
| T11 | DONE 2026-07-09 | M | **Configuration → Serial page** — Meshtastic USB device list editor in the dashboard (add/remove/label, no more hand-editing `local.yaml`), mirroring the existing Configuration → MeshCore "USB capture sources" card exactly, minus the auto-detect toggle (`SerialDeviceConfig` has no such field — a blank port already means "let meshtastic-python auto-detect"). User's own reasoning for wanting this: "editing the local.yaml could introduce mistakes" (validated by the SAME session's earlier `label: 'meshcore_usb_868'`-instead-of-`'868'` mixup — a UI with typed fields prevents exactly that class of error). Backend: `system_config_routes.py` — new `SerialDeviceEntry`/`SerialDevicesUpdate` pydantic models + `PUT /api/config/capture/serial-devices` (new `_serial_device_dict()` helper), built by copying `update_meshcore_companions`/`_meshcore_usb_dict` line-for-line and adapting field names (`serial_baud` not `baud_rate`, no `auto_detect`). `config_enrichment.py` gained `capture.serial` (list of `{serial_port, serial_baud, label}` dicts) so the form can pre-populate — deliberately a DIFFERENT key path than the top-level `serial` status list from [[T10]] (`cfg.serial` = live connected/frequency status for the topbar; `cfg.capture.serial` = static config for the edit form; same split MeshCore already uses between `cfg.meshcore` and `cfg.capture.meshcore_usb`, no collision). `identity_routes.py`'s `_ADMIN_SECTIONS` tuple needed `"configuration.serial"` added explicitly (found by reading the code, not assumed) — otherwise the frontend's generic `_buildRouteGuard` (derives `configuration.<section>` from the route and checks membership) would have blocked admin access to the new page entirely; viewer-locked same as MeshCore/Radio (not in `_VIEWER_SECTIONS`). Frontend: NEW `frontend/js/configuration/serial_card.js` (`SerialConfigCard`, reuses the existing `.cfg-companion`/`.cfg-companions` CSS classes verbatim — no new CSS needed), new sidebar sub-item + `#cfg-serial-panel` section + script tag in index.html, mount branch in `configuration_panel.js`, route + command-palette entries in `app.js` (`configuration/serial`). Tests: NEW `test_serial_devices_route.py` (8 cases, calls the async route handler directly bypassing FastAPI's TestClient since no existing harness covers this router — `save_section_to_yaml` mocked to inspect the yaml payload without touching disk; CI-only, fastapi-gated) + NEW `test_config_enrichment.py` (3 cases, Mac-runnable for real — `config_enrichment.py` has zero fastapi dependency, unlike most of this session's other new test files). py_compile + `node --check` clean; 29 total Mac-runnable tests pass this session. Changelog: folded into the existing "Multiple Meshtastic USB sticks" bullet (still 69 bullets, parser-verified) rather than a new one, since this completes that same feature. **LIVE-VERIFIED 2026-07-09 evening** (user screenshot): Configuration → Serial page rendered correctly, pre-populated the existing `433` device from `local.yaml` (port `/dev/ttyUSB1`, baud 115200), matched the sidebar/topbar visual style of the other pages. User reaction: "nice" — no follow-up issues. |
| T12 | DONE 2026-07-09 | L | **Serial Meshtastic "Unknown" packets from locally-decoded content now show their real type** — user compared their 433 feed (every `!06f4` packet showing "unknown") against 868/concentrator (healthy mix of Position/Telemetry/NodeInfo/Encrypted) and asked why. ROOT CAUSE (same oneof mechanism flagged as a future candidate back in [[T9]], now actually built): `encrypted`/`decoded` share ONE protobuf oneof on `MeshPacket` — a packet the connected 433 stick's OWN key decrypts locally has `decoded` populated (portnum + payload, already parsed by meshtastic-python) and `encrypted` EMPTY, so the OLD code's raw-frame-reconstruction-then-redecrypt path always got a header with zero payload bytes and correctly-but-uselessly landed on "Unknown" — the concentrator never hits this because it captures real over-the-air ciphertext directly off the SX1302 (no meshtastic-python, no oneof), so IT can show "Encrypted" for undecryptable packets (real bytes, no key) vs 433's structural "Unknown" (no bytes at all, upstream threw them away). FIX = a proper second decode path, not a tweak: `RawCapture` (models/packet.py) gained an optional `pre_decoded: dict` field (`{portnum: int, payload: bytes, request_id: int}`); `MeshtasticDecoder.decode()` (meshtastic_decoder.py) takes a new `pre_decoded` kwarg — when set, calls `dispatch_portnum()` directly (the SAME portnum-handler table `src/decode/portnum_handlers.py` already used for concentrator-decrypted packets, reused not duplicated) instead of running the PKI/channel-key crypto loop, changed `if CryptoService.is_pki_packet(...)` to `elif` so the new branch and the old crypto path are mutually exclusive and existing behavior is byte-for-byte unchanged when `pre_decoded=None` (verified: diffed 8 pre-existing local test failures against original code with the SAME crypto stub — identical failures either way, confirming zero regression from the `elif` refactor). `PacketRouter.decode()` (packet_router.py) and `coordinator.py`'s `_process_capture()` thread `pre_decoded` through untouched otherwise. `serial_source.py` gained `_build_pre_decoded(packet)`: reads `packet["decoded"]["portnum"]` (a STRING enum name like `"TELEMETRY_APP"` per protobuf JSON convention — verified against the real `meshtastic.protobuf.portnums_pb2.PortNum.Value()` lookup) + base64 `payload`, returns `None` safely for missing/unrecognized portnums (dispatch never guesses). VERIFIED END-TO-END against the REAL protobuf library (not just mocks): built an actual `MeshPacket` with `TELEMETRY_APP` + a real serialized `telemetry_pb2.Telemetry(device_metrics.battery_level=87)`, ran it through the ACTUAL `serial_source.py` → `MeshtasticDecoder.decode()` pipeline (stubbed only `Crypto.Cipher.AES`, since pycryptodome isn't installed even under the meshtastic-having `/opt/homebrew/bin/python3.11` locally, and the pre_decoded fast path never touches crypto methods anyway — `CryptoService()` constructs fine with a dummy AES since it's only referenced inside method bodies, never at class-def time) — got back `PacketType.TELEMETRY`, `decrypted=True`, `battery_level=87` correctly, confirming the whole chain end to end. Tests: 3 new Mac-portable early-exit cases in `test_serial_source.py` (no "decoded" key / not-a-dict / missing portnum, none need the real library), NEW `test_meshtastic_decoder_predecoded.py` (5 cases incl. the telemetry round-trip, header fields sourced correctly, request_id passthrough, dispatch-failure lands on UNKNOWN never ENCRYPTED, too-short-frame still returns None — CI-only, needs both `meshtastic` AND `Crypto`/pycryptodome, both declared deps so CI has both) + 3 new success-path cases in `test_serial_radio_handshake.py` (real portnum resolution, unrecognized name, missing payload). 32 total Mac-runnable tests pass this session. User supplied `/Users/einstein/Software/meshtastic` (local firmware source clone) as a resource mid-task — not needed for THIS fix (fully verified via the python library + protobuf alone), but earmarked for the [[T10]] channel-hash-frequency gap (computing exact frequency for non-zero/custom `channel_num` needs the firmware's real hash algorithm, unverifiable from meshtastic-python alone — good candidate to revisit with that clone). Changelog bullet added under "Multi-radio capture" (70 bullets, parser-verified). NOT yet Pi-verified live — user needs to redeploy and confirm the repeating `!06f4` packet (and similar locally-decoded traffic) now shows a real type (likely Telemetry/NodeInfo/Position) instead of "Unknown". |

| T13 | DONE 2026-07-09 | L | **Real channel-hash frequency computation for `serial` Meshtastic capture, replacing [[T10]]'s per-region-guess table.** Direct follow-up: user asked me to "have a look" at `/Users/einstein/Software/meshtastic` (a local firmware source clone they supplied) to close the exact gap flagged at the end of T10 (non-zero/custom `channel_num` reported `0.0`/unknown). Reading `src/mesh/RadioInterface.cpp` (`applyModemConfig`) revealed T10's fix was itself subtly wrong as a general rule, not just incomplete: the hardcoded `EU_433: 433.875` "default" was only correct BY COINCIDENCE for this user's specific channel name — EU_868's narrow band (869.4-869.65 MHz) only fits exactly ONE 250kHz slot so its default IS deterministic regardless of channel name (hence T10's EU_868 value was always right), but EU_433 (433.0-434.0 MHz) fits FOUR slots (433.125/433.375/433.625/433.875), and which one is "default" depends on `djb2_hash(primary_channel_name) % 4` — a completely different channel name would land on a DIFFERENT one of those four, and T10's code would have kept reporting 433.875 regardless, silently wrong for anyone else's setup. Extracted from firmware source and verified: (1) the exact formula `freqSlotWidth = spacing + padding*2 + bw/1000; numFreqSlots = round((freqEnd-freqStart+spacing)/freqSlotWidth); freq = freqStart + bw/2000 + padding + slot*freqSlotWidth`, where `slot` = `channel_num-1` (explicit, 1-based per protobuf) or `hash(name) % numFreqSlots` (default/auto); (2) the exact djb2 hash (`hash=5381; hash=hash*33+c` per byte, 32-bit wraparound) from `RadioInterface.cpp`'s own `hash()`; (3) the exact region band table (freqStart/freqEnd per region) from the `regions[]` array, confirmed all 7 currently-supported regions (US/EU_433/EU_868/ANZ/IN/KR/SG_923) use PROFILE_STD or PROFILE_EU868 (both spacing=0,padding=0 — identical simplified math); (4) `Channels::getName()`'s fallback when the channel's own name is blank: hashes the MODEM PRESET's firmware display string instead (e.g. "LongFast" for LONG_FAST) — and this list is NOT identical to this codebase's own `src/radio/presets.py` UI labels: firmware's LONG_MODERATE hash-string is **"LongMod"**, not "LongModerate" — using the wrong one would have silently computed a wrong slot, so a SEPARATE verified table was built rather than reusing presets.py's display_name. VALIDATION: computed the full formula by hand for EU_433 with `channel_name=""` (blank) + LONG_FAST preset → `djb2("LongFast") % 4 == 3` → `433.875 MHz`, reproducing the user's actual live-observed value EXACTLY, byte-for-byte, before writing a single line of implementation code. New `src/radio/channel_frequency.py` (`resolve_frequency_mhz()`, `_djb2()`, `_preset_hash_name()`, `_REGION_BAND_MHZ`, `_PRESET_HASH_NAME` table) — handles `override_frequency` (verbatim, wins outright) and `frequency_offset` (fine-tune, added at the end) too, both real LoRaConfig fields not previously read. Added a self-imposed safety guard beyond firmware's own behavior: an explicit `channel_num` that exceeds the region's actual slot count now returns 0.0/unknown rather than computing a nonsensical out-of-band number (firmware itself REJECTS such configs at set-time, so a real device never reports one out of range, but the guard is cheap insurance). `serial_source.py`: `_read_radio_info()` now also reads `use_preset`, `frequency_offset`, `override_frequency`, and NEW `_read_primary_channel_name()` (searches `interface.localNode.channels` for `role==PRIMARY`, returns `.settings.name` — confirmed `waitForConfig()` populates `channels` synchronously same as `localConfig`, no extra wait needed); `_default_frequency_mhz()`/`_REGION_DEFAULT_MHZ` DELETED entirely, replaced by `resolve_frequency_mhz()` calls in both `serial_source.py` (packet stamping) and `config_routes.py`'s `_serial_status_entry()` (topbar badge) — same invariant as T10, badge and packet feed can never disagree since both call the identical function. User also asked mid-task: "what happens if I have a LongFast channel from 868 but also from 433" — confirmed by design this can't collide: each capture source reads its OWN device's config independently, and the two regions have different band math (868 deterministic single-slot vs 433's 4-slot hash), so identical channel names on different regions/devices simply produce different frequencies, with `capture_source` (`serial_433` vs `serial_868`/`concentrator`) providing a second layer of disambiguation regardless. Tests: NEW `test_channel_frequency.py` (21 cases, Mac-portable, zero meshtastic dependency — djb2 known-values, default-channel hash resolution incl. the LongMod-not-LongModerate regression guard, explicit-channel slot math, the out-of-range guard, override_frequency, missing-region/bandwidth edge cases); updated `test_serial_radio_handshake.py` (new primary-channel-name read test, updated frequency assertions to call the new module) — 53 Mac-portable + 32 real-meshtastic-interpreter tests pass this round. Changelog: rewrote the T10 bullet in place to describe the real computation instead of the old per-region-guess table (still 70 bullets, parser-verified) rather than add a new one, since this fully supersedes rather than adds to that feature. **LIVE-VERIFIED 2026-07-09 evening:** clean full restart, boot log shows `serial_source: Serial capture started on /dev/ttyUSB1 (region=EU_433 channel_num=0)` and the packet feed correctly kept showing `433.9 MHz` post-redeploy — computed fresh via the real formula now, not the old hardcoded table, same visible result confirming no regression. |

| T14 | DONE 2026-07-09 | M | **Serial Meshtastic sticks no longer capture their own self-telemetry as spammy/confusing packets.** Direct follow-up to the `-100 dBm / 0.0 dB` mystery from [[T12]]/[[T13]]: after confirming via firmware source (`RadioLibInterface.cpp`: `"We assume if rx_snr = 0 and rx_rssi = 0, the packet was generated locally"`) that the repeating `!06f4 telemetry` packets were likely the connected 433 stick's OWN periodic self-report (not a remote node), asked the user to verify definitively via a live check: `sudo systemctl stop meshpoint` → one-off `meshtastic.serial_interface.SerialInterface` query using Meshpoint's OWN already-installed venv (no separate CLI tool needed, since `meshtastic` is already a declared dependency) → `iface.myInfo.my_node_num` → `0x9d406f4`, an EXACT match to `09d406f4`. Confirmed: the connected stick's own self-originated packets (NodeInfo/Telemetry it generates about itself, never actually received over the air) pass through the identical `"meshtastic.receive"` event stream as genuinely-received remote packets — meshtastic-python doesn't distinguish them — so they were flowing through decode/storage/the packet feed/node counters as confusing `-100 dBm` readings roughly once a minute. User's own framing: "it really spams our logs and displays and counters, maybe even drop own packages" + suggested adding a node ID to local.yaml/webinterface. DECISION (explained to user, they didn't push back): skip the manual-config idea entirely — the stick's own node number is ALREADY readable live from the SAME connect-time handshake already built in [[T10]]/[[T13]] (`interface.myInfo.my_node_num`, populated by the same `waitForConfig()` that already populates `localConfig`/`channels`), so zero config needed and it can never go stale if the stick is swapped/reset. FIX: `serial_source.py` — `_read_radio_info()` gained `own_node_num` (try/except-protected like every other handshake field); `_packet_to_raw_capture()` checks `packet.get("from") == own_node_num` as the VERY FIRST thing (before raw_bytes reconstruction, before pre_decoded building) and returns `None` immediately on a match — cheapest possible point to kill the noise, before ANY downstream processing touches it; logged at `debug` level (not `info`) so the fix itself doesn't just relocate the spam into the logs. Exposed via API: `config_routes.py`'s `_serial_status_entry()` already spread `**info` so `own_node_num` flows through automatically; added a formatted `own_node_id_hex` (e.g. `"09d406f4"`) alongside it. Frontend: `topbar_serial_chip.js` shows the detected ID (short `"!06f4"` form, matching the packet feed's own node-ID style) in the badge's hover tooltip — visible, not hidden magic, per the user's "webinterface" ask. Tests: NEW `DropSelfOriginatedPacketTest` in `test_serial_source.py` (4 cases, Mac-portable — self packet dropped, remote packet still captured, unknown own_node_num doesn't drop anything, missing "from" field doesn't crash) + one new assertion in `test_serial_radio_handshake.py`'s existing LongFast preset test (`own_node_num` correctly read) — 57 Mac-portable + real-meshtastic tests pass this round, verified end-to-end against the real protobuf library before any test was written (built a fake self-packet + a fake remote packet, confirmed the drop logic discriminates correctly). Changelog bullet added under "Multi-radio capture" (71 bullets, parser-verified). **LIVE-VERIFIED 2026-07-09 evening:** user confirmed via the topbar badge tooltip (screenshot: "This stick's own node ID: !06f4 (its self-telemetry/nodeinfo is filtered from the packet feed)") that the detected ID matches, then confirmed no NEW `!06f4 telemetry` packets appeared for 6+ minutes after the restart (checked at 17:36, last one at 17:30) — the drop is working live. Historical rows from before the fix (packets + the phantom `!09d406f4` node entry, sitting at a permanent stale `-100 dBm`) don't get cleaned up retroactively by the capture-side fix, so built a FOLLOW-UP: new `scripts/purge_self_originated_node.py` (dry-run by default, `--apply` flag, matches the established backfill-script convention) takes a node ID (accepts the `!`-prefixed dashboard display form directly, e.g. `'!09d406f4'`), deletes matching rows from `packets` (by `source_id`), `telemetry`, `messages` (both by `node_id`, found by checking `database.py`'s full `CREATE TABLE` list for every column that could reference a node), and the `nodes` row itself. Verified end-to-end against a scratch DB matching the real schema before handing it over: correctly removed the phantom node's 2 packets/1 telemetry row/1 node row while leaving an unrelated node completely untouched. Changelog: folded into the same T14 bullet (still 71, parser-verified) since it's a direct cleanup companion to that fix, not a separate feature. **LIVE-VERIFIED 2026-07-09 evening:** user ran `--apply` on the Pi themselves; dashboard screenshot afterward confirms `!09d406f4` is gone from both the node list and the packet feed, "Nodes Discovered" dropped 120→119 (exactly the one phantom row removed), no other nodes affected. T14 fully closed end to end: capture-side filter verified live (no new self-packets since restart) + historical cleanup verified live (purge script ran clean). |

| T15 | DONE 2026-07-09 | S | **Topbar USB Serial badge didn't show "reconnecting" during a dashboard restart, unlike the Meshtastic/MeshCore chips.** User noticed via screenshot: on a `meshpoint` restart, the Meshtastic chip blinks amber "reconnecting" and MeshCore shows "Reconnecting… -- -- --", but the Serial badge just silently kept showing its last-known (now stale) region/frequency with no visual change. ROOT CAUSE: my own gap from building [[T10]]'s topbar chip — `topbar_controller.js`'s `_wireWebSocket()` calls `this._meshcore.setDashboardReachable(...)` on every websocket connect/disconnect/init-state check (3 call sites), but `TopbarSerialChip` never had a `setDashboardReachable()` method at all, and nothing called into it, so it had zero awareness that the websocket (and likely the whole backend) had dropped. FIX: `topbar_serial_chip.js` now caches `_lastDevices` (was rendering directly from `setSerial()` before, no cache) and adds `setDashboardReachable(reachable)` mirroring `TopbarMeshcoreChip`'s exact semantics — when unreachable, every badge's lamp goes amber/blinking (`topbar-serial__lamp--reconnecting`, reusing the SAME `topbar-meshtastic-blink` keyframe MeshCore's lamp already uses) and region/frequency blank to `--`, while the device `label` (e.g. "433") stays visible since that's static identity, not live status. New CSS `.topbar-serial--reconnecting`/`.topbar-serial__lamp--reconnecting` mirror MeshCore's amber border-glow treatment exactly. `topbar_controller.js`'s `_wireWebSocket()` now calls `this._serial.setDashboardReachable(...)` at all 3 existing call sites alongside the MeshCore call. Also fixed the constructor default from `true` to `false` to match `TopbarMeshcoreChip`'s exact initial-state convention (avoids a one-frame flash of "assumed connected" before `_wireWebSocket()` runs). Changelog: folded into the existing topbar-badge bullet under "Multi-radio capture" (still 71, parser-verified) since it's a fix to a feature from earlier this same session, not a new one. NOT yet Pi-verified live — user needs to redeploy and confirm the Serial badge now blinks amber during a restart same as the other two. |

| T16 | DONE 2026-07-09 | S | **USB Serial topbar badge restructured to match the Meshtastic/MeshCore chips' layout** — user compared the 3 badges side by side and asked: since it's known to be Meshtastic (captured via serial), say "Meshtastic" not "USB"; replace the "433"/"868" config label with the node ID, then freq, then "the channellist ... same as the first meshtastic and the meshcore". Checked `topbar_meshtastic_chip.js` before assuming anything: its trailing segment ("LONGFAST") is actually the MODEM PRESET, not a channel name — already read at connect time in [[T10]] (`dev.modem_preset`), so no backend change needed, pure frontend restructure. New layout: `Meshtastic | ● lamp | !06f4 (own node ID, "call sign" slot) | region | freq | preset` — dropped the standalone label text entirely since region (EU_433 vs EU_868) already disambiguates devices at a glance, matching the user's framing that the label was mostly redundant now. `_formatPresetLabel()` duplicated from `topbar_meshtastic_chip.js` (same enum-name strings, both read via `ModemPreset.Name()`) per this repo's established small-helper-duplication convention. CSS: renamed `.topbar-serial__label` → `.topbar-serial__call` (bigger/bolder, matching the "call sign" style), added `.topbar-serial__preset` + `.topbar-serial__sep--bar` mirroring the Meshtastic chip's exact styling, extended the existing offline/reconnecting dimming rules and the medium-width responsive hide-rule to the new preset element. [[T15]]'s reconnecting-state work (built same session, just before this) already covers the new elements for free — reconnecting still blanks region/freq/preset to `--` and shows `----` for the call slot. NOT yet Pi-verified live — user needs to redeploy and visually compare all 3 badges. |

| T17 | DONE 2026-07-09 | S | **Self-drop guard from [[T14]] was silently eating the user's own chat messages, not just self-telemetry.** User connected the OFFICIAL Meshtastic app to the SAME physical 433 Heltec stick over BLE (Meshpoint has it on USB serial simultaneously — firmware fans out packets to all attached client transports), sent "Nou dan ook maar op 433 :)" via that app on the LongFast primary channel, then asked why it never appeared in Meshpoint's own Messages panel ("i still cant see any longfast for 433 ... where is that chat and do you read it from the meshtastic serial?"). Investigated `_setup_message_interception()` (`src/api/server.py`) first — confirmed it's fully protocol/capture-source-agnostic (`coord.on_packet(on_text_packet)` fires for ANY `PacketType.TEXT` packet regardless of source) and `ChannelHashResolver.lookup()` (`src/api/channel_hash_resolver.py`) falls back to bucket 0 for unmapped hashes, so routing wasn't the bug. ROOT CAUSE found in `serial_source.py`'s `_packet_to_raw_capture()`: a message sent from the BLE app to the SAME physical stick makes that stick its own packet's "from" node — [[T14]]'s self-originated drop (`packet.get("from") == own_node_num`) fired unconditionally on ANY portnum, including `TEXT_MESSAGE_APP`, deleting the packet before decode/storage/Messages ever saw it. The drop was only ever meant for routine self-reported beacons (telemetry/nodeinfo/position), not user-composed chat sent via another client on the same radio. FIX: added an `is_text` check (`packet["decoded"]["portnum"] == "TEXT_MESSAGE_APP"`) that exempts text messages from the self-drop — telemetry/nodeinfo/position from the stick's own node num are still dropped exactly as before, only chat content now survives. Tests: new `test_self_originated_text_message_is_not_dropped` in `test_serial_source.py` (20 total Mac-portable cases in that file now, all pass). Changelog: folded into the existing T14 bullet under "Multi-radio capture" (still 71 bullets, parser-verified) since it's a correction to that same fix, not a new feature. NOT yet Pi-verified live — user needs to redeploy, then send another BLE-originated chat message on the 433 stick's LongFast channel and confirm it now shows up in Meshpoint's Messages panel. |

| T18 | DONE 2026-07-09 | S | **SenseCap M1 onboard LED/button/fan GPIO probe — all three pins confirmed live.** User wants to use the expansion-board LED for incoming-message notification, the CPU button for double-tap-reboot/triple-tap-shutdown, and the fan for temperature-driven control — asked first for the GPIO numbers and a test script, since no schematic is publicly available for this board. Initial research (WebSearch/WebFetch) only corroborated **GPIO 22 (LED)** (a community teardown + a Seeed `dtoverlay=gpio-led,gpio=22,...` snippet agreed); the user's own guesses of button=13/fan=14 were UNVERIFIED from any source and turned out wrong when tested live (`scripts/test_gpio_hardware.py fan --fan-pin 14` did nothing; button similarly silent). Rather than keep guessing pin-by-pin, added `button-scan` (reads a batch of 16 candidate pins simultaneously via `gpiozero.Button`, pull_up=True, for 20s while the user mashes the button, reporting which pin(s) toggle) and `fan-scan` (single Enter-confirmation, then pulses each candidate pin HIGH for 0.4s in turn with a `Testing GPIOxx...` announcement, so the user can correlate the announcement with the fan spinning up) — both skip pins already known to be reserved on this board (SPI0 7-11 = concentrator bus, confirmed via existing `/dev/spidev0.x` config elsewhere in the repo; I2C1 2-3 = ATECC608 crypto chip + temp sensor per the teardown; HAT ID EEPROM 0-1; concentrator reset 17/25 from `reset_concentrator.sh`; GPIO 22 = LED). **Live results:** `button-scan` → GPIO27 toggled on every press (confirmed button pin); `fan --fan-pin 13` → fan audibly spun up and stopped (confirmed fan pin — note this is NOT the user's original guess of 14, it's the OTHER original guess, for the button, repurposed — a good reminder that guessed pin/peripheral pairings can be right-pin-wrong-peripheral, not just wrong entirely). Script defaults updated to the confirmed values (`LED_PIN_DEFAULT=22`, `BUTTON_PIN_DEFAULT=27`, `FAN_PIN_DEFAULT=13`); `RESERVED_PINS` also grew to include 13/27 so future re-scans (e.g. if this needs re-deriving on different hardware) don't re-test known-good pins. Changelog bullet added under "Import and maintenance scripts" (still parser-verified). All three peripherals are now safe to build real features on: LED-on-incoming-message (trivial — toggle from the existing message-broadcast callback in `_setup_message_interception`), button double/triple-tap (small debounce+counter state machine), fan-by-temperature (reuse whatever temp reading the RF Environment tab already surfaces) — NONE of these built yet, this task was scoped to hardware identification only; revisit when the user asks for the actual feature. |

Older wishlist (idea-level): LoRaWAN CSV/TTN export; LoRaWAN MIC verification;
light theme (medium-large, dark-first CSS);
DAB+ via welle-cli (NPO Radio 5); true-RF S-meter via pyrtlsdr; EU433 LoRaWAN
plan (needs 433 concentrator, not the M1). Meshtastic firmware source available
locally at /Users/einstein/Software/meshtastic (user-supplied) — already used for
[[T13]]'s channel-hash frequency formula AND [[T14]]'s self-telemetry diagnosis;
good resource for any future question needing firmware-level (not just
meshtastic-python-level) ground truth.

Suggested order: T3 → T2 → T1 → T4, then by mood.
