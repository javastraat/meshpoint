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
