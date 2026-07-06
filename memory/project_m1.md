---
name: project-m1-sniffer
description: Sencap M1 / SX1303 passive sniffer — EU868 + Meshtastic scanner; sync word 0x2B via lgw_reg_w; AES-128/256-CTR decrypt; MeshCore BW62.5 is a hardware impossibility on SX1303
metadata:
  type: project
---

# Sencap M1 / SX1303 — EU868 + Meshtastic Scanner

**Why:** M1 is a passive EU868 + Meshtastic scanner.
MeshCore sniffing on the M1 is impossible — SX1302/1303 hardware cannot do BW62.5
(permanently `#if 0 /* TODO */` in Semtech's own HAL source). MeshCore requires an
SX1262 companion radio instead.

**How to apply:** When suggesting work on the M1, treat it as a Meshtastic + EU868 scanner only.
Any MeshCore-related sniffing must go on an SX1262/SX1276 companion radio.

---

## Hardware

- **Board**: Sencap M1 Raspberry Pi hat
- **Chip**: SX1303 LoRa concentrator (multi-channel gateway chip); front-ends are SX1250
- **Driver**: Semtech `sx1302_hal` / `libloragw` — cloned into `sx1302_hal/`

---

## Real SX1302/1303 HAL architecture

| Concept | Wrong assumption | Correct |
|---|---|---|
| Multi-SF config | `DR_LORA_MULTI` per-channel datarate | Global bitmask via `lgw_demod_setconf()`, `multisf_datarate = LGW_MULTI_SF_EN (0xFF)` |
| Multi-SF bandwidth | configurable | **Fixed at BW125** — hardware constraint |
| BW62.5 support | configurable on IF chain | **Physically impossible** — `#if 0 /* TODO */` in Semtech source |
| Channel count | 8 LoRa channels | 8 multi-SF (ch0-7) + 1 LoRa service (ch8) + 1 FSK (ch9) = **10 total** |
| sync_word in lgw_conf_rxif_s | filters LoRa packets | **FSK-only field** — cannot filter LoRa per-channel |
| bandwidth field | raw Hz (125000U) | **Enum**: BW_125KHZ=0x04, BW_250KHZ=0x05, BW_500KHZ=0x06 |

Key constants from `sx1302_hal/libloragw/inc/loragw_hal.h`:
- `LGW_IF_CHAIN_NB = 10`, `LGW_MULTI_NB = 8`, `LGW_MULTI_SF_EN = 0xFF`
- No `BW_62K5HZ` — confirming hardware limitation
- No `DR_LORA_MULTI` — multi-SF is global, not per-channel

---

## HAL sync word handling — critical bug fixed

The standard `sx1302_lora_syncword(bool public, uint8_t sf)` called inside `lgw_start()`
only supports **0x12** (private, `public=false`) and **0x34** (LoRaWAN, `public=true`).
Meshtastic uses **0x2B** — which is neither.

The SX1302 registers encode sync words as "peak positions":
`PEAK1 = 2 × (sw >> 4)`, `PEAK2 = 2 × (sw & 0x0F)`

| Sync word | PEAK1 | PEAK2 | Used by |
|-----------|-------|-------|---------|
| 0x12 | 2 | 4 | LoRa private default |
| 0x34 | 6 | 8 | LoRaWAN public |
| **0x2B** | **4** | **22** | **Meshtastic** |

**Fix:** set `lorawan_public=true` in `lgw_conf_board_s` so `lgw_start()` programs 0x34
(PEAK1=6, PEAK2=8) on ch0–ch7. Then override only ch8 (service channel) to 0x2B:

```c
lgw_reg_w(SX1302_REG_RX_TOP_LORA_SERVICE_FSK_FRAME_SYNCH0_PEAK1_POS, 4);
lgw_reg_w(SX1302_REG_RX_TOP_LORA_SERVICE_FSK_FRAME_SYNCH1_PEAK2_POS, 22);
```

`lgw_reg_w` is safe to call on a running concentrator. Only 2 writes needed.

**Earlier mistake:** setting all 4 FRAME_SYNCH registers to 0x2B also pushed ch0–ch7
multi-SF to 0x2B — meaning they filtered for Meshtastic and rejected all LoRaWAN 0x34
traffic. Fixed by using `lorawan_public=true` + service-channel-only override.

Meshpoint works around the same limitation by shipping a patched `libloragw.so` with a
modified `sx1302_lora_syncword(bool, uint8_t syncword)` signature (see their `patch_hal.sh`).
Our approach avoids patching the HAL entirely.

---

## RSSI offset — fixed

`rssi_offset` in `lgw_conf_rxrf_s`:
- **Wrong**: `-166.0` — this is the SX1276/SX125x era value
- **Correct**: **`-215.4`** — calibrated for SX1250-based front-ends (RAK2287, SenseCap M1 WM1303)

Source: Semtech reference `global_conf.json.sx1250.*` files; confirmed by Meshpoint (`concentrator_config.py`).

---

## ETSI EN300.220 sub-bands (EU863-870)

| Sub-band | Range | Duty cycle | Max ERP |
|----------|-------|-----------|---------|
| K | 863–865 MHz | 0.1% | 25 mW |
| L | 865–868 MHz | 1% | 25 mW |
| M | 868–868.6 MHz | 1% | 25 mW |
| N | 868.7–869.2 MHz | 0.1% | 25 mW |
| P | 869.4–869.65 MHz | **10%** | **500 mW** |
| Q | 869.7–870 MHz | 1% | 25 mW |

Sub-band P is the most permissive slot — 500 mW and 10% duty cycle. Meshtastic chose 869.525 MHz
because it sits in sub-band P and is also the EU868 LoRaWAN default RX2 downlink frequency.

---

## Final channel layout (sniffer.c)

```
RF0 centre: 868.300 MHz  (lower EU868)
RF1 centre: 869.525 MHz  (Meshtastic / RX2 default)

ch0: 867.9 MHz   BW125 SF5–SF12 multi   RF0  EU868 optional, sub-band L (1%, 25mW)
ch1: 868.1 MHz   BW125 SF5–SF12 multi   RF0  EU868 mandatory ch0 (LoRaWAN)
ch2: 868.3 MHz   BW125 SF5–SF12 multi   RF0  EU868 mandatory ch1 (LoRaWAN)
ch3: 868.5 MHz   BW125 SF5–SF12 multi   RF0  EU868 mandatory ch2 (LoRaWAN)

ch4: 869.225 MHz BW125 SF5–SF12 multi   RF1  sub-band N edge (0.1%, 25mW)
ch5: 869.425 MHz BW125 SF5–SF12 multi   RF1  sub-band P (10%, 500mW)
ch6: 869.625 MHz BW125 SF5–SF12 multi   RF1  sub-band P/Q edge
ch7: 869.825 MHz BW125 SF5–SF12 multi   RF1  sub-band Q (1%, 25mW)

ch8: 869.525 MHz BW250 SF11             RF1  [MESHTASTIC LongFast EU_868] — sub-band P, RX2 default
ch9: FSK — disabled
```

EU868 mandatory channels (LoRaWAN spec) are ch1/ch2/ch3 (868.1/868.3/868.5 MHz).
These are the 3 channels every end device uses for Join-Request messages.

---

## Meshtastic EU_868 LongFast (Netherlands)

| Parameter | Value |
|-----------|-------|
| Frequency | 869.525 MHz |
| BW | 250 kHz |
| SF | SF11 |
| CR | 4/5 |
| Sync word | 0x2B |

Captured on ch8 (LoRa service channel, RF1, IF offset = 0).

---

## Meshtastic packet decode (implemented in sniffer.c)

### 1. 16-byte unencrypted radio header

```
[0:4]  dest_id    (uint32 LE)
[4:8]  src_id     (uint32 LE)
[8:12] packet_id  (uint32 LE)
[12]   flags: bits 0-2 = hop_limit, bit 3 = want_ack,
              bit 4 = via_mqtt, bits 5-7 = hop_start
[13]   channel_hash
[14]   next_hop
[15]   relay_node (lowest byte of last relaying node's ID; 0 = direct)
```

Validity check: `hop_limit > hop_start` is physically impossible → drop packet.

### 2. AES-CTR decryption (AES-128 or AES-256)

Nonce (16 bytes, matching Meshtastic firmware `initNonce()`):
```
bytes 0–3 : packet_id  (uint32 LE)
bytes 4–7 : 0x00
bytes 8–11: src_id     (uint32 LE)
bytes 12–15: 0x00
```

Default key — base64 `"AQ=="` (index 1) expands to 16 bytes (AES-128):
```c
{ 0xD4, 0xF1, 0xBB, 0x3A, 0x20, 0x29, 0x07, 0x59,
  0xF0, 0xBC, 0xFF, 0xAB, 0xCF, 0x4E, 0x69, 0x01 }
```

Key expansion rule (mirrors `Channels::getKey()` in firmware):
- 0 bytes → all-zeros (no encryption)
- 1 byte (index) → start from `MESHTASTIC_DEFAULT_PSK`, increment last byte by `(index-1)`; index 1 → last byte unchanged → always 16 bytes
- 16 bytes → use as-is → **AES-128-CTR**
- 32 bytes → use as-is → **AES-256-CTR**
- Other → zero-pad to 16 bytes → AES-128-CTR

`expand_key()` returns the actual key length (16 or 32). `aes_ctr()` selects
`EVP_aes_128_ctr()` or `EVP_aes_256_ctr()` accordingly. Both ciphers use the same
nonce layout. `mesh_keys[MAX_KEYS][32]` and `mesh_key_len[MAX_KEYS]` store key + length.

AES-CTR is symmetric — encrypt == decrypt. OpenSSL EVP, IV = nonce. ✓

### 3. Protobuf Data message

After decryption the bytes are a serialised `meshtastic.Data` protobuf:
- Field 1 (varint): `portnum`
- Field 2 (length-delimited bytes): `payload` (application data)
- Field 5 (varint): `request_id` (optional)

### 4. Portnum table

| portnum | Name | Sniffer output |
|---------|------|----------------|
| 1 | TEXT_MESSAGE | raw UTF-8 text |
| 2 | REMOTE_HARDWARE | hex dump |
| 3 | POSITION | `lat=… lon=… alt=…m` |
| 4 | NODEINFO | `id=!… name="…" short="…" hw=… role=… pkey=…` |
| 5 | ROUTING | `error=<name>` (0 = ACK) |
| 6 | ADMIN | hex dump |
| 8 | WAYPOINT | `id=… name="…" desc="…" lat=… lon=… icon=…` |
| 10 | DETECTION_SENSOR | raw UTF-8 text |
| 34 | PAXCOUNTER | `wifi=… ble=… uptime=…s` |
| 64 | SERIAL | hex dump |
| 65 | STORE_FORWARD | `rr=… hb_period=…s msgs_total=… saved=… max=…` |
| 66 | RANGE_TEST | raw UTF-8 text |
| 67 | TELEMETRY | `[DeviceMetrics]` / `[EnvMetrics]` / `[LocalStats]` / `[PowerMetrics]` |
| 70 | TRACEROUTE | `route: <id>(dB) … route_back: …` |
| 71 | NEIGHBORINFO | `neighbors: <id>(<snr>dB) … [total=N]` |
| 72 | TEXT_COMPRESSED | hex dump |
| 73 | MAP_REPORT | `name="…" hw=… fw=… region=… lat=… lon=… online=…` |
| 74 | AUDIO | hex dump |
| 75 | PKI_ENCRYPTED_DM | detected, not decrypted |
| unknown | — | `[encrypted / wrong key]` |

---

### 5. Sub-message protobuf field reference

#### Position (portnum 3) — `meshtastic.Position`

| field | wire | type | output |
|-------|------|------|--------|
| 1 | 0 varint | sint32 zigzag | latitude × 10⁻⁷ degrees |
| 2 | 0 varint | sint32 zigzag | longitude × 10⁻⁷ degrees |
| 3 | 0 varint | int32 | altitude (m, AMSL) |

sint32 zigzag decode: `(uint32_t)(n>>1) ^ (uint32_t)(-(int32_t)(n&1))`

#### User / NodeInfo (portnum 4) — `meshtastic.User`

| field | wire | type | output |
|-------|------|------|--------|
| 1 | 2 bytes | string | node id (e.g. `!a1b2c3d4`) |
| 2 | 2 bytes | string | long name |
| 3 | 2 bytes | string | short name (4 chars) |
| 5 | 0 varint | HardwareModel enum | hardware model |
| 7 | 0 varint | Role enum | role |
| 8 | 2 bytes | bytes (32) | public_key (X25519) |

Hardware model enum sample: 4=T-Beam, 9=RAK4631, 43=Heltec-V3, 44=Heltec-WSL-V3, 71=Tracker-T1000-E
Role enum: 0=CLIENT, 1=CLIENT_MUTE, 2=ROUTER, 3=ROUTER_CLIENT, 4=REPEATER, 5=TRACKER, 6=SENSOR

#### Routing (portnum 5) — `meshtastic.Routing`

| field | wire | type | output |
|-------|------|------|--------|
| 3 | 0 varint | RouteError enum | error reason |

RouteError: 0=NONE (ACK), 1=NO_ROUTE, 2=GOT_NAK, 3=TIMEOUT, 4=NO_INTERFACE, 5=MAX_RETRANSMIT, 6=NO_CHANNEL, 7=TOO_LARGE, 8=NO_RESPONSE, 9=DUTY_CYCLE_LIMIT

#### Waypoint (portnum 8) — `meshtastic.Waypoint`

| field | wire | type | output |
|-------|------|------|--------|
| 1 | 0 varint | uint32 | id |
| 2 | 2 bytes | string | name |
| 3 | 2 bytes | string | description |
| 4 | 0 varint | sint32 zigzag | latitude_i × 10⁻⁷ |
| 5 | 0 varint | sint32 zigzag | longitude_i × 10⁻⁷ |
| 6 | 0 varint | uint32 | icon (Unicode code point) |

#### Paxcounter (portnum 34) — `meshtastic.Paxcount`

| field | wire | type | output |
|-------|------|------|--------|
| 1 | 0 varint | uint32 | wifi count |
| 2 | 0 varint | uint32 | ble count |
| 3 | 0 varint | uint32 | uptime_seconds |

#### StoreAndForward (portnum 65) — `meshtastic.StoreAndForward`

| field | wire | type | output |
|-------|------|------|--------|
| 1 | 0 varint | RequestResponse enum | rr (ROUTER_HEARTBEAT, CLIENT_HISTORY, …) |
| 3 | 2 bytes | Statistics sub-msg | messages_total, messages_saved, messages_max |
| 5 | 2 bytes | Heartbeat sub-msg | period, secondary |

#### Telemetry (portnum 67) — `meshtastic.Telemetry`

Outer Telemetry oneof: field 2=DeviceMetrics, field 3=EnvironmentMetrics, field 4=LocalStats, field 6=PowerMetrics.

**DeviceMetrics** (`meshtastic.DeviceMetrics`):

| field | wire | type | output |
|-------|------|------|--------|
| 1 | 0 varint | uint32 | battery_level (%) |
| 2 | 5 fixed32 | float | voltage (V) |
| 3 | 5 fixed32 | float | channel_utilization (%) |
| 4 | 5 fixed32 | float | air_util_tx (%) |
| 5 | 0 varint | uint32 | uptime_seconds |

**EnvironmentMetrics** (`meshtastic.EnvironmentMetrics`):

| field | wire | type | output |
|-------|------|------|--------|
| 1 | 5 fixed32 | float | temperature (°C) |
| 2 | 5 fixed32 | float | relative_humidity (%) |
| 3 | 5 fixed32 | float | barometric_pressure (hPa) |

**LocalStats** (`meshtastic.LocalStats`):

| field | wire | type | output |
|-------|------|------|--------|
| 1 | 0 varint | uint32 | uptime_seconds |
| 2 | 5 fixed32 | float | channel_utilization (%) |
| 3 | 5 fixed32 | float | air_util_tx (%) |
| 4 | 0 varint | uint32 | num_packets_tx |
| 5 | 0 varint | uint32 | num_packets_rx |
| 6 | 0 varint | uint32 | num_online_nodes |
| 7 | 0 varint | uint32 | num_total_nodes |

**PowerMetrics** (`meshtastic.PowerMetrics`):

| field | wire | type | output |
|-------|------|------|--------|
| 1 | 5 fixed32 | float | ch1_voltage (V) |
| 2 | 5 fixed32 | float | ch1_current (A) |
| 3 | 5 fixed32 | float | ch2_voltage (V) |
| 4 | 5 fixed32 | float | ch2_current (A) |
| 5 | 5 fixed32 | float | ch3_voltage (V) |
| 6 | 5 fixed32 | float | ch3_current (A) |

#### RouteDiscovery / Traceroute (portnum 70) — `meshtastic.RouteDiscovery`

| field | wire | type | output |
|-------|------|------|--------|
| 1 | 2 packed | repeated fixed32 | route node IDs (forward path) |
| 2 | 2 packed | repeated sint32 zigzag | snr_towards (×4, divide by 4 for dB) |
| 3 | 2 packed | repeated fixed32 | route_back node IDs |
| 4 | 2 packed | repeated sint32 zigzag | snr_back (×4) |

Packed repeated: wire type 2, blob contains raw concatenated fixed32 values (4 bytes each) or varints.

#### NeighborInfo (portnum 71) — `meshtastic.NeighborInfo`

| field | wire | type | output |
|-------|------|------|--------|
| 1 | 0 varint | uint32 | node_id of reporter |
| 4 | 2 bytes | Neighbor (sub-msg) | repeated heard neighbours |

**Neighbor** sub-message:
| field | wire | type |
|-------|------|------|
| 1 | 0 varint | uint32 | node_id |
| 2 | 5 fixed32 | float | snr (dB) |

#### MapReport (portnum 73) — `meshtastic.MapReport`

| field | wire | type | output |
|-------|------|------|--------|
| 1 | 2 bytes | string | long_name |
| 2 | 2 bytes | string | short_name |
| 3 | 0 varint | HardwareModel enum | hw_model |
| 4 | 2 bytes | string | firmware_version |
| 5 | 0 varint | RegionCode enum | region |
| 6 | 0 varint | ModemPreset enum | modem_preset |
| 8 | 0 varint | sint32 zigzag | latitude_i × 10⁻⁷ |
| 9 | 0 varint | sint32 zigzag | longitude_i × 10⁻⁷ |
| 11 | 0 varint | uint32 | num_online_local_nodes |

---

### 6. Protobuf helper functions (in sniffer.c)

| function | purpose |
|----------|---------|
| `pb_varint(buf, len, pos)` | decode varint; advances `*pos` |
| `pb_zigzag(n)` | sint32 zigzag → int32 |
| `pb_float(buf, pos)` | read 4-byte LE float (wire type 5) |
| `pb_skip(buf, len, pos, wire)` | skip unknown field by wire type |
| `decode_position(buf, len)` | parse `meshtastic.Position` |
| `decode_user(buf, len, src_id)` | parse `meshtastic.User` + upsert node DB |
| `decode_device_metrics(buf, len)` | parse `meshtastic.DeviceMetrics` |
| `decode_env_metrics(buf, len)` | parse `meshtastic.EnvironmentMetrics` |
| `decode_local_stats(buf, len)` | parse `meshtastic.LocalStats` (Telemetry field 4) |
| `decode_power_metrics(buf, len)` | parse `meshtastic.PowerMetrics` (Telemetry field 6) |
| `decode_telemetry(buf, len)` | dispatch Telemetry oneof to correct sub-decoder |
| `decode_routing(buf, len)` | parse `meshtastic.Routing` error code |
| `decode_waypoint(buf, len)` | parse `meshtastic.Waypoint` |
| `decode_paxcounter(buf, len)` | parse `meshtastic.Paxcount` |
| `decode_store_forward(buf, len)` | parse `meshtastic.StoreAndForward` |
| `decode_traceroute(buf, len)` | parse `meshtastic.RouteDiscovery` (packed fixed32 + SNR) |
| `decode_neighborinfo(buf, len)` | parse `meshtastic.NeighborInfo` |
| `decode_map_report(buf, len)` | parse `meshtastic.MapReport` |
| `decode_data_pb(buf, len, src_id)` | parse outer `meshtastic.Data`, dispatch by portnum |
| `decode_meshtastic(payload, len)` | top-level: header parse → multi-key AES-CTR → decode_data_pb |

Unknown portnum after AES-CTR → wrong key / not Meshtastic → sniffer prints `[encrypted / wrong key]`.

---

## Comparison with Meshpoint

Full feature comparison (source: Meshpoint v0.7.6 README):

| Feature | Meshpoint | sniffer.c |
|---------|-----------|-----------|
| RX — 8 channels simultaneous | Yes | Yes |
| TX — send messages | Yes (up to 27 dBm) | No — receive only |
| Smart relay (hop-preserve, experimental) | Yes | No |
| AES-128 private channels | Yes | Yes |
| AES-256 private channels | Yes | **Yes** |
| Node database | In-memory | **CSV, persists across restarts** |
| LoRaWAN decode (ch0–ch7) | No | **Yes** |
| MeshCore decode | Yes (USB companion) | No |
| MQTT gateway (dual-protocol) | Yes | No |
| Meshradar cloud map | Yes (meshradar.io) | No |
| Local web UI + map | Yes (port 8080) | No |
| SQLite packet history | Yes | No |
| Chat / messaging UI | Yes | No |
| GPS positioning | Yes (gpsd) | No |
| MeshCore USB companion | Yes (Heltec V3/V4) | No |

Portnum decode — sniffer.c matches or exceeds Meshpoint on every type:

| portnum | Meshpoint | sniffer.c |
|---------|-----------|-----------|
| 1 TEXT_MESSAGE | text | text |
| 3 POSITION | lat/lon/alt | lat/lon/alt |
| 4 NODEINFO | name, hw, role | name, hw, role, **public key + node DB** |
| 5 ROUTING | error code | error code |
| 8 WAYPOINT | name, desc, lat/lon | id, name, desc, lat/lon, icon |
| 10 DETECTION_SENSOR | text | text |
| 34 PAXCOUNTER | wifi, ble | wifi, ble, **uptime** |
| 65 STORE_FORWARD | rr type | rr type, heartbeat period, msg stats |
| 66 RANGE_TEST | text | text |
| 67 TELEMETRY | DeviceMetrics + EnvMetrics | DeviceMetrics + EnvMetrics + **LocalStats + PowerMetrics** |
| 70 TRACEROUTE | route nodes | route + **SNR per hop** + route_back + **SNR back** |
| 71 NEIGHBORINFO | neighbors + SNR | neighbors + SNR |
| 73 MAP_REPORT | name, hw, lat/lon | name, hw, fw, region, preset, lat/lon, **online count** |
| 75 PKI_ENCRYPTED_DM | not decrypted | not decrypted |

sniffer.c also decodes EU868 LoRaWAN (ch0–ch7). Meshpoint ignores LoRaWAN entirely.

PKI DMs cannot be decrypted by any passive sniffer — requires the recipient's X25519 private key.

**Meshpoint smart relay:** re-broadcasts captured packets with original sender ID preserved,
only decrementing `hop_limit`. No second radio needed. Identity-preserving relay is filtered
by RSSI, packet type and rate-limited to share duty-cycle with messaging TX.

---

## LoRaWAN MAC decode (ch0–ch7, sniffer.c)

LoRaWAN packets arrive on ch0–ch7 (sync word 0x34). The sniffer dispatches to `decode_lorawan()`
for any packet not on 869.525 MHz.

### What is decoded (unencrypted MAC header)

| PHYPayload field | Encrypted | Decoded |
|------------------|-----------|---------|
| MHDR / MType | No | Yes — Join-Request / Unconfirmed-Data-Up / … |
| DevAddr (4 bytes) | No | Yes |
| FCnt (16-bit lower) | No | Yes |
| ADR / ACK / FPending flags | No | Yes |
| FOptsLen | No | Yes |
| FPort | No | Yes |
| FRMPayload | Yes (AppSKey/NwkSKey) | length only |
| MIC (4 bytes) | — | shown as hex |
| **Join Request: JoinEUI + DevEUI + DevNonce** | **No** | **Yes — fully readable** |
| Join Accept | Yes (AppKey) | `[encrypted — need AppKey]` |

### PHYPayload structure

**Data frame** (MType 2–5):
```
MHDR(1) DevAddr(4 LE) FCtrl(1) FCnt(2 LE) FOpts(0–15) [FPort(1)] [FRMPayload] MIC(4)
FCtrl bits (uplink):  ADR(7) ADRACKReq(6) ACK(5) ClassB(4) FOptsLen(3-0)
FCtrl bits (downlink): ADR(7) RFU(6) ACK(5) FPending(4) FOptsLen(3-0)
```

**Join Request** (MType 0):
```
MHDR(1) JoinEUI(8 LE) DevEUI(8 LE) DevNonce(2 LE) MIC(4) — total 23 bytes, nothing encrypted
```

**Rejoin Request** (MType 6):
```
Type 0/2: MHDR(1) Type(1) NetID(3) DevEUI(8 LE) RJCount(2) MIC(4)
Type 1:   MHDR(1) Type(1) JoinEUI(8 LE) DevEUI(8 LE) RJCount(2) MIC(4)
```

### EUI display
EUIs are stored little-endian on the wire. `print_eui()` reverses the 8 bytes to display
in the standard big-endian notation (e.g. `70-B3-D5-7E-D0-00-01-70`).

---

## MeshCore sync word / params (for future companion radio work)

- Sync word: **0xCD** (private LoRa, 1-byte)
- Source: `UniversalMeshGui/coordinators/lora.cpp` → `#define LORA_SYNC_WORD 0xCD`
- **Not usable on M1** — SX1303 cannot do BW62.5, and sync_word in lgw_conf_rxif_s is FSK-only
- MeshCore radio params: 869.618 MHz, BW62.5, SF8 CR4/8 or SF5 CR4/5

---

## HAL init sequence (sniffer.c)

```
lgw_board_setconf()          — com_type=LGW_COM_SPI, com_path="/dev/spidev0.0", lorawan_public=true
lgw_rxrf_setconf(0)          — RF0 @ 868.3 MHz, LGW_RADIO_TYPE_SX1250, rssi_offset=-215.4, tx_enable=false
lgw_rxrf_setconf(1)          — RF1 @ 869.525 MHz, same settings
lgw_demod_setconf()          — multisf_datarate=LGW_MULTI_SF_EN (SF5–SF12 globally)
lgw_rxif_setconf(0–7)        — enable/rf_chain/freq_hz (IF offset) only; BW/SF not set for multi-SF
lgw_rxif_setconf(8)          — enable/rf_chain=1/freq_hz=0/bandwidth=BW_250KHZ/datarate=DR_LORA_SF11
lgw_rxif_setconf(9)          — enable=false (FSK disabled)
lgw_start()                  — programs ch0–ch7 sync word to 0x34 (lorawan_public=true)
lgw_reg_w(SERVICE_PEAK1, 4)  — override ch8 only to Meshtastic 0x2B
lgw_reg_w(SERVICE_PEAK2, 22)
lgw_receive() loop           — STAT_CRC_OK only → print_packet()
                                → is_meshtastic(freq) ? decode_meshtastic() : decode_lorawan()
lgw_stop()
```

---

## Meshpoint reference

`meshpoint/` in the project root is a clone of [KMX415/meshpoint](https://github.com/KMX415/meshpoint)
— an open-source Python/FastAPI Meshtastic base station targeting the same hardware (SenseCap M1,
RAK2287). Key lessons learned from studying it:

- **Sync word approach**: Meshpoint ships a patched `libloragw.so` with a modified
  `sx1302_lora_syncword(bool, uint8_t syncword)` signature (`patch_hal.sh`). Our sniffer
  avoids patching by calling `lgw_reg_w()` directly after `lgw_start()`.
- **RSSI offset**: `-215.4` confirmed for SX1250 hardware.
- **EU868 channel plan**: Meshpoint uses only 2 active multi-SF channels (±62.5 kHz around
  869.525 MHz), optimised purely for Meshtastic sub-band P. Our plan adds EU868 LoRaWAN
  mandatory channels for broader monitoring.
- **Decrypt chain**: source of truth for nonce layout, key expansion, and portnum table. Supports AES-128 and AES-256 keys.
- **MeshCore**: handled via USB companion (Heltec V3/V4 running MeshCore firmware), not the
  SX1303 concentrator — confirms our hardware limitation note.

---

## Files

| File | Purpose |
|------|---------|
| `sniffer.c` | EU868 + Meshtastic passive sniffer with AES-128/256-CTR decode (complete) |
| `Makefile` | `LORAGW_PATH = $(CURDIR)/sx1302_hal`, links `-lcrypto` |
| `sx1302_hal/` | Semtech official HAL (Lora-net/sx1302_hal, cloned) |
| `reset_m1.sh` | GPIO reset for M1 before starting sniffer |
| `INSTALL.md` | Full setup: SPI, dependencies, build, GPIO, run, troubleshooting |
| `README.md` | Overview: channel plan, Meshtastic params, output format, decryption |
| `meshpoint/` | Reference: Meshpoint open-source base station for same hardware |

---

## Next steps

- [ ] Build and test on hardware: `sudo apt install libssl-dev`, `cd sx1302_hal && make`, `make`, `bash reset_m1.sh && sudo ./sniffer`
- [ ] Verify all portnum types decode correctly end-to-end (TRACEROUTE SNR, LocalStats, PowerMetrics, MAP_REPORT)
- [ ] Verify EU868 LoRaWAN Join Requests appear decoded on ch1/ch2/ch3
- [ ] SX1262 companion radio sniffer for MeshCore BW62.5 (separate future project — SX1303 cannot do BW62.5)
