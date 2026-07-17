# Band Plan (SX1302 Concentrator Channel Config)

Reference for the concentrator's predefined channel plans — one per supported
region, defined in [`src/hal/concentrator_config.py`](../src/hal/concentrator_config.py)
(`ConcentratorChannelPlan`). This is about the **onboard SX1302's own receive
channels** (what physical frequencies the concentrator listens on), not the
Meshtastic radio's own frequency-slot selection — see
[RADIO-CONFIG-EXPLAINED.md](RADIO-CONFIG-EXPLAINED.md) for that (a Meshtastic
node's own TX frequency, US slot map, custom frequency slots).

## Hardware shape

Every plan configures the same physical layout:

- **2 RF chains** (`radio_0_freq_hz`, `radio_1_freq_hz`) — analog front-end
  anchor frequencies.
- **8 multi-SF channels** (ch0–ch7) — 125 kHz BW, demodulate SF5–SF12
  simultaneously. Each is anchored to one of the two RF chains and must sit
  within **±490 kHz** of that chain's frequency (a hard SX1302 IF-engine
  limit).
- **1 single-SF channel** (ch8, the "service channel") — configurable
  bandwidth (125/250/500 kHz), one spreading factor at a time. This is the
  channel a region's Meshtastic default (e.g. LongFast, SF11/250 kHz) runs on.
- 1 FSK channel (not used by Meshpoint).

## Supported regions

| Region | Default (primary/service channel) | Band limits |
|---|---|---|
| `US` | 906.875 MHz | 902.0 – 928.0 MHz |
| `EU_868` | 869.525 MHz | 863.0 – 870.0 MHz |
| `ANZ` | 919.875 MHz | 915.0 – 928.0 MHz |
| `IN` | 865.875 MHz | 865.0 – 867.0 MHz |
| `KR` | 922.875 MHz | 920.0 – 923.0 MHz |
| `SG_923` | 917.875 MHz | 917.0 – 925.0 MHz |

`ConcentratorChannelPlan.for_region(region)` picks the factory method below
for each. Selected automatically by `meshpoint setup`'s Region step, or via
`radio.region` in `local.yaml`.

---

## EU_868 — the odd one out: LoRaWAN + Meshtastic simultaneously

`eu868_lorawan()` — the only plan that isn't Meshtastic-only. Splits the two
RF chains between two protocols entirely, because the Meshtastic LongFast
channel (869.525 MHz) sits 1.025–1.625 MHz above the LoRaWAN uplink band —
too far for one RF chain's ±490 kHz IF window to cover both.

```
radio_0 = 868.300 MHz  →  ch0–ch4: LoRaWAN (5 TTN uplinks, sync word 0x34)
radio_1 = 869.525 MHz  →  ch8:     Meshtastic LongFast (sync word 0x2B)
                           ch5–ch7: disabled (nothing useful within
                                    ±490 kHz of radio_1)
```

| Channel | Frequency | BW | SF | Protocol | RF chain | IF offset |
|---|---|---|---|---|---|---|
| ch0 | 867.900 MHz | 125 kHz | SF7–12 | LoRaWAN | RF0 | −400 000 Hz |
| ch1 | 868.100 MHz | 125 kHz | SF7–12 | LoRaWAN | RF0 | −200 000 Hz |
| ch2 | 868.300 MHz | 125 kHz | SF7–12 | LoRaWAN | RF0 | 0 |
| ch3 | 868.500 MHz | 125 kHz | SF7–12 | LoRaWAN | RF0 | +200 000 Hz |
| ch4 | 868.700 MHz | 125 kHz | SF7–12 | LoRaWAN | RF0 | +400 000 Hz |
| ch5–ch7 | — | — | — | disabled | RF1 | — |
| ch8 | 869.525 MHz | 250 kHz | SF11 | Meshtastic | RF1 | 0 |

TTN channels covered: 868.1, 868.3, 868.5 (the 3 mandatory ones) plus 867.9
and 868.7. Out of reach from this RF0 anchor: 867.1/867.3/867.5/867.7.

There's a second, unused EU868 factory, `meshtastic_eu868_default()`
(Meshtastic-only, 2 multi-SF channels at 869.4625/869.5875 MHz) — defined but
never wired into `for_region()`, which always returns `eu868_lorawan()` for
`EU_868`. Kept in the source as a documented alternative, not dead by
accident.

## US, ANZ, IN, KR, SG_923 — Meshtastic-only wide-band plans

The other five regions have ≥2 MHz of usable band and use
`_build_wide_band_plan()`: 8 multi-SF channels spaced 200 kHz apart starting
700 kHz below the primary frequency, plus the single-SF service channel at
the region default.

| Region | Primary (ch8) | RF0 | RF1 | Multi-SF base (ch0) |
|---|---|---|---|---|
| `US` | 906.875 MHz | 906.800 MHz | 907.400 MHz | 906.200 MHz |
| `ANZ` | 919.875 MHz | 919.800 MHz | 920.400 MHz | 919.200 MHz |
| `IN` | 865.875 MHz | 865.800 MHz | 866.400 MHz | 865.200 MHz |
| `SG_923` | 917.875 MHz | 917.800 MHz | 918.400 MHz | 917.200 MHz |

Multi-SF channels for these four: `base + i × 200 kHz` for `i` in `0..7` (all
8 enabled).

**`KR` is hand-rolled, not via the shared helper** — its 3 MHz band is
narrower and the primary sits near the top, so multi-SF coverage is
deliberately limited to the lower/middle portion to stay within `radio_0`'s
IF range:

```
radio_0 = 922.400 MHz, radio_1 = 921.400 MHz
ch8 (primary) = 922.875 MHz
ch0–ch5 = 921.800 MHz + i × 200 kHz  (6 enabled channels)
ch6–ch7 = disabled
```

## Custom frequency / SF / BW (not a region default)

`ConcentratorChannelPlan.from_radio_config(region, frequency_mhz, sf, bw)` is
what actually runs at startup — it only returns the hardcoded region plan
above when the frequency **and** SF11/250 kHz (LongFast) match the region
default exactly. Any other combination (a custom slot, a different modem
preset) instead builds a plan around the requested frequency:

- **`EU_868`** (a "narrow band" region) → `_build_narrow_plan()`: single-SF
  channel at the custom frequency/SF/BW, only 2 multi-SF channels
  (±62.5 kHz), the remaining 6 disabled.
- **Everything else** → `_build_centered_plan()`: single-SF channel at the
  custom frequency, `radio_1` at `+800 kHz`, 8 multi-SF channels spread
  ±700 kHz around it in 200 kHz steps.

A frequency outside the region's band limits is rejected outright (`from_radio_config`
raises `ValueError`), unless it happens to exactly match *another* region's
default — in that case it logs a warning and silently falls back to the
configured region's own default instead of erroring.

---

## Sync words — why the 8 multi-SF channels rarely help with Meshtastic

The board is configured with `lorawan_public = True` unconditionally
(`sx1302_wrapper.py`, `_configure_board()`), which makes `lgw_start()`
program **all 8 multi-SF channels (ch0–ch7) to the public LoRaWAN sync word
`0x34`** — for every region, not just `EU_868`. Only the single-SF service
channel (ch8) gets overridden to Meshtastic's `0x2B` via a direct register
write (`set_syncword()`).

Practical effect: **only ch8 (the single primary/service channel) can ever
decode Meshtastic traffic**, on every region. The 8 multi-SF channels are
genuinely useful for `EU_868` (real TTN LoRaWAN uplinks live there) but on
the other five regions they're only listening for LoRaWAN-sync-word traffic
that may not exist in that band at all — they do **not** give extra coverage
of alternate Meshtastic presets or slots, despite what the unused
`meshtastic_eu868_default()` docstring implies. See
[`concentrator_source.py`](../src/capture/concentrator_source.py)'s
`_MESHTASTIC_EU868_FREQS_HZ` comment for the same note in code.

## A table you might see disagree: `src/radio/presets.py`

`src/radio/presets.py` has its own `REGION_DEFAULTS` dict (frequency
suggestions used elsewhere, e.g. default frequency for a serial/USB
Meshtastic stick) — it agrees with the concentrator's table for `US` and
`EU_868`, but **differs for `ANZ`, `IN`, `KR`, and `SG_923`**:

| Region | `concentrator_config.py` (this doc, authoritative for the concentrator) | `presets.py` `REGION_DEFAULTS` |
|---|---|---|
| `ANZ` | 919.875 MHz | 916.0 MHz |
| `IN` | 865.875 MHz | 865.4625 MHz |
| `KR` | 922.875 MHz | 921.9 MHz |
| `SG_923` | 917.875 MHz | 923.0 MHz |

[RADIO-CONFIG-EXPLAINED.md](RADIO-CONFIG-EXPLAINED.md#region)'s region table
matches `concentrator_config.py`, not `presets.py` — if you're cross-
referencing frequencies across the codebase and they don't match, this is
why. Not something this pass changed or fixed, just flagging it as found.

---

## See Also

- [RADIO-CONFIG-EXPLAINED.md](RADIO-CONFIG-EXPLAINED.md): Meshtastic's own
  frequency-slot selection (US slot map, custom slots, SF/BW/CR), separate
  from the concentrator's receive plan documented here
- [Configuration > Radio](CONFIGURATION.md#radio): full field reference
- [HARDWARE-MATRIX.md](HARDWARE-MATRIX.md): supported concentrator boards
