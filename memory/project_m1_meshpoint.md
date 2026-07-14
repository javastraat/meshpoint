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

### 2026-07-11 follow-up: LoRaWAN packet-detail consistency fix

- Root cause: same LoRaWAN packet could render different decrypt status in Packet detail depending on entry point.
  - Dashboard live feed uses websocket packet objects that include `decrypted`.
  - LoRaWAN tab used `GET /api/lorawan/packets`, which did not include `decrypted`.
- Fix: `src/api/routes/lorawan_routes.py` now selects and returns `decrypted` for each packet row.
- Result: opening the same LoRaWAN packet from Dashboard or LoRaWAN tab now shows the same decrypt state.

### 2026-07-11 follow-up #2: Dashboard LoRaWAN modal readability

- Problem: Dashboard modal showed only "No matching key" for some LoRaWAN packets and hid already-decoded header/MAC metadata, while LoRaWAN tab still showed JSON.
- Fix: `frontend/js/packet_detail_modal.js` now keeps LoRaWAN decoded JSON visible even when `decrypted === false` (no app session keys), and suppresses CR rendering for LoRaWAN modem rows so Dashboard and LoRaWAN-tab labels stay consistent.

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
`serial` source has SINCE gained the same treatment — `capture.serial` list,
source name `serial_<label>`, e.g. `serial_433`; see backlog #7 DONE.)

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

#### Live device config drift — RESOLVED 2026-07-11
The M1 (`pi@192.168.2.189`, service config at `/opt/meshpoint/config/local.yaml`)
now runs THREE sources: `concentrator` + `meshcore_usb` label "868" at
/dev/ttyUSB0 + `serial` list label "433" at /dev/ttyUSB1, plus repeater_poll
(1 repeater @ 15 min), led/fan/button enabled, mqtt, frozen node_id 0xc3ecf862.
User copied the live file into repo `config/local.yaml` (2026-07-11) — verified:
gitignored (.gitignore:27, secrets safe) and loads cleanly through
`load_config()` on the Mac (all dataclasses populated correctly).
Still open suggestion: `/dev/serial/by-id/usb-Silicon_Labs_CP2102_...` paths
instead of ttyUSB0/1 for robustness if more USB devices get added.

## Repeaters UI split + zero-filter (2026-07-10)

- Frontend `repeaters_tab` now renders each repeater as a two-card unit: one
  card for radio/health identity + one dedicated Sensors card.
- LPP sensor channels where every numeric reading is exactly 0 are now hidden.
  This suppresses dead channels like Ch2 current/power/voltage all at 0.
- Added responsive CSS so paired cards collapse to a single column on narrow
  screens.
- Follow-up visual polish: stronger card hierarchy (subtle layered background,
  improved spacing/typography), plus Sensors card meta label (`N ch · M vals`).

## MeshCore DB import (2026-07-10)

- Root `meshcore.db` contains `contacts`, `neighbours`, `telemetry_history`,
  `status_history`, and `neighbour_history` tables.
- Best-win import target is the telemetry history subset that maps to Meshpoint's
  flat telemetry model: voltage, one temperature stream, humidity,
  barometric_pressure, and uptime_seconds.
- New importer script writes raw history into `packets` (JSON payload for the
  unmapped fields) and summary telemetry rows for the chartable fields.
- Importer defaults to the live archive URL `https://einstein.amsterdam/meshcore/meshcore.db`;
  local `--source-db /path/to/file.db` remains available as an override.
- Contacts and neighbours are now true upserts (overwrite on conflict instead of
  ignore), and `--telemetry-only` limits the import to chartable telemetry rows
  while skipping nodes and packet history.
- Added `--contacts-only` to refresh just the contacts/neighbours roster while
  skipping packet and telemetry history entirely.
- Telemetry import now prefers environmental temperature channels per timestamp:
  channel 4 first, then 3, then channel 1 MCU die temp only as a fallback.
- **freq/SF/BW stamping added 2026-07-11** (was hardcoded NULL): all
  `meshcoredb:%` synthetic rows now stamp the companion's radio settings via
  `--freq/--sf/--bw` (defaults 869.618 / SF8 / 62.5), same treatment as the
  `nb:` rows in import_contacts.py, so they don't render blank freq/SF in the
  feed. RSSI stays NULL except status_history `last_rssi` rows (the archive
  chain only records SNR — verified against meshcore.db schema). Mac-verified
  end-to-end: real script run against local meshcore.db into a scratch DB
  built from src/storage/database.py schema — 33,611 rows all stamped, 715/715
  neighbour rows SNR-present, 907 real last_rssi values preserved.
- **NOT changelogged — BY DESIGN (user, 2026-07-11): standalone scripts are
  operator tooling, never in CHANGELOG.md or README.** The CLAUDE.md changelog
  rule applies to app code only.

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
| 5 | ~~P2~~ DONE 2026-07-08 | M | Of the 8 unused endpoints only 2 carried NEW data (verified: /api/stats/summary already embeds rssi_distribution + protocol/type dists — the old "wire 5" plan would have re-plotted duplicates). WIRED: `/api/analytics/signal/snr` → SNR histogram card on Stats next to RSSI (purple #a855f7, clone of _updateRssiHist, fetched via Promise.all in refresh(), NOT part of session/all-time toggle — last-500-packets only); `/api/packets/by-source/{id}` → "Recent Packets" collapsible section in node drawer (last 15: time · type · RSSI/SNR; source_id==node_id, both 8-hex no `!`). KEPT for later inspection per user (NOT pruned): /api/packets/count+protocols+types, /api/nodes/map+summary, /api/telemetry/{id}(+history) — all duplicate data already on screen via other endpoints. SNR chart browser-verified (screenshot 2026-07-08: renders next to RSSI, bimodal far/near clusters; drawer packets not yet checked). NOTE spotted in screenshot: "Best RSSI −4 dBm" implausible → near-field filter SINCE BUILT (verified in code 2026-07-11): `RSSI_NEAR_FIELD_CEILING_DBM = -20.0` in signal_analyzer.py (avg/min/max) + stats_reporter.py (session accumulators) + `rssi < -20` in stats_routes.py `_get_best_signal`. Whole inspection backlog now closed |
| 6 | ~~P3~~ DONE 2026-07-08 | L | Spectrum view — built as T6 (Band Spectrum card, see OLD LIST): sweep mode + /api/device/spectrum + canvas card, live-verified; later moved to its own RF Environment page |
| 7 | ~~P3~~ DONE (verified in code 2026-07-11) | M | Meshtastic `serial` multi-device — `capture.serial` list of `SerialDeviceConfig` (+label) in config.py, `_add_serial_source` loops it in server.py, source name `serial_<label>` (serial_source.py). Legacy scalar serial_port/serial_baud still works. Live on the Pi as `serial_433` (banner-verified 2026-07-10) |
| 8 | ~~P3~~ CLOSED by-design 2026-07-11 | S | `nb:` rows: freq/SF/BW already stamped since 2026-07-05 (importer --freq/--sf/--bw + backfill script). RSSI stays blank FOREVER by design: neighbours.json carries only SNR (no RSSI exists to fill), and live receptions create new complete rows — synthetic rows are never retro-edited (would conflate our radio path with the remote repeater's). User accepted 2026-07-11 |
| 9 | ~~P3~~ DONE 2026-07-08 | M | Concentrator-channels card — built as T4 (see OLD LIST): radio_concentrator_card.js + `concentrator` key in GET /api/config, live on Hardware page |

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
2 more bullets → 38). #6 was in fact DONE the same day as T6 (Band Spectrum
card), #9 too (T4, Concentrator Channels card), and #7 too (multi
Meshtastic serial — live as `serial_433`; all three lines were stale until
2026-07-11). Remaining open: #8 nb: blank RSSI cosmetic.

---

## What it does NOT do (intentional)

- LoRaWAN payloads NOT decrypted (need AppSKey/NwkSKey from the network)
- LoRaWAN NOT on the map (no position in LoRaWAN packets)
- LoRaWAN NOT relayed (ever)
- MeshCore NOT relayed (ever — listen only)
- Meshtastic 433 (Heltec V3 serial) packets handled by existing `serial` source —
  they decode and appear in dashboard like any Meshtastic packet

---

## CURRENT WORKLIST v6 (2026-07-12 end of day — supersedes v5 below; THE list to work off)

Closed since v5 (full narrative/build detail lives in the v5 section below,
kept for history — this is just the summary): the whole RTL-SDR listener
buildout — P2000/Pagers/POCSAG/RTL433 tabs (4 new dongle-sharing decoder
tabs alongside Radio, `src/audio/pager_listener.py` + `src/audio/rtl433_listener.py`
+ `src/audio/sdr_registry.py`), the sidebar "dongle in use" green-dot badge
(`frontend/sidebar/listener_badge.js`, including a same-day `POLL_MS`
naming-collision bug fix), the Digital/Analogue skin toggle + status pill
relocation into the Radio tab's own card (plus the follow-on uppercase/bold
CSS-inheritance fix and red busy-dot addition), 24-hour time + column-width
fixes on the pager/RTL433 message logs, `scripts/install.sh` gaining
RTL-SDR/redsea/multimon-ng/rtl_433 sections (rtl_433 via apt, not
from-source, after live-testing both approaches), and the RF Environment
page's new Stray Frames card (W14) — built as an in-memory ring buffer on
purpose, and after real runtime showed the volume is low enough that the
user explicitly decided the ring buffer is sufficient (no persisted DB
table needed, that open question is now closed).

Also closed: a real incident where the RTL-SDR dongle got wedged at the
USB/kernel level after heavy tab-cycling during testing (POCSAG/Radio/
RTL433 all briefly failed) — diagnosed as hardware-level, not a code bug,
and resolved by a full reboot. A genuine software bug found and fixed
along the way: rtl_433 was silently discarding its own crash reason when
run without `-F log`, now fixed so future failures are actually diagnosable.

| # | Status | Effort | Item |
|---|--------|--------|------|
| — | Open | S | Prune or document the 6 kept-for-later duplicate API endpoints (packets/count+protocols+types, nodes/map+summary, telemetry/*) |
| — | Open | M | Server-side downsample-across-range for the Repeater Trends chart — a fixed high limit (`hours=100000&limit=50000`) will eventually start truncating again as live polls keep growing the row count unbounded |
| W18 | DONE 2026-07-12 | S-M | **Mini RTL-SDR player widget.** See closure paragraph below. |
| W6 | Open | M-L | True-RF S-meter via pyrtlsdr — real dBm instead of post-demod audio loudness |
| W5 | DONE 2026-07-13, LIVE-VERIFIED | M-L | **DAB+ tab via welle-cli — fully closed.** See closure paragraph below. |
| — | DONE 2026-07-13 | S | **DAB+ channel tabs no longer auto-tune on click.** Real bug the user hit live: "i am on c11 and switch tabs it tunes to that ab and my listening stops" -- clicking ANY channel tab (even just to peek at another channel's station list) immediately retuned and killed current playback, because `_switchChannelTab()` treated "view this tab" and "tune to this channel" as the same action. Asked the user to confirm the fix design before building it (per their "tel me first"): browsing a channel tab becomes a pure view switch with no side effect; a channel tab that isn't the one actually running shows a "Not currently tuned to X" prompt plus an explicit **Scan** button ("Stops the current station and retunes to this channel"), and the already-tuned channel's own tab gets a **Rescan** button (user confirmed both: "rescan is fine :)") to force a fresh decode without leaving the tab. Both buttons drive the exact same `_tune(channel)` call via one shared `data-dab-scan-channel` attribute -- Scan and Rescan are the same action, just surfaced in two different states. Favorites deliberately keeps its existing immediate-tune behavior (picking a favorite already means "play this now", unlike passively browsing a tab). `node --check`ed; CHANGELOG bullet corrected in place (parser-verified) -- the earlier wording claiming tab-clicks tune "unless already running" was accurate when written but became stale after this fix. |
| — | DONE 2026-07-13 | S | **DAB+ VFD readout: big name, small channel code (swapped from big channel code, small ensemble label).** User screenshot showed `11C`'s secondary slot reading the literal string "DAB+" -- not descriptive, since that's genuinely what welle-cli decodes as `11C`'s real ensemble label (confirmed via the earlier live scan: `9C`'s real label is likewise just the literal string "9C"). Discussed two options before building: always follow the live decoded ensemble label (simple, but shows those two unhelpful literals), or prefer our own curated preset name when we have one. User picked the hybrid explicitly ("hybrid for now, later we will implement the scan and a json orso" -- referencing the already-tracked "GUI-triggered scan → persisted JSON presets" idea a few rows up as the eventual generalization). Implemented: the big VFD slot now shows `DAB_CHANNEL_PRESETS`'s curated `name` when the tuned channel matches a known preset (Commercial/Throwback/etc), falling back to the live `ensemble_label` for anything else (e.g. a manually-tuned channel with no curated name, where the live value is all there is and fills in as it decodes) -- and the channel CODE moved down into the small secondary slot (previously the reverse). Added a `[data-dab-channelnum]`-scoped font-size override (`clamp(26px, 6vw, 44px)`, down from the shared `.lsn-freq__num`'s `clamp(40px, 9vw, 64px)`) since names like "Commercial" run longer than FM's numeric frequency digits that class was originally sized for. `node --check`ed; CHANGELOG bullet extended in place (parser-verified). |
| — | DONE 2026-07-13 | S | **DAB+ VFD readout swapped again: now-playing station/RadioText big, channel+name small.** User, looking at a live screenshot of the previous round's layout (big "Commercial", small "11C", station text still stuck in the small tag row): "swap the presetname with the rds, so qmusic text is on top bigger and presetname and channel next to the pop music indicator... its because it was taken from radio where we needed alot of space for the freq" -- correctly diagnosing that the big/small hierarchy was inherited wholesale from the Radio tab's layout (where the big slot makes sense for frequency digits) without reconsidering what's actually glanceable-important for DAB+ (the station name/RadioText, not which channel it's on). Swapped the two blocks: the `.lsn-freq` big slot now holds the now-playing marquee text (`data-dab-nowplayingtext`, reusing the exact same `_renderNowPlaying()`/`_setNowPlayingText()` logic from the previous layout unchanged -- only the DOM position and a new `.lsn-station__text--big` CSS modifier for VFD-cyan sizing changed, `clamp(20px, 4.5vw, 32px)` since a full "station — RadioText" sentence is longer than a channel name), and the old channel-code-then-name display was consolidated into one small `data-dab-chantag` span (e.g. "11C · Commercial") placed in the tag row next to the SNR/PTY pills (`margin-left: auto` to push it to the right, matching where it visually landed in the user's own mockup-by-request). Removed the now-dead `[data-dab-channelnum]` font-size override from the previous round since that element no longer exists. `node --check`ed; CHANGELOG bullet extended in place (parser-verified) to describe both readout rounds. |
| — | DONE 2026-07-13 | S | **Radio tab's presets restyled to match the DAB+ tab's list look.** User: "we have this nice dab channel layout and look tabs etc do it also on the radio tab, there we know wich channels belong to wich tab (group)" -- the group→tab mapping already existed (`PRESET_GROUPS`, one category tab per group + Favorites, exactly like DAB+'s channel tabs), only the visual style needed to change: `.lsn-presets` went from a wrapped chip grid to a vertical list of rows (star, name, frequency on the right), and `.lsn-preset-tab`'s border-radius changed from a full pill (999px) to 8px to match `.lsn-tabbar__btn`'s shape (kept Radio's own cyan accent rather than switching to DAB+'s green, consistent with the rest of this tab's cyan-themed VFD/active-preset styling). No click-handling changes needed in `listener_panel.js` -- the existing delegated click listener already used `closest('button[data-freq]')` on the whole row element, so adding two new `<span>` children (label, frequency) to `_btn()`'s markup didn't require touching the event logic at all. `node --check`ed; CHANGELOG bullet extended in place (parser-verified). |
| — | RESOLVED 2026-07-13 | — | `scripts/dab_channel_scan.py` run live on the Pi — full 38-channel scan found `7D`/`8B`/`11C`/`12C`; `9C` read "nothing" on that run but decoded fine (SNR 7 dB, 15 stations) on an isolated retest, a false negative from back-to-back channel switching (fixed: settle gap 0.5s→1.5s, default timeout 20s→30s). Current DAB+ presets (`7D`/`8B`/`9C`/`11C`/`12C`) already match every channel confirmed live at this antenna — no preset changes needed. |
| — | Open | M | **GUI-triggered scan → persisted JSON presets, read on page load.** User's idea (2026-07-13): instead of (or alongside) the hardcoded `DAB_CHANNEL_PRESETS` array in `dab_panel.js`, let a user trigger a scan from the dashboard itself; write the results (channel, ensemble label, SNR, station list) to a JSON file on disk, and have the DAB+ tab read that file to populate its channel presets on load. Makes the preset list self-discovered per-deployment (right for THIS antenna's actual reception) instead of something I have to hand-curate and get wrong (see the dead `6C` preset, sourced from a different city's scanner data). Needs: (a) a background-task version of the scan (full 38-channel run takes ~13-19 min at the new 30s/channel default, too long for a synchronous request — likely a `POST /api/dab/scan/start` + `GET /api/dab/scan/status` poll pair, same shape as the update-check system's own background-task convention); (b) refactor the scan logic out of `scripts/dab_channel_scan.py` into something both the CLI script and the API route can call, rather than duplicating it; (c) a results file (e.g. `data/dab_channels.json`) the DAB+ tab fetches instead of (or merged with) the static preset list. Not yet designed in detail — flagged as a good next DAB+ enhancement, not started. |
| — | Open | S | **"Check for updates" for the Meshtastic serial stick's firmware, mirroring the MeshCore Companion card's version-check button (2026-07-13, DONE).** Configuration → Serial now shows the connected stick's firmware version (`2.7.26.54e0d8d`, live-verified) but has no comparison against the latest available Meshtastic firmware release yet — the same gap MeshCore's Companion card just closed. Would need: (a) confirming the actual Meshtastic firmware release repo/tag format (likely `meshtastic/firmware` on GitHub, NOT verified yet — don't assume, research first like both MeshCore features did) and how to compare against the reported `firmware_version` string shape (`2.7.26.54e0d8d` -- looks like `MAJOR.MINOR.PATCH.<hash>`, a different shape from MeshCore's `vX.Y.Z-hash`, so the existing `_semver_and_hash()`/`_latest_release_version_string()` comparison logic in `meshcore_config_routes.py` can't just be reused as-is without checking); (b) same design defaults as the MeshCore version (manual/on-demand only, no polling, cached briefly, shown right on the Serial card next to the Firmware tile, not the sidebar). Not started -- flagged here per explicit user request to track it. |
| — | DONE 2026-07-13 | XS | **`scripts/install.sh` installs `welle.io` (DAB+).** New section 10 (`apt-get install -y -qq --no-install-recommends welle.io`), right after rtl_433, before the Meshtastic/MeshCore CLI section -- same apt-not-from-source rationale as rtl_433 (package is small, ships both the GUI app and the `welle-cli` binary Meshpoint actually drives). Sections 10-22 renumbered to 11-23 accordingly; `bash -n` syntax-checked after the renumber. README's DAB+ install bullet and the CHANGELOG bullet updated to match (no longer "manual-only"). Not yet run on the Pi -- next fresh/upgrade install.sh run will exercise it for the first time. |
| W4 | Open | L | Light theme — tokenize the dark-first CSS, light map tiles, per-page contrast pass; topbar toggle already has a slot reserved |
| W2 | Parked | M | LoRaWAN key store + MIC verify/decrypt — trigger: you run your own LoRaWAN devices |
| W11 | Parked | M | TTN uplink-only forwarder — trigger: TTN entanglement deemed worth it |
| — | DONE 2026-07-13 | S | **Companion firmware version display.** See closure paragraph below. Splits off the "version check" half of the old combined Noted item below; flashing itself remains separately tracked. |
| — | Noted | — | Firmware flasher (upstream #85/#59) — if flashing the 3 sticks becomes a pain. Source found 2026-07-13: https://github.com/meshcore-dev/flasher.meshcore.io (the actual flasher.meshcore.io site's repo) — not yet investigated for how it could integrate with Meshpoint (likely a browser-based Web Serial flasher, so possibly just linking to it rather than reimplementing flashing ourselves). |
| — | Noted | — | Reticulum as 6th network on the spare Heltec V3 433 (upstream #11) — wildcard |
| — | DONE 2026-07-12 | XS | **Installer installs Meshtastic and MeshCore CLI tools.** User asked for a new `install.sh` section for both; initially wrote `pipx install meshcore-cli` and said "meshtastic command is pipx install meshcore-cli" — a mixup, since `meshcore-cli` is unambiguously the MeshCore package, not Meshtastic's. Asked for clarification rather than guessing the Meshtastic command; user confirmed the mixup and went to find the real one, then supplied `pip3 install --upgrade "meshtastic[cli]" --break-system-packages`. Added as new section 10 in `scripts/install.sh` (right after rtl_433, before the SX1302 HAL build) — kept the two install methods exactly as given rather than harmonizing them (pip3 with `--break-system-packages` for meshtastic-cli since Debian's system Python is PEP 668-protected; pipx for meshcore-cli, isolated per-tool venv). No skip-check/idempotency guard added, matching the plain-apt/pip convention this script already uses for gpsd/rtl_433 (pip/pipx installs are fast and safe to always re-run, unlike the slow from-source builds that DO have skip checks). Noted that `pipx` was already added to the section-1 apt package list (from an earlier, not-narrated edit) so it's available before this section runs. Every subsequent section renumbered 11→22 (was 10→21) — `bash -n` syntax-checked after the renumber. CHANGELOG bullet added (parser-verified); neither tool is used by Meshpoint itself, both are just for admin convenience debugging radios directly from the Pi's shell. Not yet live-verified (the install itself hasn't been run on the Pi). |
| — | Open | S | Retest `scripts/install.sh` on a fresh microSD flash (IS_UPGRADE=0 path — new `meshpoint` user creation, first-time systemd install, SPI/UART/I2C enablement, etc. — none exercised by the upgrade-mode run already done). Upgrade-mode path (IS_UPGRADE=1) is fully LIVE-VERIFIED (twice, including an idempotency-rebuild-after-removal test); still want a genuine fresh-flash run since it exercises a different code branch entirely — now also covers the new Meshtastic/MeshCore CLI tools section, not yet run at all |
| — | Retest | S | Metrics `require_auth`: confirm a valid session actually authenticates a `/metrics` scrape (only the "blocks with no credentials" half was tested live — 401 confirmed correct). Also consider whether a proper long-lived API-key mechanism is worth building instead of reusing short-lived dashboard session JWTs for this, since those expire and are awkward for an unattended Prometheus scrape config. User flagged 2026-07-12, deferred ("its ok for now") |
| — | DONE 2026-07-13 | XS | **P2000 (FLEX) parsing — bug found via real hardware, fixed.** Narrowed 2026-07-12 to "the one genuine remaining gap" (Pagers/POCSAG/RTL433 already proven live; FLEX has its own separate regex, `_FLEX_RE`, flagged unverified against real hardware when built). User ran the exact `rtl_fm -f 169.65M -M fm -s 22050 -l 250 | multimon-ng -a FLEX -t raw /dev/stdin` pipeline manually in a Pi shell and captured a real page: `FLEX|2026-07-13 18:51:53|1600/2/K/A|13.006|002029582 000120161 000120999|ALN|A1 13161 Heesterveld 1102 Amsterdam 67412` — then reported the P2000 tab itself showed nothing despite the log confirming the identical pipeline was running. Root cause: `_FLEX_RE` (`src/audio/pager_listener.py`) was written against a colon/space format guessed from documentation alone (no RTL-SDR hardware existed to test against at build time) — real multimon-ng output is pipe-delimited, a completely different shape. Worse, the "recognized protocol but unmatched format, show it raw anyway" fallback also only checked for a `FLEX:` prefix, so real pipe-delimited pages fell all the way through `_parse_line()` to `return None` — silently discarded exactly like a blank banner line, not even surfaced as raw/unknown. This is exactly why nothing appeared: real pages were arriving and being thrown away, not a reception problem. Rewrote `_FLEX_RE` to match the real pipe-delimited shape; when a page lists multiple space-separated capcodes (simulcast/alternate addressing, confirmed in the real captured line) only the first is kept for the compact capcode column (`m.group("capcode").split()[0]`), full line always preserved in `raw`. Verified directly against the exact real captured line plus edge cases (single capcode, empty-message tone-only `TON` page, a deliberately malformed FLEX line to confirm the fallback-to-raw path still fires instead of vanishing, banner/blank lines still correctly ignored) and a POCSAG regression check (unrelated regex, confirmed untouched) — all via direct Python calls to `_parse_line()`, no stub framework needed since this module has no fastapi/aiosqlite dependency. `ast.parse`-checked. CHANGELOG bullet extended in place (parser-verified) on the existing P2000/Pagers entry. **This closes the last open gap from the P2000/Pagers/POCSAG/RTL433 retest row above** — all four pager-family tabs now confirmed against real hardware/real signals. **LIVE-VERIFIED 2026-07-13**: user redeployed and screenshotted the real P2000 tab — "listening on 169.6500 MHz", two genuine FLEX ambulance-dispatch pages decoded correctly end to end through the actual dashboard UI (`002029582`/`A1 AMBU 17106 Buys Ballotlaan 3045BB Rotterdam ROTTDM bon 109110` and `002029571`/`A2 Strandslag 2A Strandslag 2 SGRAVH : (pat. vervoer, Lifeguards RB)`), timestamp/protocol/capcode/message columns all rendering correctly. P2000/Pagers/POCSAG/RTL433 are now ALL fully closed and live-verified against real signals — no remaining gaps on any of the four pager-family tabs. |
| — | DONE 2026-07-13 | S | **Repeater login stuck on a stale routing path — real production incident, root-caused and fixed.** User report: repeater `da0b77f13bc7` (NL-AMS-R-PD2EMC), which had polled successfully for days (Repeater Trends chart showed its last good sample at 13 Jul 20:19), started failing every login attempt continuously ("login failed or timed out", all 3 retries, every 5-min poll round) for close to an hour. Investigated methodically rather than guessing: (1) confirmed the password was correct and unchanged (`repeater_poll.repeaters[]` in `local.yaml` pasted by user); (2) confirmed the repeater itself was healthy and reachable — user ran `telemetry.sh`, an entirely separate personal script (`/Users/einstein/Software/meshcore`, not part of this repo) connecting via a different physical BLE companion ("MeshCore-PD2EMC TAG1"), and it logged in and pulled full telemetry successfully; (3) confirmed ordinary MeshCore reception through Meshpoint's own USB companion was unaffected the whole time (messages/adverts still flowing normally); (4) user rebooted the Pi (full power cycle) and the exact same failure recurred immediately on the next poll — ruling out a wedged in-process session, since a reboot clears all local state. That combination (repeater reachable+correct password from elsewhere, passive reception fine, reboot doesn't help) pointed away from "repeater down" or "wrong password" and toward something specific to Meshpoint's own companion's routing state that a reboot wouldn't touch. Researched the actual `meshcore` Python library (PyPI package, `fdlamotte/meshcore_py` on GitHub, v2.3.7 — pip show/import unavailable on the Mac dev machine, so fetched the real source via WebFetch rather than guessing from memory) and confirmed contacts cache a routing path (`out_path`/`out_path_len`) used for directed messages like login, with an explicit `reset_path(key)` command that clears it and falls back to flood routing. This exactly explains the whole symptom set: a directed login retries the same cached path forever once it goes stale (e.g. a relay hop it routed through reboots/moves/drops off the mesh — an event that happens elsewhere on the mesh, invisible to Meshpoint's own logs), while flood-routed traffic (adverts, messages) never depends on that path at all, and the stale state lives in the companion's contact list, not in Meshpoint's own process, so a Meshpoint-side reboot can't fix it. Fixed: `poll_repeater()` (`src/transmit/meshcore_tx_client.py`) now calls `self._mc.commands.reset_path(key)` whenever `send_login_sync` returns `None`, wrapped in its own `asyncio.wait_for(..., timeout=10.0)` and a bare `except Exception: logger.debug(...)` so a failure resetting the path can never mask the real login error already being returned — best-effort recovery, not a hard dependency. Verified with a mock `MeshCore` handle (no real hardware/library on the Mac): confirmed `reset_path` is awaited with the correct key exactly once on a login failure and request_status is correctly never reached (short-circuit preserved); confirmed `reset_path` is NOT called on a successful login (no unnecessary resets); confirmed `reset_path` itself raising doesn't change the returned error. Existing `tests/test_repeater_poller.py` (10 cases) still pass unmodified. `ast.parse`-checked. CHANGELOG bullet added (parser-verified) under MeshCore repeaters.

**Follow-up, same day: first fix shipped as a no-op, caught live.** User applied the fix via the dashboard's self-update system (commit `9fe8936`, confirmed via the Updates page showing it as the latest applied commit with a rollback point recorded) and the exact same failure pattern continued unchanged. Root cause: `reset_path(key)` was called with `key` -- the short 6-byte/12-hex-char contact-lookup prefix (`"da0b77f13bc7"`) used everywhere else in this function for `get_contact_by_key_prefix`/`fetch_all_neighbours` -- but `reset_path`'s destination validation (confirmed via WebFetch against the real `meshcore_py` source, `commands/base.py`'s `_validate_destination`) requires a FULL 32-byte public key, raising `ValueError("Invalid prefix len, expecting 32, got 6")` on anything shorter. My own broad `except Exception: logger.debug(...)` around the reset call silently swallowed that error -- exactly the kind of self-inflicted silent failure the original design comment warned against for the *login* error, but didn't protect against for the reset call's *own* internal validation bug. So the reset never actually executed at all; the "fix" was a no-op that looked identical to doing nothing. User then pasted the repeater's actual full public key (`da0b77f13bc793a8166a87000f1c238a769261e7b4200203c0ca1c37b3e3b67b`) -- confirmed independently it's exactly 64 hex chars / 32 bytes and starts with the same short prefix, matching `_validate_destination`'s exact requirement. Fixed: `reset_path(contact)` now passes the already-resolved `contact` object (from the earlier `get_contact_by_key_prefix(key)` call a few lines up), which carries the full `public_key` field the library's dict-shaped destination handling expects. Re-verified with a mock `reset_path` that specifically models the real library's validation behavior (raises `ValueError` for a short bare string, succeeds for a dict) -- confirmed the corrected call passes the full `contact` object, not the short prefix, and would have caught the original bug had this exact test existed on the first attempt. Lesson for next time a `meshcore` library command takes a "destination": check whether it wants the short lookup-prefix `key` (used for `get_contact_by_key_prefix`, `fetch_all_neighbours`'s `pubkey_prefix_length=6` convention) or the full resolved `contact` object/its `public_key` -- they are NOT interchangeable, and a broad `except Exception` around a new call can hide exactly this kind of shape mismatch instead of surfacing it. **Third round, same day: second correction's coverage gap caught live within minutes.** User deployed the `contact`-object fix and watched the very next failure log a DIFFERENT error string than before: `"Repeater da0b77f13bc7 poll failed: timed out"` instead of the earlier `"...failed (login failed or timed out)..."`. Those are two genuinely different branches inside `poll_repeater()` -- the reset call only lived inside the explicit `if login is None:` block, but `asyncio.wait_for()` timing out on EITHER the login call itself or the later `req_status_sync` call raises `asyncio.TimeoutError` that bubbles straight past that inner check into the function's OUTER `except asyncio.TimeoutError: out["error"] = "timed out"` handler, where no reset ever ran. So the corrected-but-narrowly-scoped fix from round 2 still wasn't firing for this failure shape, which is exactly the one the user hit next. Restructured: removed the reset call from inside the narrow `if login is None` branch entirely and moved it into the function's `finally` block, gated on `password and out["error"] and contact is not None` -- now fires uniformly for every failure shape (explicit login-None, login's own timeout, status/telemetry/neighbours timeouts, or a bare exception) rather than one specific one. Verified with 5 scenarios via mocked `wait_for`/`send_login_sync`/`req_status_sync` (temporarily monkeypatching the module's `asyncio.wait_for` to a short real timeout so a slow stand-in coroutine genuinely raises `TimeoutError`, rather than just mocking the exception directly): (1) explicit `login is None` -> reset called; (2) login's own `wait_for` genuinely times out -> reset called (the exact gap just found); (3) `req_status_sync`'s `wait_for` times out -> reset called; (4) full success -> reset NOT called; (5) `reset_path` itself raising doesn't change the reported error. All 10 pre-existing `test_repeater_poller.py` cases still pass. `ast.parse`-checked. CHANGELOG bullet extended in place again (parser-verified).

User also asked directly what was pushed to git around 20:19 (the last good poll, confirmed via the Repeater Trends chart, at a 15-min poll interval) that might explain the sudden onset. Checked `git log --name-only` for that window: nothing landed touches MeshCore/repeater code at all (`src/transmit/`, `src/capture/meshcore_usb_source.py`) -- the only nearby commit (20:13, `df95168`) is the `patch_hal.sh`/install.sh restart-suppression fix, an installer-script-only change with zero code-level connection to the repeater poller. That said, this exact commit exists BECAUSE the user was actively testing the just-fixed "Run install.sh" Terminal quick-command around that same window, and that testing involved REAL `systemctl restart meshpoint` events (some premature, per the bug being fixed). Flagged to the user as the strongest concrete candidate for an actual disruption at that moment (not a code diff, but a real action taken around the same few minutes) -- not yet confirmed either way. **Fourth round, same day: deployed, reset genuinely fires now, but the theory itself may be wrong.** User deployed the broader-coverage fix and pasted a fresh full service-startup log. Confirmed the reset now runs on literally every failed attempt with no exception -- `"Reset cached routing path for repeater da0b77f13bc7 after poll failure (timed out)"` logged on all 3 attempts in the round -- yet the poll still timed out on every single one of those 3 attempts anyway. This is the most important new data point: if a stale cached `out_path` were the whole story, clearing it should let at least one of three FRESH attempts (each preceded by its own reset) succeed via flood routing. It didn't. That significantly weakens "stale path alone" as a sufficient explanation -- either the reset isn't actually taking effect at the companion/device level (the code only checks that the call didn't raise, never inspects what the companion actually replied -- could be silently getting back an ERROR event and we'd never know), or there's a separate, deeper issue (genuine RF/physical link degradation between the Pi's own companion and this specific repeater, or the companion itself being unhealthy) that a routing fix can't touch. Also noted from the same log: `get_contacts` returned 0 contacts, then 350, then 0 again within about 25 seconds of each other right after startup -- a companion roster flapping like that independent of the repeater poll itself is a mildly suspicious sign of its own, not yet investigated further. Clarified for the user that the SX1302 HAL patch (`patch_hal.sh`, applied by the `install.sh` upgrade they ran) is unrelated hardware entirely -- it only touches the onboard SX1302 concentrator's driver (Meshtastic/LoRaWAN TX/RX), completely separate from the USB-connected MeshCore companion stick this incident is about. Added real diagnostic visibility rather than another blind fix attempt: the reset call's own result is now inspected and logged (`reset_result.type.value`, same `hasattr(result.type, "value")` pattern already used for `send_advert`'s own event-type logging), so the next occurrence will show whether the companion actually replied `OK`, `ERROR`, or something else -- previously only "didn't raise" was checked, which said nothing about whether the device-level command actually succeeded. Verified this doesn't crash on an ERROR-typed response via a fake `Event`-like stand-in. All existing tests still pass; `ast.parse`-checked; CHANGELOG bullet extended in place (parser-verified). **Genuinely unresolved as of this round** -- unlike the previous three rounds, this one is explicitly NOT presented as "the fix"; it's diagnostic instrumentation to figure out what's actually happening, since the mechanism believed to be the cause (stale `out_path`) no longer fully explains the symptoms on its own. Next step once deployed: read what the companion actually replies to the reset command, and if it's genuinely `OK` every time yet login still fails, treat this as a real RF/hardware-level investigation (signal to this specific repeater, companion health) rather than a routing/software fix.

**RESOLVED 2026-07-13, ~21:56**: user pasted `repeater_poller: Repeater da0b77f13bc7 polled OK` -- the incident is over, first successful poll since it broke at 20:19 (roughly 1h37m of continuous failures across four rounds of live debugging). Didn't get a chance to confirm the exact device-level reply the new diagnostic logging captured before it recovered, so it remains unconfirmed whether the eventual success came from: the `reset_path()` mechanism genuinely working but needing several repeated attempts to re-learn a workable flood route (each attempt also re-triggers real mesh chatter -- adverts, other traffic -- that could organically help a fresh path get discovered), or the underlying RF/companion condition simply clearing up on its own around the same time coincidentally. Given the fix (correctly-scoped `reset_path(contact)` in the `finally` block, covering every failure shape) is sound regardless of which explanation is right, and it's now shipped and live, this is being treated as closed. If this repeater (or any other polled repeater) hits this exact symptom again -- works for a long stretch, then fails every login continuously, other access methods unaffected, reboot doesn't help -- the fix is already in place and should self-recover within a poll round or two; if it doesn't self-recover next time, that would be the stronger signal to revisit the RF/hardware-level hypothesis in earnest. Confirmed stable across a subsequent `meshpoint` service restart too (`21:58:39 polled OK`) -- not just a one-off recovery blip, the poll genuinely stayed healthy. This incident is fully closed. |
| — | DONE 2026-07-13 | S | **`import_meshcore_db.py` run live -> Recent Packets feed flooded, root-caused and fixed (unrelated to the repeater login incident above, same session).** User ran the einstein.amsterdam import for the first time this session and reported "wow it messed alot up" after seeing a wall of identical-looking `telemetry` rows for `NL-AMS-R-PD2EMC` at one timestamp. First hypothesis (source-archive duplicate rows) was checked and ruled out via a purpose-built dry-run script (`scripts/dedupe_meshcoredb_packets.py`, keeps lowest-rowid per exact `packet_id`, verified against a scratch DB before handing over) -- it reported **zero** duplicates on the real `concentrator.db`. User then pasted two packet-detail modals proving these are genuinely distinct rows (`channel:1/voltage` vs `channel:1/temperature`, different `packet_id`s) -- confirmed: `insert_packet()` (`scripts/import_meshcore_db.py`) is *designed* to write one packet row per sensor channel/status field, not one row per poll, and this repeater genuinely reports ~10-20 distinct channel/status values per snapshot (LPP channels 1/3/4 plus `status_history` counters like `sent_direct`). Not a bug -- but a real UX problem regardless: dozens of historical poll timestamps each exploding into 14-22 rows genuinely buries live mesh activity (`nodeinfo`/`neighbour_advert` from other nodes) in the feed. User then asked directly "cant we remove them from the db" -- before agreeing, checked what actually depends on `capture_source='meshcore_db_import'` rows via `grep -rl` across the whole codebase rather than assuming: found `src/api/routes/topology_routes.py:104`'s graph query actively matches `packet_id LIKE 'meshcoredb:neighbour:%'` (alongside the live poller's own `nb:%` rows) to draw historical neighbour-star edges on the Topology page -- deleting those specifically would thin out that graph. Confirmed `stats_routes.py` (Farthest Direct Signal) and `node_repository.py` (`last_heard` floor) already *exclude* `meshcoredb:%` rows from their own logic, so nothing there depends on the rows existing either way; and confirmed the repeater/node History/Sensors/Trends cards read from the separate `telemetry` table (`_import_telemetry_samples`), untouched by any of this. Built three pieces: (1) `GET /api/meshcore/packets` (`src/api/routes/meshcore_routes.py`) now excludes `capture_source='meshcore_db_import'` by default (new `include_imported` query param to opt back in), fixing the feed going forward without deleting anything; (2) `scripts/dedupe_meshcoredb_packets.py` (already built during the investigation, kept as a permanent maintenance script); (3) `scripts/purge_meshcoredb_packets.py` -- deletes `meshcoredb:telemetry:%`/`meshcoredb:status:%` rows (the actual clutter) but deliberately leaves `meshcoredb:neighbour:%` alone, verified against a scratch DB proving neighbour/live/unrelated rows all survive while telemetry/status rows are removed. Both scripts follow this repo's established dry-run-by-default/`--apply`-to-write convention (matching `repair_neighbour_timestamps.py`). Re-running `import_meshcore_db.py` later regenerates the same deterministic `packet_id`s, so the purge isn't a one-way loss of the underlying archive data. All three verified via scratch-DB tests (not live hardware -- pure SQL/Python, no fastapi/aiosqlite needed for these). `ast.parse`-checked. CHANGELOG bullet added (parser-verified) under MeshCore repeaters. **LIVE-VERIFIED 2026-07-13, fully closed**: dedup step confirmed 0 duplicates on the real DB (as above). Purge dry run against the real `concentrator.db` reported 38,732 telemetry/status rows -- matches expectations given how dominant the clutter was (this was the large majority of the ~41,647 "packets received" stat seen earlier in the session). User ran `--apply`, confirmed "Removed 38732 meshcore_db_import packet row(s)", then pasted the real Recent Packets feed afterward: genuinely clean, showing only real mesh activity (`nodeinfo`, `neighbour_advert`, a `text` message) with no imported noise, immediately readable at a glance for the first time all session. Both the one-time purge and the going-forward API filter (so a future re-import doesn't recreate the same clutter) are confirmed working end to end. |
| — | DONE 2026-07-13 | S | **MeshCore Companion card gains a firmware-version readout.** User asked "is there a way to show the version number of the connected meshcore node," then asked where a firmware check-and-update should live in the nav. Researched properly before building rather than guessing at the payload shape (the meshcore python library's own docs don't describe it): confirmed via WebFetch against `fdlamotte/meshcore-cli`'s actual source that firmware version is NOT part of `self_info`/the connect-time handshake Meshpoint already reads for frequency/bandwidth/SF/TX power -- it's a separate live command, `send_device_query()`, whose response payload uses the literal key `"fw ver"` (note the space, not `fw_ver`) as a protocol-level integer always present, plus `ver`/`model`/`fw_build` (human-readable version/model/build date) only on firmware reporting `fw ver >= 3`. Cross-checked against this codebase's own existing `get_radio_info()` docstring, which already independently noted "send_device_query() does not return those \[radio\] fields" from an earlier session -- consistent confirmation. Design question (where should firmware check/update live) resolved by scope-splitting: the read-only version DISPLAY is small/safe and belongs right on the existing Configuration -> MeshCore Companion card; actual firmware FLASHING is a much bigger, separate, higher-risk feature (needs real flashing tooling against a port Meshpoint is actively using, real brick risk, not a YAML-edit-and-restart like every other Configuration page) and stays deferred as the existing "Noted" wishlist item, now split so the version-check half is done and the flasher half keeps its own row (with the actual flasher source found this session: `https://github.com/meshcore-dev/flasher.meshcore.io`, not yet investigated for integration feasibility -- likely just a browser Web Serial tool worth linking to rather than reimplementing). Built: new `DeviceInfo` dataclass + `MeshCoreTxClient.get_device_info()` (`src/transmit/meshcore_tx_client.py`) -- queried once per connection and cached (unlike `get_radio_info()`'s free `self_info` read, this needs a real device round-trip, so repeating it on every `GET /api/config` poll would be wasteful and risk interfering with other in-flight companion commands, a real concern after this session's whole repeater-login saga); handles both firmware generations (falls back to showing the bare `protocol_version` integer as "protocol vN" when no human-readable fields exist) and an `EventType.ERROR` reply gracefully. Wired into `GET /api/config`'s `meshcore.device` block (`src/api/routes/config_routes.py`, mirrors the existing `radio_info` wiring exactly). Frontend: 5th readout tile on the Companion card (`frontend/js/configuration/meshcore_card.js`) next to Frequency/Bandwidth/SF/TX Power, with model+build-date in a hover tooltip when available (same `title=` convention established on the Stats page earlier this session). Verified with 5 mocked scenarios (modern firmware with full fields, old firmware bare-integer-only, an ERROR response, cache-hit-doesn't-requery, not-connected) plus a standalone Node check of the formatting helpers (`_fmtFirmware`/`_firmwareTitle`) covering the same cases. Existing `test_repeater_poller.py` (10 cases) still pass unmodified. `ast.parse`-checked, `node --check`ed. CHANGELOG/README updated. **LIVE-VERIFIED 2026-07-13**: screenshot shows the real 5th tile on the Companion card reading `v1.16.0-07a3ca9` next to Frequency (869.618 MHz) / Bandwidth (62.5 kHz) / SF8 / TX Power (22 dBm) -- confirms this companion's firmware falls into the modern `fw ver >= 3` branch with a real human-readable version string (not the bare-integer "protocol vN" fallback), and that the WebFetch-sourced payload-shape research (no real hardware available to test against directly) was correct on the first attempt, unlike the repeater-login saga earlier this session. Feature is fully closed.

**Same-day follow-on: "Check for updates" button.** User asked "how can we check if we have the latest version" after seeing the real firmware readout. Researched the actual update-comparison source before writing any comparison logic (same discipline as the version-display research above): confirmed via the GitHub API that the firmware repo is `meshcore-dev/MeshCore` (org repo list fetched directly, ruling out `meshcore_py`/`meshcore-cli`/`flasher.meshcore.io`, which are client tooling not firmware), and -- the key gotcha -- confirmed against a REAL release that the release tag (`room-server-v1.16.0`) does NOT carry the build hash the companion itself reports; only asset filenames do (`Heltec_v3_room_server-v1.16.0-07a3ca9.bin`), and that hash (`07a3ca9`) exactly matched the user's own companion's already-displayed version (`v1.16.0-07a3ca9`) -- strong independent confirmation the whole approach (repo, format, comparison) is correct before writing a single line of comparison code. Design choices, per user's own "what do you advise" ask: (1) lives on the Companion card itself, not the sidebar, to avoid confusing this with Meshpoint's own separate self-update-check pill (same class of mistake the Hardware/Peripherals rename fixed once already); (2) manual/on-demand only, zero automatic polling -- companion firmware never changes except via a physical reflash, so there's no live state to watch, and it avoids competing for GitHub's unauthenticated 60-req/hr rate limit with Meshpoint's own periodic self-update checker; (3) scope deliberately narrow (up-to-date vs. available-version + release link only) -- resolving the exact per-board asset filename is the separate, still-deferred flasher feature's job, not this one's. Built: `_check_firmware_update()`/`_latest_release_version_string()`/`_semver_and_hash()` (`src/api/routes/meshcore_config_routes.py`, same file/module as the existing companion-name route) -- mirrors `src/api/routes/update_check.py`'s existing pattern almost exactly (stdlib `urllib.request`, no new HTTP dependency, 300s result cache) for Meshpoint's own software, just pointed at a different repo/response shape. Comparison logic does a proper numeric semver tuple comparison (matching `update_check.py`'s own `_parse_version` convention) rather than a naive string `!=`, and additionally flags a same-semver-different-hash case (a patch rebuild without a version bump) as an update too. New `GET /api/config/meshcore/firmware-check` -- deliberately NOT admin-gated (`Depends(require_admin)`) unlike the companion-name PUT route, since this is read-only/side-effect-free and any logged-in session (viewer or admin) can check; still inherits the router-level `protected` (logged-in-required) dependency from `server.py`'s `include_router` call. Frontend: small "Check for updates" link-style button + status line added directly inside the existing Firmware readout tile (`frontend/js/configuration/meshcore_card.js`), not the channel-editing toolbar below -- shows "Checking…" -> "Up to date" (green) / "Update available: vX.Y.Z-hash — release notes" (amber, linked) / an error message (red), matching the `title=` hover-tooltip and color-coded status-text conventions already established this session (Stats page, RTL-SDR busy-dot). Caught and fixed a real security gap during verification, not after: an XSS-focused test case revealed that while `latest_version` was HTML-escaped, `release_url` wasn't scheme-validated -- HTML-entity-escaping text prevents markup injection but does nothing to stop a `javascript:` URI from executing on click. Fixed with an `/^https?:\/\//i` allowlist check before ever rendering the link, verified both that a legitimate GitHub URL still renders and that `javascript:`/`data:` URIs are silently dropped instead. Verified thoroughly: 6 scenarios for the backend comparison logic against the exact real confirmed release data (exact match / older semver / same-semver-different-hash / local-newer-than-latest / GitHub-unreachable / caching-prevents-refetch), all via stubbed fastapi/pydantic/jwt (no real deps on Mac, matching this repo's standing convention); 5 scenarios for the frontend render logic via a hand-built DOM stub (up-to-date/update-available-with-link/server-error/null-result/XSS-escaping-including-the-caught-URL-scheme-bug). Existing `test_repeater_poller.py` (10 cases) still pass unmodified. `ast.parse`-checked, `node --check`ed. CHANGELOG/README updated (new bullet + API table row). **LIVE-VERIFIED 2026-07-13**: screenshot shows the real button clicked on the deployed dashboard -- "Check for updates" link followed by a green "Up to date" result for the real companion (`v1.16.0-07a3ca9`), matching exactly what the GitHub API research predicted. Feature is fully closed. |
| — | DONE 2026-07-13 | S | **Configuration → Serial gains live device readouts, mirroring the MeshCore Companion card.** User, looking at the Serial page (label/serial port/baud rate only, no live data): "can you get the data from the connected meshtastic companion?" Investigated before building: found most of what's useful is ALREADY read from the connected device and even already exposed via `GET /api/config`'s top-level `serial` array (`SerialCaptureSource._read_radio_info()` -> `_serial_status_entry()`, `config_routes.py`) -- node ID, long/short name, region, channel, modem preset, SF/bandwidth/coding rate, connection status -- just never rendered on this specific config page, only used for the topbar chip and `meshpoint report`. The one genuinely missing piece: firmware version and hardware model, confirmed via grep nowhere read from the connected device at all (only aggregate hw_model stats from OTHER mesh nodes, and Meshpoint's own separate software version, both unrelated). Researched the real `meshtastic` python library before writing code (mirroring the MeshCore research discipline): confirmed via the actual `meshtastic/protobufs` `mesh.proto` source that `DeviceMetadata` has exactly `firmware_version` (string) and `hw_model` (enum) fields, and via `mesh_interface.py`/`node.py` that getting them requires an explicit `interface.localNode.getMetadata()` call (sends an admin message, blocks on `waitForAckNak()`) -- the response then lands in `interface.metadata` as a side effect, NOT auto-populated at connect like the other fields. This is the Meshtastic-python equivalent of MeshCore's `send_device_query()` -- same "real round trip, not a free read" shape -- but conveniently simpler to integrate here: `_read_radio_info()` already only runs ONCE at connect time and caches its result in `self._radio_info` (`get_radio_info()` just returns a copy), so no NEW caching mechanism was needed at all, just two more fields added to the existing one-shot read. Design choices, per user's explicit "mirroring the Companion card's pattern, and this go on the existing Serial page": readout tiles reuse the MeshCore Companion card's exact `.cfg-mc-readouts`/`.cfg-mc-readout` CSS classes directly (confirmed they're visually generic already, not MeshCore-branded in the CSS itself -- same bare-global-class reuse precedent as the DAB+ tab reusing Radio's `.lsn-*` classes earlier this session) rather than duplicating near-identical CSS; shown per-device (since Serial supports up to 4 sticks, unlike MeshCore's single companion), matched to its live status entry by `name` (`serial_<label>` or bare `serial` with no label -- confirmed this matching convention from `SerialCaptureSource.name`'s own property); a "Not connected." hint when a configured device has no live/connected status yet. Built: two new fields in `_read_radio_info()`'s initial dict + a new try/except block calling `getMetadata()` then reading `interface.metadata` (`src/capture/serial_source.py`) -- explicitly flagged in its own comment as UNVERIFIED against real Meshtastic hardware (none on the Mac dev machine), since the field names are confirmed against the real protobuf but the exact `getMetadata()`/`interface.metadata` interaction hasn't been exercised live, unlike the MeshCore firmware feature which got a same-day live confirmation. No backend route changes needed at all -- the existing `**info` spread in `_serial_status_entry()` already carries any new fields through automatically. Frontend: `_liveStatusFor()`/`_readoutsHtml()`/`_fmtHwModel()` (`frontend/js/configuration/serial_card.js`), wired into `_addDeviceRow()`; `_fmtHwModel()` humanizes the raw enum name (e.g. `HELTEC_V3` -> "Heltec V3") rather than showing the shouty raw string. Verified with 3 backend scenarios (mocked `meshtastic.protobuf` modules: full metadata available, `getMetadata()` raising -- confirms other fields stay populated despite the metadata failure, and metadata staying `None` after a call that doesn't raise) and 4 frontend scenarios via a pure-logic Node script (labeled device matching by name, bare unlabeled device with partial/missing metadata falling back to short_name, no live status at all, and a `connected: false` mid-reconnect case) -- the labeled-device case deliberately used the exact real node data pattern (`BABC1832`, `!09d406f4`) seen earlier this same session's live logs. Existing `test_repeater_poller.py` (10 cases) still pass unmodified. `ast.parse`-checked, `node --check`ed. **Also fixed, unrelated, found while editing the same stylesheet**: `frontend/css/configuration.css`'s `.cfg-companion__remove` rule was missing its closing brace, silently merging the next rule (`.cfg-quick-deploy`) into it -- caught by a whole-file brace-balance check (exactly one unclosed brace before the fix, zero after), not by any visual symptom the user reported. CHANGELOG/README updated. **LIVE-VERIFIED 2026-07-13**: screenshot shows all 7 tiles rendering correctly on the real deployed dashboard for the `433` serial stick -- Node ID `!09d406f4`, Name `Meshtastic 06f4`, Region `EU_433`, SF `SF11`, Bandwidth `250 kHz`, and critically the two previously-unproven fields: Firmware `2.7.26.54e0d8d` and Hardware `Heltec V3` (correctly humanized from the raw `HELTEC_V3` enum). Confirms `getMetadata()`/`interface.metadata` genuinely works against real Meshtastic hardware, not just the mocked test scenarios. Feature is fully closed. |
| W18 | DONE 2026-07-12 | — | **Sidebar mini radio player fully closed.** All pieces now LIVE-VERIFIED: audio-reconnect-after-reload ("reload reconnects to radio :)"), and RDS+RadioText combination/marquee scrolling/preset-label fallback/server-persistence (user confirmed all three together, 2026-07-13). No remaining gaps on this feature. |
| — | DONE 2026-07-13 | S | **Serial card gets "Check for updates", mirroring MeshCore's.** User: "next on the serial page can you implement a version update check same as you did in meshcore the url for the git of meshtastic is: https://github.com/meshtastic/firmware". Fetched the real latest release from that repo before writing any matching logic (same discipline as MeshCore's original build) -- found it's actually SIMPLER than MeshCore's case: the release `tag_name` itself is already the device's exact version format (`v2.7.26.54e0d8d`, i.e. `vX.Y.Z.hash`), no need to dig through asset filenames for the build hash the way MeshCore's check has to. New `src/api/routes/serial_config_routes.py` (split out for the same reason `meshcore_config_routes.py` was -- `config_routes.py` is already at 791 lines), `GET /api/config/serial/firmware-check?current_version=...`. Deliberately different caching shape from MeshCore's: MeshCore's own check only ever queries company[0] (the one TX-designated companion; see the follow-up row below correcting this), so caching the whole comparison result happens to work today, but Serial's check is explicitly per-device from the start since it can have up to 4 devices on different firmware -- caches only the shared GitHub release fetch (`_release_cache`, 5 min TTL) and always computes the per-device update-available comparison fresh against whichever `current_version` the caller passes, rather than caching a single comparison result that would incorrectly apply to every device. Frontend: `serial_card.js` gets the same Check-for-updates button/status pattern as `meshcore_card.js`, wired per-device (each device div's own button passes that device's own `firmware_version` closure variable) -- button only renders when a firmware_version is actually known, since a stick that fails to answer the metadata request has nothing to compare. Stub-verified all three comparison cases (same version, older version, same-semver-different-hash) against the exact real `meshtastic/firmware` release fetched live during this session. `py_compile`d (`serial_config_routes.py`, `server.py`), `node --check`ed; CHANGELOG bullet added, README endpoint table row added (parser-verified). **LIVE-VERIFIED on the Pi**: screenshot shows the real Heltec V3 stick's Firmware tile with "Check for updates" / "Up to date" (2.7.26.54e0d8d matches the latest real release) -- user: "update check on serial works". |
| — | DONE 2026-07-14, live-verified | M | **MeshCore per-companion readouts, built from the earlier scoped plan.** User compared Serial's unified per-device card against MeshCore's split layout via screenshots and asked: "can you make the companion part in meshcore the same as in serial capture sources so we see the name sf cr etc in the card instead of a new section above the chatrooms?" Built exactly per the prior scoping (all 5 planned steps, no plan drift): (1) `meshcore_tx_client.py` -- factored `get_radio_info()`/`get_device_info()`'s parsing into standalone `read_radio_status(mc)`/`read_device_info(mc)` module-level functions taking a raw connection; `MeshCoreTxClient`'s own methods are now thin wrappers, TX behavior unchanged. (2) `src/capture/meshcore_usb_source.py` -- `MeshcoreUsbCaptureSource` (confirmed real class name, not `MeshcoreUsbSource` as originally scoped) gained its own `get_radio_info()`/`get_device_info()` (+ `_device_info_cache`) calling those same shared functions against `self._meshcore`, its own already-live connection. (3) `server.py` gained `_find_meshcore_sources(coord)` (plural -- every configured companion, vs. the pre-existing singular `_find_meshcore_source()` still used for TX wiring, untouched), wired into `config_routes.init_routes(meshcore_sources=...)`. (4) `config_routes.py` gained `_meshcore_companion_status_entry(src)` and a new additive `mc_status["companions"]` list in `GET /api/config` (one entry per companion: name/connected/radio/device) -- the existing singular `meshcore.radio`/`meshcore.device` keys (still company[0]-only) were left in place for back-compat. (5) `meshcore_card.js`: added `_liveCompanionFor(label)` (mirrors `serial_card.js`'s `_liveStatusFor` exactly, matching on the reconstructed `meshcore_usb_<label>` name), a new `_companionReadoutsHtml(live)` + `_checkCompanionFirmwareUpdate(div, currentVersion)` embedded per-row in `_addCompanionRow()` (mirroring `serial_card.js`'s `_readoutsHtml`/`_checkFirmwareUpdate` pattern verbatim, reusing the existing `_fmtFreq`/`_fmtBw`/`_fmtSf`/`_fmtTxPower`/`_fmtNodeId`/`_fmtFirmware`/`_firmwareTitle` helpers); the old `<div class="cfg-mc-readouts">` block and its `_checkFirmwareUpdate`/`_wire()` wiring were removed from `_renderOnline()`, which now only renders the companion-name edit UI and the shared channel table (module docstring updated to describe this split). Firmware-check converted to the per-device query-param shape planned in step 5: `meshcore_config_routes.py`'s `GET /api/config/meshcore/firmware-check` now takes `current_version` as a query param instead of resolving company[0] server-side, and its cache (`_release_cache`) now stores only the shared GitHub fetch rather than a full comparison result -- exact mirror of `serial_config_routes.py`'s existing shape, since multiple companions can be on different firmware simultaneously (the original single-companion-cache design was built on the "MeshCore only has one companion" assumption the user corrected earlier). TX routing stays untouched per the plan's explicit out-of-scope note -- `_tx_service._meshcore_tx`/`_find_meshcore_source()` (singular) still always resolves company[0] for actually sending. `py_compile`d all five touched Python files, `node --check`ed `meshcore_card.js`; CHANGELOG bullet added (parser-verified), README endpoint table row and "What's Different" bullets updated to describe the per-device layout. **Live-verified single-companion behavior found a real regression, fixed same session**: user deployed and reported the per-companion row showed "Not connected" (readouts and Check-for-updates button both gone) despite the topbar chip and the old singular card both showing the companion genuinely connected -- "where is my meshcore data gone?" / "we had it all working". Root cause (confirmed via Explore subagent, not guessed): `MeshcoreUsbCaptureSource` only ever tracked connection state as a private `self._connected` -- unlike `serial_source.py`, it never had a public `connected` property -- so `config_routes.py`'s `getattr(src, "connected", False)` (the exact same accessor pattern that works for Serial) found no such attribute on MeshCore sources and silently defaulted to `False` every call. The topbar/old card stayed correct only because they read connection state through a completely different object (`MeshCoreTxClient`, which does have its own `connected` property), not through `coord.capture_coordinator._sources` at all. Fixed with a two-line `@property def connected(self): return self._connected` added to `MeshcoreUsbCaptureSource` (`src/capture/meshcore_usb_source.py`), mirroring Serial's exact accessor. `py_compile`d; CHANGELOG bullet extended in place (parser-verified). **LIVE-VERIFIED 2026-07-14 after the fix deployed + restart**: screenshot shows the companion row fully populated -- Node ID `#73f513ba`, Frequency `869.618 MHz`, Bandwidth `62.5 kHz`, SF `SF8`, TX Power `22 dBm`, Firmware `v1.16.0-07a3ca9` with "Check for updates" -> "Up to date", and Hardware `Heltec V3` -- matching Serial's identical 7-tile layout side by side (Serial screenshot in the same message: Node ID/Name/Frequency/Region/SF/Bandwidth/TX Power/Firmware+check/Hardware). User: "better :)". **Second-companion test also LIVE-VERIFIED same day**: screenshot with a real second companion (433, LILYGO T-LoRa V2.1-1.6) attached shows genuinely distinct per-row data -- Companion 1 (868, Heltec V3): Node ID `#73f513ba`, 869.618 MHz, SF8, 62.5 kHz, TX 22 dBm; Companion 2 (433, LILYGO): Node ID `#609cfb6c`, 433.65 MHz, SF11, 250 kHz, TX 20 dBm, both independently reporting firmware `v1.16.0-07a3ca9` with their own "Check for updates" state. This is the exact scenario the original architecture couldn't have supported (both rows would have silently echoed company[0]'s data pre-fix). Feature fully closed, no remaining gaps. |
| — | DONE 2026-07-14 | S | **Topbar now shows one MeshCore chip per companion, not just one.** User, after the per-companion readouts/rename fixes above: "also i noticed on the top my 2nd meshcore doesnt show" (screenshot: topbar had one MeshCore chip, two Meshtastic-serial chips, despite two MeshCore companions configured). Investigated via Explore subagent rather than guessing -- found `TopbarSerialChip` (`frontend/topbar/topbar_serial_chip.js`) already solves this correctly (empty container div, one badge built per array entry from `cfg.serial`), while `TopbarMeshcoreChip` was still hardcoded to one static `<span>` in `index.html` reading only singular `meshcore.connected`/`.radio`/`.companion_name` -- never touched the `meshcore.companions` array this session's earlier readouts fix already added to `GET /api/config`. Pure frontend port of Serial's exact working pattern to MeshCore, zero backend changes needed (the per-companion data already existed). Rewrote `TopbarMeshcoreChip` to accept a container element and build one badge per `meshcore.companions` entry; `index.html`'s `#topbar-meshcore-group` changed from wrapping one static chip to an empty container like `#topbar-serial-group`; `topbar_controller.js`'s constructor call dropped its now-unused second `chipEl` arg. Channel name slot still reads the shared `meshcore.channel_keys` (same value on every badge -- genuinely mesh-wide config, not a per-badge stand-in). Verified via a DOM stub (fake classList/createElement): 2 distinct companion badges built from real-shaped data (869.618 MHz "868" / 433.65 MHz "433"), group hides at zero companions, reconnecting state doesn't throw. `node --check`ed. CHANGELOG bullet added (parser-verified). **LIVE-VERIFIED 2026-07-14, found and fixed a styling bug**: user's screenshot showed both companion chips rendering side by side by name/frequency (confirming the core fix works), but "the dots on meshcore are not green also they dont blink when reconnecting." Root cause: `topbar.css` keys the dot's color/blink animation off a MODIFIER class on the lamp element itself (`.topbar-meshcore__lamp--online .topbar-meshcore__dot` etc, lines 240-257) -- the rewrite's `_buildBadge()` set `lamp.className = 'topbar-meshcore__lamp'` (base only), never adding the `--online`/`--offline`/`--reconnecting` suffix the OLD single-chip code's dedicated `_setLamp()` method used to add, and which had no equivalent carried over into the new per-badge builder. Fixed: `lamp.className` now includes the state suffix. Also fixed the DOM stub used to verify it -- the stub's `textContent = ''` wasn't clearing `children`, unlike real DOM, so a naive re-test would have kept reading stale badges after a repaint and missed this exact class of bug; fixed the stub too before re-verifying all 3 lamp states. `node --check`ed. CHANGELOG bullet extended in place (parser-verified). Chips now confirmed rendering with correct data; lamp color/blink fix not yet re-deployed/re-screenshotted. |
| — | DONE 2026-07-14 | M | **Meshtastic USB serial devices can now be renamed from the dashboard too, mirroring MeshCore's new per-companion rename.** User: "is it in serial also possible to rename a meshtastic node and place the save and advert, or is that only for meshcore possible?" Investigated first via Explore subagent -- confirmed rename was NOT implemented anywhere for Serial: `SerialCaptureSource.send_nodeinfo()` only re-broadcasts the stick's EXISTING identity, never calls `setOwner()`/builds an AdminMessage; `serial_card.js` only has a read-only name readout. The dashboard's own "Identity" card (Configuration -> Identity) is a DIFFERENT thing entirely -- it renames the Meshpoint's own onboard concentrator identity (868 MHz internal radio), not a USB stick. User confirmed the real need after seeing screenshots (their own Identity card + the official Meshtastic app renaming the physical "06f4" stick directly): "we want it in the ui on meshpoint, there the nodes/companion dont have bluetooth only direct serial" -- these sticks can only be renamed via a direct USB/laptop session with the official app, which isn't practical for an always-in-place field deployment. Chose "Build it now" when asked (mirroring the earlier MeshCore rename decision). **Key research finding before writing any code**: found the REAL `meshtastic` Python package actually installed on this Mac under Homebrew's Python 3.11 (`/opt/homebrew/lib/python3.11/site-packages/meshtastic/`, NOT the Mac's default `python3`/`python3.13` which have nothing installed) -- used it to inspect `Node.setOwner()`'s actual source rather than guessing the API. This surfaced a genuine hazard: `setOwner()` calls a CLI-oriented `our_exit()` helper (bare `print()` + `sys.exit(1)`) whenever `long_name`/`short_name` is passed as non-None but empty/whitespace-only -- calling this from inside Meshpoint's long-running FastAPI process with a blank string would have killed the ENTIRE dashboard process, not just failed the one request. Designed `SerialCaptureSource.set_owner()` to make this unreachable BY CONSTRUCTION: strip and validate both names (reject empty, reject >36/>4 chars respectively -- confirmed against the REAL Meshtastic app's own UI text visible in the user's second screenshot, "Long Name can be up to 36 bytes long", and the library's own `nChars = 4` short-name truncation constant) entirely BEFORE ever calling the real `setOwner()`, so it only ever receives `None` or an already-valid non-empty string -- plus a defensive `except SystemExit` catch as a last-resort safety net in case some other internal path still raises it. Also found and fixed a related staleness risk: `send_nodeinfo()` used to build its outgoing NodeInfo from `iface.getMyNodeInfo()` (meshtastic-python's own internal node cache, not guaranteed to reflect a rename made moments earlier through the same interface) -- switched it to prefer `self._radio_info`'s long_name/short_name (this source's OWN cache, updated immediately on a successful `set_owner()` call) so an advert sent right after a rename announces the NEW name, not a stale one. Built: `SerialCaptureSource.set_owner(long_name, short_name)` (`src/capture/serial_source.py`) -- None for either param means "leave unchanged", matching `setOwner()`'s own convention. `SerialDeviceConfig` (`config.py`) gained `long_name`/`short_name` fields (`capture.serial[i]`) -- applied ONCE at connect time inside `start()`, not via a reconnect-callback like MeshCore's, because `SerialCaptureSource` genuinely has no auto-reconnect loop to hook into (confirmed via Explore agent: unlike `MeshcoreUsbCaptureSource._reconnect_until_connected()`, Serial has none) -- a swapped-in blank replacement stick picks up the configured name on the NEXT service restart instead, consistent with this card's own existing "Requires a service restart after changes" convention rather than inventing new reconnect infrastructure for a smaller edge case. New `src/api/routes/serial_config_routes.py` routes: `PUT /identity` and `POST /advert` (both label-scoped via a new `_resolve_serial_source(label)`, mirroring `meshcore_config_routes.py`'s `/companion-name`/`/companion-advert` shape exactly, including the same `_persist_*` full-list-yaml-write pattern). **Caught and fixed the same latent list-save wipe bug found in MeshCore's equivalent, before it could ship**: `PUT /api/config/capture/serial-devices` (`system_config_routes.py`) rebuilt every device fresh from the request body every time, which has no long/short-name fields in its shape at all -- saving that form (e.g. just to add a new stick) would have silently erased every existing device's configured name; fixed by preserving `long_name`/`short_name` across that save via label match, same fix shape as the MeshCore companions one. Also added the two new fields to `_serial_device_dict()` and `config_enrichment.py`'s hand-curated `capture.serial` API dict (neither serialized them, so the frontend would never have seen a persisted name to prefill). Frontend: `serial_card.js` gained `_identityHtml(data, live)` (Long name + Short name inputs, "Send advert after save" checkbox, Save button, mirroring `meshcore_card.js`'s `_companionIdentityHtml` almost exactly, just two name fields instead of one) and `_saveDeviceIdentity(deviceDiv, label)`, wired per-row in `_addDeviceRow()`. Verified thoroughly given the SystemExit hazard: 9 scenarios for `set_owner()` against a stubbed `iface`/`localNode` (happy path both names, empty long_name rejected BEFORE the real call ever fires, overlong short_name rejected, overlong long_name rejected, both-None passthrough no-op, a forced `SystemExit` from the fake library caught and NOT propagated -- proving the safety net actually works, an ordinary `RuntimeError` handled gracefully, not-connected, and `send_nodeinfo()` confirmed to prefer the freshly-updated own cache over stale library state) -- all against a real Python 3.11 interpreter with the actual installed `meshtastic` package importable (stubbed only its two submodules `mesh_pb2`/`portnums_pb2` needed for `send_nodeinfo`'s protobuf construction, not the library itself); label-resolution and list-save name-preservation logic verified directly against real `SerialDeviceConfig`/`AppConfig`-shaped objects; frontend identity block prefill/live-fallback/blank/XSS-escaping verified via a DOM stub, same discipline as MeshCore's equivalent. `py_compile`d all seven touched Python files (`config.py`, `main.py`, `serial_source.py`, `server.py`, `serial_config_routes.py`, `system_config_routes.py`, `config_enrichment.py`), `node --check`ed `serial_card.js`. CHANGELOG/README/CONFIGURATION.md all updated (new "Serial Device Identity" section mirroring the MeshCore Companion Identity one). **Live-verified deployment found a real hang, fixed same session**: user tried it on the real 433 stick and reported the status stuck on "Renaming device…" indefinitely (screenshot showed the pending state never resolving). Root cause: `set_owner()` also called `iface.waitForAckNak()` after `setOwner()`, mirroring `getMetadata()`'s existing pattern in this file -- but the real `Node.setOwner()` source sets `onResponse=None` specifically for the local/directly-attached node case (renaming yourself vs. a remote mesh node), so nothing ever sets the ack/nak flags that call polls for. `waitForAckNak()` busy-waits with blocking `time.sleep()` for a 20-second default timeout -- and since `set_owner()` runs synchronously inside an async FastAPI route handler with no thread-executor wrapper, this froze the ENTIRE dashboard's event loop for 20 seconds on every rename click, not just that one request (explaining the "stuck" symptom -- the whole UI would appear to hang, not just this button). Fixed by removing the `waitForAckNak()` call entirely: `sendData()` (which `setOwner()` rides on, confirmed by reading its real source) queues the write and returns immediately regardless of ack state, and the local-node `onResponse=None` design is the library authors' own intentional signal that no wait is expected for this path -- `Node.setOwner()`'s own source never calls `waitForAckNak()` itself either, that was purely my own addition based on a flawed analogy to `getMetadata()` (a genuinely different request/response operation, not a fire-and-forget local rename). Re-verified all "9 scenarios" from the build with an updated stub whose fake `waitForAckNak()` now `raise`s if ever called at all (proving it's genuinely unreachable, not just untriggered by these particular test inputs). `py_compile`d; CHANGELOG bullet extended in place (parser-verified). **Still needs**: a fresh deploy + retry on the Pi to confirm the rename now completes promptly instead of hanging -- not yet re-verified after this fix. |
| — | DONE 2026-07-14 | M | **Every MeshCore companion can now be renamed and adverted independently.** Follow-on from the per-companion readouts fix above: user looked at the "Companion name" section and asked "is this for the first or second companion... maybe we need it in every companion section." Correct catch, confirmed by reading the code before answering: the rename card called `MeshCoreTxClient.set_companion_name()`, which -- exactly like TX/status before the readouts fix -- only ever targets company[0] via `_find_meshcore_source()`; a second companion had no way to be renamed at all. Same fix shape as the readouts: (1) `meshcore_tx_client.py` -- factored `set_companion_name()`/`send_advert()`'s validation/command logic into standalone `send_set_companion_name(mc, name)`/`send_companion_advert(mc, flood)` functions (mirroring `read_radio_status()`/`read_device_info()`'s existing pattern exactly); class methods are now thin wrappers. (2) `MeshcoreUsbCaptureSource` (`meshcore_usb_source.py`) gained its own `set_companion_name()`/`send_advert()` methods calling those against `self._meshcore`, restarting its own auto-fetching afterward (no callback indirection needed here, unlike the TX client, since the source already owns `restart_auto_fetching()` directly). (3) Config schema: `MeshcoreUsbConfig` (`config.py`) gained its own `companion_name` field (per-companion, in `capture.meshcore_usb[i]`) alongside the pre-existing mesh-wide `meshcore.companion_name` (kept as a fallback for the primary companion only, so existing `local.yaml` files keep working). (4) `server.py`: replaced the old `_reapply_companion_name(meshcore_tx, config)` (TX-client-only) with a generalized `_reapply_companion_name(source, config, is_primary)` + `_desired_companion_name()`/`_companion_label()` helpers, registered via a NEW per-source connected-callback loop over `_find_meshcore_sources(coord)` (every companion, not just primary) -- had to combine primary's channel-sync + name-reapply into one callback since `set_connected_callback` is a single slot per source, not a list. (5) `meshcore_config_routes.py`: `PUT /companion-name` gained a `label` field (resolves via a new `_resolve_companion_source(label)` against a new `_meshcore_sources` list, mirroring `config_routes.py`'s identical wiring), and a NEW `POST /companion-advert` (also label-scoped) so the rename flow's "send advert after save" targets the SAME companion just renamed instead of always company[0] via the general `/api/messages/advert`. (6) `meshcore_card.js`: moved the Companion Name field/advert checkbox/Save button from the shared "MeshCore Companion" card into each companion's own row (`_companionIdentityHtml()`, wired per-row via `_saveCompanionName(div, label)`); the shared card now only holds connection status + the channel table, since MeshCore channels are genuinely mesh-wide config (unlike identity), matching the user's own framing. **Caught and fixed a latent bug this surfaced before it could ship**: `PUT /api/config/capture/meshcore-companions` (the "Save USB sources" button, a full-list-replace endpoint) had no `companion_name` in its request/response shape at all -- saving that form for any reason (e.g. just adding a new companion) would have silently wiped every existing companion's configured name on the next reconnect. Fixed by matching old entries to new ones by label and carrying `companion_name` across (`system_config_routes.py`); also added the missing field to `_meshcore_usb_dict()` and `config_enrichment.py`'s hand-curated `capture.meshcore_usb` API dict (neither serialized it, so the frontend would never have seen a persisted name to prefill anyway). Verified thoroughly given the size: 5 label-resolution scenarios (own name vs. legacy-fallback-for-primary-only vs. non-primary-gets-no-fallback vs. bare/unlabeled companion), the standalone rename/advert functions against a stubbed connection (success / companion-rejected / empty-name / not-connected paths), the companion-list-save name-preservation fix, and the frontend identity block's prefill logic (persisted name / live-radio-name fallback / blank / XSS-escaping) via a DOM stub -- all via stubs, no real fastapi/meshcore/aiosqlite deps on the Mac. `py_compile`d all six touched Python files, `node --check`ed `meshcore_card.js`. CHANGELOG/README/CONFIGURATION.md all updated (the config reference now documents the new per-companion field and the legacy fallback). **Not yet live-verified**: needs a Pi restart + testing rename/advert on both the 868 and 433 companions independently (the user does have both connected now, confirmed via the earlier live 2-companion readouts screenshot, so this should be fully testable next session). |
| — | DONE 2026-07-13 | S | **Serial and MeshCore Companion cards brought to near-parity.** User compared the two config cards side by side via screenshots: "now i see hardware in serial but not in meshcore, db in meshcore but not serial, i want equal as much info as possible". Delegated the investigation to an Explore subagent first rather than guessing what's actually available from each protocol/library -- confirmed: (1) Serial's missing `tx_power` is sitting unread in the same already-fetched LoRaConfig protobuf as region/bandwidth/SF (`src/capture/serial_source.py`'s `_read_radio_info()`); (2) Serial's missing `frequency_mhz` is already computed server-side by `_serial_status_entry()` (`config_routes.py`) via the same `resolve_frequency_mhz()` the topbar chip uses, just never rendered by `serial_card.js` -- pure frontend gap, not a data gap; (3) MeshCore's missing hardware model is already fetched (`get_device_info()`'s `model` field, flows into `/api/config`'s `meshcore.device.model`) but only shown as a Firmware-row hover tooltip, not its own visible row like Serial has; (4) MeshCore genuinely has no "Region" equivalent -- confirmed via the `meshcore` library's `SELF_INFO` parser field list, no regulatory-domain concept exists, it configures raw frequency/bandwidth/SF/CR directly instead of Meshtastic's named-region-plus-modem-preset abstraction. Implemented all three real additions: `tx_power` added to `_read_radio_info()`'s info dict (flows through automatically via `**info` spread in `_serial_status_entry()`, no route change needed); `serial_card.js` gains Frequency and TX Power rows; `meshcore_card.js` gains a visible Hardware row reading `mc.device.model` (and `_firmwareTitle()`'s tooltip trimmed to just build date, since model has its own row now). Stub-verified the full Serial dict-merge chain (`resolve_frequency_mhz` + `**info` spread) with a synthetic device info dict -- confirmed `tx_power` flows through with no key collisions (no fastapi on the Mac, so tested the merge logic directly rather than importing the route module). Final shape: both cards show ID/Name/Frequency/Bandwidth/SF/TX Power/Firmware/Hardware; Region stays Serial-only since it's the one field with no MeshCore equivalent to add. `py_compile`d, `node --check`ed; CHANGELOG bullet added (parser-verified). **Live-verified on the Pi** (both screenshots confirmed: Serial shows 9 tiles including Frequency/TX Power, MeshCore shows 6 including Hardware) -- user then directly counted tiles and asked for MeshCore's own Node ID: "on meshcore we have 6 and in meshtastic 9 values... get more info from meshcore the same as we get from meshtastic". Checked the real installed `meshcore` pip package on the Mac (pulled in earlier this session via pipx for CLI tooling) rather than guessing the field's type -- confirmed `self_info["public_key"]` in `reader.py` is a 64-char hex string (`dbuf.read(32).hex()`), already captured in the same connect-time `SELF_INFO` cache `get_radio_info()` reads the other fields from, just not threaded into `RadioStatus`. Added `RadioStatus.public_key`, read it in `get_radio_info()`, exposed it as `meshcore.radio.public_key` in `config_routes.py`, and added a new **Node ID** tile to `meshcore_card.js` showing an 8-hex-char `#`-prefixed short form (matching Meshtastic's `!09d406f4` visual weight) with the full key in a hover tooltip. Stub-verified `RadioStatus`'s new field end to end with a realistic public key value. `py_compile`d (`meshcore_tx_client.py`, `config_routes.py`, both exit 0), `node --check`ed; CHANGELOG bullet extended in place (parser-verified). **LIVE-VERIFIED on the Pi**: screenshot shows MeshCore's card now at 7 tiles (Node ID `#73f513ba`, Frequency, Bandwidth, SF, TX Power, Firmware, Hardware) matching Serial's 9 (Node ID, Name, Frequency, Region, SF, Bandwidth, TX Power, Firmware, Hardware) -- user: "better?" confirming the final side-by-side. Near-parity fully closed; the only remaining differences (Name shown as an editable field on MeshCore instead of a duplicate tile, Region with no MeshCore equivalent) are both deliberate, not gaps. |
| — | DONE 2026-07-13 | S | **Fixed a second install.sh-via-Terminal bug: mid-run interruption.** User pasted a broken/truncated transcript and reported "the meshpoint restarts due to this the install script in terminal will stop" -- then confirmed the key diagnostic clue unprompted: "in a shell all is ok" (i.e. only the web Terminal breaks, a real SSH session running the identical `install.sh` does not). Grepped every `systemctl restart`/`stop` in `scripts/` first rather than guessing -- confirmed `install.sh` itself never restarts anything automatically (only echoes the instruction, twice). Root cause: `scripts/patch_hal.sh` (called mid-`install.sh`, section 13, right before "Installing Meshpoint to /opt/meshpoint...") prints "Done. Restart meshpoint: sudo systemctl restart meshpoint" -- correct when patch_hal.sh is run standalone (its own documented use case), premature when it's a substep of the larger `install.sh`, which still has several sections left (sudoers, systemd service, watchdog, Meshtastic/MeshCore CLI) before its own correctly-timed final banner. Acting on that premature message restarts meshpoint mid-install; since the web Terminal's PTY is a child process inside meshpoint's own systemd cgroup (confirmed via `apply_finish.sh`'s own pre-existing comment about the identical hazard: "this script is spawned from the meshpoint service process; stop kills the unit cgroup and terminates us"), that restart kills the PTY -- and the rest of the install run -- before it finishes. An SSH session lives outside that cgroup entirely, hence "in a shell all is ok". Fixed with a new `MESHPOINT_INSTALL_IN_PROGRESS` env var: `install.sh` sets it before calling `patch_hal.sh` (section 13), and `apply_finish.sh` sets it before calling `post_update.sh` (which can also trigger the same HAL patch, and already restarts automatically as its own last step, making the message doubly redundant there); `patch_hal.sh` checks the flag and prints a bare "Done." instead of the restart suggestion when set. `bash -n`-checked all four touched scripts (`install.sh`, `patch_hal.sh`, `apply_finish.sh`, `post_update.sh` -- the last needed no direct edit, it inherits the env var through its own `bash` invocation of patch_hal.sh). CHANGELOG bullet extended in place (parser-verified). Not yet live-verified -- next install.sh run via the Terminal tab should complete without stopping partway. |
| — | DONE 2026-07-13 | XS | **Fixed the install.sh quick-command: password prompt.** User tried it live: "it asks for a sudo password for meshpoint". Root cause was self-inflicted -- the catalog entry's command was `cd /opt/meshpoint && sudo bash scripts/install.sh`, but `config/sudoers-meshpoint` only grants NOPASSWD for the EXACT absolute-path invocation `/bin/bash /opt/meshpoint/scripts/install.sh` (its own header comment: "sudo matches the literal argv... never the binary" -- no wildcard on the script path either). A relative `bash scripts/install.sh` after a `cd` doesn't match that pinned rule at all, so sudo silently fell through to an interactive password prompt the passwordless `meshpoint` service account has no way to answer. Fixed by changing the command to `sudo /bin/bash /opt/meshpoint/scripts/install.sh` -- exact match, no `cd`, absolute paths throughout, mirroring how the sudoers file itself is written. Added a note to the entry's own `description` field explaining this constraint so a future edit doesn't reintroduce the same relative-path mistake. `py_compile`d; CHANGELOG bullet extended in place (parser-verified). |
| — | DONE 2026-07-13 | XS | **Terminal quick-command: "Run install.sh (upgrade software)".** User's idea: "run the install script in a window so users can upgrade if we add software" -- expose a way to re-run `install.sh` from the dashboard so new system dependencies (e.g. `welle.io`, added this session for DAB+) get discoverable/installable without an SSH session. Researched existing infra first (via a research subagent) before building: the Terminal tab is already a real PTY (`pty.fork()` + full bash) with live WebSocket-streamed output, not a sandboxed allowlist -- an admin can already type any command including `sudo bash scripts/install.sh` and watch it run live, zero new execution machinery needed. The actual gap was discoverability: `CommandCatalog` (`src/api/terminal/command_catalog.py`) is a curated list of buttons that insert canned text at the prompt (not sandboxed, just saves retyping), rendered dynamically by category in the frontend's command-guide drawer with zero hardcoded category list to update. Added one new `CommandEntry` (`run-install-sh`, new `CATEGORY_SETUP = "Setup"`) inserting `cd /opt/meshpoint && sudo bash scripts/install.sh`, marked `dangerous=True` (same typed-confirmation treatment as "Restart service"). Also surfaced a bigger design question the user chose to defer rather than bundle in: the existing self-update "Apply" flow (`UpdateApplier.apply()` -- git fetch/checkout/reset + `apply_finish.sh`'s pip install + `post_update.sh` + restart) deliberately does NOT run `install.sh`, per its own docstring, specifically to avoid a heavy `apt-get`/reinstall on every routine update click -- meaning a dashboard-triggered update still won't pick up new system packages automatically, only this manual Terminal button does. User picked the cheap fix (this button) now and left "should new deps auto-install on Apply" as a separate future decision, not something to change today. `py_compile`d, verified `CommandCatalog().categories()`/`.find('run-install-sh')` return the new entry correctly; confirmed the frontend command drawer groups by whatever categories the API returns (`frontend/js/terminal/command_drawer.js`), so no frontend changes were needed either. CHANGELOG bullet added (parser-verified). |
| — | DONE 2026-07-13 | S | **Favorites rows show live RadioText when on the currently-tuned channel.** User screenshot comparison: channel tab rows showed live RDS-style text ("SLAM! — Onair: Nelly Furtado - Say It Right"), Favorites rows showed only the flat "channel · label" -- "in channels i see the rds but in favourites not, is that doable?". Root cause: a favorite only ever stores `{channel, sid, label}` in localStorage (no DLS field, since RadioText changes constantly and can't be saved statically at favorite-time). Fixed by cross-referencing `this._lastStatus.services` in `_favRowHtml()` -- if a favorite's channel matches the channel actually tuned right now, look up its live entry by sid and use its real-time `label`/`dls` (identical data a channel tab's own `_stationRowHtml()` already uses), falling back to the static stored label for any favorite on a channel that isn't the one currently playing (no live data exists for those -- welle-cli only decodes DLS for the ensemble it's actually tuned to). `node --check`ed; CHANGELOG bullet extended in place (parser-verified). |
| — | DONE 2026-07-13 | S | **Two DAB+ VFD fixes same day**: (1) `.dab-chan-tag` (the small "11C · Commercial" tag) had `margin-left: auto`, pushing it all the way to the far edge of the tag row's 720px-capped width instead of sitting next to the PTY pill as designed -- user: "why so wide and 11c commercial should be next to pty"; removed the auto-margin, now sits with the same 8px gap as the SNR/PTY pills via `.lsn-station`'s existing flex gap. (2) Real backend bug: pressing Stop could leave a stale error message in the status line (e.g. "idle — ofdm-processor: SyncOnPhase failed") -- that's routine welle-cli OFDM sync-retry chatter that appears even during a normal successful lock (confirmed against the live scan output earlier in this session), not a real failure, but `_ERROR_RE`'s "failed" match caught it anyway, and `stop()`/the idle watchdog never cleared `_last_error` at all. Fixed both: added `_BENIGN_PREFIX_RE` to skip any `ofdm-processor:` line before the error check in `dab_listener.py`'s `_stderr_loop`, and added `self._last_error = ""` to both `stop()` and the idle watchdog's stop path. Verified the regex fix against the exact live log lines from earlier in this session (`ofdm-processor:restart`/`Lost coarse sync`/`SyncOnPhase failed`/`Found sync` all correctly skipped; `rtlsdr_write_reg failed with -9` still correctly caught as a real error). Also confirmed (no code change needed): the now-playing marquee/scroll behavior survived the earlier VFD swap unchanged -- `.lsn-station__scroll`/`.lsn-station__text` wrapper structure and `_setNowPlayingText()`'s overflow measurement are identical to every other marquee instance in this file, so long "station — RadioText" combinations still scroll automatically. `node --check`ed / `py_compile`d; CHANGELOG bullet extended in place (parser-verified). |
| W5 | DONE 2026-07-13, LIVE-VERIFIED | M-L | **DAB+ tab via welle-cli — full build, now fully closed.** Before building, researched welle-cli's architecture from its real GitHub source (not memory): confirmed the Debian/Raspberry Pi OS `welle.io` apt package ships both the GUI app and the headless `welle-cli` binary (verified live: `which welle-cli` → `/usr/bin/welle-cli`), read `webradiointerface.cpp`/`jsonconvert.cpp`/`.h` to get the exact `/mux.json` schema (ensemble label, per-service `sid`/`label`/`dls`/`url_mp3`), and had the user manually test the whole chain live on the Pi first per their own request ("check first and advise i will look into installing welle.io") — `welle-cli -c 12C -w 7979` locked onto the real NPO ensemble (SNR climbing to 15, 10 real stations decoded with live DLS text), and `curl http://127.0.0.1:7979/mp3/0x8201` produced a genuine playable 48kHz stereo MP3 (confirmed via `ffprobe`) before any Meshpoint code was written. Built as a sixth RTL-SDR tab alongside Radio/P2000/Pagers/POCSAG/RTL433, but architecturally different from all of them: DAB+ carries several stations per ensemble, so it's a two-level UI (pick a channel/ensemble preset — 12C/11C/7D/9C/11A — then a specific station once welle-cli decodes the list) instead of a flat preset list. New `src/audio/dab_listener.py` (`DabListener`, mirrors `Rtl433Listener`'s single-subprocess shape): spawns `welle-cli -c <channel> -w 7979`, polls its own local `/mux.json` every 2s via stdlib `urllib.request` (matches `update_check.py`'s existing no-new-dependency convention — no httpx/aiohttp added), grows (never wipes) the station list as welle-cli decodes each one, filters out data-only services with no `url_mp3` (e.g. TPEG). Same `sdr_registry` dongle-exclusivity as the other five (`_OWNER = "dab"`). `GET /api/dab/stream/<sid>` proxies welle-cli's own `/mp3/<sid>` per-request via a `curl` subprocess (not the shared-queue fan-out `RtlListener` needs — welle-cli's webserver already serves multiple simultaneous HTTP clients itself, so this is a thin 1:1 pass-through). Frontend: new `frontend/js/dab_panel.js` (`DabPanel`, same `mount(root)`/`show()`/`hide()` interface as `PagerPanel`), wired into `listener_panel.js`'s existing tabbar as a 6th tab. Also built ★ favorites (channel+station together, localStorage-backed like the Radio tab's presets) — clicking a favorite on a different channel auto-retunes, then waits (polling the existing 2s status refresh) for that specific station's sid to appear in the progressively-filling list before auto-playing it, giving up after 30s if it never shows — this was flagged by the user mid-build ("can we then switch between channels... or will it first readout all?" then "can we have also favorites") and wasn't in the original design. Verified entirely via stubs on the Mac (no fastapi/aiosqlite venv, per standing convention): monkeypatched `asyncio.create_subprocess_exec`/`shutil.which`/`_fetch_mux_json_sync` to exercise the full async lifecycle (bad-channel rejection, dongle claim/release, mutual exclusion with a sibling listener via real `sdr_registry`, status shape, stop/cleanup) plus a separate parse-logic check against the REAL captured Pi JSON shape (confirms TPEG correctly filtered, DLS/label nesting handled). `node --check`ed all touched JS. CHANGELOG (parser-verified via `ChangelogParser.parse_file`), README ("What's Different" bullets, full RTL-SDR paragraph, Optional-RTL-SDR-setup install steps, API endpoint table) all updated. **LIVE-VERIFIED 2026-07-13** on the real Pi: screenshot shows the DAB+ tab tuned to 12C, real "NPO" ensemble, SNR 14.0 dB, a real decoded station list, and the ★ favorite "NPO Radio 1" actively playing with live DLS text ("NPO Radio 1 — Radio Tour de France - NOS") — the whole chain (tune → progressive station decode → favorite auto-tune-and-play) confirmed working end to end, not just the raw `welle-cli` binary. User reaction: "wow totaly amazed great audio quality sofar :)". That screenshot prompted four same-day follow-on fixes: (1) **tab order** — DAB+ moved from last to right after Radio in the tabbar (it's the other audio tab, decoders come after); (2) **sidebar badge label** — `listener_badge.js`'s `_LISTENER_OWNER_LABELS` was missing a `dab` entry, so the sidebar showed the raw internal owner string `dab` instead of `DAB+`, same class of bug as the RDS/label-mapping misses earlier in this project; the sidebar mini-player's owner-label map (`telemetry_rail.js`) got the same fix; (3) **sidebar mini-player now covers DAB+** — previously Radio-only (explicitly deferred as a fast-follow when W5 was first built); since Radio and DAB+ share one dongle and only one can ever run, `SidebarTelemetryRail._refreshPlayer()` now polls both `/api/listener/status` and `/api/dab/status` and shows whichever is active. The DAB+ "now playing" text needed a different approach than Radio's: Radio's tuned frequency IS what's playing (one pipeline), but DAB+'s ensemble can serve different stations to different browser tabs at once, so "what's playing" is inherently a per-browser-tab concept, not something `/api/dab/status` can report globally. Solved by exposing `window.dabPanel` (mirroring the existing `window.listenerPanel` pattern) with two new public bridge methods: `getNowPlaying()` (reads `DabPanel`'s own `_playingSid` against its last-polled station list) and `stopFromSidebar()` (routes through `DabPanel`'s own stop path rather than a bare `POST /api/dab/stop`, so local playback state stays in sync if the user visits the tab afterward); (4) **DAB+ tab redesigned to match Radio's Digital skin** — user asked "can we then have the dab player page more like the radio page? the digital part" after seeing the plain buttons-and-list v1 layout. Rewrote `dab_panel.js`'s markup to reuse Radio's exact global CSS classes (`.lsn-leds`/`.lsn-badge`/`.lsn-led--onair`/`.lsn-led--tune`, `.lsn-freq`/`.lsn-freq__num`/`.lsn-freq__unit`, `.lsn-station`/`.lsn-station__scroll`/`.lsn-tag--qual`/`.lsn-tag--pty`, `.lsn-vu`/`.lsn-vu__bar`, `.lsn-status`/`.lsn-status__dot`) rather than inventing new ones -- confirmed all are bare/global selectors, not scoped to the Radio tab, so no new CSS was needed for the visual parity itself. New: ON AIR/TUNING LEDs (mirrors `_tuning` local flag + `status.running`, same semantics as Radio's), a big VFD-style channel-code readout with the ensemble label as the secondary unit slot, a scrolling "now playing" tag row (SNR quality pill colour-coded green/amber/red at 12/6 dB thresholds, PTY pill, marquee station+DLS text using the same measure/toggle logic as `setStation()`), a real client-side Web Audio VU meter (duplicated `_ensureAudioGraph`/`_startVuLoop`/`_stopVuLoop` from `ListenerPanel`, attached to `#dab-audio` instead of `#lsn-audio`), and a native `<audio id="dab-audio" controls preload="none">` element replacing the old hidden-audio-plus-custom-buttons approach. The station list below keeps its own Play/★ per row (now driving the shared now-playing display instead of separate per-row state), and the old channel-status bar (label+SNR+Stop) was removed in favour of the new VFD display, with Stop folded into the Channel panel next to the channel-preset buttons. `node --check`ed all touched files; CHANGELOG bullet extended in place (parser-verified) rather than a new bullet, since it's the same not-yet-released feature. **(5) Channel preset list corrected and expanded, same day** — user pasted a real multi-city DAB scanner listing (Alkmaar/Eindhoven/Hengelo/Rotterdam) and asked "what do you advise". Cross-referencing frequency + Ensemble ID across all four cities confirmed 12C/11C/9C/7D are genuinely nationwide (identical everywhere) — but caught two real mistakes in the original preset list: the `9C` label said "Amsterdam/regional" when it's actually one of the nationwide ones (same tier as 12C/11C/7D), and `11A` (labeled "Regional") turned out to not be Dutch at all — it only appears in the Eindhoven scanner list at Extended Country Code `0xe0` (Belgium, vs `0xe3` for every real NL ensemble), carrying VRT-adjacent Belgian stations picked up as border spillover. Confirmed user's antenna is near Amsterdam, then added the two ensembles that are genuinely Amsterdam-local per the scanner data: `6C` (Radio SALTO, FunX Amsterdam) and `8B` (Noord-Holland/Flevo — NH, Omroep Flevoland). Preset list at this point: 12C/11C/9C/7D/6C/8B, `11A` dropped — **later superseded**, see (7) below where `6C` itself gets dropped after live-testing. **(6) Manual channel dropdown added same day** — user asked "how many channels does DAB+ have?" (answered: 38 in Band III, `5A`-`13F`, ETSI EN 300 401; NL doesn't use L-Band's extra 23), then asked for a way to tune any of them without a code change. Added a `<select>` next to the preset buttons in the Channel panel, populated by generating the full Band III raster in JS (`DAB_ALL_CHANNELS`, 8 channels × A-D + channel 13's A-F = 38 options) rather than hardcoding 38 strings, plus its own Tune button. The dropdown's value syncs to the currently-tuned channel on each status poll (skipped while the select itself has focus, so it doesn't fight a user mid-pick) and gets disabled whenever another listener holds the dongle, matching the preset buttons' existing busy-state handling. `node --check`ed; CHANGELOG bullet extended again in place (parser-verified). **(7) `6C` dropped from presets same day** — user reported "nothing on 6c" after trying it live. Root cause: `6C`'s channel/frequency data came from the Alkmaar scanner specifically, a different physical transmitter than whatever actually serves this Amsterdam antenna -- unlike the 4 confirmed-nationwide channels, local/regional ensembles aren't guaranteed to match between transmitter sites. Removed `6C` from `DAB_CHANNEL_PRESETS`, leaving 5 presets (12C/11C/9C/7D/8B); the manual channel dropdown (see above) is the intended way to find whichever local channel actually reaches this location by trial, rather than guessing another one to hardcode. **(8) `scripts/dab_channel_scan.py` added same day** — user asked for a way to test all channels systematically rather than guessing one at a time via the manual dropdown, "first on the pi maybe then in the gui". Built as a standalone stdlib-only script (no meshpoint imports, matches `network_watchdog.py`/`edit_contact.py`'s existing convention): drives `welle-cli -c <channel> -w 7979` directly per channel across the full 38-channel Band III raster, polling `/mux.json` (same parsing logic as `DabListener._mux_poll_loop`, already live-verified) every 2s up to a configurable timeout (default 20s), stopping early once an ensemble label and at least one station have decoded. Prints a running per-channel log then a final summary (channel, ensemble name, SNR, station list) for every channel that found something. `--channels`/`--timeout`/`--port` CLI args via argparse, matching `edit_contact.py`'s style. Explicitly documented in the script's own docstring: must stop any active Radio/DAB+/P2000/Pagers/POCSAG/RTL433 tab first, since this script drives welle-cli directly and has no awareness of `sdr_registry`'s dongle-exclusivity lock. **Run live on the Pi same day, twice** (full 38-channel scan, then an isolated `9C` retest) — see the RESOLVED entry a few rows above for the actual results, the blank-label filter bug it surfaced, and the settle-gap/timeout tuning that followed; not duplicating those details here to avoid the two notes drifting out of sync. Preset labels in `dab_panel.js` were refreshed afterward to name the real confirmed stations (e.g. `9C` -> "Throwback/hits (Sublime, KINK, Qmusic Foute Uur...)") instead of the earlier cross-city guesses. GUI-side "scan all channels" button is tracked as its own separate open item (see the "GUI-triggered scan -> persisted JSON presets" row above) rather than repeated here. **(9) Channel picker reorganized into sub-tabs, same day** — user: "can we have tabviews for the channel presets... first tab is the favourites... the other once clicked same as now click and populate channels on that tab... now its one big page". Replaced the old flat layout (favorites bar + channel buttons + manual dropdown + separate always-visible Stations panel, all stacked) with a nested sub-tabbar inside the "Channel" panel, reusing the outer app's own `.lsn-tabbar`/`.lsn-tabbar__btn` classes (just overriding the page-level horizontal padding, since this one nests inside a panel that already has its own). Tabs: ★ Favorites (default active -- user explicitly wanted something visible without an extra click: "first tab = fav because then there is something there for the user instead of having to click on tab header"), one per channel preset, and Manual. Clicking a channel tab tunes to it exactly like the old buttons did, unless it's already the running channel (added a guard here that didn't exist before, to stop a re-click from causing an unnecessary retune/restart); its station list renders inside that same tab instead of a separate panel further down. Picking a favorite now also switches `_activeChannelTab` to its channel so the played station is actually visible instead of leaving the view stuck on Favorites while a different channel tunes in the background -- a real gap caught during this rewrite, not something the user asked for explicitly. Caught and fixed a self-introduced regression before shipping: the Manual tab's `<select>` was being fully rebuilt via `innerHTML` on every 2s status poll, which would wipe an open dropdown or in-progress pick out from under the user -- fixed by only building the select/button shell once per tab-switch and updating just its `.value`/`.disabled` plus a separate stations sub-container on subsequent polls. `node --check`ed; CHANGELOG bullet updated in place (parser-verified) to describe the tabbed structure instead of the old flat one. **(10) Two small same-day follow-ons to the tab reorg**: channel tabs now show a short friendly name (NPO/Commercial/Throwback/MTVNL/NH-Flevo) instead of the bare channel code -- user: "why channel number and not maybe name (12C)" -- with the code moved into the tab's tooltip; and the Favorites tab was changed to render as the same station-list row style (star/scrolling text/Play-Stop) as a channel tab instead of a chip grid -- user: "also show favs as a list like the channel stations" -- with the star now removing the favorite and Play/Stop toggling playback in place (repainted instantly via `_repaintStationButtons()`, extended to also handle the favorites list's own buttons, not just a channel tab's). `node --check`ed; CHANGELOG bullet extended in place again (parser-verified). |
| — | DONE 2026-07-12 | — | Re-screenshot post-reboot: **POCSAG and RTL433 both LIVE-VERIFIED via screenshot** — POCSAG shows "listening on 439.988 MHz" with 3 real POCSAG1200 messages (including the original "Test message"), RTL433 shows "idle" (correctly stopped) with 120 real `Generic-Remote` events retained in the log from the earlier session. Confirms both tabs actually recovered cleanly after the reboot, not just verbal confirmation. Radio itself still not separately re-screenshotted (only POCSAG/RTL433 tabs were shown), but the shared-plumbing argument above covers it too. |
| — | RESOLVED 2026-07-12 | — | The original "POCSAG shows no messages despite the pager physically receiving it" report was purely the wedged-dongle symptom, not a frequency mismatch. Confirmed by sending a genuinely fresh page after the reboot — screenshot shows a brand-new message ("this is a new test for meshpoint pocsag", 08:58:34, distinct from the earlier buffered "Test message" at 08:50:23) decoding correctly at 439.9875 MHz. Further confirmed by a THIRD screenshot showing multiple more real pages flowing in over several minutes (`pd2emc1`, two `XTIME=...` time-sync broadcasts, two `YYYYMMDDHHMMSS...` pages) at varying capcodes (224/208/8/216/200) — POCSAG is genuinely decoding real production traffic reliably, not a one-off fluke. 439.9875 MHz is confirmed the right frequency; no further action needed. |
| — | DONE 2026-07-12 | XS | **Frequency display bumped to 4 decimal places everywhere on the Listener page.** User noticed while confirming POCSAG: the UI showed "listening on 439.988 MHz" when the actual tuned frequency is 439.9875 MHz — traced to `pager_listener.py`'s `status()` rounding to only 3 decimals server-side (`round(hz/1e6, 3)`), silently losing the real trailing `5` before the frontend ever saw it (pure display bug, the dongle was always tuned correctly to the exact `frequency_hz` the whole time). Bumped that rounding to 6 decimals (matching `rtl_listener.py`'s existing convention for the Radio/FM tab, which was already precise). Standardized display: renamed `listener_panel.js`'s `fmtFreq3()` → `fmtFreq4()` (`toFixed(3)` → `toFixed(4)`, all 5 call sites updated: Digital/Analogue skin frequency readouts, station label, Radio's own "listening on X MHz" line) and updated the two frequency placeholder strings (`--.---` → `--.----`) to match; `pager_panel.js`'s "listening on X MHz" line (shared by P2000/Pagers/POCSAG/RTL433) now explicitly formats with `Number(status.frequency_mhz).toFixed(4)` instead of interpolating the raw JSON number as-is. Verified: POCSAG now correctly reads `439.9875`, P2000/Pagers read `169.6500`/`172.4500` (trailing zeros now shown for consistency), RTL433 reads `433.9200`. `node --check`ed, `ast.parse`-checked, stub-verified the exact backend values for all three pager kinds. **LIVE-VERIFIED 2026-07-12**: user briefly saw stale "169.65 MHz" (old cached `pager_panel.js`, same class of issue as the earlier `POLL_MS` sidebar-badge bug — confirmed `toFixed(4)` cannot itself drop trailing zeros), then confirmed "a reload helped" — screenshot shows the P2000 tab correctly reading "listening on 169.6500 MHz". |

Closed 2026-07-12: **W18, Mini RTL-SDR player widget**, following the
"advise before building" pattern the user explicitly asked for
("check and advise me dont so it yet"). Investigated the sidebar's
existing telemetry region first: `SidebarTelemetryRail`
(`frontend/sidebar/telemetry_rail.js`) already owns the exact visual
slot (Uptime/Sessions/Noise-floor block, sitting right below the "Ops"
nav group) the user was pointing at in their screenshot. Design
converged over several rounds of clarification, each narrowing scope:
(1) user proposed showing a player "above or even instead of" the
noise-floor graph when Radio is tuned; (2) confirmed swap-not-stack
("when radio stopped switch player back to noise floor"); (3) asked
for a volume control and RDS; (4) agreed a compact mute toggle (not a
slider) fits the narrow sidebar better; (5) the one real architecture
question -- share `ListenerBadge`'s existing 5s poll of
`/api/listener/status`, or run an independent one -- user asked "what
do you advise", recommended independent (matches every other sidebar
module's convention: `RadioTxBadge`/`UpdateCheckBadge`/`ListenerBadge`
all poll independently; the extra redundant GET every 5s is
negligible), user confirmed.

Key finding during investigation that shaped the whole design:
background audio playback across page navigation **already works,
undesigned** -- `SidebarController._renderActive()` only toggles
`display:none` on inactive route sections (never removes them from the
DOM), and `ListenerPanel.hide()` never calls `_stopAudio()` either, so
the `<audio id="lsn-audio">` element and its stream just keep playing
in the background the moment you navigate away. Nobody built that on
purpose; it simply falls out of the SPA's hide-via-CSS approach. This
meant the sidebar player wasn't fighting against playback being torn
down on navigation, and directly informed the volume design: rather
than reusing the Radio page's own Level slider (a **server-side**
pre-encode gain sent to `/api/listener/tune` -- changing it triggers a
full pipeline retune, an audible glitch each time), the sidebar's mute
toggle drives the `<audio>` element's own **client-side** `.volume`/
`.muted` property directly -- instant, zero server round-trip, and
correctly persists since the element itself never gets destroyed.
Explicitly scoped to Radio only, not P2000/Pagers/POCSAG/RTL433 (no
audio to control on those, and they already have the sidebar "in use"
badge from earlier this session).

No backend changes needed at all -- `/api/listener/status` already
returns everything required (`running`, `frequency_mhz`, `mode`,
`rds_ps`, etc). Built: new markup in `index.html`
(`#telemetry-player`, initially `display:none`) as a sibling to the
existing `.telemetry-rail__noise` block -- station dot, truncating
station-name text, and two icon buttons (mute with two swappable
Feather-style SVGs for on/off state, stop). Extended
`SidebarTelemetryRail` directly (not a new module) with its own
independent 5s poll (`_refreshPlayer()`/`_applyPlayer()`): when
`status.running` is true, hides `.telemetry-rail__noise` and shows the
player, text prefers `rds_ps` (trimmed) and falls back to
`{freq} MHz {MODE}`; when false, swaps back. `_toggleMute()` flips
`document.getElementById('lsn-audio').muted` directly and syncs the
icon; `_applyPlayer()` also re-syncs the mute icon on every poll tick
in case the audio was muted via the Radio page's own native
`<audio controls>` UI instead. `_stopRadio()` POSTs to the existing
`/api/listener/stop` and immediately re-polls for instant UI feedback
rather than waiting for the next tick. New CSS in
`telemetry_rail.css` (`.telemetry-rail__player*`), matching the
noise-floor block's existing padding/border/font conventions, green
dot + amber "pressed" mute state reusing colors already established
elsewhere this session. Verified without live hardware (none on the
Mac dev machine): a hand-built minimal DOM stub (no jsdom available)
exercising `_applyPlayer()`'s swap logic in both directions, the
RDS-vs-frequency-fallback text branch, `_toggleMute()`/`_applyMuteIcon()`'s
icon-swap logic in both directions, and `_stopRadio()`'s fetch call --
all confirmed correct. `node --check`ed. CHANGELOG/README updated
(folded into the existing RTL-SDR listener bullets).

**Bug found and fixed same round, first live look**: user deployed and
screenshotted the real Radio tab tuned to 98.000 MHz with full RDS
active (main page correctly showing "SLAM! — Onair: Joel Corry -
Whisper") but the sidebar widget showed only the bare station name
("SLAM!"), missing the RadioText/now-playing half entirely -- user
flagged "no rds is shown" (meaning the fuller RDS text, not that RDS
was completely absent, since the station name alone WAS present and
correctly sourced from `rds_ps`). Root cause: `_applyPlayer()` only
ever read `status.rds_ps`, never `status.rds_rt`, unlike
`listener_panel.js`'s own `setStation()` call which combines both
("PS — RT", skipping RT if identical to PS). Fixed to mirror that
exact same combination logic; also added a `title` attribute with the
full untruncated text, useful now that the combined string is longer
and more likely to hit the sidebar's `text-overflow: ellipsis`. Verified
with the stub harness using the literal real values from the
screenshot (`rds_ps: 'SLAM!'`, `rds_rt: 'Onair: Joel Corry - Whisper'`)
plus the RT-identical-to-PS dedup case -- all three produce the
expected text. `node --check`ed, CHANGELOG bullet updated in place
(parser-verified).

**Same-session follow-up, user asked for scrolling**: after seeing the
fuller "SLAM! — Onair: Bl…" text get cut off with a plain ellipsis in
the narrow sidebar, user asked "can you scroll the rds in the sidebar
widget?" -- i.e. marquee it like the Radio page's own station display
already does, rather than just truncating. Reused the EXACT same
`@keyframes lsn-marquee` already defined in `frontend/css/listener.css`
(confirmed it's loaded globally via a `<link>` in `index.html`'s
`<head>`, same as every other page's CSS, not lazy-loaded per-route --
so referencing it from `telemetry_rail.css` needed no duplication, just
one new rule pointing at the same keyframe name). Restructured the
markup: `#telemetry-player-text` is now wrapped in a new
`.telemetry-rail__player-scroll` clipping container (mirrors
`.lsn-station__scroll`), and `_setPlayerText()` (new method in
`telemetry_rail.js`) replicates `listener_panel.js`'s own
`setStation()` measure-and-toggle approach exactly: skip if the text
is unchanged from last poll (`_playerTextCache`, avoids re-triggering/
flickering the animation every 5s tick when nothing changed), else
measure `scrollWidth - clientWidth`, and if the overflow exceeds 8px
set `--scroll-dist`/`--scroll-dur` custom properties and add the
`scroll` class (force a reflow via `void textEl.offsetWidth` first,
same trick the Radio page's own code already uses), otherwise clear
both properties and remove the class. Verified with the stub harness
extended to fake `scrollWidth`/`clientWidth`/`style.setProperty` on a
parent/child pair: long overflowing text correctly triggers scrolling
with the right computed distance/duration, an unchanged poll doesn't
re-trigger (cache hit), and short text that fits stays static with no
scroll class. `node --check`ed, CHANGELOG bullet updated in place
(parser-verified).

**Same-session follow-up, third gap found live**: user tuned to the
"Radio 10" preset and screenshotted the sidebar showing bare
"91.6000 MHz WFM" while the main Radio page correctly showed "Radio
10" (the preset label, since this station has no RDS at all --
confirmed by the user: "its because radio10 doesnt have rds"). Root
cause: the preset label a user clicks lives ONLY in
`ListenerPanel._station`, a private in-memory field on that one
module, NEVER sent to the backend at all -- `/api/listener/status`
only ever had `rds_ps`/`rds_rt` to work with, no concept of a
user-chosen label. Presented two options before building (small:
expose the instance and read the field directly; big: persist the
label server-side via the tune request so it's a real single source
of truth that survives reloads) -- user asked "what do you advise",
recommended small (ships fast, no backend touch) with the honest
caveat that this doesn't fix the underlying limitation that the label
is ephemeral (a page reload loses it on the MAIN page too, today,
independent of this fix -- not something this change introduces).
User confirmed the exact priority order to use ("when rds comes in of
course show rds, else preset and freq") -- exactly what `listener_panel.js`'s
own `setStation()` fallback chain already does, so this just makes the
sidebar consistent with logic that already existed. Built: one-line
addition to `app.js`'s `_bootListenerPanel()` (`window.listenerPanel = panel`,
matching the existing pattern for `window.telemetryRail`/
`window.concentratorWS`); `telemetry_rail.js`'s `_applyPlayer()` now
checks `window.listenerPanel._station` as the middle rung between RDS
and bare frequency. Verified with the stub harness across all three
states in sequence (preset shown when tuned with no RDS yet -> RDS
takes over the instant it arrives, ignoring the now-stale preset label
-> back to bare frequency when both are absent) -- matches the exact
scenario from the screenshot. `node --check`ed both files, CHANGELOG
bullet updated in place (parser-verified).

**Same-session upgrade, "bigger fix" requested**: user explicitly asked
"tell me first please" before choosing between the small fix just
shipped (reach into `ListenerPanel._station` via a newly-exposed
`window.listenerPanel`) and persisting the label server-side instead.
Laid out concretely what the bigger fix touches (`TuneRequest` gains a
field, `RtlListener` stores + returns it, `listener_panel.js` sends +
restores it, `telemetry_rail.js` simplifies to read it straight off
the shared status payload instead of reaching into another module) and
what it actually buys (surviving a page reload for RDS-less stations
specifically -- narrower than it sounds, since RDS already wins the
priority fight whenever present on both the small and big fix). User
said yes, build it.

Built: `RtlListener` (`src/audio/rtl_listener.py`) gained
`self.station_label: str = ""`, a new `station_label` param on
`tune()`, and it in `status()`. Deliberately did NOT clear it inside
the shared `_stop_locked()` helper -- that's called from three places
(`tune()`'s own pre-restart teardown, `_start_locked_retrying()`'s
mid-retry teardown, plus the two genuine-stop call sites) and clearing
there would have wiped out the label `tune()` had JUST set, before the
pipeline even finished (re)starting, on every retry. Instead added an
explicit `self.station_label = ""` at the two call sites that actually
mean "nothing is tuned anymore": the public `stop()` method and the
idle-timeout auto-stop block. `TuneRequest`
(`src/api/routes/listener_routes.py`) gained a `station_label: str =
""` field, passed straight through to `tune()`. Frontend:
`listener_panel.js`'s `_tune()` now sends `station_label: this._station
|| ''` with every tune request (empty for a manual frequency-only
tune, matching the existing reset-to-`''` behavior there already);
`_applyStatus()` now syncs `this._station` FROM `st.station_label`
whenever `st.running` is true, right at the top before anything else
reads it -- restores the label on a fresh page load's very first
status poll, and is a harmless no-op after a local preset click since
tune()'s own response already echoes back the exact label just sent
(no race). `telemetry_rail.js` simplified per the plan: reads
`status.station_label` directly off the same payload it already
polls, replacing the `window.listenerPanel._station` reach-in
entirely; removed the now-unneeded `window.listenerPanel = panel`
line from `app.js` that the small fix had added (avoiding leaving
behind dead cross-module wiring once its one purpose was obsoleted).

Verified with a stub harness patching `_start_locked_retrying`/
`_start_locked` to avoid real subprocess spawning: (1) tune with a
label -> status reflects it; (2) retune to a different preset ->
label updates; (3) manual frequency-only tune -> label clears; (4)
tune then stop -> label clears, running false. Also specifically
targeted the edge case the "don't clear in `_stop_locked()`" design
was protecting against: simulated a pipeline that dies on its first
start attempt (triggering `_start_locked_retrying()`'s internal
mid-retry `_stop_locked()` call) before succeeding on retry --
confirmed `station_label` survives that internal teardown instead of
being wiped before the retry even finishes. `ast.parse`-checked both
Python files, `node --check`ed all three JS files. CHANGELOG/README
updated (README's tune endpoint row now mentions the optional label).

**Same-session, real bug found from live use (not a screenshot this
time -- user described the repro in words)**: "when starting radio its
works, i goto dashboard still playing, do a reload seems to still play
but it isnt" -- tuned Radio, navigated to Dashboard, pressed the
topbar's reload button (confirmed via `topbar/topbar_actions.js`: a
genuine `location.reload()`, not a partial/data-only refresh), and the
sidebar kept showing the correct station name, green dot, and even an
animated VU meter -- while no audio was actually playing. Root cause:
`ON AIR`/VU/station-name are ALL driven purely by server-side status
polling (`st.running`, `st.audio_level`), completely independent of
whether the browser's own `<audio id="lsn-audio">` element actually
has a stream attached -- and that element only ever gets a `src` set
via `_startAudio()`, called ONLY from `_tune()`'s success path, never
automatically just because status polling discovers `running: true`.
A full `location.reload()` destroys the whole DOM/JS state (unlike
route navigation, which just `display:none`s inactive sections) --
the backend `RtlListener` process keeps running completely
uninterrupted (nothing in this reload path ever calls `/api/listener
/stop`), but the fresh page load starts with a blank, disconnected
`<audio>` element. This bug pre-dates this whole session's sidebar
work entirely -- reloading while already ON the Listener page had the
exact same silent-audio problem before, just far less visible since
nobody was mirroring "still playing" onto every other page. The new
sidebar player made a latent bug much more noticeable, it didn't
introduce one.

First pass only partially fixed it: added `this._audioConnected`
bookkeeping to `ListenerPanel` (`frontend/js/listener_panel.js`) and
had `_applyStatus()` auto-call `_startAudio()` when it sees
`st.running && !this._audioConnected`. Caught before calling it done,
by re-tracing the user's EXACT repro: they reloaded while on
Dashboard, not Listener -- and `_applyStatus()` only ever runs via
`_refreshStatus()`'s poll, which is gated behind `show()`, which only
fires when the router matches the `listener` route. Since they never
revisited Listener this session, `ListenerPanel` never mounts, `#lsn-audio`
doesn't even exist in the DOM, and the fix never fires. Needed a
second piece that runs regardless of route: `SidebarTelemetryRail`'s
own poll (`_refreshPlayer()`), which already runs continuously from
app boot onward, completely independent of which page is showing.

Second pass (the actual fix): new public method
`ListenerPanel.syncAudioFromStatus(status)` -- mounts on demand (cheap,
just builds hidden markup, no network calls) ONLY when
`status.running` is true (so a session that never touches RTL-SDR at
all never pays for building that page's DOM), starts audio if not
already connected, and resets `_audioConnected` back to false when
told the backend has stopped -- but only if already mounted, so a
"never touched, not running" poll tick stays a true no-op. Re-exposed
`window.listenerPanel = panel` in `app.js` (had JUST removed this same
line last round when the station-label fix made it unnecessary --
re-added now for a genuinely different reason: cross-page audio
reconnect, not reading a display string). `SidebarTelemetryRail._applyPlayer()`
now calls `window.listenerPanel.syncAudioFromStatus(status)`
unconditionally at the top (not gated by `active`), specifically to
correctly reset the flag even while parked on some other page when the
backend legitimately stops -- guards against a real edge case: if the
flag were only ever reset by `ListenerPanel`'s OWN poll (which isn't
running while hidden), a stop-then-restart cycle happening entirely
while the user was elsewhere would leave a stale `_audioConnected = true`
that incorrectly skips reconnecting the next time it's discovered
running again.

Verified with a stub harness (patched `_mount()` to a no-op stub,
faked `#lsn-audio` with a `play()` call counter) across five sequenced
states: (1) never mounted + not running -> stays unmounted, zero mount
calls; (2) running for the first time -> mounts, connects, one play()
call; (3) still running on the next poll -> no duplicate reconnect,
play() count unchanged; (4) stops -> `_audioConnected` correctly
resets to false; (5) running again after that stop -> reconnects
again, play() count increments a second time -- specifically proving
the stale-flag edge case above is handled correctly. `node --check`ed
all three JS files. CHANGELOG bullet updated in place (parser-verified).
**LIVE-VERIFIED 2026-07-12**: user confirmed "reload reconnects to
radio :)" -- the exact repro (tune, navigate away, reload) now
correctly resumes real audio instead of leaving the UI showing a
silent false-positive. The other four sidebar-player fixes from this
same round (RDS+RT combination, marquee scrolling, preset-label
fallback, server-persisted preset label) are still unconfirmed live,
independent of this one.

Same-session, small icon swap: user's own screenshot showed the
RTL-SDR sidebar nav item still using a headphones icon, left over from
when this was just the single-purpose Radio/FM tab -- now misleading
since 4 of 5 tabs (P2000/Pagers/POCSAG/RTL433) decode text, not audio.
Asked "any suggestions? maybe antenna or usb dongle" -- advised antenna
over USB dongle: reads as "receiving something over RF" generically
(covers all five tabs, not just listening), and is visually distinct
from Hardware's existing concentric-arc broadcast-wave icon and RF
Environment's bar-chart icon (a dongle silhouette reads as a generic
"device" icon at small sizes, less immediately identifiable). User
agreed. Swapped the `frontend/index.html` sidebar icon to a simple
mast + splayed dual arms + junction dot + base-stand path (matches the
existing stroke-based icon convention exactly, no fill except the
small solid junction dot). XML-validated the SVG snippet directly.

## CURRENT WORKLIST v5 (2026-07-12 end of day — supersedes v4 below; THE list to work off)

Closed since v4: Configuration → Peripherals page (fan/LED/button editor,
DONE), W17 GitHub update-check sidebar pill + all its follow-up fixes
(channel_id guard, click-navigate, apply/rollback cache refresh, header
placement, redundant-badge removal — DONE, live-verified), W19
`scripts/edit_contact.py` (DONE, live-verified), node map Home button
(placement/icon/zoom fixes — DONE, live-verified). All four folded into
CHANGELOG.md + README.md + CONFIGURATION.md where warranted (checked
systematically 2026-07-12, README was missing the Peripherals page and
the whole update-check feature — both added).

Also closed 2026-07-12: installer RTL-SDR bits (`scripts/install.sh`
section "3c"). Blacklists the kernel DVB-T stack — `dvb_usb_rtl28xxu`
(usb bridge) plus `rtl_2832`/`rtl_2830` (demodulator modules it depends
on) — into `/etc/modprobe.d/blacklist-rtlsdr-dvb.conf`, then `modprobe -r`
unloads them immediately in dependency order (bridge first) so a reboot
isn't required to test. Module spelling confirmed live 2026-07-12: user
pasted `cat /etc/modprobe.d/raspi-blacklist.conf` from the actual Pi
showing `blacklist rtl_2832` / `blacklist rtl_2830` (underscored) already
present and presumably working — I'd initially "corrected" these to the
no-underscore kernel-source spelling (`rtl2832`/`rtl2830`) from memory
without verifying against the real device, which was wrong; matched the
installer to the live-proven underscored spelling instead. Note: the
existing `raspi-blacklist.conf` is a different file from the one this
installer manages (`blacklist-rtlsdr-dvb.conf`) — likely a pre-existing
manual setup on this box, predating this installer feature. Left it
untouched (never SSH/modify the Pi unprompted); the two files coexisting
is harmless since modprobe.d loads all `*.conf` files, just redundant.
Then clones+builds `rtl-sdr` from source
(osmocom upstream, `cmake -DINSTALL_UDEV_RULES=ON`) rather than
`apt install rtl-sdr`, matching the SX1302 HAL build's from-source
pattern and leaving room to swap in the RTL-SDR Blog fork later for the
user's actual V4/R828D dongle without an apt package fighting it. Both
steps idempotent (blacklist-file-exists check, `ldconfig -p | grep
librtlsdr` check) — safe on upgrade re-runs. `meshpoint` user's
`plugdev` group membership was already handled generically elsewhere
in the installer (section 8, alongside audio/video for GPS/LoRa USB
devices) — no separate udev-rule work needed since `-DINSTALL_UDEV_RULES=ON`
has the rtl-sdr build install its own udev rules. Not yet live-verified
on the Pi (Mac-side `bash -n` syntax check only). Folded into
CHANGELOG.md (v0.7.7, Configuration and server section).

Also closed 2026-07-12: installer section "3d" builds `redsea`
(windytan/redsea, RTL-SDR RDS decoder — station name/radio text/PI
code) right after the rtl-sdr section, per user's exact given commands
(apt meson/libsndfile1-dev/libliquid-dev, `meson setup build && meson
compile && meson install`). Idempotent via `command -v redsea`. Not yet
live-verified on the Pi. Folded into CHANGELOG.md (same section).

Also closed 2026-07-12: installer section "3e" builds `multimon-ng`
(EliasOenal/multimon-ng, POCSAG/AFSK/DTMF decoder for `rtl_fm`-piped
audio). User's given commands used the project's old qt4-qmake build
(`qt4-qmake`, `libx11-dev`, etc) — verified via WebFetch against the
upstream README before writing this that multimon-ng dropped Qt4
entirely and now builds via CMake (`cmake -S . -B build && cmake
--build build && cmake --install build`); `qt4-qmake` isn't even
packaged in current Raspberry Pi OS (Bookworm) repos, so the literal
pasted commands would have hard-failed the installer under `set -euo
pipefail`. Used the current CMake build instead, apt-installing
`libpulse-dev`/`libx11-dev` (optional audio-in/X11-scope deps, still
needed) but no Qt packages. Idempotent via `command -v multimon-ng`.
Not yet live-verified on the Pi. Folded into CHANGELOG.md (same
section).

Also closed 2026-07-12: installer section "20" appends `fastfetch` to
`/home/pi/.bashrc` (user confirmed this exact path) so every login
shell shows the system-info banner, matching what the user already
sees when running `fastfetch` manually. Idempotent via `grep -qx
fastfetch`. Also renumbered every install.sh section header
sequentially 1-19 (previously had orphaned letter-suffixes like `2b`
with no `2a`, `3b`/`3c`/`3d`/`3e` under a bare `3`) — comment-only,
no behavior change. Not yet live-verified on the Pi. Folded into
CHANGELOG.md (same section).

Also closed 2026-07-12: `meshpoint report`'s CAPTURE SOURCES section
was missing a line for connected Meshtastic USB serial sticks — caught
live by the user during the fresh-flash test (their second Meshtastic
stick, separate from the SX1302 concentrator's own Meshtastic channel,
never appeared anywhere in the report, not even in MESHTASTIC TX).
Root cause (`src/cli/report_command.py:295-340`,
`_print_sources_section`): the function only ever read
`cfg["concentrator"]` and `cfg["capture"]["meshcore_usb"]` — it never
touched `capture.serial` or, critically, the top-level `cfg["serial"]`
key that `GET /api/config` (`src/api/routes/config_routes.py:144-170,
229, 304`) actually populates with LIVE `SerialCaptureSource` status
(`connected`, `frequency_mhz`, `spreading_factor`, `long_name`, etc,
via `_serial_status_entry()`). Fix: added a block in
`_print_sources_section` reading `cfg.get("serial")` (top-level, not
nested under capture) and printing one line per stick, mirroring the
existing `meshcore_usb` block. Verified with a stub `ReportData` for
both connected and disconnected states, then LIVE-VERIFIED 2026-07-12
on the fresh-flashed Pi: `serial_433: 433.875 MHz SF11 · connected ·
Meshtastic 06f4` now appears correctly under CAPTURE SOURCES. Folded
into CHANGELOG.md (CLI section). Fresh-install test overall passed —
`meshpoint report` came up clean at uptime 0m with all three networks
(LoRaWAN/Meshtastic/MeshCore) and both USB sticks reporting correctly.

Also closed 2026-07-12: split the PROTOCOLS section's merged
"Meshtastic" line into per-radio lines (user caught that the
concentrator's 869.525 MHz channel and the serial stick's 433.875 MHz
channel — physically separate meshes, different bands, can never talk
to each other — were being summed into one packet/node count). Chose
"Both" from AskUserQuestion: split PROTOCOLS AND add a dedicated
MESHTASTIC SERIAL section mirroring MESHCORE. Root-cause research
(background agent) confirmed `packets.capture_source`
(`src/storage/database.py:47`) was already tracked per-packet end to
end (`"concentrator"` vs `"serial_<label>"`,
src/capture/concentrator_source.py:160,
src/capture/serial_source.py:344, src/coordinator.py:266-278) — just
never grouped by in the aggregate queries. Added
`PacketRepository.get_protocol_distribution_by_source()` and
`.get_distinct_node_count_by_source()` (src/storage/packet_repository.py),
wired through `TrafficMonitor.get_traffic_summary()`'s new
`meshtastic_by_source` field and `/api/nodes/summary`'s new
`meshtastic_nodes_by_source` field (src/api/routes/nodes.py). CLI:
`_print_meshtastic_protocol_lines()` replaces the old inline Meshtastic
block in `_print_protocols_section` — prints one merged line when
there's only one source (unchanged single-radio behavior, verified via
existing `tests/test_report_command.py`, 15/15 still pass) or one line
per source once a second one appears in packet history, source label
as a dim suffix in the VALUE (not the key) so the 20-char `_kv` column
padding doesn't break alignment. New `_print_meshtastic_serial_section()`
mirrors `_print_meshcore_section` — one block per configured serial
stick (state, radio, channel, node ID), only prints when
`cfg["serial"]` is non-empty. Verified with stub `ReportData` for both
single-radio and split cases, and the new SQL queries verified
directly against a throwaway in-memory sqlite3 DB (no aiosqlite on
Mac) — both grouped-count queries returned correct results.
LIVE-VERIFIED 2026-07-12 on the Pi: PROTOCOLS shows two Meshtastic
lines (1,677 pkts/171 nodes via concentrator · 869.525 MHz, 13
pkts/1 node via serial_433 · 433.875 MHz), and MESHTASTIC SERIAL shows
`serial_433: connected · Meshtastic 06f4`, `Radio: 433.875 MHz ·
BW250 · SF11`, `Node ID: !09d406f4` (no Channel line — this stick's
`channel_name` is empty on the real device, correctly skipped by the
`if channel:` guard). This entire multi-radio Meshtastic reporting
feature (CAPTURE SOURCES serial line + PROTOCOLS split + MESHTASTIC
SERIAL section) is now fully closed and live-verified.

Poller → roster decision, revisited 2026-07-12: researched in depth
(background agent) — the live poll payload is pubkey-prefix + secs_ago
+ snr only (no name/position), confirmed via a real
`repeater_status.json` paste (`secs_ago` up to 2,362,482s ≈ 27 days for
older neighbours). Designed and briefly implemented a fix
(`NodeRepository.upsert_from_neighbour_report()` — placeholder name =
node_id, "newest wins" CASE on `last_heard` only, never touches
`packet_count`, mirroring the existing offline `import_meshcore_db.py`
pattern) and was about to wire it into `RepeaterPoller._poll_one` /
`_build_repeater_poller` (`src/api/server.py:880-902`) when the user
said to hold off — reverted the `NodeRepository` change cleanly
(`git diff` confirmed clean). **Decision: still open, deferred again.**
Neighbours remain topology-map-only via `repeater_status.json`, no
`nodes` table writes. If revisited: the design above is ready to
reimplement as-is — the open judgment call is specifically whether
`last_heard`/"Active (15 min)" should ever reflect secondhand
(repeater-reported) evidence vs. strictly direct/relay reception, not
a technical blocker. User added a second, stronger reason after seeing
the full Repeaters page (not just the card): a polled repeater can be
a REMOTE site the user administers, not co-located with the Meshpoint
box — its neighbours reflect its own local RF environment, which may
be geographically unrelated to what Meshpoint's own antenna can hear.
Merging that into the shared `nodes` table would conflate "nodes near
this box" with "nodes near some other site," a category mismatch on
top of the staleness/trust concerns already noted. Also: the
Repeaters page already surfaces a neighbour *count* per repeater card
(e.g. "Neighbours: 26") for monitoring purposes — the thing being
deferred is only exploding that count into individually named/
positioned roster entries, not neighbour visibility generally.

Closed 2026-07-12: made that neighbour count clickable, as a
display-only complement to the deferred decision above (no `nodes`
table writes, just presenting what's already fetched). Backend:
`meshcore_repeaters()` (`src/api/routes/meshcore_routes.py:42-71`) now
also batch-resolves neighbour pubkey prefixes against the roster
(reusing the existing `_repeater_names()` helper generically — it was
never actually repeater-specific) and attaches a `name` field per
neighbour, one query across ALL repeaters' neighbour lists combined
(not per-neighbour, not per-repeater) — verified this doesn't mutate
`RepeaterPoller.latest` (which gets persisted to `repeater_status.json`
verbatim) by building new dicts rather than enriching in place;
confirmed via a stubbed fastapi+aiosqlite unit test (no real deps on
Mac) that the source poller state stayed untouched after a call.
Frontend: new `frontend/js/neighbours_modal.js` (`NeighboursModal`,
modeled on the existing `PacketDetailModal` overlay pattern, reusing
its `.pdm-*` CSS classes rather than inventing new modal chrome) shows
neighbours sorted freshest-first (lowest `secs_ago`), each row
clickable into the standard node drawer when a name was resolved.
`repeaters_tab.js`'s Neighbours row now carries a
`data-rp-neighbours="<repeater key>"` attribute with ONE delegated
click listener on `#rp-grid` (bound once in `_mount()`, survives the
grid's `innerHTML` re-render every poll refresh — no per-card rebind
needed). Also removed the per-card "polled Xm ago" footer (`rp-card__foot`,
plus its now-dead CSS rule) per explicit user ask — redundant with the
summary bar's "Oldest poll" stat once there's only one repeater
configured. All JS syntax-checked with `node --check`; Python route
change syntax + logic checked with a stubbed fastapi/aiosqlite unit
test. LIVE-VERIFIED 2026-07-12 on the Pi: modal opened from the
Neighbours row, listed all 26 neighbours freshest-first (37m ago down
to 5d ago), several with roster-resolved names (NL-AMS-BA01-RE,
AA-Rep-Mesh-01, Repeater Baarsjes, etc — real repeaters/nodes already
known from direct/relay reception), and clicking a resolved neighbour
correctly opened the node drawer (confirmed for !5fd2a0f85c57 /
NL-AMS-BA01-RE, showing role REPEATER, protocol meshcore, full
position/signal/metrics). This feature is fully closed.

Priority order below is the recommended working order (discussed and
agreed 2026-07-12) — install.sh retest deliberately kept at the bottom
since it's on the user to run whenever ready, not a build task.

Configuration audit done 2026-07-12 (background agent, cross-referenced
all 19 `section_map` sections in `src/config.py:622-641` against every
`frontend/js/configuration/*_card.js` + backing route). Full gaps (zero
UI, YAML-only): **`repeater_poll`** (enabled/interval_minutes/whole
repeater roster incl. passwords — matches this session's own poller
work, highest priority since it's the one leaking credentials into
YAML-only territory), **`metrics`** (enabled/require_auth Prometheus
toggle, trivial 2-boolean win), **`dashboard`** (host/port/static_dir,
lower urgency — changing your own web server's port from inside itself
is awkward regardless of UI). Partial-coverage gaps worth a look:
`mqtt.tls_ca_cert` (only gap in an otherwise complete card, blocks
private/TLS broker CA config), `relay.serial_port`/`serial_baud`
(needed to point relay at a real SX1262 device, API already accepts
it). Everything else flagged was minor/edge-case (radio's
tx_power_dbm/sync_word/preamble_length/spectrum_sweep_interval_seconds,
three broadcast startup_delay_seconds fields, capture.concentrator_spi_device,
meshtastic/meshcore default_key_b64, upstream.enabled — deliberately
excluded by design per existing code comment, not a real gap). Not yet
decided which (if any) to build — recorded here as the reference audit,
revisit `repeater_poll` UI as the natural next pick given it already has
a "Deferred" cousin item (poller → roster) tracked below.

Closed 2026-07-12: Messages tab "monitor mode" (eye icon) UX fix. User
report: "when opening page it doesnt show the chats i have to press
the eye icon to show it." Root cause (background agent investigation):
`frontend/js/messaging.js:13` `_monitorMode` defaulted to `false` and
was never persisted (plain in-memory flag, unlike the map-view/
node-sort-filter localStorage precedent elsewhere) — combined with
this box being deployed as a repeater/observer (never itself a DM
party), essentially all DM traffic it sees is classified `overheard`
(`src/api/server.py:1284-1318` — tagged only when NEITHER source nor
destination is this node) and hidden by design (privacy default: don't
surface strangers' DMs unopted). Confirmed NOT a two-icon conflation —
one eye icon, one `_monitorMode` flag, consistently applied to both the
REST load (`messaging_contacts.js`) and live WebSocket routing
(`messaging.js:193-199`). User's explicit fix choice (verbatim, "Other"
answer to an AskUserQuestion offering persist-only / persist+default-on
options): "when we go to the messaging tab (page) everything should be
shown please" — i.e. always show everything on open, not a
remembered-preference system. Implemented: `_monitorMode` now defaults
`true` (was `false`), constructor comment explains why; the button's
initial markup also gets `msg-icon-btn--active` class + "Monitor ON"
title + `aria-pressed="true"` so the icon's visual state matches reality
from first render (previously only updated on click). No persistence
added — matches what the user actually asked for (always-show), not the
persist-a-toggle option. `node --check` passed. Not yet live-verified on
the Pi.

Closed 2026-07-12: `repeater_poll` config gets a dashboard UI —
Configuration → Repeater Poll (named to avoid the same collision the
"Hardware"→"Peripherals" rename fixed earlier: the top-level Radio
group already has a read-only **Repeaters** status page). Backend:
`src/api/routes/repeater_config_routes.py` (new) — `PUT
/api/config/repeater-poll`, accepts enabled/interval_minutes/repeaters
(each key/name/password/password_unchanged), merges by
lowercased-key lookup against the existing roster so
`password_unchanged=True` preserves whatever password is already on
file (mirrors the MQTT broker password's dirty-tracking convention),
saves via `save_section_to_yaml("repeater_poll", ...)`. Audit log
params deliberately exclude the password value (only logs
`repeater_keys`, never the secret). `config_enrichment.py` now also
exposes `repeater_poll` in `GET /api/config` with `password_set: bool`
per repeater instead of the real value — never sends a password back
to the browser. Wired into `server.py` (import, `include_router`,
`init_routes`). Frontend: new `frontend/js/configuration/
repeater_poll_card.js` (`RepeaterPollConfigCard`, mirrors
`serial_card.js`'s add/remove-row shape, up to 8 repeaters), wired into
`configuration_panel.js`'s `_mountSection`, plus the sidebar nav link +
section container in `index.html`, plus the route allowlist AND
command palette entries in `app.js` (`configuration/repeater-poll` —
easy to miss, there's a separate `allowedRoutes` array that silently
blocks navigation if a route isn't listed there even with the DOM/JS
otherwise wired correctly). Confirmed (per user's own question) that
the top-level Repeaters nav item auto-reveals once a repeater is
added and the service restarted — `_bootRepeatersPanel()` in
`app.js:321-333` already re-checks `GET /api/meshcore/repeaters`'s
`available` flag on every page load, no extra work needed for that
interplay. Verified end-to-end with a stubbed fastapi/pydantic/jwt
unit test (no real deps on Mac): confirmed no password leak in the GET
payload, confirmed password preservation on unchanged edit + correct
new-password set on a fresh entry, confirmed both values land
correctly in a scratch local.yaml, confirmed audit log never contains
either password. All JS `node --check`ed. Also updated README.md and
CONFIGURATION.md to reflect dashboard-editability (previously said
"repeater_poll: in local.yaml" as the only way).

Bug found + fixed same day, caught live by the user ("the repeaters
tab says admin required but i am loged in as admin" — turned out to
mean the NEW Configuration → Repeater Poll page, not the existing
Repeaters status page). Root cause: `frontend/js/app.js`'s
`_buildRouteGuard()` (client-side belt-and-braces gate) checks each
route against `identity.available_sections`, a list the SERVER
computes per role in `src/api/routes/identity_routes.py`'s
`_ADMIN_SECTIONS`/`_VIEWER_SECTIONS` tuples — a completely separate
allowlist from the `allowedRoutes` array in `app.js` I had already
updated. I added the route to `allowedRoutes` + the command palette
but missed this second, server-side list, so the client-side guard
denied navigation even for a real admin session (the toast literally
says "Admin access required" regardless of actual role, since the
guard fires before role-specific messaging). Fixed: added
`"configuration.repeater-poll"` to `_ADMIN_SECTIONS` only (not
`_VIEWER_SECTIONS` — correctly admin-only, matches every other config
page with secrets). Take-away for next time a Configuration page gets
added: THREE places need the new route, not two — `allowedRoutes` +
command palette in `app.js`, AND `_ADMIN_SECTIONS` in
`identity_routes.py`. LIVE-VERIFIED 2026-07-12 on the Pi: admin access
now works, the page loads with the existing repeater
(`da0b77f13bc7`) populated and the password field correctly shows
"Leave blank to keep current password" — confirms `password_set`
round-trips correctly end to end. This entire Repeater Poll config
page feature is now fully closed and live-verified.

Closed 2026-07-12: W20, but redesigned from the original ask before
building — user wanted advice first ("advise me first before we do
anything"). Original W20 spec was full drag-and-drop manual reordering
(hamburger icon). Recommended favorites/pin instead, citing an
existing in-repo precedent I found first: `frontend/js/node_cards.js`
+ `node_cards_sort.js` + `meshpoint_node_favorites.js` already
implement exactly this pattern for the Node Cards list (star toggle,
localStorage, favorites-pinned-first sort) — simpler to build well
(no drag/touch/accessibility work), and solves the actual want ("my
channel(s) at the top") without over-building a full ranking UI. User
agreed. Built: new `frontend/js/meshpoint_channel_favorites.js`
(mirrors `meshpoint_node_favorites.js`'s shape almost exactly —
separate module rather than generalizing the node one, since the two
domains share nothing else and duplication here is cheap and
established as the repo's convention for this kind of thing;
`meshpoint.channelFavorites` storage key, 50-entry cap vs nodes' 200
since realistically far fewer channels exist). `messaging_contacts.js`:
constructor subscribes to `MeshpointChannelFavorites.onChange()` for
auto re-render (same as `node_cards.js`'s pattern), new
`_sortChannelsWithFavoritesFirst()` (favorited channels first in
starred order, everyone else keeps existing config order, stable
sort using original index as tiebreaker — NOT a generic multi-mode
sort class like node cards has, since channels only ever need this
one sort, unlike nodes' 4 modes), star toggle button added to
`_buildConvoEl()` only for channel rows (not DMs), `.msg-convo--fav`
row highlight mirroring `.nc-card--fav`. Verified the favorites
toggle + stable sort logic with a Node.js simulation (mocked
window/localStorage/CustomEvent, no browser needed) — confirmed
toggle/has/list all work and the sort correctly pins favorited
channels first while preserving relative order elsewhere. All JS
`node --check`ed. Not yet live-verified on the Pi.

Closed 2026-07-12, same session as the channel favorites above: two
follow-on asks, both small and both frontend-only.

1. **Admin-side MeshCore channel reorder** (Configuration → MeshCore,
user's ask: "up down buttons next to the channels... admin task").
Key discovery before building anything: `meshcore.channel_keys` is
`dict[str, str]` (`src/config.py:87`) — Python dicts preserve
insertion order, `save_section_to_yaml` already writes with
`sort_keys=False`, and `_saveChannels()` in `meshcore_card.js`
already submits rows in DOM order (`querySelectorAll` returns
document order) via `PUT /api/config/meshcore/channels`. So this
needed ZERO backend changes — reordering the `<tr>` elements in the
DOM and re-saving is the entire mechanism. Added up/down (▲▼) buttons
to the `#` column of each channel row (Public row 0 stays locked/first,
never gets buttons), wired in `_wireChannelHandlers()` doing a plain
`insertBefore` swap with the previous/next sibling, new
`_reindexChannelRows()` renumbers the `#` column and disables
up/down at the top/bottom edges — called after initial render,
`_addEmptyRow()`, and `_deleteRow()`. Verified the swap semantics
with a plain-array Node.js simulation (edge no-ops, multi-move
sequences) before touching the DOM code. This also means the admin
order flows through to `GET /api/messages/channels`
(`src/api/routes/messages.py:206,224` — same `.items()` iteration)
so it's the shared default order the channel-favorites layer builds
on top of.
2. **"Fav" filter tab in Messages** (user's ask, prompted by seeing
the All/MT/MC toggle row: "maybe in the all mt mc a fav to show fav
channels"). Added a 4th toggle button next to All/MT/MC
(`frontend/js/messaging.js`). In `messaging_contacts.js`'s `render()`,
`baseChannels` special-cases `this._filter === 'fav'` to filter by
`MeshpointChannelFavorites.has()` instead of protocol; DM
conversations are naturally hidden in this mode as a side effect of
no conversation ever having `protocol === 'fav'` (documented with a
comment so it doesn't look like a bug later) — Fav is a
channels-only concept, no favorite-DMs today. Also improved the
empty-state message to be filter-aware ("No favorited channels yet
-- click the star..." instead of the generic "No conversations yet"
when Fav mode is empty). Verified all 4 filter modes (all/meshtastic/
meshcore/fav) end to end with a Node.js simulation matching the exact
filtering logic. All JS `node --check`ed. LIVE-VERIFIED 2026-07-12 on
the Pi: star toggles render and persist correctly (Public/TechInc/
PD2EMC/test all starred), the Fav filter correctly isolates exactly
those 4 (hiding unstarred LongFast/Techinc), and Configuration →
MeshCore shows the ▲▼ reorder buttons next to each channel number
(0=Public locked, 1-8 user channels). Both this session's
channel-ordering features (favorites+Fav filter, admin reorder) are
now fully closed and live-verified.

Closed 2026-07-12: "Farthest Direct Signal" imported-repeater bug.
`_get_farthest_neighbour_direct()` (`src/api/routes/stats_routes.py:313-363`,
the FALLBACK used when no genuinely-captured direct reception exists
yet — the live path via `StatsReporter.record_farthest_direct()` is
separate and was already fine) queried `neighbour_advert` packets by
max distance with no filter distinguishing Meshpoint's own captures
from historical imports.

First fix attempt was WRONG and caught live by the user pasting a
fresh screenshot still showing "Zoetermeer Repeater" after the fix —
they then had me inspect the actual production `concentrator.db`
(copied it into the repo for me to query directly, since I can't SSH
to the Pi). Background-agent research had reported the marker as
`capture_source='meshcore_db_import'` (accurate for what CURRENT
`scripts/import_meshcore_db.py` produces going forward), and I shipped
a fix based on that alone. But direct SQL inspection of the real DB
showed the actual 25 `neighbour_advert` rows all have `packet_id`
prefixed `nb:` with `capture_source` BLANK (empty string, not even
NULL) — from `import_contacts.py`, an OLDER script referenced only in
a comment now (`scripts/survey_topology_data.py:11`, the actual file
no longer exists in the repo, superseded by `import_meshcore_db.py`
but its historical output was never re-imported in the new format).
Lesson: a background agent reading current source code describes what
the code WOULD do, not necessarily what's actually sitting in a
long-lived production database — real data can predate the code that
would generate it today. Corrected fix: WHERE clause now excludes
BOTH markers — `capture_source != 'meshcore_db_import'` (current
script, defense in depth) AND `packet_id NOT LIKE 'nb:%'` /
`NOT LIKE 'meshcoredb:%'` (the actual historical marker, confirmed
zero legitimate captured packets ever use either prefix). Verified
directly against the real copied `concentrator.db`: old query matched
25 rows (all 25 were `nb:`-prefixed imports), new query matches 0 —
correct, since every neighbour_advert row in this box's actual
database is an import, none are genuine direct MeshCore neighbour
captures yet. Confirmed the frontend (`stats_tab.js:478-493`) already
handles a null/absent `farthest_direct` gracefully (falls back to the
existing `--` placeholder, same convention as the RSSI/SNR tiles) —
no frontend change needed. Deliberately did NOT exclude repeater-role
nodes — orthogonal concern, repeaters can legitimately be heard
directly. Not yet re-verified live on the Pi (the DB copy confirms the
query result, but the actual dashboard render hasn't been re-checked
since this second fix).

**Poller → roster decision: CLOSED 2026-07-12 (finally).** Reopened by
the user after seeing the Farthest-Direct-Signal fix — they pointed
out `import_contacts.py` (repo ROOT, not scripts/, git-tracked since
the very first commits) already does almost exactly the "poller →
roster" design from way earlier in this session: upserts `nodes` with
a `MAX()`-guarded `last_heard` (secondhand data can never un-freshen a
genuinely-heard node) and inserts synthetic `nb:<node_id>:<timestamp>`
packets, just run manually against a `neighbours.json` fetched from an
external URL, never wired to the live `RepeaterPoller`. This resolved
the main hesitation (was it actually safe/proven?) — it already was,
just not automated. Told the user this before building (they asked
"tell me first please" mid-implementation), then built:
- `NodeRepository.upsert_from_neighbour_report(node_id, last_heard)`
  (`src/storage/node_repository.py`) — more conservative than
  `import_contacts.py`'s own SQL: the live poll only has pubkey+SNR
  (no name/role/position like `neighbours.json` has), so this never
  overwrites an already-known role/name/position, only fills in if
  unset. `packet_count` untouched.
- `PacketRepository.insert_neighbour_report(repeater_key, node_id, snr, last_heard)`
  (`src/storage/packet_repository.py`) — same `nb:` tag, but
  `nb:<repeater_key>:<node_id>:<timestamp>` (adds repeater attribution
  the original script's flat `nb:<node_id>:<timestamp>` doesn't have),
  needed for the new per-repeater stat below.
- `RepeaterPoller._store_neighbour_reports()` (new), called from
  `_poll_one()` alongside `_store_telemetry()` — uses `result` (this
  poll's raw response), not `entry` (which falls back to the previous
  poll's neighbour list on a failed/empty poll — reprocessing THAT
  would recompute `last_heard` as freshly-newer every cycle even
  though nothing new was actually heard). Constructor gained
  `node_repo`/`packet_repo` params, wired in `server.py`'s
  `_build_repeater_poller()` via `coord.node_repo`/`coord.packet_repo`.
- `_farthest_neighbour_for_repeater()` (new, `meshcore_routes.py`) —
  per-repeater farthest-neighbour stat, added to each entry in
  `GET /api/meshcore/repeaters` as `farthest_neighbour`. Distance is
  measured from **the repeater's own position** (its `node_id` already
  has lat/lon in `nodes` from prior capture/import), NOT Meshpoint's
  own antenna — deliberate, matching the "remote repeater" reasoning
  from earlier in this decision's history: a repeater's neighbours
  reflect its own local RF environment, not Meshpoint's.
- `repeaters_tab.js` — new "Farthest neighbour" row on each repeater's
  Health card (distance/SNR/name), next to the existing "Neighbours"
  count.

Verified thoroughly before calling it done: (1) real sqlite3 test of
both new repo methods against the actual schema — confirmed a stale
secondhand report can't regress a known node's `last_heard` or clobber
its real name, confirmed a brand-new neighbour gets a placeholder name,
confirmed re-polling replaces rather than duplicates the per-repeater
packet, confirmed a genuinely fresher secondhand report DOES advance
`last_heard` when appropriate; (2) real sqlite3 test of
`_farthest_neighbour_for_repeater()` with two repeaters at different
sites and overlapping neighbour pools — confirmed correct per-repeater
attribution (no cross-contamination) and correct use of the repeater's
own position, not a device-wide one; (3) direct call to
`RepeaterPoller._store_neighbour_reports()` with fake repos — confirmed
pubkeys get lowercased, invalid/empty entries get skipped, repeater_key
flows through correctly to the packet tag. Existing
`tests/test_repeater_poller.py` (10 cases) and
`tests/test_report_command.py` (15 cases) both still pass unmodified —
no regressions from the constructor signature change. All Python
`ast.parse`-checked, all JS `node --check`ed.

LIVE-VERIFIED 2026-07-12 on the Pi, with an independent cross-check:
Repeaters page showed "Farthest neighbour: 113 km · SNR -9.5 dB ·
DTIS | NL WTE | 8881ED" (pubkey `6d374dc5d68e`). User confirmed this
matches their own separately-run external tool (`web_map_repeaters.py`
→ `neighbours.json` → map at einstein.amsterdam/meshcore/, unrelated
codebase, own distance calculation) showing the identical node at
113.4 km. Also confirmed live that the real name ("DTIS | NL WTE |
8881ED") displayed correctly rather than a placeholder pubkey — proof
`upsert_from_neighbour_report()`'s "never overwrite a known name"
CASE logic worked as designed, since that node already existed with a
real name from some earlier direct/relayed capture. Also verified
(prompted by user question about the CLI's `pubkey_prefix_length: 4`
default, 8 hex chars) that this doesn't affect Meshpoint at all:
`MeshCoreTxClient.poll_repeater()` (`src/transmit/meshcore_tx_client.py:299-300`)
explicitly requests `pubkey_prefix_length=6` (12 hex chars), matching
the existing `nodes.node_id` convention everywhere else in the
dashboard — no truncation mismatch. This feature (live poller → nb:
roster + per-repeater farthest-neighbour stat) is now fully closed
and live-verified, with real-world cross-validation.

Closed 2026-07-12: `metrics` config gets a dashboard page —
Configuration → Metrics (enabled/require_auth toggles). User set up a
real Prometheus server to test against before asking for this. New
`src/api/routes/metrics_config_routes.py` (`PUT /api/config/metrics`),
`config_enrichment.py` gained a `metrics: {enabled, require_auth}`
block in `GET /api/config`. Notable: unlike every other config page
this session, this one applies LIVE with no restart — confirmed by
checking `server.py:1509-1510`, `metrics_routes.init_routes()` is
handed `config.metrics` BY REFERENCE (the same nested dataclass
instance the rest of the app shares), and `prometheus_metrics()`
reads `_config.enabled`/`_config.require_auth` fresh on every
request rather than caching a snapshot at boot — so mutating the
same object in place from the new PUT route is visible immediately.
Verified this exact behavior with a stub test (constructed both
route modules against the same `AppConfig`, called the PUT, asserted
`metrics_routes._config.enabled` flipped without re-calling
`init_routes()`). Explained the `require_auth` tradeoff honestly in
the UI copy rather than glossing over it: `require_auth=True` accepts
either the dashboard's session cookie or an `Authorization: Bearer
<jwt>` header (confirmed via `_extract_token()` in
`src/api/auth/dependencies.py:52-58`), but those JWTs are short-lived
login session tokens, not a long-lived API key — awkward for an
unattended Prometheus scrape config in practice; `require_auth=False`
is fully open but only ever exposes aggregate stats, no secrets.
Remembered the "3 places, not 2" lesson from the repeater-poll page
this time: wired `configuration/metrics` into `app.js`'s
`allowedRoutes` AND command palette AND `identity_routes.py`'s
`_ADMIN_SECTIONS` (the piece that was missed last time and caused a
live "admin required" bug for an actual admin session). All Python
`ast.parse`-checked, all JS `node --check`ed, existing 25-test suite
(`test_repeater_poller.py` + `test_report_command.py`) still passes.
Not yet live-verified on the Pi.

Fixed 2026-07-12: CONFIGURATION.md's "Automatic Update Checks" section
had drifted stale — still described the badge as appearing "next to
Settings in the sidebar ... and next to the Updates sub-item," which
was the ORIGINAL W17 design before the user asked to remove those two
spots ("dont show it on the settings") in favor of a single pill under
the device name/status at the top of the sidebar. Verified against
actual current code (`frontend/sidebar/update_check_badge.js:11-13`'s
own comment: "Only drives the one header pill ... the Settings-group/
Updates-subitem badges were dropped per user request") before fixing
the wording — confirmed README.md and CHANGELOG.md were already
correct/up to date, only CONFIGURATION.md had the stale description.

Metrics config page (closed earlier this round): user's own "admin
required even when logged in" concern this time turned out to be a
false alarm — checked `identity_routes.py` and confirmed
`"configuration.metrics"` WAS already correctly in `_ADMIN_SECTIONS`
(the "3 places, not 2" lesson from the repeater-poll page held this
time); likely just a deploy-timing question, resolved itself. Then
**LIVE-VERIFIED end to end with a real Prometheus server**: user set
one up specifically to test this feature. Walked through: `curl
.../metrics` (confirmed all ~26 metrics render correctly with real
live values — 1669 nodes, RSSI/SNR averages, relay stats, SX1302 CRC
counters, etc), added a `meshpoint` scrape job to the user's real
`prometheus.yml` (gave the full file back, not just a diff, since
they asked), reload via lifecycle API failed ("Lifecycle API is not
enabled") so used `systemctl restart prometheus` instead, then
confirmed via a screenshot of Prometheus's own Status → Targets page:
both `prometheus` (self) and `meshpoint` jobs showing `UP`, 69ms
scrape latency. Ran a live query (`meshpoint_nodes_total` → `1669`,
screenshot confirmed) proving the whole pipeline works. User chose
`require_auth: false` for their test setup ("we turned it off on the
web for testing") after I explained the JWT-expiry tradeoff. Docs:
added a full "Available metrics" table (all ~26 metric names/types/
descriptions, pulled directly from `metrics_routes.py`'s
`_render_metrics()`, not guessed) and a "Connecting a Prometheus
server" section (sample scrape config, reload/restart commands,
verification query) to `docs/CONFIGURATION.md`'s Prometheus Metrics
section; README's existing Prometheus bullet extended to mention the
new Configuration → Metrics page and point to CONFIGURATION.md for
the full reference (the `/metrics` endpoint itself is inherited from
upstream, only the config PAGE is new this session — CHANGELOG bullet
already scoped correctly, left as-is). This feature is about as
thoroughly live-verified as anything gets this session — real
external tool, real screenshots, real data flowing end to end.

Closed 2026-07-12: P2000/Pagers RTL-SDR tabs. User asked to
"investigate first" — spawned a background agent to map the existing
RTL-SDR listener architecture before designing anything, then verified
its key claims directly (read `rtl_listener.py` myself) rather than
trusting the report blindly. Findings that shaped the design: the FM
listener already does a `rtl_fm | tee >(redsea) | ffmpeg` two-stage
pipeline via asyncio subprocess with its own process group for clean
`killpg` teardown (`src/audio/rtl_listener.py:258-284`) — the closest
existing precedent, though P2000/Pagers are actually simpler (no
ffmpeg stage, since there's no audio — multimon-ng's own stdout IS the
decoded output). No existing WebSocket infra for this (the FM listener
uses HTTP chunked audio + polling `/api/listener/status` every 500ms),
so P2000/Pagers follow the same polling convention rather than new
plumbing. Critically: **no concept existed of "only one thing can hold
the dongle at a time"** — a real gap, since a single RTL-SDR can only
tune one frequency for one process.

Asked the user two design questions before building: (1) exclusivity
model — chose **manual stop required** (starting one while another is
active returns an error, not auto-stop); (2) navigation — chose
**tabs inside the existing RTL-SDR page**, not new sidebar entries.
Mid-build, user also corrected the exact pipeline commands they'd
originally given: **removed `-a SCOPE`** from both P2000 and Pagers
(it's for an X-window waterfall display we don't have on a headless
service) — caught before I'd used it anywhere consequential.

Built: `src/audio/sdr_registry.py` (new, tiny shared "who owns the
dongle" claim/release registry — `claim()` no-ops for the same owner,
raises `RuntimeError` for a different one, `release()` is a safe
no-op if some other owner already claimed it since). Wired into the
EXISTING `RtlListener.tune()`/`_stop_locked()`/`_read_loop()` (3
integration points, `src/audio/rtl_listener.py:164,347,375`) so the FM
listener respects the same registry, not just the new pager kinds.
New `src/audio/pager_listener.py`: `PagerListener(kind)` parameterized
class (kind = "p2000" or "pagers", nearly identical pipelines just
different frequency + multimon-ng `-a` flags), mirrors
`RtlListener`'s retry-on-busy-device pattern, in-memory `deque(maxlen=200)`
message ring buffer, idle-watchdog auto-stop after 10 min of no status
polling (matches the FM listener's `_IDLE_STOP_SECS` convention). New
`src/api/routes/pager_routes.py` (two routers, `/api/p2000/*` and
`/api/pagers/*`, both wrapping the same shared endpoint-builder
function to avoid copy-paste — verified via stub test that each
router's closures correctly bind to their OWN listener instance, not
a late-binding bug where both would point at the same one). Wired into
`server.py` (lifespan start/stop, route registration).

**multimon-ng output parsing is UNVERIFIED against real hardware** —
important caveat to carry forward. No RTL-SDR or multimon-ng on the
Mac dev machine, so `_parse_line()`'s FLEX/POCSAG regexes were written
from documented/expected multimon-ng output conventions, not tested
against a real captured signal. Designed defensively: any line
starting with a recognized protocol prefix (`FLEX:`/`POCSAG`) but not
matching the expected field layout still gets surfaced as a raw
"unknown" message rather than silently dropped, so a format mismatch
degrades gracefully instead of losing real decoded pages. **Expect to
need adjustment once tested live on the Pi with a real dongle and
signal** — flagging this explicitly so it's not mistaken for
something fully proven.

Frontend: new `frontend/js/pager_panel.js` (`PagerPanel`, reused for
both kinds — message log + Start/Stop button + status line, polling
every 2s). `listener_panel.js` gained a small tab bar (Radio/P2000/
Pagers) wrapping the EXISTING FM markup in a `data-tab="radio"` div
(verified this doesn't break any of the existing `root.querySelector()`
calls, since they still find the same IDs regardless of added nesting
depth) plus two new empty tab-content divs mounted by `PagerPanel`
instances; `show()`/`hide()` now delegate to whichever tab is active
rather than always running the FM status poll.

Verified before calling it done: registry claim/release/conflict
logic (pure unit tests — same-owner no-op, different-owner blocks,
stale release doesn't clear another's claim); the FLEX/POCSAG parser
against constructed sample lines (correct field extraction, correctly
ignores blank/banner lines); a full async lifecycle test using a
stand-in shell pipeline in place of real `rtl_fm`/`multimon-ng`
(spawn → parse → status poll → cross-listener blocking → clean
teardown → registry release, all confirmed working end to end); the
pager-routes closure-binding test above. All Python `ast.parse`-checked,
all JS `node --check`ed. Not yet live-verified on the Pi — this is the
first genuinely new RTL-SDR capability to ship this session without
any live hardware test at all, given the constraints above.

Follow-up fix same round: user spotted from live screenshots that the
Pagers tab said plain "idle" while P2000 was actively listening — a
real gap, since `status()` only ever reported "is THIS listener
running," never "is the dongle busy with something else." Added
`dongle_owner: sdr_registry.current_owner()` to both
`RtlListener.status()` and `PagerListener.status()`
(`src/audio/rtl_listener.py`, `src/audio/pager_listener.py`) so every
tab can see who actually holds the dongle, not just its own state.
Frontend: `pager_panel.js`'s `PagerPanel` constructor gained a `kind`
param (had only `apiPrefix`/`title` before — needed to distinguish
"dongle_owner is ME" from "dongle_owner is someone else"); `_render()`
now shows "busy -- in use by P2000/Pagers/Radio" and disables the
Start button when a sibling holds it. Applied the identical treatment
to the Radio tab's own status text and Tune button in
`listener_panel.js` for symmetry — all three tabs now consistently
show "busy" instead of a misleading bare "idle" whenever a sibling
tab is active. Verified with a stub test: confirmed `dongle_owner`
correctly shows `None` when free, the OTHER listener's kind while it's
running, and clears back to `None` after stop. All syntax-checked.
Not yet live-verified on the Pi (same caveat as the base feature).

Closed 2026-07-12 (same day, later): added a fourth **POCSAG** tab —
same POCSAG512/1200/2400 decoders as Pagers but on a separate
439.9875 MHz band. User tested the exact command live on the Pi
(`rtl_fm -f 439.9875M -M fm -s 22050 -l 250 | multimon-ng -a POCSAG512
-a POCSAG1200 -a POCSAG2400 -t raw /dev/stdin`) and pasted the real
captured terminal output — this **confirmed the `_POCSAG_RE` regex
design from the P2000/Pagers build was correct** (first real-hardware
validation of anything in that feature), but also revealed multimon-ng
pads POCSAG alpha message text with literal `<NUL>` tokens
(`POCSAG1200: Address: 2041152  Function: 3  Alpha:   Test
message<NUL><NUL>`) that the original parser didn't strip. Added
`_TRAILING_NUL_RE = re.compile(r"(?:<NUL>)+\s*$")` in
`src/audio/pager_listener.py`, applied in `_parse_line()`'s POCSAG
branch. Added the `"pocsag"` entry to `_KINDS`; expanded
`src/api/routes/pager_routes.py` from 2 routers to 3 (same shared
`_add_endpoints()` helper, re-verified via stub test that all three
routers' closures bind to their own listener, not just the original
two); wired a third `PagerListener("pocsag")` into `server.py`
(lifespan start/stop, route registration). Frontend: added `pocsag:
'POCSAG'` to `pager_panel.js`'s `_DONGLE_OWNER_LABELS`; added a 4th
tab button/content div/`PagerPanel` instance to `listener_panel.js`
and extended `_showActiveTab()`/`_switchTab()`/`hide()`/the Radio
tab's own busy-label map to cover the `pocsag` case. All JS
`node --check`ed, changelog re-parsed with `ChangelogParser.parse_file()`.
CHANGELOG.md/README.md updated (feature bullet, setup section, API
table). Same live-verification caveat as P2000/Pagers otherwise
(exclusivity/UI flow not yet clicked through on the Pi) — see the
retest row below, now covering all three pager tabs.

Closed 2026-07-12 (same day, later still): user sent a screenshot of
POCSAG working live on the Pi (see above) and noticed the Digital/
Analogue skin toggle + "idle" status pill — which only make sense for
the Radio tab — were showing on every tab, including POCSAG, since
they lived in the shared page-level `<header class="lsn-panel__head">`
above the tab bar rather than inside the Radio tab's own card. Moved
them into a new `panel__header` row on top of the `.lsn-radio` panel
in `listener_panel.js`'s `_mount()`; the page header now holds only
the "Listener" title. Kept all existing element IDs (`lsn-skins`,
`lsn-status`, `lsn-status-dot`, `lsn-status-text`) unchanged so no
other JS (`_mountSkin()`, `_setStatus()`, etc.) needed touching — pure
markup relocation. No CSS changes needed (`.lsn-head-right` already
just an inline flex row, `.panel__header` already supports
space-between). `node --check`ed.

Follow-up fix same round (bug caught from a live screenshot right
after the move above): the "busy — in use by P2000" status text on
the Radio tab rendered huge/shouty ("BUSY — IN USE BY P2000") compared
to the same text on the P2000/Pagers/POCSAG tabs. Root cause: moving
`#lsn-status` into the new `.panel__header` row made it inherit that
class's `text-transform: uppercase` + `font-weight: 600` — plain
`<span>`s cascade those properties, unlike the `<button>` skin
toggles sitting right next to it, which keep their own case because
browsers' UA stylesheets reset `text-transform` on form controls by
default (that's why "Digital"/"Analogue" looked fine but the status
text didn't — same header, only the buttons were protected). Fixed
with an explicit `text-transform: none; font-weight: 400;` on
`.lsn-status` in `listener.css`. Same round, user also asked for the
status dot to go **red** while busy (a sibling tab holds the dongle),
keeping green reserved for "this tab is genuinely on air" — added
`.lsn-status__dot--busy` / `.pager-status__dot--busy` (red `#f87171`
with a matching glow, mirroring the existing green `--on` variant)
and wired `_setStatus()` (`listener_panel.js`) / `_render()`
(`pager_panel.js`) to toggle it whenever `busyOwner` is set, applied
identically across Radio and all three pager tabs. `node --check`ed.

Closed 2026-07-12 (same day, later still): user asked for a way to
tell the RTL-SDR dongle is in use from anywhere in the dashboard, not
just by opening the Listener page — confirmed they wanted "a green dot
and the title Radio/P2000/Pagers/POCSAG" next to the RTL-SDR sidebar
link. Found the sidebar already has exactly this kind of plumbing
built and reserved: `SidebarController.setStatusBadge(routeId, value,
variant)` (`frontend/sidebar/sidebar_controller.js:60`) plus a
`data-badge-for="radio"` badge span already wired to the existing
`radio_tx_badge.js` (the "TX 23h" pill next to Hardware) — same
pattern, new instance. Added `data-badge-for="listener"` next to the
RTL-SDR label in `index.html`; new `frontend/sidebar/listener_badge.js`
(`ListenerBadge` class, modeled directly on `RadioTxBadge`) polls the
existing `GET /api/listener/status` every 5 s and reads its shared
`dongle_owner` field — deliberately only ONE of the four status
endpoints, since `dongle_owner` reflects `sdr_registry.current_owner()`
process-wide and is identical across all four (`/api/listener`,
`/api/p2000`, `/api/pagers`, `/api/pocsag`); maps the owner name to a
display label (`radio`→Radio, `p2000`→P2000, etc. — duplicates the
same small mapping already sitting in `pager_panel.js` and
`listener_panel.js`, matching this repo's established
small-duplicated-helper convention rather than a new shared import) and
calls `setStatusBadge('listener', label, 'live')`, or `null` to hide
when free. New `.sidebar__badge--live` CSS variant (green dot via
`::before`, reusing the exact color/glow already used for the
Listener page's own "ON AIR" LED) added to `sidebar.css`. Wired into
`app.js` next to the other sidebar badge instantiations
(`RadioTxBadge`, `UpdateCheckBadge`). Verified with a stub test
feeding a sequence of fake `dongle_owner` values through `_refresh()`
and asserting the exact `setStatusBadge` calls (shows "P2000"/"POCSAG"
with the `live` variant, hides with `null` when owner is absent) — all
matched expected. `node --check`ed, changelog re-parsed. Not yet
live-verified on the Pi (does the badge actually show/hide correctly
when a real tab starts/stops, and does polling from a page other than
Listener work as expected through a real login session) — folded into
the existing P2000/Pagers/POCSAG retest row below.

Bug found and fixed same day, live on the Pi: the sidebar badge above
never appeared at all, even after the user redeployed and hard-refreshed
with cache cleared (both correctly ruled out as the cause along the
way — the styling fix shipped in the same deploy WAS visible, proving
the page wasn't stale). Root cause, found via the browser console:
`Uncaught SyntaxError: Identifier 'POLL_MS' has already been declared`
in `listener_badge.js`. **Lesson for this codebase**: none of the
`<script src="...">` tags in `index.html` use `type="module"`, so every
top-level `const`/`let`/`class` in every loaded file shares ONE global
lexical scope — a second file declaring the same top-level name isn't
silently shadowed like it would be in separate ES modules, it's a
hard `SyntaxError` that aborts parsing of the whole file. `POLL_MS`
was already declared at top level in `update_check_badge.js` (loaded
one script tag earlier); `listener_badge.js` declaring its own
top-level `const POLL_MS` never got a chance to run at all, so
`ListenerBadge` was never defined, `window.ListenerBadge` stayed
`undefined`, and `app.js`'s `if (window.ListenerBadge)` guard silently
skipped instantiating it — no crash surfaced anywhere else, which is
why the backend (verified correct and returning `dongle_owner: "p2000"`
via a direct `GET /api/listener/status` the user pasted) and every
other diagnostic looked clean. Fixed by renaming this file's two
top-level constants to unique names (`LISTENER_BADGE_POLL_MS`,
`_LISTENER_OWNER_LABELS`). While fixing, proactively scanned every
script-tag-loaded file in `index.html`'s load order for other
top-level `const`/`let`/`class` name collisions (none found — this was
the only one) and also for top-level `function` name collisions, which
are lower-severity (silently overwritten by whichever loads last,
rather than a hard crash) but same root cause: found five pre-existing
ones (`_escapeHtml`, `_formatRelative`, `_formatUptime`,
`_isEditingTarget`, `_parseTimestamp`, each duplicated across two
files) — left alone since none are newly introduced or reported as
broken, but worth remembering this is a systemic footgun in a
non-module multi-script frontend: **any new top-level `const`/`let`/
`class` name needs to be checked against every other loaded script,
not just its own file**, since collisions fail silently (via `function`
overwrite) or fatally (via `const`/`let` `SyntaxError`) rather than
raising anything file-local. Verified with `node --check`.

| # | Status | Effort | Item |
|---|--------|--------|------|
| — | Open | S | Prune or document the 6 kept-for-later duplicate API endpoints (packets/count+protocols+types, nodes/map+summary, telemetry/*) |
| — | Open | M | Server-side downsample-across-range for the Repeater Trends chart — a fixed high limit (`hours=100000&limit=50000`) will eventually start truncating again as live polls keep growing the row count unbounded |
| W14 | DONE 2026-07-12 | M | **Stray Frames.** See closure paragraph below (built as an in-memory ring buffer, not a DB table, per user's explicit "test first" ask). |
| — | DECIDED 2026-07-12 | — | **Stray Frames storage: ring buffer is enough, closed.** After real runtime (561 RF scans), card showed its first genuine entry — a 58-byte `meshtastic`-hinted frame from `concentrator` (-92.4 dBm / -6.0 dB SNR) that failed full decode, most likely an encrypted packet on a channel we don't have the key for (benign, not a bug). Volume this low (1 frame after hundreds of scans) doesn't justify a persisted DB table + retention cap — user explicitly decided the in-memory ring buffer (`deque(maxlen=500)`, resets on restart) is sufficient as-is. Closes the open question this feature was built to answer; no further action unless real-world volume changes materially later. |
| W18 | Open | S-M | Mini RTL-SDR player widget — when the Radio/RTL-SDR listener is actively streaming, show a small persistent player (bottom-left of the sidebar/menu) with basic transport controls (stop, etc.) so the user doesn't have to navigate back to the Radio page just to stop playback |
| W6 | Open | M-L | True-RF S-meter via pyrtlsdr — real dBm instead of post-demod audio loudness |
| W5 | Open | M-L | DAB+ listener mode via welle-cli — unlocks NPO Radio 5 (DAB-only) |
| W4 | Open | L | Light theme — tokenize the dark-first CSS, light map tiles, per-page contrast pass; topbar toggle already has a slot reserved |
| W2 | Parked | M | LoRaWAN key store + MIC verify/decrypt — trigger: you run your own LoRaWAN devices |
| W11 | Parked | M | TTN uplink-only forwarder — trigger: TTN entanglement deemed worth it |
| — | Noted | — | Firmware flasher / companion version check (upstream #85/#59) — if flashing the 3 sticks becomes a pain |
| — | Noted | — | Reticulum as 6th network on the spare Heltec V3 433 (upstream #11) — wildcard |
| — | DONE 2026-07-12 | XS | **Installer installs rtl_433** (generic RTL-SDR OOK/FSK decoder). User initially gave from-source build commands (clone → `mkdir build` → `cmake ../` → `make`/`make install`, matching the redsea/multimon-ng pattern) — added as new section 9 in `scripts/install.sh` that way first. Then the user asked a clarifying question about `apt-get install -qq` (does `-qq` alone limit what gets installed?) — explained `-qq` is purely output verbosity, not scope; the flag that actually limits extras is `--no-install-recommends`. User tested `sudo apt install -qq --no-install-recommends rtl-433` LIVE on the Pi and pasted the real output: only `libsoapysdr0.8` pulled in as a hard dependency, the `soapysdr0.8-module-all`/`soapysdr0.8-module` recommended packages correctly skipped, ~509 KB total — confirming the apt package is small and current enough that a from-source build wasn't warranted here (unlike rtl-sdr/redsea/multimon-ng, which lag upstream too far as apt packages). User then asked to switch the installer section to this instead. **Replaced** the git-clone/cmake/make block with a single `apt-get install -y -qq --no-install-recommends rtl-433` (note the apt package name uses a hyphen, `rtl-433`, vs the upstream binary's underscore, `rtl_433`) — no idempotency check needed since apt itself already no-ops cleanly on a re-run, matching the plain-apt convention used by the gpsd section (5) rather than the from-source skip-check convention. `bash -n` syntax-checked. CHANGELOG bullet and README's "rtl_433 (optional, installer-only for now)" manual-install snippet both updated to match (apt command, not git/cmake). At the time this row was written, this was installer-only with no dashboard tab/API — that gap was closed later the same day, see the RTL433 tab closure a few rows down. **LIVE-VERIFIED 2026-07-12**: user ran the full `sudo scripts/install.sh` in upgrade mode on the real Pi and pasted the complete transcript — `rtl_433` installed cleanly and non-interactively (`Setting up rtl-433 (25.02-1+deb13u1)`), confirming the `-y` flag works as expected end to end, not just the earlier interactive Ctrl-C'd test. **SECOND LIVE-VERIFICATION same day**: user deliberately removed `redsea`/`multimon-ng`/`rtl-433` (but left `librtlsdr` and the DVB blacklist alone) and reran `install.sh` — full transcript confirms all three idempotency checks correctly flipped from "skip" to "actually (re)build": redsea cloned+compiled via meson from scratch (including its `nlohmann_json` fallback-subproject download), multimon-ng cloned+compiled via CMake from scratch, `rtl-433` re-selected and unpacked by apt ("Selecting previously unselected package"), while `librtlsdr already installed, skipping` and the DVB blacklist check both correctly still skipped since those weren't touched. Confirms the idempotency checks test real system state each run, not a one-way "installed once, never rebuilds" flag — meaningful robustness signal for a script users may re-run after partially wiping something. Whole run completed cleanly again, no errors. |
| — | DONE 2026-07-12 | M | **RTL433 tab.** User ran the bare `rtl_433` command live on the Pi (no args, default 433.92 MHz) and pasted real captured output — decoded a `Generic-Remote` OOK device (House Code/Command/Tri-State fields) in rtl_433's default human-readable multi-line block format, and asked for a 5th listener tab "same as the other tabs listen stop indicators etc" with the same dongle-guarding. Key design call (made without a separate ask, mirroring how `-a SCOPE` was silently dropped earlier — a non-behavior-changing pipeline tweak, not a real design fork): run rtl_433 with `-F json` instead of the default text format, since rtl_433 supports 200+ device protocols with wildly different decoded field sets (a temperature sensor and a remote control share almost no fields) — JSON gives one reliable object per line rather than needing a per-device regex, and is rtl_433's own recommended machine-readable format; tuner/info logging still goes to stderr, only decoded events hit stdout. New `src/audio/rtl433_listener.py` (`Rtl433Listener`, no `kind` param needed since there's only one variant, unlike `PagerListener`) mirrors `PagerListener`'s architecture closely but simpler: ONE self-contained process (`rtl_433 -F json`, no `rtl_fm` piping needed since rtl_433 talks to the dongle directly) instead of two piped processes; `_read_loop()` does `json.loads()` per line, silently skipping non-JSON stray lines rather than crashing; same registry claim/release, retry-on-busy-device, and idle-watchdog conventions as every other listener kind. New `src/api/routes/rtl433_routes.py` (single router, same start/stop/status shape as the pager routers). Wired into `server.py` (5th listener global, lifespan start/stop, route registration) — `ast.parse`-verified. Frontend: rather than duplicate ~150 lines of `PagerPanel`'s shell for one different method, added an optional 4th constructor param (`rowRenderer`) so `PagerPanel` can be reused as-is for a message shape that isn't protocol/capcode/message — `listener_panel.js` passes a new module-level `_rtl433RowHtml(m, esc)` that shows the device `model` plus a generic `key: value` listing of whatever other fields a given event happens to carry (verified its output against the real captured device's fields — renders correctly as `model / House Code: 55853  ·  Command: 94  ·  Tri-State: 1ZXX0X1ZZZ1X`). 5th tab button/content div added, `_showActiveTab()`/`_switchTab()`/`hide()`/the Radio tab's own busy-label map all extended for `rtl433`; `_DONGLE_OWNER_LABELS` (`pager_panel.js`) and `_LISTENER_OWNER_LABELS` (the sidebar badge) both gained `rtl433: 'RTL433'`. Verified with a stub test: registry exclusivity (blocked while `radio` holds the dongle, and blocks a sibling `p2000` claim while rtl433 is running), a full async lifecycle using a real stand-in shell script emitting one valid JSON line + one deliberately-malformed non-JSON line (confirmed the malformed line is silently skipped, not crashing the reader), and the routes module's `init_routes` binding correctly. All JS `node --check`ed, all Python `ast.parse`-checked. CHANGELOG/README updated (5th tab in the feature bullet, API endpoint tables, install section reworded now that RTL433 has a real dashboard integration instead of being installer-only). **LIVE-VERIFIED 2026-07-12**: screenshot shows the RTL433 tab actually running on the deployed Pi — green "listening on 433.92 MHz" status, Stop button active, 24 real decoded `Generic-Remote` events in the log (`id`/`cmd`/`tristate` fields all rendering correctly via the generic key:value renderer). Follow-up fix same round: user's screenshot showed both the timestamp (`09:19:58 PM`) and the model name (`Generic-\nRemote`) wrapping onto two lines per row, and asked for 24-hour time. Root cause for the model wrap: `.pager-row__proto` was sized for short fixed labels like `FLEX`/`POCSAG1200` (6em), too narrow for rtl_433's longer, unbounded device model names. Fixed: added `hour12: false` to both `PagerPanel`'s default `_rowHtml()` and `_rtl433RowHtml()`'s `toLocaleTimeString()` calls (dropping the AM/PM token also removes one whole wrap-triggering word); widened `.pager-row__time` (4.5em → 5.5em, `white-space: nowrap` added since the 24h format is a fixed 8 characters) and `.pager-row__proto` (6em → 9em, no forced nowrap since some rtl_433 model names run longer still and a rare wrap there is an acceptable tradeoff over an excessively wide column for every other row). This also folded into the pre-existing "24-hour clock everywhere" CHANGELOG bullet (updated in place, parser-verified) rather than a new bullet, since it's the same sweep just missing the pager/RTL433 tabs that didn't exist yet when that sweep was made. `node --check`ed, and the exact 24-hour output re-verified against the real timestamp from the screenshot (`21:19:58`, no suffix).

**Incident same day, RTL-SDR dongle wedged after heavy tab-cycling** (2026-07-12): user reported POCSAG suddenly showing "No messages yet." despite the pipeline correctly running (`pager_listener` log confirmed the right `rtl_fm -f 439987500 ...` command, green "listening" UI) and despite confirming their real pager physically received the page — genuinely tricky, since the pipeline LOOKED healthy. First hypothesis (frequency mismatch between the 439.9875 MHz test tone used to validate parsing earlier vs. the real production paging frequency) was floated but not yet confirmed when the user pasted the real service log, which showed the actual bug: **RTL433 crash-looping** every ~13s (`rtl_433 listener starting` → `rtl_433 listener ended: Use "-F log" if you want any messages, warnings, and errors in the console.` twice in a row). Root cause: rtl_433 silently suppresses ALL of its own startup/device/error output when `-F json` is used without also specifying `-F log` — so whatever the real fatal reason was (device busy from POCSAG only 5s prior, PLL not locked, etc — the earlier manual test had already shown `[R82XX] PLL not locked!` as a real flakiness sign on this dongle) never reached our logs at all, just this one generic hint line. Fixed `src/audio/rtl433_listener.py`: added `-F log` alongside `-F json`; also fixed a related masking bug in `_read_loop()`'s EOF handler — `self._last_error = self._last_error or f"process exited (code {rc})"` meant an earlier benign stderr line (this exact hint contains the substring "error", matching `_ERROR_RE`) permanently blocked the real exit-code note from ever being recorded, even on a later genuine crash. Changed to always append the exit-code note regardless of prior content. Verified with a stub test: a stand-in process that writes the exact real hint line to stderr then exits — confirmed `last_error` now reads `"...console. -- process exited (code 0)"` instead of silently stopping at the stale hint text.

Then: user reported "radio also nogo" -- the completely separate, unmodified-this-session `RtlListener`/FM pipeline ALSO failing. Since Meshpoint's own `sdr_registry` claim/release bookkeeping was confirmed NOT leaking (the log showed a fresh "starting" line on the second RTL433 attempt, meaning `claim()` succeeded after the first attempt's EOF handler released it), a from-code registry bug was ruled out. Diagnosis: this pointed to the actual RTL-SDR USB device being wedged at the kernel/hardware level — user had also just run the installer's `sudo scripts/install.sh` upgrade (which ends with "restart the service to apply changes") a few messages earlier; a plain `systemctl restart` only restarts the Meshpoint process itself, so if any earlier `rtl_fm`/`multimon-ng`/`rtl_433` subprocess from before that restart hadn't cleanly released the USB device (orphaned rather than properly killed), Meshpoint's fresh in-memory registry would come up believing the dongle free while the actual hardware stayed locked — plus the dongle had already been rapidly claimed/released across P2000/Pagers/POCSAG/RTL433 testing all session, a known real-world trigger for RTL-SDR tuner/USB flakiness. Recommended a full reboot (clears both kernel USB state and any orphaned process, unlike a service restart) rather than more software debugging. **CONFIRMED 2026-07-12: "reboot helped"** — Radio/POCSAG/RTL433 all presumed working again post-reboot (not yet re-screenshotted, but user confirmed verbally). The original POCSAG "no messages" report was never independently re-tested after the reboot to confirm whether it was ALSO just the wedged-dongle symptom or a genuine frequency mismatch — worth a follow-up if it recurs. The `-F log`/exit-code-masking fix stands regardless, since it makes any future real crash immediately diagnosable instead of hitting this exact dead end again. |
| — | Open | S | Retest `scripts/install.sh` on a fresh microSD flash (IS_UPGRADE=0 path — new `meshpoint` user creation, first-time systemd install, SPI/UART/I2C enablement, etc. — none exercised by the upgrade-mode run below). **Upgrade-mode path (IS_UPGRADE=1) LIVE-VERIFIED 2026-07-12**: user ran `sudo scripts/install.sh` on the real Pi end to end, full transcript pasted — every section from this whole session correctly either skipped (already-satisfied idempotency checks: DVB blacklist, librtlsdr, redsea, multimon-ng, libloragw.so, fastfetch banner) or applied cleanly (rtl_433 apt install, HAL TX sync word patch/rebuild), completed with "Meshpoint upgrade to v0.7.7 complete!" and no errors. Still want a genuine fresh-flash run at some point since it exercises a different code branch entirely. |
| — | Retest | S | Metrics `require_auth`: confirm a valid session actually authenticates a `/metrics` scrape (only the "blocks with no credentials" half was tested live — 401 confirmed correct). Also consider whether a proper long-lived API-key mechanism is worth building instead of reusing short-lived dashboard session JWTs for this, since those expire and are awkward for an unattended Prometheus scrape config. User flagged 2026-07-12, deferred ("its ok for now") |
| — | Retest | S | P2000/Pagers/POCSAG tabs, remaining gap only: **POCSAG confirmed working live on the Pi 2026-07-12** — screenshot showed the tab tuned to 439.988 MHz, decoding real POCSAG1200 pages end to end through the deployed dashboard UI (tab switch, Start/Stop, status line, message log all working), including the "no Alpha field" case (a tone-only page with `Function: 2` and no text payload) correctly falling back to showing the raw decoded line since there's nothing to extract — that's the intended `m.message || m.raw` fallback in `pager_panel.js`, not a bug. Also live-confirmed 2026-07-12: red busy-dot + normal-case "busy — in use by X" text on the Radio tab (see the CSS-inheritance fix a few paragraphs up). The sidebar "dongle in use" badge (`listener_badge.js`) had a real bug — a `POLL_MS` top-level `const` collision with `update_check_badge.js` threw a page-wide `SyntaxError` that silently killed the whole file before `ListenerBadge` was ever defined, so the badge never appeared no matter how many times the user redeployed/hard-refreshed. Root-caused via the browser console and fixed (renamed to unique top-level names). **LIVE-VERIFIED 2026-07-12 after the fix**: screenshot shows the sidebar RTL-SDR item with a green dot + "POCSAG" label while the POCSAG tab is tuned to 439.988 MHz — badge now shows/hides correctly through a real deploy. **RTL433 also LIVE-VERIFIED 2026-07-12** (see its own closure row above) — running on the real Pi, 24 real decoded events shown. Still open: FLEX (P2000) has not been live-verified against a real signal, and the busy/exclusivity flow (start one tab, confirm a sibling shows "busy" and its Start/Tune is disabled) hasn't been clicked through live across all five tabs |

Closed 2026-07-12: **W14 Stray Frames** (upstream #80 — "log RF frames that fail all
three decoders instead of dropping silently"). Advised the user through two design
questions before building: (1) where in the pipeline to hook — found the single choke
point at `src/coordinator.py:275` (`PipelineCoordinator._process_capture`), the
`if packet is None: return` that already silently swallows every raw capture whose
decode failed, whether via the SX1302's protocol-hint path or the full
`PacketRouter.decode()` try-all-three fallback; also covers the separate
`meshcore_usb` → `adapt_event()` path, which bypasses `PacketRouter` entirely but hits
the same `if packet is None` line; (2) where to show it — first proposed a tab bar
inside the RTL-SDR Listener page's pattern, but caught before building that `rf_tab.js`
already uses a card-grid (`rf-grid` of `article.rf-card`) with no tabs at all, and the
Listener page's tabs exist specifically because those are mutually-exclusive dongle
owners, a constraint Stray Frames doesn't share — corrected to a new
`rf-card--wide` card instead, same family as the existing Channel histogram card.

Storage design pivoted after the user raised a concrete worry: "we use now retained
1000000 imagen we get 1m packcges we cant decode" — i.e. don't commit to a persisted
table + retention cap before knowing real-world stray-frame volume on actual broadband
SX1302 capture, which could plausibly dwarf genuine decoded traffic. Agreed: built as
an in-memory ring buffer (`deque(maxlen=500)`) instead, mirroring the exact convention
`PagerListener` already uses for its own message log in this codebase — no new DB
table, no new retention config key, resets on restart. Explicit decision: **not**
gated by a minimum frame-size filter — logs everything that fails decode, since
filtering by size risked hiding exactly the "small malformed real packet" case that's
most interesting to catch; growth is bounded by the ring buffer itself, not content
filtering.

Built: `src/decode/stray_frame_log.py` (new, `StrayFrameLog` class) — records
`received_at`/`capture_source`/`protocol_hint`/`byte_length`/`rssi`/`snr`/`raw_hex` per
entry, with the true `byte_length` always preserved even though `raw_hex` itself is
defensively capped at 512 bytes (genuine LoRaWAN/Meshtastic/MeshCore frames are far
smaller; an oversized payload here is itself a signal, not something worth storing in
full). Coordinator (`src/coordinator.py`) gained a `self._stray_frames` instance and
`stray_frame_log` property, plus the one-line hook at the existing
`if packet is None: return`. New `GET /api/rf/stray-frames` in
`src/api/routes/rf_routes.py` (`init_routes()` gained an optional 4th param, backward
compatible), wired from `server.py` via `coord.stray_frame_log`. Frontend:
`frontend/js/rf_tab.js` gained the new card (`_refreshStrayFrames()` /
`_updateStrayFrames()` / `_strayRowHtml()`), polled alongside the existing
`/api/rf/status` refresh cycle; each row is a native `<details>` element (time, source,
hint or "unclassified", size, RSSI/SNR, hex preview in the `<summary>`, full hex on
expand) — no custom expand/collapse JS needed. New CSS in `frontend/css/rf.css`
(`.rf-stray-*` classes) deliberately written using this page's existing tokenized
`var(--*)` convention rather than reusing `listener.css`'s hardcoded dark-only pager-log
colors, since `rf.css` (unlike `listener.css`) is already written for the eventual
light-theme pass (W4).

Verified without live hardware (none on the Mac dev machine, per this file's standing
convention): `StrayFrameLog` ring-buffer eviction and the 512-byte hex cap directly;
`PipelineCoordinator._process_capture()` end to end with `_router.decode` mocked to
return `None`, confirming both the hinted/fallback decode-failure path AND the separate
`meshcore_usb` failed-`adapt_event` path both land in the same ring buffer; the
`rf_stray_frames()` route function directly (stubbed `fastapi.APIRouter`), both
uninitialized (`init_routes()` never called → empty response, not a crash) and
initialized. Existing `tests/test_coordinator_location.py` (10 cases) still pass
unmodified — confirms the new `__init__` line and property didn't disturb the
location-source wiring. All Python `ast.parse`-checked, `rf_tab.js` `node --check`ed,
CHANGELOG re-parsed with `ChangelogParser.parse_file()`. README updated (RF Environment
tab bullet + new `GET /api/rf/stray-frames` row in the API table). **Not yet
live-verified on the Pi** — in particular, real stray-frame volume/content is still
unknown; that's the actual point of shipping this as a cheap ring buffer first rather
than committing to persistent storage. If it proves useful, revisit graduating to a
DB table with a real retention cap based on observed volume.

**Live-tested 2026-07-12, bug found and fixed same round**: user deployed and
screenshotted the real card twice. First screenshot: card rendering correctly, empty
(no stray frames yet) — as expected, nothing to fix. Second screenshot, after the
spectral scan had produced real histogram data: a stray-looking "No hardware scan yet.
Enable spectral scan under Configuration → Advanced or wait for the first scheduled
scan." line appeared to be rendering *inside* the new Stray Frames card, between its
hint text and its own "No stray frames yet." empty state. Traced this to a pre-existing,
unrelated bug in `.rf-histogram-empty` (`frontend/css/rf.css`) that predates this
session entirely and had simply never been visible before: the rule sets
`display: flex` unconditionally, which beats the browser's built-in
`[hidden] { display: none }` UA-stylesheet rule regardless of CSS specificity (author
stylesheets always win over UA styles unless the UA rule is `!important`) — so
`rf_tab.js`'s `emptyEl.hidden = !!hasHist` stopped actually hiding the message once a
real histogram existed to hide it for the first time. Sitting inside a
`.rf-histogram-wrap` with a *fixed* `height: 260px` and default `overflow: visible`,
the still-visible message overflowed straight past the Channel histogram card's own
bottom border into the ~16px grid gap and beyond, landing squarely inside the Stray
Frames card's box below it — nothing to do with the new feature's own code, just the
first thing on this page ever unlucky enough to expose the CSS bug. Fixed with a
`.rf-histogram-empty[hidden] { display: none; }` override (higher specificity than the
bare class rule, wins cleanly). Folded into the existing Stray Frames CHANGELOG bullet
as a same-round adjacent fix. **LIVE-VERIFIED 2026-07-12**: user re-screenshotted after
pulling the fix — Channel histogram card now ends cleanly at its own bottom border, no
more "No hardware scan yet" text bleeding into the Stray Frames card below it, which
now renders as its own separate clean box (still empty — no stray frames captured yet,
as expected right after restart).

## CURRENT WORKLIST v4 (2026-07-11 end of day — supersedes v2/v3 below; THE list to work off)

What's still open after the 2026-07-11 run, sorted in working order
(top = next up). W13/W14 sourced from upstream KMX415/meshpoint issues —
design references only, never merge upstream branches (fork has diverged).

| # | Status | Effort | Item |
|---|--------|--------|------|
| W13-p2 | **DONE 2026-07-11, ALL STEPS LIVE-VERIFIED** | M | Topology phase 2 complete: live neighbour polling (fetch_all_neighbours, per-repeater stars, skew-immune freshness), Repeaters card neighbour count, map "all positions" context layer (user screenshot: grey constellation across the Randstad behind the linked stars). See W13-p2 PLAN section for details. Only leftover: optional poller→roster/nb:-row upsert decision |
| — | Open — quick win | S | Installer RTL-SDR bits: udev rule (0bda:2838 → plugdev) + meshpoint into plugdev + dvb_usb_rtl28xxu blacklist into install.sh (all manual per-box today; see fresh-install fixes round 2) |
| W14 | Open | M | Stray-frames table — log RF frames that fail all three decoders instead of dropping silently (upstream #80) |
| W5 | Open | M-L | DAB+ listener mode via welle-cli — unlocks NPO Radio 5 (DAB-only) |
| W6 | Open | M-L | True-RF S-meter via pyrtlsdr — real dBm instead of post-demod audio loudness |
| W4 | Open | L | Light theme — tokenize the dark-first CSS, light map tiles, per-page contrast pass; topbar toggle ready for a `light` entry |
| — | Decide | S | Poller → roster? Should live neighbour polls also upsert nodes / write nb:-style rows (bump last_heard, name unknown pubkeys)? Currently repeater_status.json only, by design |
| W2 | Parked | M | LoRaWAN key store + MIC verify/decrypt — trigger: you run your own LoRaWAN devices |
| W11 | Parked | M | TTN uplink-only forwarder — trigger: TTN entanglement deemed worth it |
| — | Noted | — | Firmware flasher / companion version check (upstream #85/#59) — if flashing the 3 sticks becomes a pain |
| — | Noted | — | Reticulum as 6th network on the spare Heltec V3 433 (upstream #11) — wildcard |
| W17 | DONE 2026-07-12 | S-M | **Automatic update checks + sidebar badge.** User's own design ask: reuse the git-fetch check the "Check for updates" button already does (not the separate cheap semver-only check in `update_check.py`), config-driven interval + enable/disable toggle in `local.yaml`/`default.yaml` (not per-browser), badge appearing near a prominent nav item, click → Updates tab. Investigated first (per user's "have a look and advise me first please"): found update_routes.py's `POST /api/update/check` already does exactly the right check via `build_install_status_payload(sync_remote=True, ...)` → real `git fetch` + `commits_behind` count — recommended reusing THIS (not the separate `GET /api/device/update-check` semver-string check) so the badge and the manual button can never disagree; user agreed. Badge placement: user asked "next to nodes top place"; I initially proposed the sidebar header next to the version number, but before building, checked the actual sidebar markup and found a BETTER pre-existing answer — a badge slot already sat unused at `data-badge-for="settings/updates"` (`sidebar__badge--update` class), built in an earlier session but never wired up. Only problem: it's nested inside the collapsible "Settings" group (`data-expanded="false"` by default), so invisible until manually expanded — added a SECOND slot on the group toggle button itself (`data-badge-for="settings"`) so it's visible collapsed too, driven by the same controller. Modeled the whole frontend piece on the existing `RadioTxBadge` (`frontend/sidebar/radio_tx_badge.js`) — same poll-and-push-to-`SidebarController.setStatusBadge()` pattern — rather than inventing a new mechanism. New `src/hardware`-sibling backend: `UpdateCheckConfig` dataclass (`enabled: bool = True` — default ON, unlike fan/led/button's opt-in-false, since this is a read-only network check with no hardware risk; `interval_minutes: int = 60`), added to `AppConfig` + `_apply_yaml`'s `section_map` (checked immediately via real `load_config()`, not just `_merge_dataclass` — the T19 lesson stuck). `update_routes.py` gained: `periodic_update_check_loop()` (background task, same lifecycle as fan/led/button — `create_task` in `lifespan()`, cancelled on shutdown; runs an immediate check on start then repeats; interval floored at 5 min since each check is a real git fetch, not a cheap request), a module-level `_last_periodic_check` cache, `GET /api/update/badge` (cheap, cache-only, admin-gated same as the rest of this router), `PUT /api/update/check-settings` (mirrors the `hardware_config_routes.py` pattern — always `restart_required: True`, since the loop only starts once at boot). **Caught mid-build by the user's own question** ("when doing the check by button press will the update pill/message also show?"): the manual Check button's handler never touched `_last_periodic_check` at all — a manual check would update the Updates PAGE but the sidebar badge would stay stale until the next scheduled background tick, up to `interval_minutes` later. Fixed: `check_for_updates()` now also writes into `_last_periodic_check`, but ONLY when the check has no `channel_id`/`custom_branch` override — checking some OTHER picker channel out of curiosity must not make the badge misreport the actually-installed channel's status. Frontend: `update_check_badge.js`'s `refreshNow()` is called from `update_panel_controller.js` right after a successful manual check, so the badge updates instantly rather than waiting for its own 5-minute poll. `config_enrichment.py` gained an `update_check: {enabled, interval_minutes}` block so the new small form on the Updates page (`data-update-auto-form`, added directly into the existing 678-line `UpdatePanelController` rather than a separate mounting system, since that controller already owns the whole Updates page) can pre-populate. Tests: 9 new cases appended to the EXISTING `test_update_routes.py` (using its established real-TestClient-with-JWT-cookies convention, not the direct-async-call style used in `test_hardware_config_routes.py` — different existing convention per file, followed each file's own) covering the badge's 3 states, admin-gating, settings save + floor validation, and — critically — both halves of the manual-check-updates-cache guard (plain check does, channel-override check doesn't). CI-only (fastapi), confirmed NOT runnable even via `/opt/homebrew/bin/python3.11` (no fastapi there either) — verified entirely by careful manual code review against the exact implementation, same limitation as this file's pre-existing tests. Docs: new "Automatic Update Checks" section in `CONFIGURATION.md` (after Repeater Polling), CHANGELOG bullet under "Self-update system" (parser-verified). **BUG FOUND live-testing 2026-07-12**: after redeploying, page showed "1 commit behind" on the Updates page itself but the sidebar badge stayed empty ("no pill or update warning"). Root cause: the dashboard's Check button ALWAYS sends a concrete `channel_id` (whatever's selected in the picker, e.g. `"stable"`) — never `null` — so the guard `if req.channel_id is None` never matched in real usage, meaning a normal manual click never actually refreshed `_last_periodic_check`, only the periodic loop could (and the badge lagged behind whatever the loop's last run found). FIXED: compare `req.channel_id` against the result's own `active_channel_id` (derived from the REAL installed branch inside `build_install_status_payload`, independent of what channel was requested) instead of checking for `None` — `is_own_channel = req.channel_id is None or req.channel_id == result.get("active_channel_id")`. Also clarified to the user that `interval_minutes`/`enabled` changes only take effect on a service restart (read once at boot, not hot-reloaded) — they'd saved a 5-min interval via the form but not yet restarted, which wouldn't have shown anything regardless of the channel_id bug. **LIVE-VERIFIED 2026-07-12** after restart: amber "Update" pill appeared next to Settings in the sidebar exactly as designed (screenshot confirms). W17 fully closed — badge, manual-check-sync, and config-driven interval all confirmed working on the real deployment. **ONE MORE FIX same round** (user: "clicking on the pill should open the update tab now it unfolds the settings menu"): the Settings-group badge sits INSIDE the group's expand/collapse `<button>`, so any click there — badge or not — fired `_handleGroupToggle` and just toggled the group open, never navigated. Fixed generically in `sidebar_controller.js`: badges can now opt into "click navigates" behavior via a new `data-badge-route` attribute (added to the Settings badge span, value `settings/updates`); `_handleGroupToggle` checks `event.target.closest('[data-badge-route]')` first and calls `this._router.navigate(...)` instead of toggling when a click lands on such a badge. The OTHER badge slot (nested inside the real `<a href="#/settings/updates">` Updates link) already navigated correctly on its own, needed no change. Changelog bullet updated in place (still same "Automatic update checks" entry, parser-verified) rather than a new one, since it's a fix to that same not-yet-released feature's description. NOT yet Pi-verified — user needs to pull/restart and confirm clicking the Settings pill jumps straight to Updates instead of just expanding the group. **YET ANOTHER GAP same round** (user: "after applying update also remove the update pill, now it stayed until a new check was done"): traced `_finishUpdateResult()` in `update_panel_controller.js` — on a successful apply/rollback that DID detect a restart (`log` has an `'upgrade'` step with `returncode===0`), it already does a full `window.location.reload()` after the service comes back online, which WOULD naturally re-poll a fresh badge on the new page load; but the `else` branch (apply succeeded without that specific restart signature) only calls `this.refresh()` — which only touches `UpdatePanelController`'s OWN local state, never pokes the separate `UpdateCheckBadge` sidebar object at all — leaving the badge stuck showing "Update" for up to the full poll interval even though the underlying git state just changed. Fixed: both branches now call `window.updateCheckBadge?.refreshNow()` unconditionally after success (harmless no-op right before the reload in the restarted case; the actual fix in the non-restarted case) — same shared code path serves both `_apply()` and `_rollback()` since they both funnel through `_finishUpdateResult()`. Changelog bullet extended in place (same "Automatic update checks" entry, parser-verified). NOT yet Pi-verified — user needs to pull/restart, apply or rollback something, and confirm the badge clears promptly afterward instead of lingering. |
| — | DONE 2026-07-12 | XS | **Home button zoom bumped 13→14** — user's one-line follow-up ("the home button zoom level in one more please") after trying it live. `NodeMap.centerOnHome()` in `node_map.js` updated; changelog bullet adjusted in place (still same entry, parser-verified). |
| — | DONE 2026-07-12 | S | **Update pill moved to the sidebar header, not just buried in the collapsed Settings group.** User's screenshot showed the device header (logo, "PD2EMC" / "online · v0.7.7") and asked to put the update pill "under the online" so it's not hidden down somewhere. New `<a href="#/settings/updates" id="sidebar-update-pill" class="sidebar__badge sidebar__badge--update sidebar__badge--header">` as a third row inside `.sidebar__device` (column-flex, so it naturally stacks below the status line) — a PLAIN anchor link, not a JS-click-wired element, since `router.js` already listens globally for `hashchange` (confirmed by reading it first), so clicking just navigates on its own with zero extra wiring, unlike the Settings-group badge which needed the `data-badge-route` interception fix (that one's nested inside a `<button>` that would otherwise swallow the click as a toggle). New `.sidebar__badge--header` CSS override (the base `.sidebar__badge` has `margin-left:auto`, meant for a horizontal nav-row context — wrong for this column layout, so overridden to `align-self:flex-start` + top margin, hugging the left edge under its siblings). `UpdateCheckBadge._apply()` now also toggles this element's `style.display` alongside the existing two `setStatusBadge()` calls (left those in place too — the Settings-group ones still add useful context once that group is expanded, no reason to remove them). Changelog bullet updated in place (parser-verified). NOT yet Pi-verified — user needs to pull/restart and confirm the pill shows up right under "online · v0.7.7" and navigates to Updates on click. |
| — | DONE 2026-07-12 | XS | **Home button screenshot revealed two bugs, both fixed.** (1) It rendered dead-center in the Node Map panel header instead of next to the expand button — root cause: `.panel__header` uses `justify-content: space-between`, which was fine with exactly two children (title text + expand button) but treated a THIRD inserted middle child (the home button) as its own flex item, splitting the header into three evenly-spaced slots instead of two. Fixed by wrapping both action buttons in a new `.panel__header-actions` div (flex row, small gap) so `space-between` only ever sees two top-level children again. (2) User: "make it a normal icon not color emoji we dont have them on the webinterface make it a gray house same color style as the rest" — swapped the 🏠 emoji for a stroke-style SVG house icon (Feather-icon-style path, matching the `stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"` convention every other icon in this app already uses, e.g. the sidebar nav icons and collapse chevron) — inherits `.map-expand-btn`'s `color: var(--text-muted)` automatically via `currentColor`, so it's the same gray as the expand icon and brightens on hover exactly the same way, no new color rule needed. Changelog bullet extended in place (parser-verified). **LIVE-VERIFIED 2026-07-12** (user screenshot): house icon renders gray/monochrome, grouped correctly next to the expand button, not centered. Both fixes confirmed working. |
| — | DONE 2026-07-12 | M | **Found and fixed the REAL root cause of the badge-doesn't-clear-after-apply bug, plus removed the now-redundant Settings badges per user request.** User's live report after applying an update + doing a backup: "apply update didnt remove the update badge... they gone away after the next scheduled check not after boot... when refreshing the page with ctrl-r the go away, wierd." Traced this precisely: the earlier "fix" (`window.updateCheckBadge?.refreshNow()` called from `_finishUpdateResult()`) only told the FRONTEND to re-poll `/api/update/badge` — but that endpoint just returns whatever's cached in the backend's `_last_periodic_check` global, and NEITHER `apply_update()`/`apply_update_stream()` NOR `rollback_update()`/`rollback_update_stream()` ever recomputed that cache themselves. If the process happened to restart after apply, the in-memory cache would reset to `None` and the fresh boot's own immediate check would eventually fix it — but if no restart occurred (or the restart-detection didn't trigger), the SAME stale "commits_behind" answer just kept getting served over and over, explaining "not after boot" precisely. The user's ctrl-r "fix" was coincidental: a normal scheduled interval tick had likely already corrected the cache in the background by the time they refreshed, unrelated to the refresh itself. REAL FIX: extracted the periodic loop's core git-fetch-and-cache step into a shared `_run_and_cache_check(log_context)` helper; added `_refresh_badge_cache_in_background(log_context)` (fire-and-forget `create_task`, not awaited, so it doesn't hold up the apply/rollback HTTP response for an extra git fetch) called from all FOUR apply/rollback endpoints (`/apply`, `/apply/stream`, `/rollback`, `/rollback/stream`) whenever `result.success` is true — now the backend cache itself gets recomputed immediately after any successful action, independent of whether a restart happens or when the next scheduled tick would've fired. New tests in `test_update_routes.py`: `test_successful_apply_refreshes_the_badge_cache` (mocks `_refresh_badge_cache_in_background`, asserts called once with `"Post-apply"`) + `test_failed_apply_does_not_refresh_the_badge_cache` (fakes an unsuccessful `ApplyResult`, asserts NOT called) — CI-only same as the rest of this file. SEPARATELY, user: "dont show it on the settings" (referring to the smaller Settings-group/Updates-subitem badges, now redundant next to the more prominent header pill) — removed both HTML badge spans (`data-badge-for="settings"` on the group toggle, `data-badge-for="settings/updates"` on the Updates subitem), `update_check_badge.js`'s `_apply()` now only drives the header pill, and reverted the now-unused `data-badge-route`/click-interception logic from `sidebar_controller.js`'s `_handleGroupToggle` (dead code with its only caller removed — clean revert, not a hack). Changelog bullet rewritten in place to describe the real (not the earlier believed) fix, still parser-verified. NOT yet Pi-verified — user needs to pull/restart and confirm: (a) Settings no longer shows any badge, (b) applying or rolling back clears the header pill promptly instead of waiting for the next scheduled interval. |
| W18 | Open | S-M | Mini RTL-SDR player widget — when the Radio/RTL-SDR listener is actively streaming, show a small persistent player (bottom-left of the sidebar/menu) with basic transport controls (stop, etc.) so the user doesn't have to navigate back to the Radio page just to stop playback. User request 2026-07-12, added to wishlist, not yet built |
| W19 | DONE 2026-07-12 | S | **`scripts/edit_contact.py`** — user's own motivation: "i have a id wich shows wrong gps and i know where they live." Interactive CLI: takes node_id as an arg or prompts for it, looks the node up (`nodes` table, same schema as `purge_self_originated_node.py`), shows all fields, asks "Edit this node? [y/N]" (n/blank cancels), then prompts each editable field (`long_name`, `short_name`, `latitude`, `longitude`, `altitude`) with the current DB value shown in brackets as the default — exactly the "Name (Einstein): press Enter for default" flow the user specified. Invalid float input on lat/lon/altitude retries instead of crashing or silently accepting garbage. Shows a full old→new change summary and asks for a SECOND confirmation before writing (extra safety since this mutates real data, unlike the dry-run-by-default purge/backfill scripts — here the two-step "edit? / write?" confirmation serves the same role). Deliberately scoped to just those 5 fields — skipped `role` (enum-like, free-text entry risks invalid values) and left `node_id`/`protocol`/`hardware_model`/`firmware_version`/`last_heard`/`first_seen`/`packet_count` read-only (identity/computed/operational fields, not user-editable data). Followed the exact sibling-script conventions: raw `sqlite3` (not aiosqlite — standalone script), `_normalize_node_id()` strips `!`/`0x` prefix (copied from `purge_self_originated_node.py`), default DB path `/opt/meshpoint/data/concentrator.db` overridable via `--db`. Verified end-to-end against a scratch DB (2 nodes, one with real coords, one all-NULL): GPS-correction happy path persisted correctly and left the other node untouched; cancel-at-edit-prompt; node-not-found; invalid-float-then-retry-then-cancel-at-final-confirm (didn't write) — all 4 scenarios passed. No permanent test file, matching the established precedent for this whole script family (`purge_self_originated_node.py`/`repair_neighbour_timestamps.py` have none either — scratch-DB verification is this repo's convention for one-off DB maintenance scripts, not pytest suites). Changelog bullet added under "Import and maintenance scripts" (parser-verified). **LIVE-VERIFIED 2026-07-12** on the real Pi against a real MeshCore repeater node (`76b8d5759004`, "NL-AMS-Spz") — lookup and full-field display worked correctly against the live `concentrator.db`, cancel-at-edit-prompt worked cleanly. Edit path (not just cancel) not yet exercised live, but the underlying write logic is the same one already verified against the scratch DB. |
| — | DONE 2026-07-12 | M | **Configuration → Peripherals page** (fan/LED/button editor). Discovered mid-build that LED/button controllers (`src/hardware/led_status.py`, `button_control.py`) and their `LedConfig`/`ButtonConfig` dataclasses already existed from a prior session, section_map already correct (no repeat of the T19 fan bug) — this session only needed the editing UI, not the controllers. New `src/api/routes/hardware_config_routes.py` (`PUT /api/config/hardware/{fan,led,button}`, always `restart_required: True`, `max_temp_c > min_temp_c` validator on the fan model), `config_enrichment.py` gained a `hardware: {fan, led, button}` block for form pre-population. Frontend `frontend/js/configuration/hardware_card.js` (`HardwareConfigCard`, 3 independent `.cfg-card` forms in one page, `.cfg-field--toggle` for checkboxes — checked the real convention in `mqtt_card.js` rather than inventing a new class name). User caught a real naming collision before it shipped: the top-level Radio/concentrator page is ALREADY labelled "Hardware" in the sidebar (`data-route="radio"` → visible label "Hardware") — renamed the new Configuration subsection and route to **"Peripherals"** throughout (sidebar link/section id/panel id, `configuration_panel.js` mount branch, `app.js` route list + command-palette entry, `identity_routes.py`'s `_ADMIN_SECTIONS` key) while deliberately leaving internal/non-visible names as `hardware_*` (file name, route prefix `/api/config/hardware/*`, `cfg.hardware` in the enrichment payload, `HardwareConfigCard` class) since those aren't user-facing and renaming them would've been pure churn. Tests: CI-only `test_hardware_config_routes.py` (9 cases: save+restart_required for all 3, fan temp-range validator, gpio_pin range validator, 503-when-not-loaded) + 2 new Mac-portable cases in `test_config_enrichment.py`. Changelog bullet added alongside the T18 GPIO-probe bullet (parser-verified). Same session, mid-build: user asked for 3 more wishlist items recorded without derailing the build — see [[W17]] (GitHub update-check badge), [[W18]] (mini RTL-SDR player widget), [[W19]] (edit_contact.py script) above. **LIVE-VERIFIED 2026-07-12** (user screenshot): Peripherals sidebar item active/highlighted, Fan card fully pre-populated from `local.yaml` (enabled checked, pin 13, 45/65°C, duty 0.35, hysteresis 5, poll 10s), Save → green "Saved." success message, LED card rendering below with its own fields. Page confirmed working end to end. |
| — | DONE 2026-07-12 | S | **Home button on the node map.** User first asked to make the map always open centered on home instead of the last-panned position; root-caused it to a deliberate v0.7.5 feature ("remember zoom/view across reload") they didn't realize was on purpose — asked me to revert and build a Home button instead, "easier." Reverted the always-center-home change entirely (turned out the working tree was already clean/committed by the time I went to revert it — the user or their editor had already undone it before I got there, including the memory entry documenting it, which is why that entry no longer exists here) so the original remember-view behavior is back exactly as it was. New: `NodeMap.centerOnHome()` (`frontend/js/components/node_map.js`) reads the already-cached `_lastDevice` (no separate fetch needed) and calls the existing `centerOn(lat, lng, zoom)` → `flyTo`. New 🏠 button in the Node Map panel header, placed next to the existing expand (⤢) button per the user's ask, reusing its `.map-expand-btn` CSS class (no new styles needed) with id `map-home-btn`; wired in `app.js` right before the expand-button wiring block. Changelog bullet added under "Dashboard and UI" (still parser-verified, replacing the reverted one). NOT yet Pi-verified — user needs to reload, pan away from home, click the 🏠 button, and confirm it flies back to the Meshpoint's own location. |

Closed 2026-07-11: the entire old to-do backlog (audit found #6/#7/#9
already built, #8 by-design, RSSI filter already built), importer freq/SF
stamping, repo local.yaml sync, W16 message notifications (built +
live-verified), and W13 phase 1 topology graph + map mode (built +
live-verified). W12 no longer exists as its own item — req_neighbours
lives inside W13-p2; req_regions/owner/acl/clock remain a possible
"expand repeater" card on the Repeaters tab someday.

### install.sh lgpio build deps fix (2026-07-11)
User hit `error: command 'swig' failed` at "Setting up Python virtual
environment" — lgpio (requirements.txt) compiles a C extension needing
swig + python3-dev + liblgpio-dev (documented in TROUBLESHOOTING.md since
the fan build, but never added to scripts/install.sh). FIXED: all three
added to the main apt block AND preinstalled in `_upgrade_refresh_python_deps`
(the upgrade fast path runs pip BEFORE the apt section, and `set -euo
pipefail` would abort the whole upgrade there). bash -n clean; changelog
bullet under "Configuration and server" (parser-verified). Pi-verify:
rerun the installer.

### Repeater Sensors card blank-after-restart fix (2026-07-11 evening)
User screenshot: health card fine ("polled 3m ago", green) but Sensors "NO
DATA" until next poll. ROOT CAUSE: preserve-last-good branch in
repeater_poller.py only ran on FAILED polls; an OK poll with EMPTY
telemetry (req_telemetry can return nothing while status succeeds — e.g.
companion settling right after restart) overwrote the persisted sensors
with None. FIX: `entry["telemetry"] = entry["telemetry"] or
prev.get("telemetry")` now applies unconditionally (ok or failed). Poller
tests pass; changelog bullet under "MeshCore repeaters". Pi-verify:
restart service → Sensors card should show last-known readings
immediately.

### Fresh-install fixes round 2 (2026-07-11 evening, new sensecap deploy)
- RTL-SDR "idle — Failed to open rtlsdr device #0" on new box (2nd sensecap,
  RTL-SDR Blog V4, R828D): rtl_test worked as pi but `sudo -u meshpoint
  rtl_test` → usb_open error -3. CAUSE: meshpoint user not in plugdev + no
  udev rules. FIX (manual, given to user): udev rule 0bda:2838 MODE=0660
  GROUP=plugdev in /etc/udev/rules.d/60-rtl-sdr.rules + usermod -aG plugdev
  meshpoint + udevadm reload/trigger + service restart. Deliberately NOT
  `apt install rtl-sdr` (would shadow the blog-fork rtl_fm; V4 needs the
  blog build). INSTALLER TODO (small): ship the udev rule + plugdev
  membership + dvb_usb_rtl28xxu blacklist in install.sh — all three are
  manual per-box steps today (first box had them hand-done).
- GET /api/config 500 on new box: `meshcore.private_channels:` bare key in
  yaml → None overwrites the dataclass [] default → `list(None)` crash at
  config_routes.py:223. FIXED: null-guard `or []` on private_channels AND
  `or {}` on channel_keys (same risk). LESSON: yaml bare keys beat
  default_factory — guard fields at use sites, not just _config.
- install.sh: ffmpeg added to the apt block (RTL-SDR listener audio
  pipeline needs it; was manual). Both changelogged (parser-verified).

### W13-p2 PLAN (2026-07-11, user-approved — build one step at a time)

Mostly threading one new command through machinery that already exists.

**STEP 0 (FIRST, pending — user runs on Pi):** confirm the exact
`req_neighbours` method name/shape in the `meshcore` Python lib (only seen
working via meshcore-cli in the W7 session). Snippet given to user
(read-only introspection, no radio contact):
```
python3 - <<'EOF'
import inspect
import meshcore
from meshcore import commands
print("meshcore lib:", meshcore.__file__)
try:
    print("version:", meshcore.__version__)
except AttributeError:
    pass
for name, fn in inspect.getmembers(commands.CommandHandler, inspect.isfunction):
    if any(k in name.lower() for k in ("neigh", "nb", "req")):
        try:
            print(f"{name}{inspect.signature(fn)}")
        except (ValueError, TypeError):
            print(name)
EOF
```
Output tells us whether it's `req_neighbours_sync(contact)` like the
status/telemetry pair and what args it wants → how poll_repeater calls it.

**STEP 0 DONE 2026-07-11 (live output from Pi venv,
/opt/meshpoint/venv/.../meshcore):**
- `req_neighbours_sync(self, contact, count=255, offset=0, order_by=0,
  pubkey_prefix_length=4, timeout=0, min_timeout=0)` — EXISTS, same
  contact-first sync shape as req_status_sync/req_telemetry_sync. Paginated
  via count/offset.
- **BETTER: `fetch_all_neighbours(self, contact, order_by=0,
  pubkey_prefix_length=4, timeout=0, min_timeout=0)`** — convenience helper
  that presumably loops the pagination; preferred call for poll_repeater
  (inspect its return shape when building step 1: likely list of neighbour
  dicts with pubkey prefix + snr + age). NOTE pubkey_prefix_length default 4
  — probably want 6 (12 hex chars) to match our node_id keys; verify.
- Also confirmed for the future expand-repeater card: `req_acl_sync`,
  `req_owner_sync`, `req_regions_sync` (contact,timeout), `req_mma_sync
  (contact, start, end)` — the W7-era req_mma error was the missing
  start/end args.
- **STEP 1 BUILT 2026-07-11 (code in, Pi-verify pending):**
  poll_repeater (meshcore_tx_client.py) now runs `fetch_all_neighbours
  (contact, pubkey_prefix_length=6)` as a THIRD step after telemetry —
  25s wait_for, tolerant (absence never fails the poll), result unwrapped
  via `getattr(neigh, "payload", neigh)` (Event-or-plain unknown) then
  _json_safe'd into out["neighbours"]. RepeaterPoller entry carries +
  persists "neighbours" with the same keep-last-good fallback as telemetry.
  The /api/meshcore/repeaters endpoint returns latest entries → neighbours
  visible there automatically. NOT yet changelogged (bullet when phase 2
  completes with the topo merge). Poller tests pass, py_compile clean.
  **Pi-verify step 1:** pull, restart, wait one poll, then:
  `python3 -c "import json;print(json.dumps(json.load(open('/opt/meshpoint/data/repeater_status.json'))['da0b77f13bc7'].get('neighbours'),indent=1)[:2000])"`
  → paste the SHAPE so step 2 (multi-anchor topo merge) knows the field
  names (expect pubkey prefix + snr + age per neighbour).
- **STEP 1 LIVE-VERIFIED 2026-07-11 (user pasted repeater_status.json):**
  neighbours field shape CONFIRMED on the real repeater:
  `{"pubkey_prefix": "da0b77f13bc7", "pubkey_prefix_length": 6,
  "neighbours_count": 25, "results_count": 25, "neighbours":
  [{"pubkey": "ebd1ba87b868", "secs_ago": 2238, "snr": -7.25}, ...]}`
  — 25 neighbours, pubkeys are 12-hex (== our node_id format, thanks to
  prefix_length=6), secs_ago spans 37min..24days, snr floats. EXACTLY what
  step 2 needs.
- Bonus (user idea, same evening): Repeaters health card now shows a
  "Neighbours: N" row (repeaters_tab.js, reads entry.neighbours
  .neighbours_count, fallback list length; /repeaters endpoint already
  spread the whole entry so no backend change). Pi-verify with next deploy.
- **STEP 2 BUILT 2026-07-11 (Mac-verified, Pi-verify pending):**
  assemble_graph neighbour rows now carry optional "anchor" per row
  (fallback = config anchor for import rows); topology_routes gained
  `_live_neighbour_rows()` (poller.latest → rows: anchor=key,
  source_id=pubkey, last_seen = updated_at − secs_ago our-clock,
  avg_snr=snr) appended to the SQL rows; init_routes takes
  repeater_poller, threaded in server.py (poller built before
  _init_routes — verified order). 11/11 tests incl. NEW multi-anchor +
  import/live-merge-to-one-fresh-edge. Changelog topology bullet extended
  (parser-verified). NOTE `_live_neighbour_rows` can't be Mac-tested
  (fastapi import) — logic mirrored in the tested assembly.
  **STEP 2 LIVE-VERIFIED 2026-07-11 (user screenshots):** star isolated
  via legend toggles shows solid fresh + dashed stale per-neighbour edges;
  48 nodes / 53 edges (25 route / 3 direct / 25 neighbour — graph growing
  on its own); Repeaters card "Neighbours 25" row also live. STEP 2 CLOSED.
  Also answered user q: live neighbours are NOT written to the DB (only
  repeater_status.json) — unlike import_contacts.py's nb: rows; option
  noted for later: poller could also upsert nodes/nb: rows so live
  neighbours bump last_heard/feed/roster. Decide at step 3 time.
- **STEP 3 BUILT 2026-07-11 (Mac syntax-verified, Pi-verify pending):**
  context layer. Backend: GET /api/topology/graph?context=1 adds
  `context_nodes` = positioned roster nodes NOT in the graph
  (id/name/protocol/lat/lon; default request stays light). Frontend:
  legend gains "all positions" toggle (grey dot icon, off by default,
  map-only); on first enable refetches with ?context=1, map draws faint
  grey r=3 circleMarkers as backdrop (tooltip "no link evidence yet",
  click → node drawer). Changelog map sentence extended (parser-ok).
  Pi-verify: Topology → Map → click "all positions" → ~1200 grey dots
  behind the star. W13-p2 then FULLY DONE (steps 0-3 complete; optional
  later: poller nb:-row/roster upsert decision, see step-2 note).
- Original step-2 spec (implemented as above):
  - topology_routes.init_routes gains `poller` (or provider callable);
    endpoint builds live rows from poller.latest: for each entry with
    entry["neighbours"]["neighbours"]: anchor = entry["key"], per
    neighbour: source_id = n["pubkey"], snr = n["snr"], last_seen =
    entry["updated_at"] − n["secs_ago"] (our-clock anchored, skew-immune),
    cnt = 1.
  - assemble_graph: neighbour_rows rows gain "anchor" field (fallback to
    the single anchor_node_id param for the import rows); add_edge anchored
    per row. Tests: multi-anchor + merge-with-import (same neighbour in
    import + live → one edge, newest last_seen wins).
  - server.py: thread the repeater poller into topology_routes.init_routes
    (it's built in _build_repeater_poller; check availability when
    repeater_poll disabled → provider returns nothing).
  - Then step 3: context layer (positioned-but-unlinked nodes, ?context=1
    param + faint-dot map toggle).

**1. Teach the poller to ask for neighbours (backend core).**
`MeshCoreTxClient.poll_repeater()` already does login → req_status →
req_telemetry per configured repeater. Add req_neighbours as a THIRD step
in the same sequence — same asyncio.wait_for timeout guard, tolerant: if a
repeater's firmware doesn't support it, status/telemetry still succeed. No
new connections, no new cadence — one extra command inside the existing
15-minute poll with its 5-second gaps (respects the command-channel
caution). RepeaterPoller stores the neighbour list (node key, SNR, age) in
its `latest` dict and persists it in repeater_status.json like the status
data — survives restarts. Timestamps computed as now − secs_ago (the
skew-immune lesson from the import saga).

**2. Feed the topology graph live (multi-anchor).**
Today assemble_graph() takes ONE config-derived anchor for the import star.
Generalize the neighbour input to carry its anchor PER ROW, then the
endpoint merges two sources: the static import rows (nb: / meshcoredb:) —
anchored as now — and the poller's live neighbour sets — each polled
repeater becomes its own anchor. The existing edge-merge logic (newest
last_seen wins, counts accumulate) already handles overlap, so a neighbour
seen in both the old import and the live poll shows as one fresh edge. Net
effect: the star stops being a snapshot, and a second repeater in
repeater_poll grows a second star for free.

**3. Context layer on the map (user-approved toggle).**
Graph payload gains an optional set of positioned-but-unlinked nodes
(fetched only when requested, so the default stays light); Map mode gets a
"context" legend toggle — OFF by default — rendering them as faint grey
dots with tooltips and click-to-drawer. The linked skeleton stays
foreground; the ~1200 known-location nodes become the backdrop.

**4. The usual finishing.**
One optional config knob (repeater_poll opt-out for the neighbour query,
default ON — remember the section_map lesson), Mac-runnable tests (poller
with fake client, multi-anchor assembly), changelog + README touches,
memory update. Pi verification: restart, wait one poll cycle, open
Topology — star edges show fresh timestamps; bonus: Repeaters card could
show an "N neighbours" line.

**SEQUENCE: step 0 → poller (1) → verify live neighbour fetch on Pi →
graph merge (2) → context layer (3)** — so if the repeater firmware
surprises us on req_neighbours, we find out before building on top of it.

### W13 build phase 1 (2026-07-11) — Topology page (force-directed mesh graph)

**PHASE 2 REMARK (user, 2026-07-11): MeshCore repeater neighbours still need
to be fetched FROM THE REPEATER itself.** The graph's meshcore star currently
comes only from the static imports (nb: rows from neighbours.json +
meshcoredb: archive) — a snapshot around ONE repeater. The live path is
`req_neighbours` through the existing RepeaterPoller (Repeaters tab
machinery, src/transmit/repeater_poller.py): it already logs in and polls
req_status/req_telemetry per configured repeater on a cadence; adding
req_neighbours (seen working live via meshcore-cli during the W7 session,
returns neighbour list + SNR + age) would give a LIVE, per-repeater star —
every repeater in repeater_poll.repeaters becomes its own edge source, and
the topology graph updates without imports. Store per-repeater neighbour
sets (poller latest dict + persist like repeater_status.json, or synthetic
packet rows like nb:), then topology_routes picks them up as `neighbour`
edges anchored on each polled repeater instead of the single config anchor.
This is the W12 fold-in; same caution as W7: it rides the companion's
command channel — keep cadence gentle.

DATA SURVEY FIRST (scripts/survey_topology_data.py, read-only, run live on
Pi): **NEIGHBORINFO = 0 packets — modern Meshtastic firmware doesn't
broadcast it over RF by default; the upstream #72 design leaned on it.**
What exists instead: traceroute 16 pkts → 23 hop edges (incl. a 7-node
chain); direct receptions (hop_start==hop_limit>0) 2 meshtastic nodes
(undercounted — most packets have hop_start 0; meshcore can't be detected
this way at all, its hop_limit stays 0); nb: star 25 edges w/ SNR;
meshcoredb: 0 on the live DB (archive import never run there — CORRECTION
2026-07-11, user challenged: its 715 neighbour_history rows are the SAME 25
distinct pubkeys as the nb: star → adds ZERO new graph edges, only fattens
observation counts; import stays worthwhile for telemetry History/Trends
only). NOTE the repo-root
concentrator.db is a FRESH copy of the live Pi DB (timestamps matched to the
minute) — surveys/tests on it are representative.

Build (zero capture-path changes, graph assembled at request time):
- NEW `src/api/topology_graph.py` — fastapi-free pure `assemble_graph()`
  (csv_export pattern, so Mac tests run): merges 3 edge kinds into
  undirected sorted-pair edges keyed (a,b,kind) with count/last_seen/snr/
  rssi; traceroute chains → consecutive hop pairs (blank hops filtered so
  they don't break the chain — test-caught bug); direct rows → edges from
  self node; neighbour rows → star from anchor; roster join for
  name/protocol/role; is_self/is_anchor flags; counts summary; STALE_DAYS=7.
- NEW `src/api/routes/topology_routes.py` — GET /api/topology/graph
  (viewer-open, dependencies=protected), 4 SQL queries (traceroute rows,
  direct GROUP BY source+protocol w/ AVG rssi/snr, nb:%+meshcoredb:neighbour:%
  GROUP BY source, nodes roster). init_routes(packet_repo, self_node_id=
  transmit.node_id as 8-hex, self_name=device_name, anchor_node_id=
  repeater_poll.repeaters[0].key) wired in server.py _init_routes.
- identity_routes: 'topology' added to BOTH section lists (the #2 lesson).
- NEW `frontend/js/topology_tab.js` (TopologyTab) — canvas force sim
  hand-rolled (~60 lines physics: pairwise repulsion 1800/d², springs len 90
  k .04, centering .003, damping .85, alpha decay .985, rAF loop stops at
  .005); drag node / drag background pan / wheel zoom (.2-5x) / hover
  tooltip / click = spotlight node's edges (others fade) / legend chips
  toggle edge kinds. Node color by protocol (self green + ring, anchor amber
  ring), radius by log degree, labels for named nodes (hex only when
  degree>=3); edge width log(count), stale (>7d) dashed + faded. Colors read
  from CSS vars w/ fallbacks (theme-aware). NEW css/topology.css.
- index.html: nav "Topology" in Networks after Stats, section, css+script
  tags; app.js: allowedRoutes+'topology', _bootTopologyPanel, palette entry.
- Tests: NEW tests/test_topology_graph.py (8, Mac-runnable, no stubs needed
  since module is fastapi-free) — chain pairing, edge merge+newest-ts,
  direct-to-self, no-self-id drop, anchor star, roster precedence, self-loop/
  blank skip, bad JSON. All pass. Real-data check: assemble_graph on the DB
  copy → 46 nodes / 48 edges (21 route, 2 direct, 25 neighbour), 36 named,
  self+anchor resolved w/ real names. BROWSER HARNESS (scratchpad
  topology_harness.html): real topology_tab.js + topology.css + real graph
  JSON w/ stubbed fetch, opened on the Mac — user saw it live.
- Changelog bullet under "Stats and node insights" (92, parser-verified);
  README: UI/UX fork bullet (+ message-notifications bullet added same
  round) + API table row.
- LIVE ON PI 2026-07-11 (user screenshot): 46 nodes / 48 edges render,
  meshtastic traceroute web + meshcore star + green self node all visible.
  Follow-up round from the screenshot: (1) BUG — ".topo-empty { display:flex }"
  beat the [hidden] attribute, so "No topology data yet" overlaid a full
  graph; fixed with ".topo-empty[hidden] { display:none }" (remember: any
  styled element that uses the hidden attribute needs an explicit [hidden]
  rule). (2) Zoom −/+/Fit buttons in the header (wheel zoom kept; buttons
  also cover trackpad-less/mobile); auto-fit runs once per load when the
  sim settles (alpha<0.05), Fit re-centers manually — fixes nodes drifting
  off-canvas ("blue bleep" top of screen). (3) Click now spotlights AND
  opens the regular window.nodeDrawer (needs only node_id; drawer fetches
  detail/metrics/packets itself — telemetry chart + recent packets for
  free). Harness re-verified on Mac. Changelog bullet extended (still 92,
  parser-verified). Pi re-verify: empty-text gone, auto-fit, zoom buttons,
  click → drawer.
- Follow-up 2 (user request "selectors to turn off things"): legend entries
  are now TOGGLE BUTTONS (this box / neighbour source / Meshtastic /
  MeshCore) — `this._show` map; hidden node classes leave the simulation,
  drawing, hit-testing, AND fit (`_nodeVisible`/`_visibleNodes`; edges only
  active when kind enabled AND both endpoints visible; selection cleared if
  its node hides). Off-state = dimmed + line-through + grayscale dot.
  Header chips = edge kinds, legend = node classes. Changelog bullet
  extended again (parser-verified).
- Follow-up 3 (user screenshot: unstyled white −/+/Fit/Refresh on the Pi):
  I had used `btn btn--small`, a class that DOESN'T EXIST in this app —
  the dashboard's shared small-button class is **`terminal-button`**
  (terminal.css even says "can be reused in any context"; all panel
  Refresh buttons use it). Swapped all 4 buttons. LESSON: the Mac harness
  masked it by defining its own .btn — harness now loads the real
  terminal.css instead of inventing styles; when adding UI, copy classes
  from a neighbouring panel, don't assume a generic .btn exists.
- **PHASE 1 FULLY LIVE-VERIFIED on Pi 2026-07-11 (user screenshot, "nice
  :)"):** auto-fit frames all 46 nodes / 48 edges, terminal-button styling
  correct, empty-text overlay gone, meshtastic traceroute web + meshcore
  star + green self node with direct edges all rendering, legend toggles
  present. W13 phase 1 CLOSED; phase 2 = req_neighbours live polling (see
  remark at top of this section).
- **MAP MODE added same day (user idea "map modus", default off):** Graph|Map
  lw-tabs switch in the header (localStorage 'meshpoint.topoMode', default
  graph). Data check first: 32/46 graph nodes have coordinates (all 26
  meshcore + 6 meshtastic), 29/48 edges drawable. Backend: roster SQL +
  node entries gained lat/lon (0,0 null-island treated as no position; NEW
  `_field()` tolerant accessor because sqlite3.Row has no .get and old row
  shapes lack the columns — 9th unit test covers passthrough + null-island).
  Frontend: `.topo-map` div overlays the canvas (z-index 2), Leaflet lazily
  initialized (window.L is global — index.html loads leaflet for the
  dashboard map; same CARTO dark_all tiles as node_map.js), nodes =
  circleMarkers (same colors, self/anchor ringed), edges = polylines (kind
  color, weight by count, dashed stale), tooltips + click→nodeDrawer, corner
  note counts hidden position-less nodes, zoom/Fit buttons route to leaflet
  in map mode, chips + legend toggles re-render the map, first render
  fitBounds. Harness rebuilt (leaflet from unpkg + lorawan.css for lw-tabs)
  and opened on Mac. Changelog bullet extended (parser-verified).
  MAP MODE LIVE-VERIFIED on Pi 2026-07-11 (user screenshots): Graph|Map
  tabs render, map shows the meshcore star over Amsterdam (solid fresh +
  dashed stale spokes), blue meshtastic edges, "14 nodes without position
  not shown" corner note, CARTO dark tiles. Both modes CLOSED.
- **Phase-2 idea (user-approved 2026-07-11): map "context layer" toggle** —
  optionally show UNLINKED positioned nodes as faint dots behind the linked
  skeleton (63 meshtastic + 1168 meshcore nodes have coordinates but only
  32 have known links; topology admits nodes only via edges — the dashboard
  map covers "where is everything", topology covers "what connects").
  OFF by default; do it together with req_neighbours phase 2. (The meshcore.db archive import does NOT grow the graph —
  same 25 neighbours.)

### W16 build (2026-07-11) — message toast + sound + toggles

User refined the design: "popup" = in-dashboard TOAST (never browser
Notification API — which wouldn't work anyway: plain-HTTP LAN origin is not a
secure context, so OS notifications are impossible until the box gets TLS;
tab-title unread count already existed via tab_title_telemetry.js watching
#msg-unread-badge). Zero backend changes — rides the existing
`message_received` ws broadcast (server.py:1443, has text/node_name/protocol/
direction).

- NEW `frontend/js/message_notifier.js` (MessageNotifier, window.messageNotifier):
  fires ONLY on direction==='received' (never sent/overheard — monitor mode
  would toast half the mesh); suppressed while location.hash is #/messages AND
  tab visible (still fires on the Messages page when tab hidden); bursts
  coalesce into one toast + "+N more" (no stacking); click → router.navigate
  ('messages') + messagingPanel.openConversation (same pattern as
  _openMessagingForNode; is_broadcast = node_id.startsWith('broadcast:'));
  5s auto-hide. Toggles in localStorage: `meshpoint:msg-toast:enabled:v1`
  (DEFAULT ON) / `meshpoint:msg-sound:enabled:v1` (DEFAULT OFF).
- sound_engine.js: new 'message' recipe (880→1175 Hz soft two-note) + NEW
  `playAlert(name)` = play bypassing the global UI-sounds flag; message sound
  is deliberately INDEPENDENT of the connect/disconnect chrome-sounds toggle.
  `play()` now delegates to playAlert after the enabled check.
- Toggles UI: "Message notifications" fieldset (2 checkboxes) in the Settings →
  System display card (index.html) bound in meshpoint_display_form.js (writes
  straight to messageNotifier, own status text); 2 command-palette entries
  (messages:toggle-toast 💬 / messages:toggle-sound 🔔) next to sound:toggle
  in app.js. Enabling either gives immediate feedback (probe toast / probe ping).
- `.msg-notify` CSS appended to messaging.css (top-right fixed, bg-card +
  accent-cyan border like r-toast, clickable).
- app.js boots it right after _wireSoundEvents (init(window.concentratorWS)).
- Known caveat (accepted): browsers block WebAudio until first page
  interaction — toast still shows.
- Verified on Mac: node --check on all 4 touched js; behavior test with fake
  DOM/localStorage/soundEngine (12 assertions: defaults, received-only,
  suppression on messages page, hidden-tab exception, coalescing, sound/toast
  independence, probe feedback) ALL PASS. Changelog bullet under "Dashboard
  and UI" (91 bullets, parser-verified).
- LIVE-VERIFIED on Pi 2026-07-11 (user): toast renders top-right with real
  sender "PD2EMC Companion 🏠" + snippet, "+1 more" coalescing confirmed in
  the same screenshot; sound then confirmed working too ("verified with sound
  on works"). Toast click-through → conversation not explicitly confirmed yet
  (works in the fake-DOM test; check casually sometime). W16 CLOSED.

## OLD: TO-DO LIST v2 (2026-07-08 15:22 — superseded by v3 above, kept for DONE details)

All of T1-T4, T6 DONE (see entries below). Fresh numbering:

| # | Prio | Effort | Task |
|---|------|--------|------|
| N1 | ~~P3~~ DONE (verified 2026-07-11) | M | Multiple Meshtastic USB sticks — built as `capture.serial` list (SerialDeviceConfig + label, source name `serial_<label>`, legacy scalars kept). Same item as backlog #7; running live as `serial_433` |
| N2 | DONE 2026-07-08 | S-M | Endpoint housekeeping done via live diagnosis (user ran stdlib diag script on Pi, all comparisons byte-identical). PRUNED 4: packets/protocols+types, nodes/map (+ orphans: telemetry.py router whole file, TelemetryRepository.get_latest_for_node, NodeRepository.get_with_position, NetworkMapper's get_map_data/get_all_nodes/get_nodes_with_position/get_node_count). **KEPT 2 — double-check saved us: `meshpoint report` CLI (report_command.py) uses /api/packets/count AND /api/nodes/summary** (frontend-only grep missed CLI consumers; remember to grep src/cli too when auditing endpoints). BONUS BUG FIXED: network summary totals were computed over get_all(LIMIT 500) → Stats page + CLI report under-reported (500 vs real 1445 nodes); now `NodeRepository.get_network_totals()` whole-table SQL aggregates (COUNT/SUM CASE/GROUP BY, COALESCE for empty table; SQL validated via stdlib sqlite3 on Mac). nodes.py no longer takes network_mapper (server call updated); NetworkMapper slimmed to get_network_summary→get_network_totals (stats_routes still uses it). README API table: nodes/map row → nodes/summary. 2 changelog bullets (45 total) |

Wishlist: W1 CSV export (DONE) · W2 LoRaWAN MIC verify (DEPRIORITIZED) · W3 433-node UI tags (DONE as T8) · W4 light theme (L) · W5 DAB+ welle-cli (M-L) · W6 pyrtlsdr true-RF S-meter (M-L) · W7 MeshCore repeater monitoring (DONE 2026-07-10, details below) · W8 LED (DONE) · W9 button (DONE) · W10 tab switch (DONE) · W11 TTN uplink forwarder (PARKED) · W12 repeater detail: neighbours/regions/owner/acl/clock (PARKED, see W7 note) · W13 mesh topology graph (M-L) · W14 stray-frames table (M) · W15 duty-cycle budget (ALREADY EXISTED — removed same day) · W16 message notification sound (S).

**W13-W16 added 2026-07-11 — sourced from upstream KMX415/meshpoint open
issues/PRs (user reviewed the list, picked these).** CAUTION: the upstream PRs
are OPEN/unmerged, unknown quality, and the fork has diverged heavily (auth,
sidebar, panels, CSS) — treat them as design references to reimplement
fork-style, never merge the branches.
- **W13 — mesh topology graph** (upstream PR #72): force-directed graph from
  Meshtastic NEIGHBORINFO/TRACEROUTE; fork version should also plot MeshCore
  neighbour SNR data (already imported via nb: rows + meshcore.db archive).
  Natural home for parked W12's req_neighbours data — consider folding W12 in.
- **W14 — stray-frames table** (upstream PR #80): log RF frames that fail all
  three decoders to a `stray_frames` table instead of dropping silently —
  where a 6th unknown protocol or misconfigured neighbour would show up.
- **W15 — WITHDRAWN same day (user spotted it, 2026-07-11):** the live duty
  budget already exists — `DutyCycleTracker` (src/transmit/duty_cycle.py,
  sliding window, regional caps, pre-TX check_budget refusal) + the TX Status
  card's SVG duty gauge ("X% of 10.0% allotted", radio_status_card.js).
  Upstream #74's only extra is PER-CHANNEL throttle — irrelevant here (we TX
  on one channel). Lesson repeated 5x today: check the code before listing.
- **W16 — message notification sound** (upstream issues #49/#47, twice
  requested, good-first-issue): browser audio ping in the existing
  message-broadcast path — the browser equivalent of the LED message blink.
Also noted from the same review: upstream #75 = our W4 (light theme — port if
upstream builds it first); #11 Reticulum monitoring = wildcard 6th network for
the spare Heltec V3 433 via RNode firmware; #85/#59 (dashboard firmware
flasher / companion version check) interesting but needs serial-port
release/reclaim handover from the capture sources — not listed, revisit if
flashing pain grows.

**W7 MeshCore REPEATER MONITORING — DONE 2026-07-10.** User co-designed
via live meshcore-cli tests (companion reachable at meshcore.local:5000
TCP = "PD2EMC Companion 🏠" v1.15.0; also BLE TAGs; scripts in
/Users/einstein/Software/meshcore [telemetry.sh]). Key realizations:
(1) MeshCore adverts carry IDENTITY ONLY — no telemetry broadcast like
Meshtastic — so stats must be ASKED via req_status/req_telemetry (needs
login with repeater password first). (2) The `meshcore` python lib
(2.3.7, meshcore-cli's, ~= what's on Pi) exposes
`commands.req_status_sync(contact)`, `req_telemetry_sync(contact)`,
`send_login_sync(dst,pwd)`; contact resolved via
`mc.get_contact_by_key_prefix(key)`. (3) req_status returns rich router
health: bat(mV), uptime, noise_floor, last_rssi/snr, nb_recv/nb_sent
(+flood/direct splits), airtime/rx_airtime, dups, recv_errors,
tx_queue_len, full_evts. req_telemetry returns LPP list
[{channel,type,value}]: ch1 battery V + MCU temp, ch2 solar V/A/W, ch3
BMP280 temp/baro/alt, ch4 SHT3X temp/humidity. (4) Poll through the M1's
OWN USB companion (meshcore_tx_client, already connected, has the 350
contacts) — no separate companion/CLI needed. Build:
- `RepeaterConfig`/`RepeaterPollConfig` (top-level section, enabled
  False/interval_minutes 30/repeaters list) + `_coerce_repeaters`
  (drops keyless) + section_map + regression test.
- `MeshCoreTxClient.poll_repeater(key, password)` — resolve contact,
  send_login_sync (if pwd) → req_status_sync → req_telemetry_sync, all
  asyncio.wait_for-wrapped, returns {ok,status,telemetry,error}; bytes
  JSON-safed via `_json_safe`.
- NEW `src/transmit/repeater_poller.py` — RepeaterPoller (broadcaster
  lifecycle: start/stop/loop; 45s startup delay, 5s per-repeater gap,
  interval floored 60s), maps status.bat→voltage + uptime + LPP
  ambient temp/humidity/baro → Telemetry row (drawer chart + CSV);
  keeps latest per key in `self.latest`, PERSISTS to
  data/repeater_status.json (survives restart); failed poll preserves
  last-good status + marks stale.
- `GET /api/meshcore/repeaters` (available:false when off → page hides)
  + `set_repeater_poller()` wired in server lifespan
  (`_build_repeater_poller`, stopped in shutdown).
- **Dedicated PAGE (user changed mind tab→page→stats-style):** sidebar
  nav item "Repeaters" in Radio group (id nav-repeaters, hidden until
  checkAvailable()), section, NEW frontend/js/repeaters_tab.js
  (RepeatersTab — matches stats_tab.js naming) + css/repeaters.css.
  Summary stat cards + health card per repeater (battery/uptime/temp/
  humidity/airtime/pkts/noise/snr/errors, stale badge, "polled Xm ago").
  app.js: allowedRoutes+'repeaters', _bootRepeatersPanel, palette entry.
- PASSWORD SECURITY: passwords only in local.yaml (never in GET
  /api/config — hand-built payload doesn't include repeater_poll) and
  NOT in the poller's latest/endpoint output → no redaction needed.
- Tests: test_repeater_poller.py (6: coercion, LPP→telemetry mapping,
  latest+persistence, stale-preserves-last-good, skip-empty) + config
  regression. 25 pass. ruff clean. Changelog (89, "Configuration and
  server"), README fork bullet, CONFIGURATION.md "Repeater Polling",
  default.yaml block.
- **Real name auto-shown (user follow-up):** config `name` is now
  OPTIONAL. `/repeaters` endpoint joins the nodes table (`_repeater_names`
  helper, IN-clause) → each entry gets `mesh_name` (real advertised
  name from the 350-contact roster, e.g. "NL-AMS-R-PD2EMC ☀🔋"); card
  title priority = mesh_name → config name → key. default.yaml/CONFIG.md
  updated (name commented out).
- **W12 PARKED** — more repeater query commands seen working live but
  not built: req_neighbours (repeater's neighbour list + SNR + age),
  req_regions, req_owner, req_clock, req_acl. Future "expand repeater"
  detail view. req_mma errored (needs a sensor arg).
- NOT yet Pi-verified — user: add repeater_poll to local.yaml (PD2EMC
  da0b77f13bc7 + password), restart, wait ~45s, open Repeaters page.
  CAUTION: this is the companion's command channel that wedged once
  (the messaging incident) — watch that capture/messaging stay healthy
  under polling; back-off is built in but cadence may need raising if
  it interferes.
  LIVE-VERIFIED on Pi 2026-07-10 18:59 (user screenshot): "Repeater
  da0b77f13bc7 polled OK", Repeaters page renders — real name
  "NL-AMS-R-PD2EMC ☀🔋" auto-titled (emoji intact, no config label),
  green lamp, 4.12V / 37d uptime / 218,778 recv / 88,840 sent / -103
  noise / 13 SNR / 53,022 errors / "polled just now". mesh_name join
  works.
- **TELEMETRY SHAPE BUG (found 2026-07-10 from user's live
  req_telemetry, fixed):** the first live card showed NO temp/humidity
  even though poll_repeater DOES call req_telemetry. Root cause:
  `req_telemetry_sync` returns the LPP LIST DIRECTLY
  (`telem_event.payload["lpp"]`) — NOT a dict; the CLI wraps it as
  `{"lpp": res}`. My poller stored the bare list but both `_iter_lpp`
  (telemetry-table mapper) and the card read `telemetry.lpp` → silently
  dropped every sensor. FIX: poll_repeater normalizes
  `list → {"lpp": [...]}`. Card ENRICHED: now shows Temperature (ambient
  BMP280/SHT3X), Humidity, Pressure, Solar (V·W when non-zero) from the
  LPP, plus the status counters. 2 new tests (PollRepeaterShapeTest:
  bare-list-wrapped, none-stays-none) — 8 pass. NOTE for W12/future: all
  repeater data comes through the M1's ONE connected USB companion
  (meshcore_tx_client, self._mc) — no separate connection.
  Changelog reworded (still 89).
- **ALL sensors shown (user: "where are all my sensors... more channels
  i mean"):** first sensor display collapsed to one temp + humidity +
  pressure and hid solar/altitude/MCU-temp. REDESIGNED: card now has a
  "Sensors" section (rp-card__section dashed divider) listing EVERY LPP
  reading generically via `_sensorRows` — sorted by channel, label
  `Ch{n} {type}` (barometer→pressure), unit per type, ≤2-decimal trim.
  NO per-repeater sensor-model assumptions (works for any channel
  count/sensor mix; the user's has ch1 batt+MCU temp, ch2 solar V/A/W,
  ch3 BMP280 temp/baro/alt, ch4 SHT3X temp/humidity = 10 readings).
  Radio-health rows (battery/uptime/airtime/pkts/noise/snr/errors) stay
  in the top block. Verified render with the user's real 10-reading lpp
  (node -e preview). LIVE-VERIFIED on Pi 2026-07-11 (user screenshot):
  Sensors card "3 CH · 7 VALS" — Ch1 temp+voltage, Ch3 alt/pressure/temp,
  Ch4 humidity+temp all listed; Ch2 solar correctly hidden by the
  zero-filter (evening, all readings 0). History card (5083 samples,
  min/avg/max) + Trends chart also rendering on the same page.

**W2 REFRAMED (2026-07-10 discussion, user has no own LoRaWAN devices):**
MIC verify is IMPOSSIBLE for a passive sniffer without the device's
secret key (NwkSKey/AppKey) — can only validate frames from devices
whose keys you've entered. User's captures are all strangers' devices →
W2 would light up zero rows. So W2 = "add a known-device key store +
verify + optional payload decrypt", only worth building if user starts
running their own LoRaWAN devices. The export's raw `mic` column (in the
JSON payload, not yet a flat column — decoder stores it) is all the
integrity data a pure sniffer can surface. DEPRIORITIZED hard.

**W11 TTN uplink forwarder (PARKED 2026-07-10):** the SX1302 IS literal
TTN gateway hardware, but a real gateway must TX downlinks with ms-precise
RX-window timing (our TX belongs to Meshtastic). An uplink-ONLY Semtech
UDP PUSH_DATA forwarder is feasible (M) but: we cover 5 of TTN's 8
channels, uplink-only gateways are second-class on TTN, and it entangles
the box with an external service. Decide later; not on the active list.

**W1 CSV EXPORT — DONE 2026-07-10 (user: "export button on lorawan,
meshcore and meshtastic, give all packets").** Scope: 6 endpoints
(packets + census per protocol), one context-aware Export button per
page (exports the ACTIVE tab's dataset — packets vs census, reuses the
W10 `this._tab` state). Backend: NEW `src/api/csv_export.py` — pure
helpers `csv_cell`/`csv_line`/`csv_document`/`export_filename`
(fastapi-free, Mac-tested) + `streaming_csv()` (lazy StreamingResponse
import) + `stream_query()` async generator paging the cursor 500 rows at
a time (fetchmany, cursor always closed) so a full-table packets export
never buffers. UTF-8 BOM (Excel + emoji), CRLF/csv.writer quoting,
decoded_payload as one JSON cell. Endpoints on the existing
lorawan/meshtastic/meshcore routers (dependencies=protected → viewer-open,
session-cookie auth): `/export/packets.csv` + `/export/{devices,nodes,
contacts}.csv`. Packet exports LEFT JOIN nodes for a source_name column;
LoRaWAN packets flatten dev_eui/app_eui/fcnt/fport/mic out of the JSON
payload into flat columns (via _lorawan_flatten). init_routes now takes
device_name (from config.device.device_name, threaded in server.py) for
the download filename `meshpoint-<dev>-<dataset>-<UTCstamp>.csv`.
Frontend: Export CSV button next to Refresh in each panel header, click →
`window.location = /api/<proto>/export/<ds>.csv` (browser download, cookie
rides along), ds picked from this._tab. Tests: NEW test_csv_export.py
(9: cell/line/document formatting, BOM, emoji, JSON-stays-one-cell,
filename sanitization, stream_query paging+transform+cursor-close). ruff
+ node --check clean; changelog bullet under "LoRaWAN sniffing" (88,
parser-verified); README fork bullet + API table rows.
LIVE-VERIFIED 2026-07-10 (user screenshots): MeshCore packets export
(timestamp/packet_id/source_id/source_name/…/decoded_payload JSON cell)
and contacts export (node_id/long_name/…/lat/lon/last_heard) both
download and open cleanly in Excel — named repeaters flow through,
JSON payload stays one cell (no split rows), columns aligned. W1 DONE.

### W8/W9: LED + button features (TODO, added 2026-07-09)

Physically they're the SenseCap M1's case LED and side button. In code they
exist ONLY in the probe script — nothing in the app drives them yet:

- **LED = GPIO 22, button = GPIO 27** (confirmed live via the `button-scan`
  sweep in `scripts/test_gpio_hardware.py`, commit 1edcccc — the initial
  guesses of button=13/fan=14 were wrong; 13 turned out to be the fan).
- Of the three probed peripherals, only the fan graduated to a real runtime
  feature (`src/hardware/fan_control.py` + the `fan:` config section). The
  LED and button have no config section, no controller, no mention in `src/`
  beyond a comment.

Confirmed-and-idle, waiting for a feature. Natural candidates, same opt-in
config shape as the fan, living in `src/hardware/` on the proven
gpiozero/lgpio stack:

- **W8 — LED as a status light: DONE 2026-07-10** (user-approved design,
  explicitly NO PWM). Four states: steady on = all configured capture
  sources healthy; brief OFF-flicker (0.08s) per captured packet; 1 Hz
  blink (phase-locked to clock) = degraded; dark = service dead (kernel
  releases the line on process exit — free watchdog). Built: NEW
  `src/hardware/led_status.py` (LedController, `_tick(now)` state machine
  split out for tests, `_lit` guard avoids redundant pin writes, 10 Hz
  loop, fan-style lifecycle incl. gpiozero-missing error path);
  `LedConfig` in config.py (enabled False/gpio_pin 22/activity_blink True)
  + AppConfig.led + **section_map entry (the fan lesson!)** + regression
  test; `CaptureCoordinator.all_sources_running()` (all src.is_running,
  vacuously True — is_running exists on every source via base protocol);
  wired in server.py lifespan after the fan block (health_fn =
  capture_coordinator.all_sources_running, packet_count_fn =
  stats_reporter.total_packets — cheap in-memory counter, hot path
  untouched), cancelled in shutdown like fan. First tick swallows
  pre-existing packet count (no spurious flicker); activity during
  degraded doesn't arm a flicker. Docs: default.yaml `led:` block,
  CONFIGURATION.md "Status LED (SenseCap M1)" section (notes: no PWM →
  works even without lgpio), README fork bullet, changelog bullet next to
  the fan bullet (81, parser-verified). Tests: test_led_status.py (8,
  Mac-runnable: fake LED; steady/flicker/1Hz phases/recovery/first-tick/
  activity-off/degraded-no-arm + all_sources_running) + config regression
  (43 pass with fan+config suites). ruff clean. NOT yet Pi-verified —
  user must add `led: {enabled: true}` to local.yaml, apply, and watch
  the case LED (expect: steady, dips on packets; unplug a companion →
  1 Hz blink; stop service → dark). LIVE-VERIFIED 2026-07-10 ~15:20
  (user): steady glow + visible blink when sending an advert from their
  MeshCore tag. W8 fully closed.
  SAME MESSAGE also confirmed: Thermals card renders live (screenshot:
  temp ~46-48°C orange panel, duty ~40-45% cyan panel, curves visibly
  correlated, header "46.7 °C · fan 41%") — thermals feature fully
  closed. AND MeshCore badge colors + LoRaWAN section swap confirmed on
  the tabs. All 2026-07-10 UI work now live-verified.

**Box identity stabilized (2026-07-10):** boot log showed `tx_service
WARNING source_node_id (source: RANDOM, will change on every restart)` —
root cause: neither transmit.node_id nor device.device_id set (resolver:
config → derive-from-device_id → CSPRNG). User froze the current random
ID in local.yaml: `transmit.node_id: 0xc3ecf862` (validated: all keys ok,
PyYAML parses hex, not in RESERVED {0, 0xFFFFFFFF}; their 27 dBm + 10%
duty is the legal EU pairing for the 869.4-869.65 sub-band). VERIFIED
next boot: "source_node_id=0xc3ecf862 (source: config)" + "Meshtastic PKI
identity configured: 0xc3ecf862" (PKI now bound to stable ID). Long name
now 'Meshpoint PD2EMC', short 'EMC2'. STILL OPEN (cosmetic, upstream
disabled): device_identity ephemeral-ID warning + banner "PD2EMC (unset)"
— fixed only by `meshpoint setup` writing device.device_id. MQTT id is a
separate identity (!b5c10364, stable, explicit mqtt.gateway_id in yaml).
RESOLVED same day: user added `device.device_id:
474724a2-27ba-4905-8402-6bcb72bf34ef` (the last ephemeral one) to
local.yaml — next boot has ZERO warnings, banner "PD2EMC (474724a2-…)".
Their full local.yaml was reviewed against every dataclass: all valid
(incl. the baud_rate-vs-serial_baud naming split between meshcore_usb and
serial lists — both correct). Noted to user: mqtt.password absent → falls
back to default "large4cats" (their LAN broker accepts it; explicit value
recommended); storage.max_packets_retained raised to 1M (intentional).
keys.yaml lives in data/ not config/ (user asked — not missing). It holds
the Meshtastic PKI X25519 pair (private_key_hex + public_key_hex),
auto-generates on first run. 2026-07-10: user pasted the private key into
chat → ROTATED (stop service, rm data/keys.yaml, start → fresh pair,
rebinds to stable node_id 0xc3ecf862). Side effect: DM partners must
re-accept the new key; old encrypted DMs unreadable. Backup archives made
BEFORE the rotation contain the OLD (burned) key — restoring one restores
the old pair; rotate again after any such restore.

**Contact roster log trimmed (2026-07-10, user request after seeing the
350-line dump):** `log_meshcore_contact_peers` in
src/api/meshcore_contacts.py now logs count + first `_ROSTER_LOG_LIMIT`
(10) named contacts + "… and N more (full roster on the MeshCore page)";
unnamed contacts don't burn slots. The 350 contacts COME FROM THE
COMPANION's own flash contact DB (get_contacts serial command; the
350→342 wobble between fetches = its pagination settling). NEW
tests/test_meshcore_contact_log_trim.py (4, Mac-runnable — module imports
clean on Mac unlike test_meshcore_contact_enrichment.py which needs
aiosqlite). Changelog bullet under "Configuration and server" (82,
parser-verified). ruff clean. LIVE-VERIFIED 2026-07-10 13:39 boot: 10
names + "… and 340 more", full import intact (350 parsed → applied to
349 rows). Boot log is now fully clean AND compact.
**Banner per-source lines + logo alignment (2026-07-10, user request
"line for each source"):** the ASCII logo box was crooked IN SOURCE
(content rows 43 cols between │s vs 46-col borders — upstream heritage;
+3 spaces per row fixed). `print_banner(config, sources=None)` now takes
the live capture sources (new `CaptureCoordinator.sources` tuple
property; both call sites server.py + main.py pass it) and replaces the
Source+Frequency pair with one line per source:
`concentrator      LoRaWAN x5 867.9-868.7 MHz + Meshtastic 869.525 MHz
SF11 (EU_868)` (from ConcentratorChannelPlan, hardware-free; multi-SF
labelled LoRaWAN only for EU_868) / `meshcore_usb_868  MeshCore 869.618
MHz SF8` (from src._meshcore.self_info — radio_freq is ALREADY MHz) /
`serial_433  Meshtastic 433.875 MHz SF11 (EU_433)` (from
src._radio_info via resolve_frequency_mhz — NOTE: serial_source already
resolves real freq from handshake now, the 906.875 placeholder is gone,
fixed in the run-#29-era session). Not-yet-handshaken sources show
"(radio info pending)"; sources=None falls back to legacy lines.
Mac-rendered with fakes (exact output verified) + NEW
tests/test_banner_sources.py (7, Mac-runnable). Changelog bullet under
"Configuration and server" (83, parser-verified). ruff clean.
LIVE-VERIFIED on Pi 2026-07-10 13:53 boot — banner matches the Mac
render exactly (square box, all 3 source lines with real frequencies).
**Meshtastic packets feed shows names (2026-07-10, user request):**
Recent Packets on the Meshtastic page showed bare hex source/dest while
the node census above had names. Mirrored the MeshCore panel's existing
pattern into meshtastic_panel.js: `_nodeNames` map built in _loadNodes
(long_name||short_name, skip empty/id-equal), `_fmtSrc` (name +
dimmed id), `_fmtDest` now resolves names too (BCAST unchanged; handles
`!`-prefixed dest ids by stripping to bare hex for lookup). Also fixed
the first-paint race: `_load` was Promise.all(stats,nodes,packets) →
packets could render before the name map; now nodes complete first
(meshcore_panel already sequenced it this way — meshtastic was the only
straggler). node --check + ruff clean; changelog under "Dashboard and
UI" (84, parser-verified). Pi-verify: Meshtastic page after deploy.
FOLLOW-UP same session: section ORDER swapped to match MeshCore page —
Recent Packets on top, Nodes census below (pure template swap in
_buildShell, ids/handlers untouched; folded into the same changelog
bullet). ALSO: meshcore_panel.js _fmtDest gained the same name lookup
(its dest only handled 'broadcast' before; source already resolved).
ALSO: MeshCore type badges colorized via new MC_TYPE_COLORS map reusing
the mt-badge--* palette from lorawan.css (nodeinfo amber, text cyan,
neighbour_advert→neighborinfo green, telemetry purple, position green;
unknown stays gray default). Both protocol pages now fully symmetric:
layout + src/dest naming + badge colors.
ALSO: LoRaWAN page section order swapped the same way (Recent packets
above Devices) — ALL THREE protocol pages now read packets-first,
census-below. Pure template swap in lorawan_panel.js _buildShell.

**Topbar reconnect grammar unified (2026-07-10, user challenged the old
"concentrator keeps last-known values" decision — REVERSED with user
approval):** topbar_meshtastic_chip.js refactored: `_renderData()` split
out, `_lastData` cache; non-online connection states now blank to
"Reconnecting…" + "--" like the MeshCore/serial chips (was: stale values
+ amber lamp only); values restored from cache the moment the lamp goes
green (setMeshtastic arriving during a drop is cached, not rendered).
Topbar grammar now: green+values / amber+"Reconnecting…"+dashes (link
down) / red+name (link fine, radio offline). ALSO: MeshCore chip's last
separator `·` → `|` bar (index.html + new .topbar-meshcore__sep--bar
CSS), matching the Meshtastic chips' pre-trailing-segment bar. Folded
into the "Topbar chips unified" changelog bullet (84, parser-verified).
LIVE-VERIFIED 2026-07-10 (user screenshot taken mid-apply): all 3 chips
identical amber "Reconnecting… · -- | --". User: "better?" → confirmed.

**W10 PILOT BUILT on MeshCore page (2026-07-10 evening, user "go go
gadgeteers"):** the two stacked sections merged into ONE panel with a
"Recent packets | Contacts" tab strip in panel__header. Implementation:
both table-wraps live in the body inside `[data-mc-view]` wrapper divs
(pagination div moved INSIDE the contacts wrapper so its own
display:none logic is untouched); tab buttons `[data-mc-tab]`; header
suffixes `[data-mc-suffix]` ("(last 100)" vs mc-node-count) follow the
active tab. `_setTab/_applyTab` + `MC_TAB_STORE_KEY =
'meshpoint.mcTab'` localStorage persistence (default packets). ALL
existing ids/loaders/pagination/row-click handlers byte-identical; both
tables still refresh every 15s regardless of active tab. CSS: new
`.panel__header--tabs`, `.lw-tabs`, `.lw-tab`, `.lw-tab--active` block
appended to lorawan.css (shared by all 3 protocol pages — rollout to
Meshtastic "Packets|Nodes" and LoRaWAN "Packets|Devices" reuses
verbatim; panel__header is already flex space-between so tabs sit left,
suffix right). Changelog bullet (85, parser-verified).
LIVE-VERIFIED 2026-07-10 (user screenshots, "nice :)"): both tabs render
and switch correctly, suffixes follow the tab, contacts count shows.
Pilot APPROVED → **ROLLED OUT same evening (user request): W10 DONE on
all three pages.** meshtastic_panel.js (MT_TAB_STORE_KEY
'meshpoint.mtTab', data-mt-* attrs, "Recent packets | Nodes") and
lorawan_panel.js (LW_TAB_STORE_KEY 'meshpoint.lwTab', data-lw-*,
"Recent packets | Devices") got the identical mechanical treatment;
per-page localStorage keys; shared .lw-tab CSS reused untouched. ALSO
per user: MeshCore CONTACTS table column order changed — Last heard
FIRST (colgroup + thead + row template in _renderNodePage), rest
unchanged (ID, Name, Role, RSSI, SNR, Dist, Packets). Meshtastic/
LoRaWAN census column order NOT changed (not asked). Verified: node
--check all 3 panels + div/section balance script (20/20, 20/20,
21/21). Changelog bullet rewritten pilot→rollout (85, parser-verified).
Pi-verify all three tabs after deploy.

**Packet-detail modal on protocol pages + Meshtastic nodes time-first
(2026-07-10 evening, user request):** upstream's PacketDetailModal
(window.PacketDetailModal singleton, packet_detail_modal.js/css, loaded
globally, renders from an IN-MEMORY packet object — no API call) is now
opened by clicking any Recent Packets row on all 3 protocol pages.
Backend: /api/{meshtastic,meshcore,lorawan}/packets responses enriched
to the modal's shape — added protocol, hop_start/hop_limit,
bandwidth_khz, decoded_payload (JSON column parsed via _parse_payload
helper, dict-or-None), packet_id/destination_id/capture_source where
missing (lorawan). Frontend: each panel stores `this._lastPackets`,
rows get `class="lw-pkt-row" data-pkt="${i}"`, delegated tbody click →
PacketDetailModal.show(pkt, {formatNodeId: _nodeNames lookup (mt/mc),
selectedRow}). `.lw-pkt-row` cursor/hover CSS in lorawan.css.
CORRECTION (2026-07-11): channel_hash/relay_node/want_ack ARE persisted
(packet_repository INSERT has all three) — the tab endpoints just weren't
SELECTing them, so protocol-page modals dropped the Channel hash / Relay
byte rows and showed "Channel: (unknown)" while the live Dashboard feed
(reads Packet.to_dict) showed them. Fixed: added channel_hash, want_ack,
relay_node to the SELECT + response dict in BOTH meshtastic_routes and
meshcore_routes packets endpoints. Also the Meshtastic tab formatNodeId
didn't map the broadcast address → showed raw "ffffffff"; now returns
"broadcast" (matches Dashboard + MeshCore tab). Only remaining modal diff
is the fake "CR 4/8" Modem segment on the live feed: coding_rate is NOT a
DB column and is a Signal-model default (meshcore genuinely reports N/A);
user said leave it (2026-07-11 "its ok"). MeshCore round (2026-07-11
"show as much as we can"): added a readable "Node type" row to the shared
modal's Mesh section — decoded_payload.node_type (0 None 1 Client 2 Repeater
3 Room server 4 Sensor, from _build_advertisement/_find_payload_type in
meshcore_event_adapter) was only a bare int in the payload JSON; now
labeled. Stored in decoded_payload JSON so it shows on BOTH the live
Dashboard feed and the MeshCore tab. Meshtastic round (2026-07-11 same
"show as much as we can"): the modal's _payloadRows now keeps the readable
Content summary AND appends an expandable "Details" row = full decoded
payload JSON (skipped for type=='text' where it's redundant). Meshtastic
position/telemetry/nodeinfo decode MANY more fields than the summary shows
(portnum_handlers: sats_in_view, precision_bits, ground_speed, ground_track;
humidity, barometric_pressure, channel_utilization, air_util_tx,
uptime_seconds, num_packets_tx/rx; role, public_key) — all stored in
decoded_payload JSON, returned by the packets endpoints, so Details shows
them on both Dashboard + tab. Shared modal so lorawan/meshcore benefit too.
Hops row (2026-07-11): _meshRows now omits the Hops row entirely when
hopLabel==='n/a' (hop_start not >0) instead of showing "Hops: n/a" — both
protocols, user idea. LoRaWAN round (2026-07-11): (1) _buildLayer now skips
any simple (non-html/non-expandable) row whose val is 'n/a' or '(unknown)'
— hides Modem/RSSI/SNR/Channel on bare LoRaWAN joins, Channel on meshcore
adverts, etc. From/To are composite "name (id)" so never match → always
show. (2) simple_packet_feed _resolveName fallback changed from _shortId
(removed, was `!{last4}`) to the FULL id, so a LoRaWAN DevEUI
("A4:11:...:DE") or "network-server" is no longer mangled to "!D:DE"/
"!rver" in the Dashboard modal — matches the LoRaWAN tab (formatNodeId =
nodeNames[id]||id). Unknown meshtastic/meshcore nodes now also show full id
(e.g. "fa4e8270") instead of "!8270", matching their tabs. ALSO: Meshtastic NODES table Last heard moved to
FIRST column (matching MeshCore contacts). LoRaWAN Devices census
reordered too (user follow-up): Last seen FIRST, First seen SECOND,
then DevEUI/Type/Frames/RSSI/SNR/Freq/SF. All three censuses now lead
with time. LIVE-VERIFIED 2026-07-10 (user screenshot, "better :)"). Changelog +1
bullet & tab bullet extended (86, parser-verified). ruff + node --check
clean. LIVE-VERIFIED 2026-07-10 (user: "on all 3 networks packets show
modal when clicking"; screenshot shows meshcore nodeinfo with resolved
name, companion RF metadata, full payload JSON). W10 + modal round DONE.

### W10: packets/nodes VIEW SWITCH on protocol pages (idea, 2026-07-10)

User idea, refined in the same breath: instead of both sections stacked
on each protocol page (LoRaWAN/Meshtastic/MeshCore), make each page ONE
view with a **switch/toggle** (e.g. "Packets | Nodes" segmented control
in the page header) that flips between the recent-packets feed and the
node/device census. First thought was separate sidebar tabs per network
("every network gets a nodes and lastheard tab") but user immediately
preferred the in-page switch variant. Benefits: no scrolling past one
table to reach the other, more vertical room per table (could raise the
100-packet limit — API already allows up to 500), consistent shell
across all 3 panels (they're already structural twins after today's
symmetry work, so one shared pattern could serve all three; candidate:
persist choice in localStorage like meshpoint.listenerSkin). Not sized,
not started — parked as W10.
Timestamp-less boot lines EXPLAINED, user OK leaving as-is (2026-07-10):
bare lines (Opening SPI / chip version / ARB / SX1261 PRAM) = libloragw C
printf to stdout, can't reformat without fd hacks — leave; "INFO:" lines
= uvicorn's own loggers, COULD be unified via log_config in serve.py —
offered, user declined ("its ok i was just wondering"). Don't re-propose.
journald stamps every line anyway.
- **W9 — button: BUILT 2026-07-10 evening (user-spec'd design).** Short
  press = advert on ALL TX-capable radios; long press 3s = service
  restart. Full spec agreed through Q&A: adverts SERIALIZED 2s apart
  (the 868 signals OVERLAP outright — Meshtastic 869.525/BW250 contains
  MeshCore 869.618/BW62.5 — plus same-box desense), 30s cooldown
  (denied press = 1 long dark LED blink), LoRaWAN excluded by design
  (pure listener). Implementation: `ButtonConfig` (enabled False/pin 27/
  hold_time_s 3.0/advert_cooldown_s 30.0) + section_map + regression
  test; NEW `src/hardware/button_control.py` — ButtonController
  poll-based `_tick(now)` state machine (20 Hz, gpiozero Button
  pull_up=True bounce 0.05 — polarity per probe script; NO callback
  threads), **starts DISARMED (release required before any press
  counts — held-through-restart can't retrigger)**, short fires on
  release <3s, warning blink from 0.5s of hold, long fires AT 3s while
  held (once); `advert_all_radios(steps, spacing)` free async fn (each
  step independent, failures logged not fatal); `restart_service()`
  spawns `sudo systemctl restart meshpoint` DETACHED
  (start_new_session — the apply-chain lesson; sudoers rule was already
  present line 15). LED feedback via NEW `LedController.flash(pattern,
  duration)` override ('fast' 5Hz / 'off'), checked in _tick before
  normal states, self-expires; button re-issues 'fast' every tick
  during hold. Advert steps built by `_build_advert_steps()` in
  server.py: nodeinfo_broadcaster.broadcast_now (Meshtastic 868) +
  meshcore_tx_ref.send_advert() + every source with send_nodeinfo
  (serial sticks). NEW `SerialCaptureSource.send_nodeinfo()` —
  broadcasts the STICK's OWN identity (its firmware name, not EMC2;
  suggested user rename stick to e.g. EMC2-433 via phone app) via
  `iface.sendData(user.SerializeToString(),
  portNum=NODEINFO_APP)` — **API verified against real meshtastic
  2.7.10 wheel source** (sendData accepts bytes+portNum, broadcast
  default; getMyNodeInfo→dict with camelCase user keys). NOTE:
  meshcore advert covers the PRIMARY companion only (one tx client —
  fine, one companion configured). Server wiring: LED block refactored
  to keep `_led_controller` instance (button borrows it for feedback);
  `_button_controller_task` lifecycle like fan/LED. Tests: NEW
  test_button_control.py (6: disarmed boot, release-fires, cooldown
  denial+expiry, hold-once-no-short, warn threshold, advert sequence
  order+failure isolation) + LED flash tests (2) + SendNodeinfoTest (3,
  sys.modules stub for meshtastic.protobuf, saved/restored) + config
  regression — 74 pass across the hardware/config suites. ruff clean.
  Docs: default.yaml button: block, CONFIGURATION.md "User Button"
  section, README fork bullet, changelog bullet next to LED (87,
  parser-verified). NOT yet Pi-verified — user: add
  `button: {enabled: true}` to local.yaml, apply, then test short press
  (LED double-blink + adverts in log + EMC2 appears on both meshes) and
  3s hold (fast blink → restart → LED dark → steady).
  User also pointed at local checkouts for API verification:
  /Users/einstein/Software/meshtastic (FIRMWARE repo, C++) and
  /Users/einstein/Software/meshcore-dev.
  **LIVE-VERIFIED 2026-07-10 17:33-17:35, ALL behaviors:** short press →
  all 3 adverts in sequence at exact 2s spacing (meshtastic-868
  SendResult success airtime 1092ms → meshcore command_ok → serial_433
  NodeInfo !09d406f4), PLUS an accidental live demo of the cooldown
  (second press mid-sequence → "cooldown active (27s left)", sequence
  undisturbed). Hold → "Button held 3.0s" WARNING → sudo ran the exact
  whitelisted argv → graceful shutdown of every subsystem → clean boot
  in 11s with button re-armed → box captured+decrypted+RELAYED a packet
  12s after startup. W9 fully closed. Physical controls story complete:
  fan + LED + button.

**RSSI color mismatch Dashboard vs panels (2026-07-09 late, user screenshots):**
Dashboard packet feed's `_rssiClass` (simple_packet_feed.js) used −90/−110
green/amber/red cutoffs while ALL THREE protocol panels
(meshtastic/meshcore/lorawan_panel.js) use −100/−115 — so −97…−100 dBm
packets were amber on Dashboard but green on the panels. FIXED: feed now
uses −100/−115 (the LoRa-appropriate scale; −90 was Wi-Fi-calibrated), with
a comment pointing at the panels' `_rssiClass`. No other views color RSSI
(grep app.js/node_cards/node_drawer clean). Changelog bullet under
"Dashboard and UI" (76, parser-verified). Class names differ per view
(rssi-* in dashboard.css vs lw-signal--* in lorawan.css) but colors map to
the same green/amber/red tokens — only thresholds were the problem.
FOLLOW-UP (user screenshot post-deploy: feed fixed, "right side still 100
yellow"): the NODES list uses a FOURTH scheme — `_signalQuality` 4-tier
labels (Excellent/Good/Fair/Poor at >−80/>−95/>−110), duplicated in
node_cards.js AND node_drawer.js, plus `_signalBars` icon levels. −100 →
"Fair" amber chip. ALIGNED both copies to the same breakpoints: Good ≥−100,
Fair ≥−115 (Excellent >−80 kept; bars 4-bar cutoff now ≥−100, 3-bar ≥−115).
−100 now shows teal "Good" chip. Folded into the same changelog bullet.
ALSO (user decision on the topbar question): Meshtastic USB chip now shows
"Reconnecting…" in its call slot when the dashboard is unreachable, same
wording as the MeshCore chip (was '----' dashes; topbar_serial_chip.js).
Concentrator chip untouched (keeps last-known values + amber lamp).
Changelog: +1 bullet (77 total, parser-verified).
FONT FOLLOW-UP (user screenshot): the serial chip's "Reconnecting…" looked
like a different font — `.topbar-serial__call` is call-sign styled (700
weight, 0.18em letter-spacing, cyan text-shadow, 0.82rem) vs MeshCore's
plain 600-weight name slot. Added `.topbar-serial__call--status` modifier
(inherit size, 600, normal spacing, no shadow) applied only when the slot
shows status text; real call signs keep the glow styling.

**LoRaWAN FPort/FCnt "--" bug (2026-07-10, found while reviewing user's
panel logs):** every Data row showed FCnt/FPort as "--" even though FCnt is
mandatory in the MAC header and the decoder extracts both. ROOT CAUSE: key
mismatch — lorawan_decoder.py stores `fcnt`/`fport` (no underscore) in
decoded_payload; lorawan_routes.py /packets read `payload.get("f_cnt")`/
`("f_port")` → always None. Fixed at the route (reads decoder's keys,
response keeps f_port/f_cnt names the panel reads). No test added (route
file has no test scaffolding; fastapi CI-only). LIVE-VERIFIED on Pi
2026-07-10 (user paste): FCnt/FPort populate (154D66DD FPort5 FCnt~18.3k
mature session ~35min cadence, we catch ~1/3 — SF11 decode edge + 5-of-8
channel coverage; 780002FC FPort2 FCnt 11-14 WITH DUPLICATES on different
freqs = confirmed-uplink retries with no ACK → orphaned device, explains
the sequential-DevAddr rejoin parade F8→FC). Changelog bullet under
"LoRaWAN sniffing" (78, parser-verified).
RF-log review conclusions (same session, for reference): −98..−103/negative
SNR rows = direct below-noise receptions (RSSI pins at the ~−100 dBm local
noise floor; SNR carries the margin; SF11 decode edge ≈ SNR −20, SF12 ≈
−22.5); −35..−44/positive-SNR = last hop was own PD2EMC repeater or desk
gear (incl. all far UK/DE nodes at −41 "Excellent" = relayed, high hop
counts); PD2EMC adverts hourly at :21:05. LoRaWAN capture healthy: 780002Fx
sequential DevAddrs (same device rejoining), SF12 ~30-min cadence at the
floor; joins on multiple EUIs; RSSI step −95→−101 around Jul 8/9 for that
device = propagation/device change, predates nothing suspicious in our
code. One-off impossible reading "Galdere Tracker −120 dBm / SNR +11.3" =
companion misreport, watch-only.

**CI ruff red 19h (fixed 2026-07-10): ALWAYS run `pipx run ruff check src/
tests/` on the Mac before suggesting a commit** (no ruff installed, pipx
works; CI runs exactly that and fails the whole test job on lint). Two
F-lints fixed: unused `MESHTASTIC_HEADER_SIZE` import in
test_meshtastic_decoder_predecoded.py (shipped with run #29 "serial
meshtastic packets the connected stick decrypts locally…" — NOTE: that
commit implemented the serial decoded-path feature flagged earlier as a
candidate; not done by this assistant. REVIEWED 2026-07-10: that era's
serial_source.py work is healthy and MORE was done than known — the
TEMPORARY debug log is REMOVED (todo closed), dc3fc0a computes serial
channel freq from the real firmware formula (proper fix for the old
906.875 placeholder), db4de9f auto-detects the stick's own node id +
drops self-telemetry, c190b3e keeps user's own BLE/WiFi chat messages
while dropping routine self-telemetry. No follow-up needed.) and dead
`freq_default` in test_channel_frequency.py (its comment already said the
comparison is deliberately not made; call removed). Both lint-only, no
behavior change. ruff now passes clean locally. CI CONFIRMED GREEN after
push (2026-07-10, user-verified).
ALSO dropped the REGION segment (EU_433) from the serial chip per user
("we can see the freq that enough"): region element + sep removed from
_buildBadge, docstring updated, `.topbar-serial__region` CSS rules deleted.
TOPBAR UNIFICATION COMPLETED (2026-07-10, user request): concentrator chip
too — EU_868 region span+sep removed from index.html markup (this chip's
markup is STATIC in index.html, unlike the JS-built serial badges),
`_regionEl` refs removed from topbar_meshtastic_chip.js, and BOTH
Meshtastic chips' name slots (`__call`) restyled to MeshCore's plain
600-weight style (was 700/0.18em letter-spacing/cyan glow/0.82rem). The
`.topbar-serial__call--status` modifier from the earlier same-day fix
became redundant (base is now plain) — CSS rule + JS conditional REMOVED.
End state: all 3 chips = brand · lamp · plain name · cyan freq · preset/
channel; NO region segments anywhere. `--unknown` toggle in the
meshtastic chip still keys off radio.region (data still present, just not
displayed). Changelog 79 bullets, parser-verified. ruff clean.
DEPLOY INCIDENT (same change, expected in hindsight): after Apply the
topbar showed EMC2 with all "--", MeshCore dashes, serial chip GONE — the
STALE-JS TRAP again (2nd bite): new index.html (region span removed) +
old cached topbar_meshtastic_chip.js → querySelector('.__region')=null →
TypeError mid-paint → whole topbar update chain dead incl. serial group.
One-time fix: Empty Cache and Hard Reload.
**PERMANENT FIX BUILT (cache-busting, the wishlist item): NEW
src/api/html_assets.py** — `BOOT_TOKEN` (hex timestamp minted at import =
service start) + pure `bust_asset_urls(html, token)` regex-rewriting every
LOCAL .js/.css src/href in index.html to `?v=<token>`; skips http(s)://
and // externals (unpkg leaflet.markercluster is still a live CDN dep —
noted, untouched) and non-asset URLs; kept fastapi-free for Mac testing
(serve.py pattern). server.py `/` route: FileResponse → HTMLResponse
(bust_asset_urls(index.html), Cache-Control: no-cache — HTML itself must
revalidate or tokens never arrive). Every apply restarts the service →
new token → browsers refetch automatically. login/setup pages left as-is
(low churn). NEW tests/test_html_assets.py (7, Mac-runnable, incl. sweep
of the REAL index.html: zero un-tokened local assets, externals byte-
identical). ruff clean. Changelog bullet under "Self-update system" (80,
parser-verified). NOTE: the deploy carrying THIS fix is itself the last
one needing a manual hard reload.
TOPBAR LIVE-VERIFIED (2026-07-10, user screenshot + "better?"): all 3
chips render unified (EMC2 · 869.525 · LongFast / PD2EMC Meshpoint ·
869.618 · TECHINC +7 / !06f4 · 433.875 · LongFast), green lamps, no
region segments, plain names. User satisfied. Topbar polish round DONE.

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

**Commit message style (user, 2026-07-10): NEVER put internal tracking
numbers (W9, T5, N2 etc.) in commit messages** — those are memory-file
shorthand, meaningless in git history. Describe the user-visible effect
only. (Also still in force: no Co-Authored-By/AI trailers ever.)

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

**Fan-control chown broke Check for updates (2026-07-09 evening, fixed on Mac,
needs manual Pi bootstrap):** dashboard showed `Could not fetch origin: error:
cannot open '.git/FETCH_HEAD': Permission denied` + "Could not reach GitHub."
(the latter is just the frontend's `sync_error` status line in
update_panel_controller.js — SAME root cause, not a network problem; the real
network version check at /api/device/update-check is separate and was fine).
ROOT CAUSE = collision of two of our own fixes: daf9356 added non-recursive
`ExecStartPre=+/bin/chown meshpoint:meshpoint /opt/meshpoint` (lgpio fan pipe),
which flipped the repo TOP dir to meshpoint-owned; `sudo_needed()` in
install_status.py stat'ed exactly that top dir → decided "no sudo" → plain git
fetch as meshpoint hit the still-root-owned `.git/` and died. Apply/rollback
were never affected (apply.py hardcodes sudo git). User's manual `git pull` as
pi failed the same way (`insufficient permission for adding an object to
repository database .git/objects`) — expected, .git is root-owned; use sudo
git on the Pi. FIX: `sudo_needed()` now stats `.git` via new
`_ownership_probe()` (falls back to repo root when no `.git`); Pi (.git
root-owned) → sudo restored, Mac dev checkout → still plain git. 5 new tests
in TestSudoNeeded (23 pass on Mac). Changelog bullet under "Self-update
system" (74 bullets, parser-verified).
**FINAL RESOLUTION (user's call, supersedes the probe-only plan): the REAL
fix is permissions — the service user owns the WHOLE tree, recursively.**
User ran `sudo chown -R meshpoint:meshpoint /opt/meshpoint` on the Pi,
pushed+applied the probe fix (b29e09c) via dashboard Apply (Apply works even
while Check is broken — hardcoded sudo), and the Updates page went green
("Up to date with origin/main") — LIVE-VERIFIED 2026-07-09 ~21:05. To make
the chown -R durable (the apply chain's `sudo git fetch/reset` re-poisons
.git + working tree with root-owned files on EVERY apply), it's baked in at
all three lifecycle points: (1) meshpoint.service ExecStartPre — the 3 chown
lines (config -R / data -R / top non-recursive) merged into ONE
`chown -R meshpoint:meshpoint /opt/meshpoint` (every apply ends in a restart
→ self-heals); (2) post_update.sh step 3 — whole tree instead of config-only
(heals during the apply itself, before restart); (3) install.sh — whole tree
instead of data+config (fresh installs start correct). safe.directory trust
STAYS (root's sudo git on a meshpoint-owned tree also trips the
dubious-ownership check); sudoers git rules STAY (apply chain unchanged);
the `.git` probe in sudo_needed() KEPT (right answer in mixed/transitional
states and on dev checkouts). New steady state: tree meshpoint-owned
everywhere, Check runs PLAIN git, only Apply uses sudo. bash -n both
scripts OK; changelog bullet reworded to the permissions story (still 74,
parser-verified). Unit-file rollout is automatic (post_update.sh step 2
copies + daemon-reloads when it differs). Pi-verify after next apply: fan
still spins (lgpio pipe) + Check stays green after an Apply cycle.

**Fan control LIVE-VERIFIED + duty-log cosmetic fix (2026-07-09 ~21:20):**
user's journal shows real PWM tracking temp (45.3C→0.36 … 47.2C→0.42, exactly
the linear curve; sweep + capture unaffected). Log paste exposed a cosmetic
bug in `_poll_once` (src/hardware/fan_control.py): it compared/logged the
PIN READ-BACK (`self._pwm.value`, which lgpio quantizes) against the freshly
computed full-precision duty → "(was X)" disagreed with the previously
printed duty (0.41 → "was 0.40") and every poll counted as "a change" (even
"0.37 (was 0.37)" lines). FIX: duty is now `round(..., 2)` (the 1% step the
log/dashboard show) and compared against `self.current_duty` (own
bookkeeping, read-back no longer consulted) → consecutive lines agree,
identical polls stay silent. current_duty is now stored rounded (dashboard
card unaffected — it displays percent). 2 new tests (rounding; a
FakeQuantizingPWM proving read-back is ignored, assertLogs/assertNoLogs) —
15 pass in test_fan_curve.py. Changelog: folded into the existing fan bullet
(unreleased-feature convention) + that bullet's stale "third non-recursive
chown" sentence updated to point at the recursive whole-tree chown (still
74 bullets, parser-verified). DECIDED same evening (user: "back to debug we
dont want extra 8k+ logs"): duty-change line demoted INFO→DEBUG with a code
comment saying why; quantization test switched to level="DEBUG"
(assertLogs/assertNoLogs); changelog fan-bullet sentence rewritten ("stays
at debug … temporarily info to verify the ramp live … dashboard Fan card is
the live view"). 15 tests pass, still 74 bullets parser-verified. The
dashboard Fan card is the intended way to watch duty from now on.
Fan card LIVE-VERIFIED by user screenshot (2026-07-09 late): stats bar shows
CPU TEMP 45.3°C · LOAD AVG 0.16 · FAN 39% "was 41%" — whole pipeline
(sensor → curve → PWM → /api/device/metrics → card) working; the small
temp-vs-duty offset is just the two values sampling at different instants
(temp jitters ±1C between the fan's 10s polls), not a bug. Fan feature is
DONE end to end.

**Thermals card on Hardware page (2026-07-09 late, user-requested "graph
orso"):** 6h CPU-temp + fan-duty history chart. DESIGN NOTE: dual-axis
(temp+duty on one chart) rejected per dataviz guidance (#1 anti-pattern) →
TWO STACKED Chart.js panels sharing the time window, one scale each (temp
°C top #f97316, duty % bottom #06b6d4 — house colors from
node_metrics_chart; CVD/contrast validated). Backend: `FanController.history`
deque (HISTORY_HOURS=6.0 / poll_interval → maxlen 2160 @10s, sampled EVERY
successful poll in _poll_once, in-memory only) + `poll_interval_s` property;
`GET /api/device/thermals` in system_metrics.py (same protected router as
/metrics, viewer-open; available:false when fan disabled → card hides, same
grammar as stat-bar Fan card). Frontend: NEW radio_thermals_card.js
(mount/render card pattern, 60s auto-refresh gated on section--active,
downsample to ≤720 pts, "Collecting data" empty state, live "temp · fan %"
header meta), slot `r-card-thermals` after nodeinfo in radio_settings.js
(docstring card list also fixed — was missing concentrator), script tag in
index.html, `.thermals-*` CSS in radio_cards.css (FIXED-HEIGHT
.thermals-panel__plot 110px — the Chart.js maintainAspectRatio:false
lesson). Tests: FanControllerHistoryTest (3, Mac-runnable, 18 pass in
test_fan_curve.py) + SystemMetricsThermalsTest (2, CI-only in
test_system_metrics_fan.py). Changelog bullet under "Dashboard and operator
tools" (75, parser-verified); README: Hardware-group bullet + API table row.
NOT yet Pi-verified (needs deploy; check card renders, hides for viewer=no
—it's viewer-open actually—, and fills after ~1min).

## MeshCore historical database import + repeater history cards (2026-07-10)

**Goal:** Bring 18 days of MeshCore repeater history into Meshpoint for charting and UI context.
**Source:** https://einstein.amsterdam/meshcore/meshcore.db (5117 telemetry rows, Jun 22 - Jul 10)
**Destination:** The same `telemetry` table that live repeater polls write to.

### Import script (`scripts/import_meshcore_db.py`)

Fetches the remote MeshCore SQLite database (or accepts local `--source-db /path`), maps the 9471 rows in `telemetry_history` to Meshpoint's flat telemetry schema (voltage, temperature, humidity, barometric_pressure, uptime_seconds), and inserts them as chart-ready rows. Unmapped fields (current, power, altitude) are preserved as synthetic `meshcoredb:` packets with the full row as JSON in `decoded_payload`, indexed by node_id for future analytics.

**Design decisions:**
1. **Upsert, not insert:** Contacts/neighbours use `ON CONFLICT(node_id) DO UPDATE` with CASE logic to preserve better data (newer `last_heard`, updated lat/lon/role/name) across re-imports.
2. **Temperature preference:** Per-timestamp ranking (SHT3X ch4 > BMP280 ch3 > MCU ch1) — environmental sensors preferred over die temperature spikes.
3. **Multi-mode:** `--telemetry-only` (skip nodes), `--contacts-only` (skip telemetry) for incremental updates.
4. **Remote fetch:** Default URL via urllib; tempfile cleanup; backward-compat `--dest-db` override (prod default `/opt/meshpoint/data/concentrator.db`).
5. **Dry-run:** `--dry-run` previews counts without writes.

**Files:**
- `scripts/import_meshcore_db.py` — Main importer, fully tested and live-deployed
- `docs/CHANGELOG.md` — 3 bullets documenting importer features
- `memory/project_m1_meshpoint.md` — This section

**Verified live:** 5117 telemetry rows imported, 38 distinct nodes, 5 samples each Voltage/Temperature/Humidity/Barometric_Pressure/Uptime spread across the full Jun 22 - Jul 10 arc.

### Repeater history display (frontend + backend)

**Backend changes (`src/api/routes/meshcore_routes.py`):**
- Added `TelemetryRepository` injection to `init_routes()` (and wired in `src/api/server.py`)
- New `_fetch_telemetry_history(node_id)` queries telemetry for min/max/avg: voltage, temperature, humidity, plus date range and total sample count
- Endpoint `GET /api/meshcore/repeaters` now appends `history` dict to each repeater object

**Frontend changes (`frontend/js/repeaters_tab.js`):**
- New `_historyRows(h)` helper formats history stats: period (date range), voltage min/avg/max, temperature min/avg/max, humidity min/avg/max
- New `_fmt(n, decimals)` and `_shortDate(iso)` formatters for consistent display
- `_card(r)` expanded to render a third card: "History" alongside Health + Sensors
- History card shows: `Period Jun 22 to Jul 10 | Voltage 4.05/4.11/4.15 V | Temperature 14.1/26.4/56.1°C | Humidity 45.0/51.4/57.0%` with sample count meta

**CSS changes (`frontend/css/repeaters.css`):**
- Grid auto-fits 3 cards per repeater (Health | Sensors | History), stacking on narrow screens
- `.rp-card--history` reuses existing card styles; special-cased `.rp-card__head` margin

**Result:** Repeater cards now show the full lifecycle: current status (Health), active sensors (Sensors), and a 18-day statistical summary (History). All three write to the same `telemetry` table, so live future polls automatically extend the history as they arrive.

**Repeaters page layout + Trends chart (2026-07-10, this-assistant, user
"3 cards in one row? + nice stats card with charts?"):** (1) Fixed a
BROKEN CSS brace from the history session — `.rp-card--history {
grid-column: span 2 }` was nested INSIDE `.rp-card--sensors .rp-card__head`
(misplaced `}`), never applied. (2) Layout now `.rp-repeater`
`repeat(3, minmax(0,1fr))` = Health | Sensors | History in ONE row, with
a full-width **Trends** chart card below (`.rp-card--trends` grid-column
1/-1). (3) Trends REUSES NodeMetricsChart (Chart.js, node-drawer's) —
`_renderTrends(r)` fetches `/api/nodes/{key}/metrics_history?hours=1000&
limit=2000` (returns {telemetry,signal} = NodeMetricsChart input;
repeater key==node_id, imported+live telemetry already there) → renders
into `canvas[data-rp-chart]`; charts destroyed on hide + before
re-render (this._charts). NodeMetricsChart charts VOLTAGE(y1)+
TEMPERATURE(y3) for repeaters (battery_level/chutil/airutil null;
humidity/pressure NOT its series → stay in History/Sensors; charting
them = future extension). `.rp-trends-wrap` fixed 240px. 3-col→1-col
<1100px. node --check + CSS 27/27 clean; changelog 95. NOTE live
screenshot was AMBER/stale/"0/1 reporting/polled 5m ago" — a poll FAILED
(companion command-channel busy, messaging-incident risk); chart still
works (stored history, poll-independent). Watch poll health. NOT
re-verified on Pi after this change.

**Poll retry (2026-07-10, user saw "login failed or timed out" in logs):**
`_poll_one` now retries up to `POLL_ATTEMPTS=3` times with `RETRY_DELAY_S=4`
between attempts before giving up (same shape as the user's telemetry.sh
RETRIES/RETRY_DELAY). Transient "login failed or timed out" (companion
command channel momentarily busy, often right after the 350-contact boot
sync) usually clears on retry. Tests: RETRY_DELAY_S=0 in the test module
for speed; 2 new (retries-then-succeeds asserts 3 calls; gives-up-after-
max asserts POLL_ATTEMPTS calls). 10 pass, ruff clean, changelog reworded
(still 95).

**Humidity+Pressure charted + scroll fix (2026-07-10):** (1) Extended the
SHARED NodeMetricsChart (benefits node drawer too) — added Humidity (y
axis, %, #38bdf8) + Pressure (NEW y4 hPa axis, #c084fc) series + y4 scale
+ y4 in _syncAxes + tooltip labels. Each only appears when the node has
≥2 points of that field, so Meshtastic nodes without them are unaffected.
Repeater trends now show voltage/temp/humidity/pressure, all legend-
toggleable. (2) SCROLL BUG: repeaters page couldn't scroll to Trends/
History — parent `.section` is overflow:hidden and each page must promote
itself; added `.section[data-section="repeaters"] { overflow-y: auto }`
(same rule lorawan/meshcore/meshtastic have). node --check + CSS 28/28
clean; changelog reworded (95). NOT Pi-verified.

**Trends chart truncation + card-size fixes (2026-07-10):** (1) CARD SIZE:
`.rp-grid` used `auto-fill minmax(560px,1fr)` → a single repeater filled
only ONE 560px column, cramming the 3-up into the left half (text
wrapped). Fixed to `minmax(0,1fr)` (one full-width block per repeater) +
`.rp-card` padding 15px→1.25rem to match RF cards. (2) CHART MISSING
RECENT DATA: `metrics_history` / `TelemetryRepository.get_history` return
`ORDER BY timestamp ASC LIMIT ?` = OLDEST-first, so the chart's
`limit=2000` fetched samples Jun22-29 and DROPPED everything newer incl.
today; x-axis still reached Jul11 only via the hidden RSSI signal series
(recent packets), so telemetry lines flatlined after Jun29. Fixed: fetch
`?hours=100000&limit=50000` (all rows). (3) PERF: NodeMetricsChart now
downsamples TELEMETRY too (`_downsampleSignal(telem, 800)` — was signal-
only) so 5000+ points render smoothly; no-op for the drawer's short
histories. KNOWN FUTURE: as live polls grow the row count unbounded, a
fixed high limit will eventually truncate again — proper fix is
server-side downsample-across-range (candidate task). (4) REFRESH CADENCE
(user: "why 30s, data updates every 20min"): page auto-refresh 30s→300s
(5min) — no point re-fetching the full history + re-rendering the chart
40× between actual 20-min polls.
LIVE-VERIFIED on Pi 2026-07-10 (user screenshot "you like it?"): roomy
full-width 3-up cards, Trends chart shows the FULL Jun22-Jul11 range
dense throughout (truncation fixed), all 4 series (voltage flat ~4V =
solar healthy, temp daily sawtooth, humidity inverse, pressure weather),
RSSI toggled off. Repeater monitoring feature COMPLETE end-to-end.

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

| T19 | DONE 2026-07-09 | M | **Temperature-driven PWM fan control, first real feature built on [[T18]]'s confirmed GPIOs.** User's motivation: hot summer weather (+30C) coming, wants the fan reacting to actual temperature rather than running flat-out or not at all. Confirmed GPIO13 (the fan pin from T18) is a genuine hardware-PWM channel on the Pi 4 (BCM2711 PWM1) — user asked "can we owm/pwm the fan maybe?" and this pin choice makes proportional speed control free, not just on/off. New `src/hardware/fan_control.py`: `FanCurve` (pure dataclass, `duty_for(temp_c, currently_on) -> float`, zero hardware dependency, fully Mac-testable) implements linear ramp between `min_temp_c`/`max_temp_c` with a `min_duty` floor (most small fans stall below some duty rather than actually spinning slower) and a `hysteresis_c` gap below `min_temp_c` before fully switching off (prevents on/off chatter right at the threshold) — separate hysteresis semantics for "already on, sitting in the band" (stays at min_duty) vs "was off, temp creeping up" (stays off until crossing min_temp_c) baked into the state param rather than module-level state, so the pure function stays unit-testable. `FanController.run()` wraps this in an async polling loop (`gpiozero.PWMOutputDevice`, imported lazily inside `run()` so the module stays importable on Mac without gpiozero installed), same lifecycle pattern as the existing `_noise_floor_emitter_loop` in `server.py` (started via `create_task` in `lifespan()`, cancelled cleanly on shutdown). CPU temp read via `/sys/class/thermal/thermal_zone0/temp`, duplicated (not imported) from the existing `_read_cpu_temp()` in `system_metrics.py`/`executors.py` per this repo's established small-helper-duplication convention. Config: new `FanConfig` dataclass (`enabled: bool = False` — opt-in, since this hardware doesn't exist on RAK V2/Chameleon/DIY — `gpio_pin=13`, `min_temp_c=45`, `max_temp_c=65`, `min_duty=0.35`, `hysteresis_c=5`, `poll_interval_s=10`), added as `AppConfig.fan`; the existing generic `_merge_dataclass`/`_collect_unknown_keys` machinery picks it up automatically from `local.yaml` with zero extra parsing code (verified: default `enabled=False`/`gpio_pin=13`, merges `{'fan': {'enabled': True, 'min_temp_c': 50.0}}` correctly leaving `gpio_pin` untouched). `server.py` `lifespan()`: new `_fan_controller_task` module global, started right after the spectral-scan service block when `config.fan.enabled`, cancelled in the shutdown sequence alongside `_noise_floor_emitter_task`. Verified on Mac (no gpiozero, no real GPIO): `read_cpu_temp_c()` returns `None` gracefully (no `/sys/class/thermal` on macOS); `FanController.run()` with gpiozero absent logs a clear error and returns cleanly instead of crashing the app — confirms a Mac dev run or a non-Pi install with `fan.enabled` accidentally left on fails safe. Tests: NEW `tests/test_fan_curve.py` (8 cases, pure math, no hardware — off-threshold, both hysteresis-band branches, min/max temp boundaries, midpoint linear ramp, above-max clamp), all pass on Mac. Docs: new "Fan Control (SenseCap M1)" section in `CONFIGURATION.md` (full yaml block + explanation), full commented `fan:` block added to `config/default.yaml` too (user's explicit ask: "add all to the default yaml, so user see that they can do more" — so every knob is discoverable without reading source, not just `enabled`), new CHANGELOG bullet under "Import and maintenance scripts" (still parser-verified) alongside T18's probe bullet. **CRITICAL BUG CAUGHT BEFORE ANY LIVE USE**: sanity-checked `fan: {enabled: true}` through the real `load_config()` (not just `_merge_dataclass` in isolation) and got "Ignoring 1 unknown config key(s): fan" — `_apply_yaml`'s `section_map` dict (config.py ~line 512) is manually maintained, NOT derived from `AppConfig`'s dataclass fields, and `fan` had been left out of it entirely. The whole section was silently dropped; `enabled: true` would have done nothing at all, on either `default.yaml` or `local.yaml` — the earlier "verified: merges correctly" check upstream only exercised `_merge_dataclass` directly, not the real `_apply_yaml`/`load_config` path that actually runs at boot, so it missed this. Fixed (`"fan": cfg.fan` added to `section_map`), confirmed via a scratch config dir with `fan: {enabled: true}` in `local.yaml` — loads as `True` now, no warning. New regression test `test_fan_section_is_applied_without_warning` in `test_config_loader.py` (16 total pass) asserting the fan section actually reaches `cfg.fan`, specifically to prevent a future config section suffering the exact same "field added to AppConfig but forgotten in section_map" gap from going unnoticed again. Lesson: when adding a new top-level config section, `_merge_dataclass` in isolation is NOT sufficient verification — must run it through actual `load_config()`. User then asked whether this should be a Configuration-panel UI tab instead of hand-editing YAML; agreed it should, patterned directly off `AdvancedConfigCard`/`system_config_routes.py`'s `/radio/advanced` route (closest existing precedent: flat settings object, no lists, always `restart_required: True` since the fan controller task only starts once in `lifespan()`, no hot-reload wiring) — NOT YET BUILT, user redirected mid-build to prioritize the `default.yaml` documentation instead ("no if fan: enabled true is enough its ok, but add all to the default yaml..."); the Configuration → Fan page is the clear next step whenever revisited. **TWO ROUNDS OF LIVE PI FAILURES, both fixed**: (1) first restart with `fan.enabled: true` logged `fan control enabled but gpiozero is not installed` — gpiozero is preinstalled system-wide on Raspberry Pi OS (which is why `test_gpio_hardware.py` worked fine run directly with system `python3`), but Meshpoint's service runs from its own venv (`/opt/meshpoint/venv/bin/python`) which doesn't share site-packages; same class of gotcha as the already-documented `psutil` venv issue. Fixed: added `gpiozero>=2.0` to `requirements.txt`, documented the `sudo /opt/meshpoint/venv/bin/pip install gpiozero` fix in `TROUBLESHOOTING.md`/`CONFIGURATION.md`. (2) After installing gpiozero, next restart hit `gpiozero.exc.PinPWMUnsupported: PWM is not supported on pin GPIO13` — gpiozero's warnings showed it fell back through lgpio → RPi.GPIO → pigpio → its pure-Python `NativeFactory`, which only permits PWM on pins from a hardcoded per-Pi-model table; a custom carrier board's repurposed GPIO13 isn't in that table even though it's a genuine PWM1 hardware channel on the underlying Pi 4 SoC. Root-caused why the EARLIER `test_gpio_hardware.py fan --fan-pin 13` test had shown the fan spinning successfully despite this: that script's `test_fan()`/`fan_scan()` use `gpiozero.OutputDevice` (plain digital on/off via `.on()`/`.off()`), never `PWMOutputDevice` — so it never touched the PWM code path at all, and was also run with system Python rather than the venv. Fixed: added `lgpio>=0.2.2` to `requirements.txt` (Raspberry Pi Foundation's current recommended gpiozero backend for Bookworm/Pi4/Pi5, no daemon needed unlike `pigpio`, unlike `RPi.GPIO` which has known Bookworm/Pi5 kernel incompatibilities — doesn't have NativeFactory's hardcoded-pin-table restriction). `FanController.run()`'s exception handler now detects `PinPWMUnsupported` specifically by exception class name and logs the exact `pip install lgpio` fix instead of a raw traceback (still falls through to the generic `logger.exception(...)` for any other failure). New `FanControllerPinPwmUnsupportedTest` in `test_fan_curve.py` (fakes `sys.modules['gpiozero']` with a `PWMOutputDevice` that raises a fake `PinPWMUnsupported`, asserts the log contains "lgpio" and NOT "Traceback" — runs without real gpiozero or hardware) — 9 total pass. Both `TROUBLESHOOTING.md` and the CHANGELOG bullet updated with both fixes. **THIRD live failure after fixing (2)**: `pip install lgpio` itself failed twice more on the real Bookworm/trixie box — first `swig: No such file or directory` (needs `python3-dev`+`swig` to build the C extension, no piwheels wheel available for this combo), then after installing those, `/usr/bin/ld: cannot find -llgpio` (needs the native `liblgpio.so` from `liblgpio-dev`, not just the Python bindings) — full verified chain is `sudo apt install -y python3-dev swig liblgpio-dev` before `pip install lgpio`, documented as one block in `TROUBLESHOOTING.md`/`CONFIGURATION.md`. Once installed, hit a FOURTH distinct failure: `xCreatePipe: Can't set permissions (436) for /opt/meshpoint/.lgd-nfy0, Operation not permitted`, falling back to the same PWM-incapable pin factory as failure (2) — root cause this time was in `scripts/meshpoint.service`, not the app: `lgpio` creates its notification pipe directly in `WorkingDirectory` (`/opt/meshpoint`), but the unit's `ExecStartPre` only ever chowned the `config/` and `data/` subdirectories to the `meshpoint` service user (established convention, re-applied on every start) — never the top-level directory itself, so the service user had no write permission to create anything there at all (confirmed by the SECOND attempt's error changing to ENOENT "No such file or directory" — nothing was ever actually created, ruling out a stale-file-with-wrong-owner theory in favor of "can't write to this directory, period"). Fixed with a third `ExecStartPre=+/bin/chown meshpoint:meshpoint /opt/meshpoint` line (non-recursive — cheap, just the directory entry, doesn't touch the whole git tree's ownership), self-healing on every start regardless of how the checkout was deployed/updated. Immediate unblock given to user (works before pulling any new code): `sudo chown meshpoint:meshpoint /opt/meshpoint && sudo systemctl restart meshpoint`. This whole saga (4 distinct failures across gpiozero missing → PinPWMUnsupported → lgpio build chain → systemd directory permissions) is a good illustration of why "verified on Mac" claims for this feature always needed the caveat "not yet Pi-verified live" — every one of these failure modes only exists on the real Pi/venv/systemd stack and was invisible to any Mac-side check. **LIVE-VERIFIED 2026-07-09 20:29**: user ran the chown one-liner + restart, log shows `fan_control: Fan control started on GPIO13 (45-65C range, poll every 10s)` with no exception — the real PWM path is confirmed working end to end (config → FanController → gpiozero → lgpio → GPIO13), closing out all four failure modes. Not yet independently confirmed that the duty cycle actually ramps smoothly with temperature over time (vs. just "started successfully") — reasonable to consider T19 functionally done and revisit only if the user reports it isn't actually varying speed as CPU temp changes. Next logical follow-up (raised earlier, not yet built): the stats-bar FAN tile idea, and/or the Configuration → Fan UI page, both still open threads if the user wants to continue this line of work. User asked to also fold this into the install docs ("write all this to project in installation... the extra stuff we installed"): new "Enabling the SenseCap M1 Onboard Fan (Optional)" section added to `docs/ONBOARDING.md` (the main install/setup guide, styled like its existing "Adding a MeshCore Companion (Optional)" section) covering the full `apt install python3-dev swig liblgpio-dev` + `pip install gpiozero lgpio` chain, the one-line `fan: {enabled: true}` config step, and the existing-install `chown /opt/meshpoint` gotcha with a pointer to `TROUBLESHOOTING.md` for failure-mode details — this is the durable, discoverable home for "what do I need to install for this feature", separate from `TROUBLESHOOTING.md`'s job of diagnosing it after the fact. **FINAL ROUND — visibility improvements**: user noticed the duty-change log line was `debug` level (invisible at the `info` level Meshpoint actually runs at, confirmed by scanning a full boot log with zero debug lines) — asked "so its silent until state changes?" and this correction was needed: it was silent ALWAYS, not just between changes. Bumped that line to `info`. Also asked for a dashboard card (stats bar, after Load Avg) showing "the duty and last duty". Refactored `FanController.run()`'s loop body out into a new `_poll_once()` method (temp read + duty compute + pin drive + logging) so the new `current_duty`/`previous_duty` instance attributes are unit-testable deterministically (no real asyncio timing needed) — `previous_duty` only updates at the moment of an actual transition (holds the OLD value until the next change), `current_duty` updates every poll regardless. New `FanControllerDutyTrackingTest` (4 cases in `test_fan_curve.py`, now 13 total) verifies this directly against `_poll_once()` with a fake PWM object. API: `system_metrics.py` (`/api/device/metrics`, already backs the existing stats bar's CPU/RAM/disk/temp/load-avg cards) gained `init_routes(fan_controller)`/`reset_routes()` (previously had NO init pattern at all — bare module-level route, first time this file needed one) plus `fan_duty_percent`/`fan_previous_duty_percent` fields (both `None` when no controller, i.e. `fan.enabled: false`). `server.py`: `_fan_controller` added as a NEW module global alongside the existing `_fan_controller_task` (previously only the asyncio task was kept, not the controller instance itself — needed now so the metrics route has something to read live state from), `system_metrics.init_routes(_fan_controller)` called right after fan controller construction (or with `None` when disabled). New CI-only `test_system_metrics_fan.py` (2 cases, styled after the existing `test_system_metrics_load_avg.py` sibling test which is ALSO fastapi-import-dependent with no explicit skip-probe — same precedent followed, not the noqa-probe convention used elsewhere in the repo) asserting both the "no controller" and "with controller" branches produce the right percentages. Frontend: new `#stat-fan` card in `index.html` (after `#stat-load`, `hidden` by default via the native HTML attribute — confirmed `.stat-card` CSS has no `display` override that would fight it), `app.js`'s `_updateStats()` shows/hides it based on whether `fan_duty_percent` is `null`, displays `"62%"` or `"Off"` as the big value and `"was 35%"`/`"was off"` as the caption (mirroring the existing `stat-load-sub` two-line card style, no new CSS needed). Changelog bullet extended in place (still same "Import and maintenance scripts" bullet, parser-verified). User separately asked to also write the full install/dependency story into `docs/ONBOARDING.md` for a fresh install's sake (done, see above) AND asked to write the whole session into this memory file for continuity on another machine — flagged to the user that `memory/project_m1_meshpoint.md` is deliberately untracked (per this same file's own header instruction) so it will NOT transfer via git to another PC; only a manual copy (AirDrop/synced drive/scp) carries it over. NOT yet Pi-verified live — next step is the user pulling this round's changes, restarting, and confirming the Fan stats-bar card appears and updates (shows a real percentage, not stuck on "--" or hidden) plus an `info`-level `Fan: NN.NC -> duty 0.XX` line the next time the duty actually changes. |

Older wishlist (idea-level): LoRaWAN CSV/TTN export; LoRaWAN MIC verification;
light theme (medium-large, dark-first CSS);
DAB+ via welle-cli (NPO Radio 5); true-RF S-meter via pyrtlsdr; EU433 LoRaWAN
plan (needs 433 concentrator, not the M1). Meshtastic firmware source available
locally at /Users/einstein/Software/meshtastic (user-supplied) — already used for
[[T13]]'s channel-hash frequency formula AND [[T14]]'s self-telemetry diagnosis;
good resource for any future question needing firmware-level (not just
meshtastic-python-level) ground truth.

Suggested order: T3 → T2 → T1 → T4, then by mood.

**"Read full release notes" modal (2026-07-10, user: keep the 140-char
preview truncation but link to the full text):** the Updates "What's new"
preview truncates each bullet to 140 chars (`sanitize_detail_for_preview`,
_PREVIEW_DETAIL_MAX=140) — intentional teaser, our bullets are just very
long. Added a LOCAL full-notes view (offline-safe, no GitHub link — box
may be air-gapped, same reason Chart.js/xterm are vendored): NEW
`sanitize_detail_full` (de-markdown, NO truncation) + `format_bullet_full`
/`format_section_full` in release_notes.py; `/api/update/release_notes`
now returns `full_section` alongside `preview_section` (same parsed data,
untruncated). Frontend: release_notes_view.js stores `_fullSection`, adds
a "Read full release notes" link (only when bullets present) → lightweight
self-built modal (`.rn-modal-overlay`/`.rn-modal`, Escape/click-outside/×
close) reusing `_renderBullets` (category grouping preserved). Scope =
INSTALLED VERSION only (user chose (a) over whole-changelog). CSS in
settings.css. Tests: 2 new in test_update_release_notes.py (full keeps
untruncated detail; sanitize_full de-markdowns without cutting) — 25 pass.
ruff + node --check + CSS braces clean. Changelog bullet under "Self-update
system" (88). NOT Pi-verified.

**Packet modal protocol-aware payload (2026-07-10, user compared MeshCore
tab vs Dashboard modal for same packet):** the Dashboard modal showed
"Decrypt: No matching key" + no JSON for a MeshCore advert, while the
MeshCore tab showed "Decrypt: Success" + the decoded JSON. Root cause:
`_payloadRows` in packet_detail_modal.js was Meshtastic-centric
(`decrypted = packet.decrypted !== false`); the live WS packet carried
decrypted=false (hiding the payload), the stored /api/meshcore/packets
packet had no `decrypted` field (defaulted to shown). But MeshCore isn't
encrypted with channel keys — adverts/nodeinfo are DECODED. FIX: modal
now checks `packet.protocol==='meshcore'` → forces decrypted=true (skips
the "No matching key" branch) AND omits the "Decrypt" row entirely
(meaningless for MeshCore), always showing Content/JSON. Both feeds carry
decoded_payload (WS uses packet.to_dict which includes it), so both modals
now show the advert JSON consistently. Meshtastic/LoRaWAN unchanged.
Other still-differing-but-cosmetic bits noted, not fixed: Dashboard feed
uses _shortId formatNodeId ("!3bc7") vs MeshCore tab's name-resolving
(_nodeNames) callback; Dashboard packet has coding_rate ("CR N/A") the
stored meshcore API omits. node --check clean; changelog folded into
"Packet detail modal everywhere" (88). LIVE-VERIFIED on Pi 2026-07-10 (user screenshots, all 3 protocols from Dashboard feed): Meshtastic position = Decrypt Success + coords; MeshCore nodeinfo = NO Decrypt row, Channel + advert JSON (fix works); LoRaWAN data = Decrypt "No matching key" (correct — LoRaWAN payload IS AES-encrypted, no session keys). Modal now protocol-truthful. DONE. FOLLOW-UP (user: dashboard modal From shows short id !b868/!8270 not the name, all protocols): dashboard feed's modal used formatNodeId=_shortId; now uses new `_resolveName(id)` (node name from the SAME _nodeNames map the feed table already uses, else short id; broadcast→"broadcast") so From/To resolve to names (Zorglubxx, AA-Rep-Mesh-01) matching the tab modals. node --check clean; folded into changelog packet-modal bullet. Remaining cosmetic diff (not fixed, not asked): dashboard shows "CR N/A", stored protocol APIs omit coding_rate.
