# Nebra Outdoor Hotspot (CM3+) → Meshtastic feasibility

Investigation into reusing a **Nebra Outdoor Helium miner** (Raspberry Pi
**Compute Module 3 / CM3+** carrier board) for Meshtastic, given the concentrator
board on hand is SX1302/SX1301-class (user said "WM1302", "RAK2237",
"RAK2257", "RAK2247" at various points — likely means either the **WM1302**
(SX1302, confirmed Meshpoint-compatible chip) or **RAK2247** (SX1301/SX1308,
older LoRaWAN-only gateway generation, not compatible with anything here).
Exact board still unconfirmed — doesn't change the conclusions below either way.

## Hardware situation

- Host: CM3+ (BCM2837, same SoC as Pi 3B, **is** aarch64-capable — 64-bit
  Raspberry Pi OS boots fine on it). 1 GB RAM.
- Concentrator: SX1302 (WM1302/RAK2287 family) or SX1301/SX1308 (RAK2247/2257
  family) mini-PCIe card inside the Nebra Outdoor enclosure.
- Nebra's own carrier wiring (confirmed by cloning `NebraLtd/helium-miner-software`):
  `balena/config/config.txt.nebra-raspi` sets `dtoverlay=spi1-3cs` — the
  concentrator socket is **SPI1 with 3 chip-selects + GPIO reset**, not USB.
  Exact pin numbers (reset/busy/DIO) not published in that repo; would need
  `hm-pyhelper`'s `hardware_definitions.py` or physical tracing to get them.

## Why meshtasticd can't drive the concentrator directly

- `meshtasticd` (Linux native / "Portduino" build) talks to radios through
  **RadioLib**: single chip, SPI register banging, DIO1 interrupt per packet,
  one frequency/SF at a time.
- SX1302/SX1301 concentrators are driven through Semtech's **libloragw**
  C HAL: 8 parallel demodulators, no "packet ready" IRQ pin, you poll
  `lgw_receive()`/schedule `lgw_send()` against an internal timestamp counter,
  plus startup calibration. Architecturally unrelated to RadioLib.
- RadioLib has no concept of concentrator-class hardware at all — there is
  nothing to "patch"; it would mean writing a wholly new driver.
- SX1301/SX1308 (RAK2247-class) is a *further* generation back — a different
  legacy HAL (`lora_gateway` v1) from SX1302/1303's `sx1302_hal`. Confirmed
  explicitly unsupported even by Meshpoint itself:
  [docs/HARDWARE-MATRIX.md:283-296](docs/HARDWARE-MATRIX.md#L283-L296).
- Meshpoint itself doesn't patch meshtasticd/RadioLib — it bypasses both
  entirely, reimplementing the Meshtastic wire protocol (LoRa framing +
  protobuf + channel crypto) in Python directly against a patched
  `libloragw` (`extra/sx1302_hal`, `scripts/patch_hal.sh`). The patch is
  specifically a **TX sync-word override**: stock HAL can only emit 0x12/0x34,
  never Meshtastic's 0x2B; RX-side 0x2B was already handled via direct
  service-channel register writes. See `scripts/patch_hal.sh` header comment
  for the full history (an older, now-defunct version of this patch, and why
  it broke).

## Checked `NebraLtd/helium-miner-software` — no shortcut there

Cloned `helium-miner-software` + `hm-pktfwd` (the actual packet-forwarder
container). Confirmed it's **just Nebra's own LoRaWAN stack**, not a bridge to
anything mesh-related:
- `hm-pktfwd` is a thin Python wrapper that launches a prebuilt binary per
  chip family, built from `NebraLtd/lora_gateway` (SX1301 legacy HAL),
  `NebraLtd/sx1302_hal` (their own fork of the same Semtech HAL Meshpoint
  patches), `NebraLtd/packet_forwarder` — run **completely stock**, feeding
  Helium's own `gateway-rs` over the standard Semtech UDP packet-forwarder
  protocol (PUSH_DATA/PULL_RESP, port 1680 locally). Zero Meshtastic/RadioLib
  code anywhere in it.
- GPIO reset (`reset_lgw.sh`, `CONCENTRATOR_RESET_PIN` over sysfs) is
  essentially identical in mechanism to Meshpoint's own reset handling.

## The promising path: don't patch meshtasticd, extend its radio abstraction

Checked the real `meshtastic/firmware` source directly (cloned to scratchpad,
not kept in this repo). Key finding: `RadioInterface`
(`src/mesh/RadioInterface.h:82`) is **already an abstract interface meant for
exactly this** — its own doc comment: *"This defines the SOLE API for talking
to radios (because soon we will have alternate radio implementations)."*

Proof it's not RadioLib-locked: `SimRadio`
(`src/platform/portduino/SimRadio.{h,cpp}`) is a real, shipping subclass
(used for their multi-node simulator) that implements `send()`,
`getCurrentRSSI()`, `isChannelActive()`, etc. with **zero SPI/RadioLib
calls** — pure software queues/timers. The dispatch point,
`initLoRa()` (`src/mesh/RadioInterface.cpp:381`), is a plain switch over a
`portduino_config.lora_module` enum (`use_sx1262`, `use_rf95`, ...,
`use_simradio`) that returns the matching subclass — there's even a `ch341`
special case already for a USB-SPI bridge radio, so "the radio isn't a
direct SPI chip" is already precedented, not novel.

**So the Nebra-style split architecture maps cleanly onto this:**

1. **Concentrator side — mostly already built in this repo.** A standalone
   process owns the patched `sx1302_hal` (`extra/sx1302_hal` +
   `scripts/patch_hal.sh`, correct RX *and* TX sync word 0x2B), tuned to one
   Meshtastic frequency/SF/BW on the service channel — exactly what
   `extra/sniffer.c` already does (`MESHTASTIC_FREQ_HZ`, BW250 SF11 on ch8).
   It polls `lgw_receive()`/calls `lgw_send()` in a loop and exposes
   decoded frames + RSSI/SNR/timestamp over a local socket (Nebra
   `hm-pktfwd`-style, or simpler).
2. **meshtasticd side — new work, but scoped.** A new `RadioInterface`
   subclass, shaped like `SimRadio` (no SPI), that forwards `send()`'s
   payload out over that socket and turns inbound frames into
   `meshtastic_MeshPacket`s via `deliverToReceiver()`. Add one
   `use_concentrator_bridge` case next to `use_simradio` in the `initLoRa()`
   switch. Estimated scope: one new `.h`/`.cpp` pair on the order of
   `SimRadio.cpp`'s size (~300 lines) — not a RadioLib rewrite, not a
   mesh/routing layer change.

**Caveats (not yet resolved, flagged honestly):**
- Doesn't exist anywhere today, as far as a grep of the firmware tree found —
  would be new work on a `meshtastic/firmware` fork (same pattern as
  Meshpoint being its own fork rather than an upstream PR; no need for
  upstream buy-in to build/run it for personal use).
- Concentrator runs as a glorified single-channel radio this way: meshtasticd
  only wants one freq/SF/BW, so the other 7 demod chains sit idle. You keep
  real concentrator TX power, lose multi-SF simultaneous capture (not needed
  for a plain mesh node anyway).
- The bridge needs to report `isChannelActive()`/`getCurrentRSSI()` honestly
  for CAD/CSMA to behave — doable from SX1302 RX status registers (same
  signal Meshpoint's own RX path reads), but real implementation work, not
  free.
- Not yet prototyped or validated on hardware. Everything above is source
  analysis only (this repo + `meshtastic/firmware`, both read-only clones),
  no code written yet.

## Phase 1 prototype — built, awaiting real-traffic data

`extra/sniffer.c` now has opt-in logging (`--log-poll FILE --log-pkt FILE`,
CSV, zero overhead/behavior change when the flags are absent): poll-to-poll
gap timing (`mono_us,gap_us,nb_pkts`) and per-packet metadata including the
SX1302's own on-chip `count_us` timestamp and RSSI/SNR
(`mono_us,count_us,is_mesh,sf,bw_khz,rssic,rssis,snr,len`). Run on the
already-deployed Meshpoint Pi (SenseCap M1) against real traffic — no new
Nebra/CM3/CM4 hardware needed for this step. Build/run:

```bash
sudo apt install -y libssl-dev   # once, if missing
cd ~/meshpoint/extra/sx1302_hal && make
cd ~/meshpoint/extra && make
bash reset_m1.sh && sudo ./sniffer --log-poll poll.csv --log-pkt pkt.csv
```

Let it run for hours/a day, Ctrl+C, pull the two CSVs back. Not yet run —
next step is analyzing real data once it's collected.

### Phase 1 result (72 min real capture on the deployed COTX X3 Pi, 2026-11-23)

Ran standalone (meshpoint service stopped) against real mesh traffic.
415,835 poll samples, 34 decoded Meshtastic frames.

- **Poll gap**: mean/median 10.35ms (nominal 10ms `usleep`), stdev 77µs.
  p99.99 = 11.07ms. Worst single outlier in 72 min: 41.7ms (one occurrence).
  Only 0.012% of polls exceeded 11ms; zero exceeded 50ms.
- **`nb_pkts` never exceeded 1** per poll — no bursts missed; LoRa airtime
  (hundreds of ms+) is far longer than the 10ms poll period anyway.
- **RSSI/SNR spread**: -17.4 to -105.4dBm, SNR -19.5 to +7.8dB — good
  mix of strong/marginal signal, all decoded correctly including the
  weak ones.

**Conclusion: the RX-polling-latency concern that motivated this whole
prototype looks resolved.** 10ms-class polling jitter is 100-1000x smaller
than the timing constants `RadioInterface` itself already operates on
(`PROCESSING_TIME_MSEC = 4500`, ~165ms default preamble time) — so it
doesn't look like it would meaningfully affect CSMA/CAD behavior for a
`ConcentratorBridgeInterface`.

Caveats not yet resolved:
- This ran with the real `meshpoint` Python service *stopped* — no
  competing load. Arguably realistic anyway, since the bridge's polling
  loop would live in its own small process (same shape as this sniffer),
  not inside the full app — but not proven under contention.
- **TX-side timing is completely untested.** This only measured RX poll
  latency. Scheduling TX precisely against `lgw_send()`'s timestamp
  counter, and turnaround time for CSMA responses, is a separate,
  still-open question — the next thing to prototype if this path
  continues.

## Open questions / next steps (not yet started)

- Confirm actual board in hand (WM1302 vs RAK2247 vs RAK2287 — user has
  given inconsistent part numbers across the conversation).
- Trace/obtain the Nebra Outdoor carrier's exact SPI1 + reset/busy/DIO GPIO
  pin numbers (not in `helium-miner-software`; would need `hm-pyhelper`'s
  `hardware_definitions.py` or physical probing) — relevant both to a
  possible direct-wire SX1262 for plain meshtasticd, and to any bridge
  approach reusing the existing concentrator socket.
- If pursuing the bridge: design the local socket protocol
  (Unix socket vs loopback UDP; could reuse Semtech's UDP packet-forwarder
  format since it already carries the needed RX metadata, or roll something
  simpler) and sketch the `ConcentratorBridgeInterface` class against
  `SimRadio` as the template.
- Simpler fallback path (no new firmware code): pull the concentrator card
  entirely, flash 64-bit Raspberry Pi OS Lite, run stock `meshtasticd` with
  a plain SX1262 radio (CH341-based USB stick is simplest — no new holes in
  the enclosure — splice its antenna pigtail onto the Nebra's existing
  SMA/N-type feed, same 868/915 band).
