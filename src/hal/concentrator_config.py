"""Channel plan configuration for the SX1302 concentrator.

The RAK2287 has:
- 8 multi-SF channels (125kHz BW, SF5-SF12 simultaneously)
- 1 single-SF configurable channel (supports 125/250/500kHz BW)
- 1 FSK channel

For Meshtastic (default LongFast = 250kHz BW, SF11):
We use the single-SF channel at 250kHz for the primary preset.
The multi-SF channels can monitor 125kHz traffic from other
protocols or custom Meshtastic presets.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_REGION_DEFAULTS_HZ: dict[str, int] = {
    "US": 906_875_000,
    "EU_868": 869_525_000,
    "ANZ": 919_875_000,
    "IN": 865_875_000,
    "KR": 922_875_000,
    "SG_923": 917_875_000,
}

_REGION_BAND_LIMITS_HZ: dict[str, tuple[int, int]] = {
    "US": (902_000_000, 928_000_000),
    "EU_868": (863_000_000, 870_000_000),
    "ANZ": (915_000_000, 928_000_000),
    "IN": (865_000_000, 867_000_000),
    "KR": (920_000_000, 923_000_000),
    "SG_923": (917_000_000, 925_000_000),
}

_NARROW_BAND_REGIONS: set[str] = {"EU_868"}


@dataclass
class ChannelConfig:
    frequency_hz: int
    bandwidth_khz: int = 125
    spreading_factor: int = 0
    enabled: bool = True


@dataclass
class ConcentratorChannelPlan:
    """Full channel configuration for the SX1302 concentrator."""

    multi_sf_channels: list[ChannelConfig] = field(default_factory=list)
    single_sf_channel: ChannelConfig | None = None
    radio_0_freq_hz: int = 906_800_000
    radio_1_freq_hz: int = 907_400_000

    @classmethod
    def from_radio_config(
        cls,
        region: str,
        frequency_mhz: float,
        spreading_factor: int = 11,
        bandwidth_khz: float = 250.0,
    ) -> ConcentratorChannelPlan:
        """Build a channel plan from radio config.

        Uses the hardcoded LongFast region preset only when frequency,
        SF, and BW all match defaults.  Otherwise builds a plan that
        respects the caller's spreading_factor and bandwidth_khz.
        """
        freq_hz = int(frequency_mhz * 1_000_000)

        if not region:
            return _build_centered_plan(freq_hz, spreading_factor, bandwidth_khz)

        default_hz = _REGION_DEFAULTS_HZ.get(region)
        if default_hz is None:
            raise ValueError(
                f"Unsupported region '{region}'. "
                f"Supported: {', '.join(sorted(_REGION_DEFAULTS_HZ))}"
            )

        is_longfast = (spreading_factor == 11 and int(bandwidth_khz) == 250)

        if freq_hz == default_hz and is_longfast:
            return cls.for_region(region)

        if freq_hz != default_hz:
            band_min, band_max = _REGION_BAND_LIMITS_HZ[region]
            if not (band_min <= freq_hz <= band_max):
                other_defaults = {v for v in _REGION_DEFAULTS_HZ.values()}
                if freq_hz in other_defaults:
                    logger.warning(
                        "Frequency %.3f MHz belongs to another region, "
                        "using %s default %.3f MHz",
                        frequency_mhz, region, default_hz / 1e6,
                    )
                    freq_hz = default_hz
                else:
                    raise ValueError(
                        f"Frequency {frequency_mhz} MHz is outside the "
                        f"{region} band "
                        f"({band_min / 1e6:.3f}-{band_max / 1e6:.3f} MHz)"
                    )

        target_freq = freq_hz if freq_hz != default_hz else default_hz
        if region in _NARROW_BAND_REGIONS:
            return _build_narrow_plan(target_freq, spreading_factor, bandwidth_khz)
        return _build_centered_plan(target_freq, spreading_factor, bandwidth_khz)

    @staticmethod
    def default_frequency_hz(region: str) -> int | None:
        """Return the default primary frequency in Hz for a region."""
        return _REGION_DEFAULTS_HZ.get(region)

    @staticmethod
    def band_limits_hz(region: str) -> tuple[int, int] | None:
        """Return (min_hz, max_hz) of a region's band, or None."""
        return _REGION_BAND_LIMITS_HZ.get(region or "")

    @classmethod
    def for_region(cls, region: str) -> ConcentratorChannelPlan:
        """Return the default channel plan for a region.

        EU_868 returns the LoRaWAN+Meshtastic combined plan so this fork
        captures both protocols simultaneously.  Other regions fall back to
        the Meshtastic-only LongFast preset.
        """
        factories = {
            "US": cls.meshtastic_us915_default,
            "EU_868": cls.eu868_lorawan,
            "ANZ": cls.meshtastic_anz_default,
            "IN": cls.meshtastic_in865_default,
            "KR": cls.meshtastic_kr920_default,
            "SG_923": cls.meshtastic_sg923_default,
        }
        factory = factories.get(region)
        if factory is None:
            raise ValueError(
                f"Unsupported region '{region}'. "
                f"Supported: {', '.join(sorted(factories))}"
            )
        return factory()

    @staticmethod
    def meshtastic_us915_default() -> ConcentratorChannelPlan:
        """US 902-928 MHz. LongFast primary at 906.875 MHz."""
        return _build_wide_band_plan(
            primary_freq_hz=906_875_000,
            radio_0_freq_hz=906_800_000,
            radio_1_freq_hz=907_400_000,
            multi_sf_base_hz=906_200_000,
        )

    @staticmethod
    def eu868_lorawan() -> ConcentratorChannelPlan:
        """EU868 plan for simultaneous LoRaWAN + Meshtastic capture.

        RF0 at 868.3 MHz covers 5 EU868 LoRaWAN channels spanning its full
        +/-400 kHz IF window (867.9 / 868.1 / 868.3 / 868.5 / 868.7 MHz,
        125 kHz BW, SF7-SF12) -- the 3 mandatory uplinks plus 2 extra TTN
        channels reachable from this center.
        RF1 stays centered at 869.525 MHz purely to keep the ch8 service
        channel at zero IF offset for the Meshtastic LongFast channel
        (869.525 MHz, 250 kHz BW, SF11).

        ch0-ch7 multi-SF share a single board-wide sync word (LoRaWAN 0x34,
        set by lorawan_public=True at start; see sx1302_wrapper.py) -- there
        is no per-channel override, so a multi-SF channel can never decode
        Meshtastic (sync 0x2B) regardless of which frequency it's tuned to.
        Only ch8 gets its own sync word via a direct register write, which
        is why it's the sole Meshtastic capture path. That also means RF1's
        multi-SF slots would be dead weight for both protocols -- nothing
        LoRaWAN-relevant sits within +/-400 kHz of 869.525 MHz -- so they're
        left disabled instead of pointed at 869.4625/869.5875 as before.

        Sync word assignment (see sx1302_wrapper.py):
          ch0-ch7 multi-SF: LoRaWAN 0x34  (set by lorawan_public=True at start)
          ch8   service:    Meshtastic 0x2B (set via direct register writes)
        """
        plan = ConcentratorChannelPlan(
            radio_0_freq_hz=868_300_000,
            radio_1_freq_hz=869_525_000,
        )
        plan.single_sf_channel = ChannelConfig(
            frequency_hz=869_525_000,
            bandwidth_khz=250,
            spreading_factor=11,
        )
        plan.multi_sf_channels = [
            # EU868 LoRaWAN uplinks on RF0 -- full +/-400 kHz IF window (125 kHz, SF7-SF12)
            ChannelConfig(frequency_hz=867_900_000),
            ChannelConfig(frequency_hz=868_100_000),
            ChannelConfig(frequency_hz=868_300_000),
            ChannelConfig(frequency_hz=868_500_000),
            ChannelConfig(frequency_hz=868_700_000),
            # Unused slots -- disabled (see docstring: RF1 multi-SF can't help
            # either protocol without breaking the ch8 Meshtastic channel)
            ChannelConfig(frequency_hz=869_525_000, enabled=False),
            ChannelConfig(frequency_hz=869_525_000, enabled=False),
            ChannelConfig(frequency_hz=869_525_000, enabled=False),
        ]
        return plan

    @staticmethod
    def meshtastic_eu868_default() -> ConcentratorChannelPlan:
        """EU 869.4-869.65 MHz. LongFast primary at 869.525 MHz.

        Band is only 250 kHz wide so multi-SF coverage is limited
        to 2 channels.
        """
        plan = ConcentratorChannelPlan(
            radio_0_freq_hz=869_525_000,
            radio_1_freq_hz=869_525_000,
        )
        plan.single_sf_channel = ChannelConfig(
            frequency_hz=869_525_000,
            bandwidth_khz=250,
            spreading_factor=11,
        )
        plan.multi_sf_channels = [
            ChannelConfig(frequency_hz=869_462_500),
            ChannelConfig(frequency_hz=869_587_500),
        ]
        for _ in range(6):
            plan.multi_sf_channels.append(
                ChannelConfig(frequency_hz=869_525_000, enabled=False)
            )
        return plan

    @staticmethod
    def meshtastic_anz_default() -> ConcentratorChannelPlan:
        """ANZ 915-928 MHz. LongFast primary at 919.875 MHz."""
        return _build_wide_band_plan(
            primary_freq_hz=919_875_000,
            radio_0_freq_hz=919_800_000,
            radio_1_freq_hz=920_400_000,
            multi_sf_base_hz=919_200_000,
        )

    @staticmethod
    def meshtastic_in865_default() -> ConcentratorChannelPlan:
        """India 865-867 MHz. LongFast primary at 865.875 MHz."""
        return _build_wide_band_plan(
            primary_freq_hz=865_875_000,
            radio_0_freq_hz=865_800_000,
            radio_1_freq_hz=866_400_000,
            multi_sf_base_hz=865_200_000,
        )

    @staticmethod
    def meshtastic_kr920_default() -> ConcentratorChannelPlan:
        """Korea 920-923 MHz. LongFast primary at 922.875 MHz.

        Primary is near the top of the 3 MHz band. Multi-SF channels
        cover the upper portion only to stay within radio_0 IF range.
        """
        plan = ConcentratorChannelPlan(
            radio_0_freq_hz=922_400_000,
            radio_1_freq_hz=921_400_000,
        )
        plan.single_sf_channel = ChannelConfig(
            frequency_hz=922_875_000,
            bandwidth_khz=250,
            spreading_factor=11,
        )
        base_freq = 921_800_000
        for i in range(6):
            plan.multi_sf_channels.append(
                ChannelConfig(frequency_hz=base_freq + (i * 200_000))
            )
        for _ in range(2):
            plan.multi_sf_channels.append(
                ChannelConfig(frequency_hz=922_400_000, enabled=False)
            )
        return plan

    @staticmethod
    def meshtastic_sg923_default() -> ConcentratorChannelPlan:
        """Singapore 917-925 MHz. LongFast primary at 917.875 MHz."""
        return _build_wide_band_plan(
            primary_freq_hz=917_875_000,
            radio_0_freq_hz=917_800_000,
            radio_1_freq_hz=918_400_000,
            multi_sf_base_hz=917_200_000,
        )

    def to_hal_config(self) -> dict:
        """Convert to a dict suitable for HAL configuration."""
        config = {
            "radio_0_freq_hz": self.radio_0_freq_hz,
            "radio_1_freq_hz": self.radio_1_freq_hz,
            "multi_sf_channels": [
                {
                    "index": i,
                    "freq_hz": ch.frequency_hz,
                    "bandwidth_khz": ch.bandwidth_khz,
                    "enabled": ch.enabled,
                }
                for i, ch in enumerate(self.multi_sf_channels)
            ],
        }

        if self.single_sf_channel:
            config["single_sf"] = {
                "freq_hz": self.single_sf_channel.frequency_hz,
                "bandwidth_khz": self.single_sf_channel.bandwidth_khz,
                "spreading_factor": self.single_sf_channel.spreading_factor,
                "enabled": self.single_sf_channel.enabled,
            }

        return config


def _build_centered_plan(
    center_freq_hz: int,
    spreading_factor: int = 11,
    bandwidth_khz: float = 250.0,
) -> ConcentratorChannelPlan:
    """Build a channel plan centered on a custom frequency.

    Radio_0 at center (zero IF offset for BW500 support),
    radio_1 at center + 800 kHz. 8 multi-SF channels spread
    symmetrically +/- 700 kHz around center.
    """
    plan = ConcentratorChannelPlan(
        radio_0_freq_hz=center_freq_hz,
        radio_1_freq_hz=center_freq_hz + 800_000,
    )
    plan.single_sf_channel = ChannelConfig(
        frequency_hz=center_freq_hz,
        bandwidth_khz=int(bandwidth_khz),
        spreading_factor=spreading_factor,
    )
    multi_sf_base = center_freq_hz - 700_000
    for i in range(8):
        plan.multi_sf_channels.append(
            ChannelConfig(frequency_hz=multi_sf_base + (i * 200_000))
        )
    return plan


def _build_narrow_plan(
    center_freq_hz: int,
    spreading_factor: int = 11,
    bandwidth_khz: float = 250.0,
) -> ConcentratorChannelPlan:
    """Build a channel plan for narrow-band regions (e.g. EU 250 kHz)."""
    plan = ConcentratorChannelPlan(
        radio_0_freq_hz=center_freq_hz,
        radio_1_freq_hz=center_freq_hz,
    )
    plan.single_sf_channel = ChannelConfig(
        frequency_hz=center_freq_hz,
        bandwidth_khz=int(bandwidth_khz),
        spreading_factor=spreading_factor,
    )
    plan.multi_sf_channels = [
        ChannelConfig(frequency_hz=center_freq_hz - 62_500),
        ChannelConfig(frequency_hz=center_freq_hz + 62_500),
    ]
    for _ in range(6):
        plan.multi_sf_channels.append(
            ChannelConfig(frequency_hz=center_freq_hz, enabled=False)
        )
    return plan


def _build_wide_band_plan(
    primary_freq_hz: int,
    radio_0_freq_hz: int,
    radio_1_freq_hz: int,
    multi_sf_base_hz: int,
    multi_sf_count: int = 8,
    multi_sf_step_hz: int = 200_000,
) -> ConcentratorChannelPlan:
    """Build a channel plan for regions with >= 2 MHz of usable band."""
    plan = ConcentratorChannelPlan(
        radio_0_freq_hz=radio_0_freq_hz,
        radio_1_freq_hz=radio_1_freq_hz,
    )
    plan.single_sf_channel = ChannelConfig(
        frequency_hz=primary_freq_hz,
        bandwidth_khz=250,
        spreading_factor=11,
    )
    for i in range(multi_sf_count):
        plan.multi_sf_channels.append(
            ChannelConfig(frequency_hz=multi_sf_base_hz + (i * multi_sf_step_hz))
        )
    return plan
