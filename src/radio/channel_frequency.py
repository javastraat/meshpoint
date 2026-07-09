"""Meshtastic channel-to-frequency resolution.

Replicates the frequency computation in meshtastic/firmware's
``src/mesh/RadioInterface.cpp`` (``RadioInterface::applyModemConfig``),
verified line-for-line against a local firmware source checkout and
cross-checked against a real device's observed frequency (EU_433,
default channel -> 433.875 MHz, reproduced exactly by this module).

Only needed for capture sources that read a connected Meshtastic
node's own reported config (e.g. the ``serial`` USB source) rather
than programming a radio directly -- Meshpoint's own concentrator
already knows its exact configured frequency without having to guess.

Region support is limited to the regions using PROFILE_STD or
PROFILE_EU868 (spacing=0, padding=0) -- the same set already exposed
elsewhere in this codebase (``concentrator_config.py``'s
``_REGION_DEFAULTS_HZ``, ``src/radio/presets.py``'s
``REGION_DEFAULTS``). Regions with nonzero spacing/padding (EU_866,
EU_N_868, the ham-band regions) are not modelled here and resolve to
0.0 rather than a wrong number.
"""

from __future__ import annotations

from typing import Optional

# (freqStart, freqEnd) in MHz, from meshtastic/firmware's `regions[]`
# table (RadioInterface.cpp). Only PROFILE_STD/PROFILE_EU868 regions
# (spacing=0, padding=0) are included, matching the region set this
# codebase already supports elsewhere.
_REGION_BAND_MHZ: dict[str, tuple[float, float]] = {
    "US": (902.0, 928.0),
    "EU_433": (433.0, 434.0),
    "EU_868": (869.4, 869.65),
    "ANZ": (915.0, 928.0),
    "IN": (865.0, 867.0),
    "KR": (920.0, 923.0),
    "SG_923": (917.0, 925.0),
}

# Exact strings meshtastic/firmware's DisplayFormatters::getModemPresetDisplayName
# returns (useShortName=false) -- this is what Channels::getName() hashes
# when a channel's own name is blank, i.e. the common "just left it as the
# default preset" case. NOTE some of these deliberately do NOT match this
# codebase's own src/radio/presets.py display_name (built for the UI, not
# for hash-compatibility) -- LONG_MODERATE's firmware string is "LongMod",
# not "LongModerate", and picking the wrong one silently produces a wrong
# hash slot, so this table is kept separate and verified against the
# firmware source rather than reused.
_PRESET_HASH_NAME: dict[str, str] = {
    "SHORT_TURBO": "ShortTurbo",
    "SHORT_SLOW": "ShortSlow",
    "SHORT_FAST": "ShortFast",
    "MEDIUM_SLOW": "MediumSlow",
    "MEDIUM_FAST": "MediumFast",
    "LONG_SLOW": "LongSlow",
    "LONG_FAST": "LongFast",
    "LONG_TURBO": "LongTurbo",
    "LONG_MODERATE": "LongMod",
    "LITE_FAST": "LiteFast",
    "LITE_SLOW": "LiteSlow",
    "NARROW_FAST": "NarrowFast",
    "NARROW_SLOW": "NarrowSlow",
    "TINY_FAST": "TinyFast",
    "TINY_SLOW": "TinySlow",
}
# VERY_LONG_SLOW (and any preset firmware doesn't recognize) falls through
# to this literal in the firmware's switch statement's default case.
_PRESET_HASH_NAME_FALLBACK = "Invalid"
_CUSTOM_HASH_NAME = "Custom"


def _djb2(text: str) -> int:
    """Dan Bernstein's djb2, byte-for-byte matching firmware's `hash()`
    in RadioInterface.cpp: ``hash = hash*33 + c`` per byte, 32-bit
    unsigned wraparound, seed 5381.
    """
    h = 5381
    for byte in text.encode("utf-8"):
        h = ((h << 5) + h + byte) & 0xFFFFFFFF
    return h


def _preset_hash_name(modem_preset: Optional[str], use_preset: bool) -> str:
    if not use_preset:
        return _CUSTOM_HASH_NAME
    return _PRESET_HASH_NAME.get(modem_preset or "", _PRESET_HASH_NAME_FALLBACK)


def resolve_frequency_mhz(
    *,
    region: Optional[str],
    channel_num: Optional[int],
    bandwidth_khz: Optional[float],
    channel_name: Optional[str] = None,
    modem_preset: Optional[str] = None,
    use_preset: bool = True,
    frequency_offset: float = 0.0,
    override_frequency: float = 0.0,
) -> float:
    """The node's actual operating frequency, matching firmware exactly.

    ``channel_num`` is the raw config value as reported by the device
    (0 = "use the default/hash-derived slot"; a positive value N means
    the explicit 1-based slot N). When 0, the slot is derived from
    ``hash(channel_name) % num_slots`` -- using the primary channel's
    own name if set, or the modem preset's firmware display string when
    the channel name is blank (the common case for a stock setup).

    Returns 0.0 (this codebase's "unknown" sentinel) when the region
    isn't in the supported table or there isn't enough information to
    compute a slot count, rather than guessing.
    """
    if override_frequency:
        return round(override_frequency + frequency_offset, 4)

    if not region or not bandwidth_khz:
        return 0.0
    band = _REGION_BAND_MHZ.get(region)
    if band is None:
        return 0.0

    freq_start, freq_end = band
    freq_slot_width = bandwidth_khz / 1000.0  # spacing=0, padding=0 here
    if freq_slot_width <= 0:
        return 0.0
    num_slots = round((freq_end - freq_start) / freq_slot_width)
    if num_slots <= 0:
        return 0.0

    if channel_num:
        slot = channel_num - 1
        # Firmware itself rejects a channel_num above the region's slot
        # count at config-set time (RadioInterface.cpp), so a real
        # device never reports one out of range. Guard it anyway
        # rather than compute a nonsensical out-of-band number.
        if slot >= num_slots:
            return 0.0
    else:
        name = (channel_name or "").strip()
        if not name:
            name = _preset_hash_name(modem_preset, use_preset)
        slot = _djb2(name) % num_slots

    freq = freq_start + (bandwidth_khz / 2000.0) + slot * freq_slot_width
    return round(freq + frequency_offset, 4)
