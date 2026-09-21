"""ctypes wrapper for the Semtech SX1302 HAL (libloragw).

Provides Python bindings to the C library functions needed for
concentrator-based packet capture and LoRa transmission via the
SX1261 companion radio. Only functional on a Raspberry Pi with
the patched libloragw.so compiled and installed.
"""

from __future__ import annotations

import ctypes
import logging
import os
from dataclasses import dataclass
from typing import Optional

from src.hal.concentrator_config import ConcentratorChannelPlan
from src.hal.sx1302_signatures import apply_signatures
from src.hal.sx1302_spectral_scan import (
    SpectralScanResult,
    SX1302SpectralScan,
)
from src.hal.sx1302_types import (
    LgwConfBoardS,
    LgwConfRxifS,
    LgwConfRxrfS,
    LgwConfSx1261S,
    LgwPktRxS,
    LgwPktTxS,
    LgwTxGainLutS,
)

logger = logging.getLogger(__name__)

LGW_HAL_SUCCESS = 0
LGW_HAL_ERROR = -1
LGW_PKT_MAX = 16
LGW_IF_CHAIN_NB = 10
LGW_MULTI_NB = 8

LGW_COM_SPI = 0
LGW_RADIO_TYPE_SX1250 = 5

# SX1302 service-channel LoRa sync word peak-position registers.
# See loragw_reg.h: SX1302_REG_RX_TOP_LORA_SERVICE_FSK_FRAME_SYNCH0/1_PEAK*
_REG_SERVICE_PEAK1 = 932
_REG_SERVICE_PEAK2 = 933

BW_125KHZ = 0x04
BW_250KHZ = 0x05
BW_500KHZ = 0x06
BW_MAP = {BW_125KHZ: 125.0, BW_250KHZ: 250.0, BW_500KHZ: 500.0}

BW_KHZ_TO_HAL = {125: BW_125KHZ, 250: BW_250KHZ, 500: BW_500KHZ}

STAT_CRC_OK = 0x10
STAT_CRC_BAD = 0x11
STAT_NO_CRC = 0x01

_STATUS_NAMES = {
    STAT_CRC_OK: "CRC_OK",
    STAT_CRC_BAD: "CRC_BAD",
    STAT_NO_CRC: "NO_CRC",
}

MOD_LORA = 0x10
MOD_FSK = 0x20
TX_MODE_IMMEDIATE = 0
TX_STATUS = 1
TX_STATUS_FREE = 2
TX_STATUS_EMITTING = 4

# ch9, the SX1302's dedicated FSK IF chain -- genuinely independent
# hardware from ch8 (LoRa service, Meshtastic) and ch0-7 (LoRa multi-SF,
# LoRaWAN), each with its own separate config context and sync word
# (confirmed against extra/sx1302_hal's real HAL source: loragw_hal.c's
# CONTEXT_FSK is a wholly separate struct from CONTEXT_LORA_SERVICE, and
# the hardware capability table in loragw_sx1302.c lists IF_LORA_STD and
# IF_FSK_STD as two of ten independent, simultaneously-active modems --
# not a mode switch). Used for the emergency pager project's own
# framing, deliberately not the POCSAG protocol.
FSK_IF_CHAIN = 9
# FSK datarate (bps) valid range per loragw_hal.h's DR_FSK_MIN/MAX.
FSK_DATARATE_MIN = 500
FSK_DATARATE_MAX = 250_000
# FSK RX bandwidth reuses the same BW_125/250/500KHZ constants LoRa uses
# (loragw_hal.h's own comment: "values available for the 'bandwidth'
# parameters (LoRa & FSK)") -- BW_125KHZ is the narrowest defined option,
# comfortably wide for a low-baud-rate custom protocol; may need tuning
# once tested against real hardware.
FSK_DEFAULT_BANDWIDTH = BW_125KHZ
FSK_DEFAULT_DATARATE = 4_800
# Frequency deviation (kHz) for FSK TX only -- loragw_hal.c's own send()
# validation rejects anything outside 1-200 kHz. Not yet tuned against
# real hardware/firmware (there is none yet); 25 kHz is a conservative
# starting point common for a few-kbps GFSK link, not a measured value.
FSK_DEFAULT_FDEV_KHZ = 25


@dataclass
class ConcentratorPacket:
    """Decoded packet from the concentrator hardware."""

    payload: bytes
    frequency_hz: int
    rssi: float
    snr: float
    spreading_factor: int
    bandwidth: int
    coderate: int
    crc_ok: bool
    timestamp_us: int
    # "lora" or "fsk" -- lets a caller pulling packets from receive()
    # (which serves both Meshtastic/LoRaWAN's LoRa channels and the
    # pager's FSK channel from the same poll) tell them apart without
    # guessing from spreading_factor/coderate being meaningless on FSK.
    modulation: str = "lora"


class SX1302Wrapper:
    """Python interface to the SX1302 concentrator via libloragw.

    Usage:
        wrapper = SX1302Wrapper(spi_path="/dev/spidev0.0")
        wrapper.load()
        wrapper.configure(channel_plan)
        wrapper.set_syncword(0x2B)
        wrapper.start()
        packets = wrapper.receive()
        wrapper.stop()
    """

    def __init__(
        self,
        lib_path: Optional[str] = None,
        spi_path: str = "/dev/spidev0.0",
        sx1261_spi_path: str = "",
    ):
        self._lib: Optional[ctypes.CDLL] = None
        self._lib_path = lib_path or self._find_library()
        self._spi_path = spi_path
        self._sx1261_spi_path = sx1261_spi_path
        self._started = False
        self._debug_rx = os.getenv("MESHPOINT_DEBUG_RX") == "1"
        self._crc_bad_count = 0
        self._no_crc_count = 0
        self._unknown_status_count = 0
        self._spectral_scan: Optional[SX1302SpectralScan] = None
        self._sx1261_configured = False

    def load(self) -> None:
        if not self._lib_path or not os.path.exists(self._lib_path):
            raise FileNotFoundError(
                f"libloragw not found at {self._lib_path}. "
                "Build the patched SX1302 HAL first."
            )
        self._lib = ctypes.CDLL(self._lib_path)
        self._setup_function_signatures()
        logger.info("Loaded libloragw from %s", self._lib_path)

    def reset(self, gpio_pins: list[int] | None = None) -> None:
        """Toggle the concentrator reset pins (required before lgw_start).

        Different carrier boards route SX1302 reset to different GPIOs
        (pin 17 or 25 on every board confirmed so far). Both are toggled
        by default since asserting reset on an unconnected pin is
        harmless -- but on a board where NEITHER is the real reset line,
        that "harmless" default means this call is a no-op: the chip
        never actually resets, so whatever internal state a soft
        restart left it in persists, while a real reboot still "fixes"
        it (a fresh kernel/SPI/GPIO state recovers it by other means
        entirely, independent of this toggle ever hitting the right
        pin). If a board recovers reliably from `sudo reboot` but not
        from `systemctl restart meshpoint`, an unconfirmed reset pin
        (not reset timing) is the first thing to suspect.

        Override with the same ``RESET_GPIO`` environment variable
        ``scripts/reset_concentrator.sh``'s ExecStartPre/ExecStopPost
        already reads (space-separated GPIO numbers) so ONE setting
        drives both the systemd-level reset and this in-app fallback
        consistently -- setting it only for the shell script would
        leave this call still hitting the hardcoded [17, 25] right
        after, undoing any test of a different candidate pin.
        Delegated to systemd ExecStartPre for root access;
        this method is a best-effort fallback via pinctrl subprocess.

        On some RAK Hotspot V2 / RAK7248 carriers the reset timing is
        sensitive. You can increase the hold time with the environment
        variable CONCENTRATOR_RESET_HOLD_SEC (default: 0.1).
        """
        import subprocess
        import time

        if gpio_pins is None:
            env_pins = os.environ.get("RESET_GPIO")
            if env_pins:
                try:
                    gpio_pins = [int(p) for p in env_pins.split()]
                except ValueError:
                    logger.warning(
                        "RESET_GPIO=%r not parseable as space-separated "
                        "integers -- falling back to [17, 25]", env_pins,
                    )
                    gpio_pins = [17, 25]
            else:
                gpio_pins = [17, 25]

        hold = float(os.environ.get("CONCENTRATOR_RESET_HOLD_SEC", "0.1"))

        try:
            for pin in gpio_pins:
                subprocess.run(
                    ["pinctrl", "set", str(pin), "op", "dh"],
                    check=True, capture_output=True,
                )
            time.sleep(hold)
            for pin in gpio_pins:
                subprocess.run(
                    ["pinctrl", "set", str(pin), "op", "dl"],
                    check=True, capture_output=True,
                )
            time.sleep(hold)
            logger.info("Concentrator reset via pinctrl GPIO %s (hold=%.1fs)", gpio_pins, hold)
        except (OSError, subprocess.CalledProcessError):
            logger.warning(
                "In-app GPIO reset failed (pins %s) -- relying on systemd ExecStartPre",
                gpio_pins,
            )

    def configure(self, plan: ConcentratorChannelPlan) -> None:
        """Apply board, RF, and IF channel configuration before start."""
        if self._lib is None:
            self.load()

        self._configure_board()
        self._configure_rf_chains(plan)
        self._configure_if_channels(plan)
        self._configure_sx1261_for_spectral_scan()
        logger.info("Concentrator configured with %d IF channels",
                     len(plan.multi_sf_channels) + (1 if plan.single_sf_channel else 0))

    def start(self) -> None:
        if self._lib is None:
            self.load()
        result = self._lib.lgw_start()
        if result != LGW_HAL_SUCCESS:
            # If an SX1261 was staged as enabled (radio.sx1261_spi_path
            # set), it's the most likely cause: an enabled-but-unreachable
            # SX1261 makes the real Semtech HAL abort lgw_start() entirely
            # (RX/TX/relay included, not just spectral scan) -- see
            # loragw_hal.c's CONTEXT_SX1261.enable branch. The real
            # "ERROR: failed to patch sx1261..." line is easy to miss
            # buried above a long FastAPI lifespan traceback, so point at
            # the fix directly instead of a bare "lgw_start() failed".
            if self._sx1261_configured:
                raise RuntimeError(
                    "lgw_start() failed -- radio.sx1261_spi_path is set "
                    f"({self._sx1261_spi_path!r}) and is the most likely "
                    "cause (check the log above for an 'sx1261' error line). "
                    "This carrier's SX1261 may not be reachable at that "
                    "path even if the device node exists. Set "
                    "radio.sx1261_spi_path to \"\" in config/local.yaml and "
                    "restart to recover."
                )
            raise RuntimeError("lgw_start() failed")
        self._started = True
        logger.info("SX1302 concentrator started")

    def stop(self) -> None:
        if self._started and self._lib:
            self._lib.lgw_stop()
            self._started = False
            logger.info("SX1302 concentrator stopped")

    def receive(self) -> list[ConcentratorPacket]:
        """Poll for received packets. Non-blocking.

        lgw_receive returns the number of packets fetched (>= 0)
        or LGW_HAL_ERROR (-1) on failure. There is no third out-parameter.
        """
        if not self._started:
            return []

        pkt_array = (LgwPktRxS * LGW_PKT_MAX)()

        count = self._lib.lgw_receive(LGW_PKT_MAX, pkt_array)

        if count < 0:
            logger.warning("lgw_receive returned error (%d)", count)
            return []

        if count > 0:
            logger.info("lgw_receive returned %d packet(s)", count)

        packets = []
        for i in range(count):
            pkt = pkt_array[i]
            if pkt.size == 0:
                continue

            if pkt.status == STAT_CRC_BAD:
                self._crc_bad_count += 1
                logger.warning(
                    "RX CRC_BAD if=%d sf%d bw=%g rssi=%.1f snr=%.1f size=%d "
                    "(total CRC_BAD: %d)",
                    pkt.if_chain, pkt.datarate,
                    BW_MAP.get(pkt.bandwidth, pkt.bandwidth),
                    pkt.rssic, pkt.snr, pkt.size, self._crc_bad_count,
                )
                continue
            elif pkt.status == STAT_NO_CRC and (
                pkt.modulation == MOD_FSK or pkt.if_chain == LGW_MULTI_NB
            ):
                # Meshtastic's own channel (if_chain == LGW_MULTI_NB, ch8) and
                # FSK/pager traffic (ch9) are untouched here -- NEVER TOUCH
                # ch8/ch9 behavior, see project memory. On those, CRC is
                # always expected by spec/convention, so NO_CRC really is
                # noise-floor garbage, same as before.
                self._no_crc_count += 1
                logger.warning(
                    "RX NO_CRC if=%d sf%d bw=%g rssi=%.1f snr=%.1f size=%d "
                    "(total NO_CRC: %d)",
                    pkt.if_chain, pkt.datarate,
                    BW_MAP.get(pkt.bandwidth, pkt.bandwidth),
                    pkt.rssic, pkt.snr, pkt.size, self._no_crc_count,
                )
                continue
            elif pkt.status == STAT_NO_CRC:
                # Real LoRaWAN downlinks (Join-Accept, Data Down, ...) are
                # legitimately NO_CRC by spec -- LoRaWAN's PHY only puts a
                # CRC on uplinks, never downlinks, so this is what a genuine
                # downlink is *expected* to look like on ch0-ch7, not noise.
                # Falls through to normal packet construction below instead
                # of being dropped; crc_ok=False still records the status
                # honestly for whatever decodes it next.
                self._no_crc_count += 1
                logger.info(
                    "RX NO_CRC (real downlink, not noise) if=%d sf%d bw=%g "
                    "rssi=%.1f snr=%.1f size=%d",
                    pkt.if_chain, pkt.datarate,
                    BW_MAP.get(pkt.bandwidth, pkt.bandwidth),
                    pkt.rssic, pkt.snr, pkt.size,
                )
            elif pkt.status != STAT_CRC_OK:
                self._unknown_status_count += 1
                logger.warning(
                    "RX unknown status=0x%02X if=%d sf%d bw=%g rssi=%.1f "
                    "snr=%.1f size=%d (total unknown: %d)",
                    pkt.status, pkt.if_chain, pkt.datarate,
                    BW_MAP.get(pkt.bandwidth, pkt.bandwidth),
                    pkt.rssic, pkt.snr, pkt.size, self._unknown_status_count,
                )
                continue
            elif self._debug_rx:
                logger.info(
                    "RX if=%d sf%d bw=%g status=CRC_OK rssi=%.1f snr=%.1f size=%d",
                    pkt.if_chain, pkt.datarate,
                    BW_MAP.get(pkt.bandwidth, pkt.bandwidth),
                    pkt.rssic, pkt.snr, pkt.size,
                )

            # pkt.datarate is the same underlying C field for both
            # modulations (loragw_hal.h): 5-12 (a real spreading factor)
            # for LoRa, or the raw FSK bitrate in bps for FSK -- passed
            # through as-is either way; check .modulation to know which
            # meaning applies rather than assuming spreading_factor is
            # always a real SF.
            packets.append(
                ConcentratorPacket(
                    payload=bytes(pkt.payload[: pkt.size]),
                    frequency_hz=pkt.freq_hz,
                    rssi=pkt.rssic,
                    snr=pkt.snr,
                    spreading_factor=pkt.datarate,
                    bandwidth=pkt.bandwidth,
                    coderate=pkt.coderate,
                    crc_ok=(pkt.status == STAT_CRC_OK),
                    timestamp_us=pkt.count_us,
                    modulation="fsk" if pkt.modulation == MOD_FSK else "lora",
                )
            )

        return packets

    @property
    def crc_bad_count(self) -> int:
        """Total CRC_BAD packets seen since process start.

        CRC failures are typically caused by overlapping LoRa transmissions
        on the same demodulator (capture effect failure) or weak signals.
        """
        return self._crc_bad_count

    @property
    def no_crc_count(self) -> int:
        """Total NO_CRC packets seen since process start (dropped or not).

        NO_CRC indicates the chip received a packet but the LoRa header's
        CRC-present bit was off. On Meshtastic's own channel (ch8) and FSK
        (ch9/pager), CRC is always expected by spec/convention, so NO_CRC
        there really is noise-floor garbage -- still dropped, still counted
        here. On the LoRaWAN multi-SF channels (ch0-7) it's the opposite:
        real downlinks (Join-Accept, Data Down, ...) are *always* NO_CRC by
        spec (LoRaWAN's PHY CRC is an uplink-only feature) -- those are no
        longer dropped (see receive()), but still counted here since this
        property is "how many NO_CRC packets have we seen," not "how many
        did we drop."
        """
        return self._no_crc_count

    @property
    def unknown_status_count(self) -> int:
        """Total packets dropped due to a chip status code that is neither
        CRC_OK, CRC_BAD, nor NO_CRC.

        Catches any future HAL or chip-firmware quirk that introduces a new
        status code rather than silently treating it as valid.
        """
        return self._unknown_status_count

    def set_syncword(self, syncword: int) -> None:
        """Set the service-channel (ch8) sync word via direct register writes.

        With lorawan_public=True in board config, lgw_start() already programs
        ch0-ch7 (multi-SF) to LoRaWAN 0x34 (PEAK1=6, PEAK2=8).  This method
        overrides ONLY the service channel registers so ch8 uses the requested
        syncword — typically 0x2B for Meshtastic LongFast — leaving ch0-ch7
        untouched for LoRaWAN reception.

        PEAK values derived from the syncword byte nibbles:
          PEAK1 = 2 * (syncword >> 4)
          PEAK2 = 2 * (syncword & 0x0F)
        e.g. 0x2B → PEAK1=4, PEAK2=22   (Meshtastic)
             0x34 → PEAK1=6, PEAK2=8    (LoRaWAN public)
        """
        if self._lib is None:
            self.load()
        peak1 = ((syncword >> 4) & 0x0F) * 2
        peak2 = (syncword & 0x0F) * 2
        r1 = self._lib.lgw_reg_w(_REG_SERVICE_PEAK1, peak1)
        r2 = self._lib.lgw_reg_w(_REG_SERVICE_PEAK2, peak2)
        if r1 != LGW_HAL_SUCCESS or r2 != LGW_HAL_SUCCESS:
            logger.warning(
                "Failed to set service channel sync word 0x%02X (PEAK1=%d, PEAK2=%d)",
                syncword, peak1, peak2,
            )
        else:
            logger.info(
                "Service channel (ch8) sync word 0x%02X (PEAK1=%d, PEAK2=%d); "
                "ch0-ch7 remain on LoRaWAN 0x34",
                syncword, peak1, peak2,
            )

    def set_tx_syncword(self, syncword: int) -> None:
        """Override the TX LoRa sync word (e.g. 0x2B for Meshtastic).

        set_syncword() above only fixes RX: it programs the service-channel
        DEMODULATOR registers. The TX modulator is programmed per-send inside
        lgw_send(), where the stock HAL only knows LoRaWAN 0x34
        (lorawan_public=True, our board config) or private 0x12 — so every
        transmission went out with 0x34 and no Meshtastic radio (0x2B) could
        ever demodulate it, even though reception worked. Requires the
        sx1302_set_tx_syncword symbol from the patched HAL; on an older .so
        this logs a loud warning and TX stays Meshtastic-deaf rather than
        crashing.
        """
        if self._lib is None:
            self.load()
        try:
            fn = self._lib.sx1302_set_tx_syncword
        except AttributeError:
            logger.warning(
                "libloragw.so predates the TX sync word patch: concentrator "
                "TX keeps LoRaWAN sync word 0x34 and Meshtastic nodes will "
                "NOT receive anything it sends. Rebuild and reinstall the "
                "patched sx1302_hal (extra/sx1302_hal) to fix TX."
            )
            return
        result = fn(syncword)
        if result != LGW_HAL_SUCCESS:
            logger.warning("Failed to set TX sync word 0x%02X", syncword)
        else:
            logger.info(
                "TX sync word override 0x%02X active (SF7-SF12 transmissions)",
                syncword,
            )

    def configure_fsk_channel(
        self,
        rf_chain: int,
        rf_chain_freq_hz: int,
        frequency_hz: int,
        sync_word: int,
        sync_word_size: int = 2,
        datarate: int = FSK_DEFAULT_DATARATE,
        bandwidth: int = FSK_DEFAULT_BANDWIDTH,
    ) -> None:
        """Configure ch9, the dedicated FSK IF chain, for RX (call before
        start(), same as the main LoRa channel plan via configure()).

        Deliberately a standalone method rather than folded into
        ConcentratorChannelPlan/_configure_if_channels() -- ch9 is wholly
        independent hardware (own config context, own sync word; see the
        FSK_IF_CHAIN comment above) serving a different project (the
        emergency pager) with its own custom framing, not part of the
        Meshtastic/LoRaWAN channel plan those methods manage.

        Args:
            rf_chain: which RF chain (0 or 1) ch9 attaches to. Must land
                within that chain's own tuning window (its own multi-SF
                channels' frequencies +/- ~490 kHz) -- ch9 does not get
                its own separate RF front-end, only its own IF/demod.
            rf_chain_freq_hz: that RF chain's own center/anchor
                frequency (e.g. plan.radio_1_freq_hz), needed to compute
                the IF offset the same way _configure_if_channels() does
                for the main plan's channels.
            frequency_hz: the pager's absolute target frequency, e.g.
                869_462_500 (within the 869.4-869.65 MHz ETSI high-power
                sub-band, already covered by this fork's RF1 anchor at
                869.525 MHz -- no RF retuning needed for that specific
                choice).
            sync_word / sync_word_size: the pager's own FSK sync word,
                distinct from LoRaWAN's 0x34 and Meshtastic's 0x2B --
                this is what actually gives it real isolation, unlike
                the ch5-7 dead end explored earlier (those share ch0-7's
                one LoRaWAN sync-word register, no per-channel override
                exists in this HAL).
            datarate: FSK bitrate in bps (500-250,000 valid range).
            bandwidth: RX bandwidth; reuses BW_125/250/500KHZ (loragw_hal.h:
                "values available for the 'bandwidth' parameters (LoRa &
                FSK)"), not a separate FSK-specific enum.
        """
        if self._lib is None:
            self.load()
        if not (FSK_DATARATE_MIN <= datarate <= FSK_DATARATE_MAX):
            raise ValueError(
                f"FSK datarate {datarate} out of range "
                f"({FSK_DATARATE_MIN}-{FSK_DATARATE_MAX} bps)"
            )

        conf = LgwConfRxifS()
        conf.enable = True
        conf.rf_chain = rf_chain
        conf.freq_hz = frequency_hz - rf_chain_freq_hz
        conf.bandwidth = bandwidth
        conf.datarate = datarate
        conf.sync_word_size = sync_word_size
        conf.sync_word = sync_word

        result = self._lib.lgw_rxif_setconf(FSK_IF_CHAIN, ctypes.byref(conf))
        if result != LGW_HAL_SUCCESS:
            raise RuntimeError(
                f"lgw_rxif_setconf({FSK_IF_CHAIN}) failed for FSK channel"
            )
        logger.info(
            "FSK channel (ch%d) configured: %d Hz (IF %+d Hz from RF%d), "
            "%d bps, sync 0x%0*X",
            FSK_IF_CHAIN, frequency_hz, conf.freq_hz, rf_chain,
            datarate, sync_word_size * 2, sync_word,
        )

    # ── TX operations ───────────────────────────────────────────────

    def configure_tx_gain(
        self, rf_chain: int, lut_entries: list[dict]
    ) -> None:
        """Configure the TX gain look-up table (call before start).

        Each entry: {"rf_power": int, "pa_gain": int, "pwr_idx": int}
        """
        if self._lib is None:
            self.load()

        lut = LgwTxGainLutS()
        lut.size = min(len(lut_entries), 16)
        for i, entry in enumerate(lut_entries[: lut.size]):
            lut.lut[i].rf_power = entry["rf_power"]
            lut.lut[i].pa_gain = entry.get("pa_gain", 0)
            lut.lut[i].pwr_idx = entry.get("pwr_idx", 0)
            lut.lut[i].dig_gain = entry.get("dig_gain", 0)
            lut.lut[i].dac_gain = entry.get("dac_gain", 3)
            lut.lut[i].mix_gain = entry.get("mix_gain", 5)

        result = self._lib.lgw_txgain_setconf(rf_chain, ctypes.byref(lut))
        if result != LGW_HAL_SUCCESS:
            raise RuntimeError(
                f"lgw_txgain_setconf(rf_chain={rf_chain}) failed"
            )
        logger.info(
            "TX gain LUT configured: %d entries on RF chain %d",
            lut.size, rf_chain,
        )

    def send(self, tx_pkt: LgwPktTxS) -> int:
        """Schedule a packet for transmission via lgw_send.

        Returns LGW_HAL_SUCCESS (0) on success, negative on error.
        """
        if not self._started:
            raise RuntimeError("Concentrator not started, cannot transmit")

        result = self._lib.lgw_send(ctypes.byref(tx_pkt))
        if result != LGW_HAL_SUCCESS:
            logger.error("lgw_send failed (code %d)", result)
        else:
            # datarate is the same underlying C field for both modulations
            # (see receive()'s own comment) -- a real spreading factor for
            # LoRa, raw bps for FSK. "SF%d" is only meaningful for the
            # former; label it plainly for FSK instead of a fake "SFn".
            rate_label = (
                f"SF{tx_pkt.datarate}" if tx_pkt.modulation == MOD_LORA
                else f"{tx_pkt.datarate}bps"
            )
            logger.info(
                "TX queued: %d Hz, %s, %d bytes",
                tx_pkt.freq_hz, rate_label, tx_pkt.size,
            )
        return result

    def send_fsk_packet(
        self,
        payload: bytes,
        frequency_hz: int,
        rf_power_dbm: int,
        datarate: int = FSK_DEFAULT_DATARATE,
        f_dev_khz: int = FSK_DEFAULT_FDEV_KHZ,
        preamble: int = 0,
        no_crc: bool = False,
    ) -> int:
        """Build and send one FSK packet on ch9 (the pager project's channel).

        Always transmits on rf_chain=0, NOT whatever RF chain ch9 is
        configured to receive on (pager_rf_chain, typically 1) -- TX is
        only physically enabled on RF chain 0 on this hardware
        (_configure_rf_chains() sets tx_enable=(rf_chain==0); the native
        Meshtastic TX path hardcodes the same rf_chain=0 in
        tx_service.py's _build_hal_packet() even though Meshtastic's own
        channel is RF1's anchor). RF0's synthesizer can be tuned to any
        frequency in range regardless of which "RF chain" a receiver
        associates it with for demodulation -- the rf_chain field on a TX
        packet selects the physical PA path, not a frequency restriction.

        Requires configure_fsk_channel() to have already been called
        (i.e. pager_enabled at startup) -- the real HAL's lgw_send()
        reuses that same CONTEXT_FSK config (including its sync word) to
        build the FSK frame; there is no separate TX sync word parameter
        here, unlike LoRa's set_tx_syncword().

        Raises ValueError for an out-of-range datarate/f_dev/payload
        size (checked here so the caller gets a clear message instead of
        a bare lgw_send() failure). Returns LGW_HAL_SUCCESS (0) on
        success, negative on error (see send()).
        """
        if not (FSK_DATARATE_MIN <= datarate <= FSK_DATARATE_MAX):
            raise ValueError(
                f"FSK datarate {datarate} out of range "
                f"({FSK_DATARATE_MIN}-{FSK_DATARATE_MAX} bps)"
            )
        if not (1 <= f_dev_khz <= 200):
            raise ValueError(f"FSK f_dev_khz {f_dev_khz} out of range (1-200 kHz)")
        if len(payload) > 255:
            raise ValueError(f"FSK payload too long ({len(payload)} bytes, max 255)")

        tx_pkt = LgwPktTxS()
        tx_pkt.freq_hz = frequency_hz
        tx_pkt.tx_mode = TX_MODE_IMMEDIATE
        tx_pkt.count_us = 0
        tx_pkt.rf_chain = 0
        tx_pkt.rf_power = rf_power_dbm
        tx_pkt.modulation = MOD_FSK
        tx_pkt.freq_offset = 0
        # bandwidth is documented "LoRa only" for TX (loragw_hal.h) -- left
        # at its zero default, ignored by the HAL's FSK send validation.
        tx_pkt.datarate = datarate
        tx_pkt.f_dev = f_dev_khz
        tx_pkt.preamble = preamble
        tx_pkt.no_crc = no_crc
        tx_pkt.no_header = False  # variable-length (a length byte precedes payload)
        tx_pkt.size = len(payload)
        for i, b in enumerate(payload):
            tx_pkt.payload[i] = b

        return self.send(tx_pkt)

    def get_tx_status(self, rf_chain: int = 0) -> int:
        """Check TX status: TX_STATUS_FREE=2, TX_STATUS_EMITTING=4."""
        if self._lib is None:
            raise RuntimeError("Library not loaded")

        status = ctypes.c_uint8(0)
        self._lib.lgw_status(rf_chain, TX_STATUS, ctypes.byref(status))
        return status.value

    def abort_tx(self, rf_chain: int = 0) -> int:
        """Cancel a scheduled transmission."""
        if self._lib is None:
            raise RuntimeError("Library not loaded")
        return self._lib.lgw_abort_tx(rf_chain)

    def get_time_on_air(self, tx_pkt: LgwPktTxS) -> int:
        """Compute airtime in milliseconds for a TX packet."""
        if self._lib is None:
            raise RuntimeError("Library not loaded")
        return self._lib.lgw_time_on_air(ctypes.byref(tx_pkt))

    def run_spectral_scan(
        self,
        frequency_hz: int,
        nb_scan: int = 1024,
    ) -> Optional[SpectralScanResult]:
        """Run one spectral scan at the given frequency.

        Returns None if the HAL build does not expose spectral scan
        or if the scan failed for any reason. Caller is responsible
        for serialising scans (no concurrent calls on this wrapper).
        """
        if self._lib is None:
            self.load()
        if self._spectral_scan is None:
            self._spectral_scan = SX1302SpectralScan(self._lib)
        if not self._spectral_scan.supported:
            return None
        if not self._started:
            logger.debug("Skipping spectral scan: concentrator not started")
            return None
        return self._spectral_scan.run(frequency_hz, nb_scan=nb_scan)

    @property
    def spectral_scan_supported(self) -> bool:
        """True if the HAL supports spectral scan AND the SX1261 was
        successfully configured for it during ``configure()``."""
        if self._lib is None:
            try:
                self.load()
            except Exception:
                return False
        if self._spectral_scan is None:
            self._spectral_scan = SX1302SpectralScan(self._lib)
        return self._spectral_scan.supported and self._sx1261_configured

    # ── Private: HAL configuration ──────────────────────────────────

    def _configure_board(self) -> None:
        conf = LgwConfBoardS()
        conf.lorawan_public = True   # programs ch0-ch7 multi-SF to LoRaWAN 0x34 at lgw_start()
        conf.clksrc = 0
        conf.full_duplex = False
        conf.com_type = LGW_COM_SPI
        conf.com_path = self._spi_path.encode("ascii")

        result = self._lib.lgw_board_setconf(ctypes.byref(conf))
        if result != LGW_HAL_SUCCESS:
            raise RuntimeError("lgw_board_setconf() failed")
        logger.debug("Board configured (SPI=%s)", self._spi_path)

    def _configure_rf_chains(self, plan: ConcentratorChannelPlan) -> None:
        for rf_chain, freq_hz in enumerate([
            plan.radio_0_freq_hz,
            plan.radio_1_freq_hz,
        ]):
            conf = LgwConfRxrfS()
            conf.enable = True
            conf.freq_hz = freq_hz
            conf.rssi_offset = -215.4
            conf.type = LGW_RADIO_TYPE_SX1250
            conf.tx_enable = (rf_chain == 0)
            conf.single_input_mode = False

            result = self._lib.lgw_rxrf_setconf(rf_chain, ctypes.byref(conf))
            if result != LGW_HAL_SUCCESS:
                raise RuntimeError(f"lgw_rxrf_setconf({rf_chain}) failed")
            logger.debug("RF chain %d: %d Hz", rf_chain, freq_hz)

    def _configure_if_channels(self, plan: ConcentratorChannelPlan) -> None:
        radio_0_freq = plan.radio_0_freq_hz

        for i, ch in enumerate(plan.multi_sf_channels[:LGW_MULTI_NB]):
            conf = LgwConfRxifS()
            conf.enable = ch.enabled
            conf.rf_chain = 0 if ch.frequency_hz <= radio_0_freq + 500_000 else 1
            center = radio_0_freq if conf.rf_chain == 0 else plan.radio_1_freq_hz
            conf.freq_hz = ch.frequency_hz - center

            result = self._lib.lgw_rxif_setconf(i, ctypes.byref(conf))
            if result != LGW_HAL_SUCCESS:
                raise RuntimeError(f"lgw_rxif_setconf({i}) failed")

        if plan.single_sf_channel:
            ch = plan.single_sf_channel
            conf = LgwConfRxifS()
            conf.enable = ch.enabled
            conf.rf_chain = 0 if ch.frequency_hz <= radio_0_freq + 500_000 else 1
            center = radio_0_freq if conf.rf_chain == 0 else plan.radio_1_freq_hz
            conf.freq_hz = ch.frequency_hz - center
            conf.bandwidth = BW_KHZ_TO_HAL.get(ch.bandwidth_khz, BW_250KHZ)
            conf.datarate = ch.spreading_factor

            result = self._lib.lgw_rxif_setconf(LGW_MULTI_NB, ctypes.byref(conf))
            if result != LGW_HAL_SUCCESS:
                raise RuntimeError(f"lgw_rxif_setconf({LGW_MULTI_NB}) failed")

    def _configure_sx1261_for_spectral_scan(self) -> None:
        """Enable the SX1261 companion radio so spectral scan works.

        The Semtech HAL gates ``lgw_spectral_scan_*`` on the SX1261
        being explicitly enabled via ``lgw_sx1261_setconf``. Without
        this, every scan attempt returns -1 with the HAL stderr line
        ``ERROR: sx1261 is not enabled, no spectral scan``.

        Best-effort and safety-first: if anything in this routine
        fails — missing symbol, wrong SPI path, struct-layout
        mismatch in our patched HAL, or the call itself returning
        non-zero — we log loudly and return without raising. Every
        other concentrator path (RX, TX, native relay) must keep
        working even if spectral scan is unavailable.
        """
        if self._sx1261_spi_path is None or self._sx1261_spi_path == "":
            logger.info(
                "SX1261 spi_path empty; spectral scan disabled, "
                "falling back to packet-derived noise floor",
            )
            return
        if not hasattr(self._lib, "lgw_sx1261_setconf"):
            logger.info(
                "libloragw lacks lgw_sx1261_setconf; "
                "spectral scan unavailable",
            )
            return

        try:
            conf = LgwConfSx1261S()
            conf.enable = True
            conf.spi_path = self._sx1261_spi_path.encode("ascii")
            conf.rssi_offset = 0
            conf.lbt_conf.enable = False
            conf.lbt_conf.rssi_target = 0
            conf.lbt_conf.nb_channel = 0
            rc = self._lib.lgw_sx1261_setconf(ctypes.byref(conf))
        except BaseException as exc:
            logger.warning(
                "lgw_sx1261_setconf raised (%s: %s); "
                "spectral scan disabled, falling back to packet-derived noise floor",
                type(exc).__name__, exc,
            )
            return

        if rc != LGW_HAL_SUCCESS:
            logger.warning(
                "lgw_sx1261_setconf(spi=%s) failed (rc=%d); "
                "spectral scan disabled, falling back to packet-derived noise floor",
                self._sx1261_spi_path, rc,
            )
            return

        self._sx1261_configured = True
        logger.info(
            "SX1261 companion configured for spectral scan (spi=%s)",
            self._sx1261_spi_path,
        )

    def _setup_function_signatures(self) -> None:
        apply_signatures(self._lib)

    @staticmethod
    def _find_library() -> str:
        candidates = [
            "/usr/local/lib/libloragw.so",
            "/usr/lib/libloragw.so",
            "./libloragw.so",
            "../sx1302_hal/libloragw/libloragw.so",
        ]
        for path in candidates:
            if os.path.exists(path):
                return path
        return candidates[0]
