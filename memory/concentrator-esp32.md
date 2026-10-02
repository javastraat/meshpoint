# Concentrator on ESP32: T-ETH-Elite + RAK Pi HAT listening station

Brainstorm notes, started 2026-09-29. Nothing built yet.

## The idea

Build a Pi-less version of `extra/sniffer.c`. We have **5 spare RAK Hotspot V2
concentrator boards** (the RAK Pi HAT with the RAK2287 mPCIe module on it). Plug
one **as-is onto the LilyGO T-ETH-Elite's Pi-style 40-pin header**, instead of a
Raspberry Pi, and run it as a small multi-network listening station on EU868
(Meshtastic, MeshCore, Reticulum, and LoRaWAN for free) over Ethernet/PoE.

No Gateway Shield, no rewiring of the module: HAT + RAK2287 straight onto the ESP32.

## Short answer

**Plausible, and the header lines up better than expected, but two signals
land on awkward ESP32 pins.** Three parts already exist; nobody has put them
together yet:

1. The Elite's J1 header follows the **Raspberry Pi 40-pin layout**, and the SPI
   data pins (19/21/23) connect to the ESP32's shield SPI bus. See the pin map below.
2. **esxp1302** is a full ESP32 port of Semtech's `sx1302_hal` v2.1.0
   (`lgw_start`, `lgw_receive`, TX, packet forwarder), not just a demo.
3. Our `extra/sniffer.c` already has the channel plan, the ch8 sync-word trick,
   and Meshtastic decrypt/decode, all written against the same HAL API.

The hard limit doesn't change: **the SX1302 can't receive BW62.5**, so MeshCore
EU (869.618 MHz, SF8, BW62.5) still needs an SX1262 alongside it, exactly like
on the Pi.

## Pin map: RAK Pi HAT on the T-ETH-Elite J1 header

From `schematic/T-ETH-ELite.pdf` (J1, page 2) and the Pi pinout Meshpoint uses
for the RAK V2 (`/dev/spidev0.0` = CE0; reset on GPIO 17 or 25 depending on HAT
revision, **active HIGH**, see `scripts/reset_concentrator.sh`).

| Pi pin | Pi function (RAK HAT) | Elite J1 → ESP32-S3 | Verdict |
|---|---|---|---|
| 19 | SPI0 MOSI | IO11 (SPI_MOSI) | ✅ direct |
| 21 | SPI0 MISO | IO9 (SPI_MISO) | ✅ direct |
| 23 | SPI0 SCLK | IO10 (SPI_SCLK) | ✅ direct |
| **24** | **SPI0 CE0 = SX1302 CS** | **IO0 (BOOT)** | ⚠️ works as a GPIO CS after boot, but IO0 is the boot strapping pin (10k pull-up, BOOT button). If anything pulls it low during reset, the ESP32 goes into download mode. |
| 11 | **GPIO17 = SX1302 reset** (confirmed for RAK7248 by RAK's `reset_lgw.sh`) | IO41 | ✅ usable |
| 22 | GPIO25 (reset on some *other* carriers, not the RAK7248) | IO12 (SD_CS) | not needed for our HATs: leave it to the SD card |
| 26 | CE1 (unused by RAK) | IO46 | strapping pin; leave alone |
| 8 / 10 | UART TXD/RXD = **HAT GPS** (confirmed: RAK's no-LTE SPI config uses `gps_tty_path: /dev/ttyAMA0`) | TXD0 / RXD0 (IO43/44) | ✅ likely: UART0, free when "USB CDC On Boot" is enabled |
| 3 / 5 | I2C (HAT temp sensor/EEPROM, if fitted) | IO17 / IO18 | ✅ |
| 2 / 4 | 5V | +5V | see power below |
| 1 / 17 | 3V3 | +3V3 (ESP32's own SY8089 buck) | see power below |
| 6/9/14/20/25/30/34/39 | GND | GND | ✅ |

**LilyGO's own Gateway Shield is NOT Pi-compatible:** it puts SX_RST on pin 7
(IO2) and SX_CS on pin 11 (IO41), per its schematic note ("CTS is assigned as
the reset… RTS is assigned as the CS function of SX1302"). So LilyGO's
prebuilt Gateway-Shield `.bin` **won't** talk to a RAK HAT as-is. Their
`spi.cpp` needs `RADIO_CS_PIN 0` and `RADIO_RST_PIN 41` and a rebuild.

### Power (the real risk)
- The Elite's USB-C is specified at **5V 500mA**. That's too little for a RAK2287
  transmitting (hundreds of mA at 3.3V on top of the ESP32 + W5500). Power from
  **PoE** (onboard DP9900M-5V module) or a solid 5V/2A+ supply.
- LilyGO's Gateway Shield gives the mPCIe card its **own 3.3V buck** (SY8089,
  3.34A inductor) from 5V rather than using the ESP32's 3V3. **Unverified:**
  whether the RAK Pi HAT regulates its own 3.3V from pin 2/4 5V (probably, since
  a Pi's 3V3 rail is weak too) or draws from pins 1/17. Measure/check the
  RAK HAT before first power-up. If it draws from 3V3, the Elite's buck feeds
  ESP32 + W5500 + concentrator all at once.

### Mechanical
The HAT must seat with pin 1 matching the Elite's pin 1, and must clear the
RJ45/PoE module. The user has the parts to check this physically.

## Hardware facts

### T-ETH-Elite (verified from LilyGO product page + repo + schematic)
- ESP32-S3-WROOM-1 (N16R8): 16 MB flash, 8 MB OPI PSRAM (GPIO 33–37 taken), Wi-Fi + BLE 5.
- Ethernet: **W5500 on its own SPI pins** (MISO 47, MOSI 21, SCLK 48, CS 45,
  INT 14), so a separate SPI host from the header bus. ESP-IDF has a native W5500 driver.
- Header shield bus: MISO 9, MOSI 11, SCLK 10 (also the SD card, CS 12).
- Official shields: Gateway (SX1302 mPCIe + L76K GPS), LTE, SX1262/SX1276 LoRa.
  The LoRa shield's SX1262 uses **CS IO40 (Pi pin 13)**, RST IO46, BUSY IO8,
  DIO1 IO16. Pi pin 13 is unused by the RAK HAT, so an SX1262 for MeshCore could
  share the bus (see option C). **Unverified.**

### The module
**RAK's menu option 7** in `rak_common_for_gateway` is "RAK7248 no LTE (RAK2287
SPI + raspberry pi)", which is what these boards are.

**Confirmed 2026-09-29: the sticker reads RAK2287** (SX1302). The RAK V2 boards
use the **SPI** variant (Meshpoint runs them on `/dev/spidev0.0`), which is what
esxp1302 and the pin map above expect. (The earlier "2278" was a misremembered
part number.)

## Software building blocks

| Piece | What it is | Status for us |
|---|---|---|
| LilyGO `T-ETH-Elite-Gateway-Shield.ino` | Ported **only** `loragw_reg.c` + an Arduino `spi.cpp`. Reads registers + GPS. | Connectivity test only, can't receive. With CS→IO0 and RST→IO41(+12) patched, it's the cheapest first smoke test for the RAK HAT. |
| [esxp1302](https://github.com/lora-gateway/esxp1302) | Full `sx1302_hal` 2.1.0 port to **ESP-IDF** (v5.4/5.5), plus Semtech UDP packet forwarder, web config UI, `test_loragw_hal_rx` CLI. BSD-3. Active (last push 2026-06). | **The base to build on.** Targets ESP32 + ESP32-C3, **not S3** (needs sdkconfig). **Wi-Fi only** (W5500 would need adding). SPI pins are `#ifndef PIN_NUM_*` overridable: MISO 9, MOSI 11, CLK 10, CS 0; reset via `loragw_gpio.c` → 41. |
| `extra/sniffer.c` | Our Pi sniffer: 8× BW125 multi-SF + ch8 Meshtastic BW250 SF11, sync-word override via `lgw_reg_w(932/933)`, Meshtastic AES-CTR + protobuf decode, node DB. | Mostly portable C. Needs OpenSSL EVP → mbedTLS (the S3 has hardware AES); the `nodes.csv`/`keys.txt` file I/O → NVS/SPIFFS. |
| Meshpoint on the Pi | Has **no** Semtech-UDP / packet-forwarder ingest today (`src/capture/` = concentrator, serial, meshcore_usb, sx1262_spi only). | Needed if the ESP32 should feed the main Meshpoint instead of decoding on its own (Option A). |

## What each network can do on an SX1302 (EU868)

| Network | EU parameters | SX1302? | Notes |
|---|---|---|---|
| LoRaWAN | 868.1/.3/.5 + others, BW125 SF7–12, sync 0x34 | **Yes** | Multi-SF channels 0–7. Free once the HAL runs. |
| Meshtastic LongFast | 869.525 MHz BW250 SF11, sync 0x2B | **Yes** | Service channel ch8 with its own sync word (the trick sniffer.c already uses). Only one Meshtastic preset at a time (ch8 is single-SF). |
| MeshCore EU | 869.618 MHz **BW62.5** SF8 | **No** | Hardware can't do BW62.5 RX. Needs an SX1262 (option C). |
| Reticulum / RNode | No fixed frequency: whatever your RNode interface is set to | **Maybe** | Only if it's BW125 (multi-SF ch0–7) or BW125/250/500 (ch8), on one of the 9 tuned channels. **Sync word conflict:** ch0–7 share one global sync word; LoRaWAN wants 0x34, RNode is believed to use 0x12 (verify). ch8 is already Meshtastic. So you pick one of LoRaWAN or Reticulum on ch0–7, unless per-chain peaks turn out to be possible. Payloads are encrypted; **announces** are readable (destination hash, public key, app data), so a roster of who's around is realistic, message contents aren't. |

## Architecture options

**A. ESP32 as a remote "dumb" concentrator (recommended to start).**
esxp1302's packet forwarder sends raw frames (freq, SF, RSSI, SNR, payload) over
Semtech UDP to a Meshpoint. Meshpoint gets a new `udp_forwarder_source.py` capture
source and reuses the Meshtastic/LoRaWAN decode it already has.
- Least new firmware code; decode stays in Python where it's already tested.
- The ch8 sync override is a small patch on the ESP32 (same registers as `sx1302_wrapper.py`).
- Five spare boards means five cheap remote receivers feeding one Meshpoint.

**B. Standalone listening station.** Port sniffer.c's decode onto the ESP32:
decrypt/decode on the device, serve a tiny web page or push MQTT.
- Truly Pi-less, but duplicates Meshpoint's decoders in C.

**C. A + SX1262 on the same header** (CS on Pi pin 13 / IO40) for MeshCore RX:
one box covers all four networks. Physically awkward with a full HAT on the header.

## Open questions / risks

1. **Power:** does the RAK HAT take 5V (pins 2/4) or 3V3 (1/17)? PoE or USB-C only?
2. **IO0 as CS:** does the ESP32 still boot reliably with the HAT attached (CS line idle high)?
3. ~~Which reset pin~~ Settled: GPIO17 → IO41 (RAK's own `reset_lgw.sh` for the RAK7248).
4. esxp1302 on **ESP32-S3**: sdkconfig, PSRAM, SPI speed. Start slow (2 MHz) over the header.
5. W5500 Ethernet in esxp1302 (it's Wi-Fi only today).
6. SPI latch on power loss (a known RAK2287 issue, `docs/HARDWARE-MATRIX.md`):
   firmware must hold reset HIGH early at boot and on brown-out.
7. Reticulum on ch0–7: can the multi-SF chains use another sync word without losing LoRaWAN?
8. The HAT's GPS is on the UART (confirmed); on the Elite that's UART0 (IO43/44). Baud rate and module type still to find, if we want time/position.

## Where the brainstorm starts (proposed order)

1. **Power check on the bench.** Find out which rail the RAK HAT draws from and
   power the Elite from PoE or a strong 5V supply. Don't run the concentrator from the 500 mA USB-C.
2. **Smoke test:** LilyGO's Gateway-Shield example with `RADIO_CS_PIN 0`,
   `RADIO_RST_PIN 41`. Success = it reads the SX1302 version
   register. That proves header, SPI and reset with almost no code.
3. **Port esxp1302 to S3** with the same pins, and run `test_loragw_hal_rx` on
   EU868. First real packets = milestone 1.
4. Decide A vs B. Then either write the Meshpoint UDP capture source (A) or
   port sniffer.c's decode (B).
5. Only then: ch8 Meshtastic sync override, Reticulum sync-word question, SX1262 for MeshCore.

## RF sensing without an SX1261: the SX1302 capture RAM

Added 2026-09-30. Applies to **any RAK2287**, on a Pi (Meshpoint today) or on the ESP32.

### Why this matters
The RAK2287 has **no SX1261** (datasheet: "one SX1302 chip and two SX1250 chips",
one `HOST_CSN`), so the hardware spectral scan / band sweep that the SenseCap M1
does is impossible. Setting `radio.sx1261_spi_path` (`/dev/spidev0.0` or `0.1`)
gives `sx1261_check_status: got:0x00 expected:0x22` and `lgw_start()` fails,
taking the whole concentrator down (see `docs/CONFIGURATION.md` §SX1261). Today the
only real alternative on a RAK is the Heltec `extra/rfenv_companion`.

### The SX1250s can't be the scanner
They're the two RF front-ends continuously streaming I/Q into the SX1302. The HAL's
`loragw_sx1250.c` has no RSSI/scan code, and retuning one needs `lgw_stop`/`lgw_start`
(seconds of RX lost).

### But the SX1302 can record what they hear
The SX1302 has a **16 KB capture RAM** debug block (4k × 32-bit words). Semtech's own
`extra/sx1302_hal/libloragw/tst/test_loragw_capture_ram.c` drives it: pick a source
(`SX1302_REG_CAPTURE_RAM_CAPTURE_SOURCE_A_SOURCEMUX`, 0–31), set the period, start,
poll `CAPCOMPLETE`, then `lgw_mem_rb()` on page 1. Sources, **as inferred from that
file's sample-rate table and decoding code (Semtech doesn't document them):**

| Source | Rate | Format | Probably |
|---|---|---|---|
| 2–3 | 4 MHz | 12-bit I/Q | raw radio A / radio B (≈1 ms per capture) |
| 4–6 | 4 MHz | 16-bit I/Q | processed versions of the same |
| 9 | 1 MHz | 12-bit I/Q | ? |
| 10–17 | 125 kHz | 8-bit I/Q | the 8 multi-SF channels after down-conversion |

Caveats: the test tool only calls `lgw_connect()` (radios never started), so it must
run **inside** a process that has already done `lgw_start()`. Whether a capture
disturbs demodulation is unknown and has to be measured.

### What Meshpoint could do with it (on a RAK)

1. **Real channel histogram on the RF Environment page, no companion board.**
   Sources 10–17 = actual power samples per channel → noise floor + occupancy
   histogram. Wrap it in the same interface as `SpectralScanService` (the way
   `RfEnvCompanionScanService` already does), so `rf_routes.py` and the frontend
   need **zero changes**. Replaces today's packet-derived `RSSI − SNR` estimate.
2. **Partial Band Spectrum card.** FFT of sources 2/3 gives the spectrum around the
   two RF chain centres (868.3 and 869.525 MHz), roughly the parts of EU868 we
   actually listen to. Feed it into the existing `spectrum_routes` median/peak per
   100 kHz step shape; mark points outside the two windows as "no data" rather than
   faking a full 863–870 sweep.
3. **"Something's there we can't decode" detection.** Energy on a channel with no
   decoded packet at that moment = foreign traffic or interference. Notably
   **MeshCore EU (869.618 MHz) sits ~93 kHz from RF1's centre**, inside radio B's
   window: the RAK can't decode BW62.5, but it could still **show MeshCore activity
   and airtime**. The same goes for RFID readers, alarms, etc.
4. **Per-channel busy % for the LoRaWAN channels** (ch0–7) on the Hardware page's
   channel-plan table: real duty-cycle load per channel, not just decoded packets.
5. **Cross-check on the SenseCap M1:** run capture RAM next to the real SX1261 scan to
   calibrate the numbers (dBm offset), then trust them on the RAK.

### Implementation sketch
- **First hardware run 2026-09-30 (RAK2287 on Pi 5, source 3, every 5 s):** capture
  completes every time: 4096 samples @ 4 MHz, non-zero, mean power 58.0–61.7 dB raw.
  **RX kept working during captures:** 5 Meshtastic packets decoded in the same
  ~2 min run (NODEINFO from the COTX, a POSITION). Build had to use Meshpoint's patched
  HAL (`make LORAGW_PATH=/opt/sx1302_hal`), because the stock `extra/sx1302_hal` aborts
  `lgw_start()` on "no temperature sensor found" (the RAK2287 has none). Reset before
  **every** run, or the next run fails with `Failed to set SX1250_0 in STANDBY_RC` /
  chip version 0x05.
- **FFT results (source 3):**
  - **Source 3 = radio B centred on rf1 (869.525 MHz): confirmed.** The capture taken
    while a -32 dBm Meshtastic packet was on air (SF11/BW250) shows a narrow peak at
    **-81 kHz, +59 dB over floor**. A 1 ms capture catches ~1/8 of an 8.2 ms SF11 chirp,
    so a packet looks like a near-tone somewhere within ±125 kHz of centre.
  - **AGC is active:** noise floor 89.5 dB (quiet) → 56.9 dB (strong packet), about 33 dB
    of gain reduction. Raw power is therefore **not absolute**; it needs gain compensation
    (find the AGC/SX1250 gain state in a register) before it can become dBm. Mean power
    alone is useless as a level measure.
  - The quiet capture shows a ~60 kHz-wide signal at **868.68–868.74 MHz**, +21 dB over
    floor, near radio B's edge (-843 kHz). Either a real device (868.6–868.7 is the EU
    alarm allocation) or a spur. Check with source 2 (radio A, 868.3 MHz, which covers it
    at +380 kHz) and repeated quiet captures (constant = spur).
- **FFT results (source 2, 20 captures, 20:12:47–20:14:22):**
  - **Source 2 = radio A (rf0, 868.3 MHz), and the usable span is wide.** Capture
    `…977` (20:12:57) shows a strong signal at **869.629 MHz = +1329 kHz, +55.6 dB over
    floor**, with the floor dropping about 30 dB (AGC again). So radio A's capture is
    usable to at least ±1.33 MHz; both radios together plausibly cover **~866.3–871.5 MHz**
    (all of EU868 except 863–866.3). 869.629 is inside both the Meshtastic (869.4–869.65)
    and the MeshCore EU (869.587–869.649) channel: check whether the sniffer decoded a
    packet at 20:12:57. No = likely MeshCore, seen but undecodable.
  - **A hump around 868.6–869.1 MHz, seen by both radios from opposite sides:** radio A
    quiet peaks always +335…+790 kHz (868.63–869.09), radio B's quiet peak -780…-844 kHz
    (868.68–868.74). The frequency wanders each capture, +17–21 dB over floor. Two radios
    agreeing suggests real RF around 868.85 MHz, but it's also the midpoint between the two
    LOs (868.9125), so internal interference isn't ruled out. **Test: antenna off /
    50 Ω terminator** (safe: sniffer has `tx_enable = false`): gone = real RF, stays = internal.
- **Plot of a quiet source 2 capture (`…992`/`…007`):** the spectrum isn't flat. It's
  ~82–85 dB at the ±2 MHz edges and ~90 dB across ~867.5–869.3 MHz, which is the radio's
  receive filter shape. So the "+18–21 dB over floor" numbers were inflated (median
  includes the rolled-off edges). On top of that there's a distinct **~5–8 dB bump at
  ~868.65–869.0 MHz**, off-centre (LO is 868.3), so not explained by the filter. The deep
  single-bin dips (868.5, 868.63, 866.37, 870.02) are normal nulls in one noise FFT, not signals.
  - Meshpoint needs **baseline flattening**: average many quiet captures, ideally with
    the antenna off or terminated (otherwise a constant real signal gets baked into the
    baseline), then subtract it from live FFTs. Also **average captures** (Welch or several
    snapshots) for display; a single FFT scatters about ±10 dB.
- **Source 10 (16 captures @ 125 kHz, ~33 ms each):** mean power very steady, 39.2–40.6 dB raw,
  with no AGC swings (good for a per-channel floor/busy metric). But **0 packets decoded in ~80 s**
  (source 3 run: 5 in 2 min). Probably a quiet spell; re-run ~3 min while a node transmits,
  to rule out per-channel capture disturbing RX. FFT not yet run (use `--center 867.9`).
- **Status 2026-09-30: proof of concept done; probe runs stopped, CSVs/PNGs cleaned up.**
  Next step is a decision: build a `CaptureRamScanService` into Meshpoint or not. The
  remaining refinements (antenna-off baseline, source 10 FFT + RX re-check, AGC gain
  register, known-carrier calibration) get done on the real feature, not with more CSV runs.
- Probe: written 2026-09-30. `sudo ./sniffer --capture
  <src> [--every N]` snapshots the capture RAM every N s (default 10) while RX keeps
  running, writing `capture_srcNN_<epoch>.csv`; `extra/capture_fft.py` FFTs it and
  prints peaks with absolute frequencies (verified on a synthetic 869.618 MHz carrier).
  Test with a Heltec sending a CW carrier at a known offset. A clean FFT peak at the
  right frequency confirms the source mapping. Also check whether packets still decode
  during captures. On a RAK, reset with `scripts/reset_concentrator.sh` (GPIO17), not
  `extra/reset_m1.sh` (M1 GPIO23).
- Then in Meshpoint: `sx1302_wrapper.py` already binds `lgw_reg_w` (ctypes in
  `sx1302_signatures.py`). Add `lgw_reg_r` + `lgw_mem_rb`, the capture-RAM register
  indices from `loragw_reg.h`, and a `CaptureRamScanService` running on the existing
  `radio.spectral_scan_interval_seconds` / `spectrum_sweep_interval_seconds` cadence.
  FFT in Python (numpy). No new config keys needed; it's used only when the SX1261 path
  is empty, same precedence as the companion fallback.

## Sources
- T-ETH-Elite product page: https://lilygo.cc/products/t-eth-elite-1
- LilyGO repo (Elite + Gateway Shield schematics, examples, prebuilt bin): https://github.com/Xinyuan-LilyGO/LilyGO-T-ETH-Series
- esxp1302 (ESP32 SX1302 HAL port): https://github.com/lora-gateway/esxp1302
- Semtech sx1302_hal: https://github.com/Lora-net/sx1302_hal
- RAK's own gateway scripts (menu option 7 = RAK7248 no LTE, RAK2287 SPI + Pi): https://github.com/RAKWireless/rak_common_for_gateway (`lora/rak2287/reset_lgw.sh`, `global_conf_uart/`, `lora/install_normal.sh`)
