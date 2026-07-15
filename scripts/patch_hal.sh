#!/usr/bin/env bash
#
# Patch and recompile the SX1302 HAL for TX sync word support.
#
# The stock HAL hardcodes TX sync words to LoRaWAN values (0x12/0x34):
# the TX modulator registers are programmed per-send inside lgw_send(),
# and 0x2B (Meshtastic) does not exist on that path at all. RX-side 0x2B
# is handled separately (direct service-channel demodulator register
# writes from the Python wrapper after lgw_start()), which is why the
# concentrator could always HEAR Meshtastic nodes while nothing it
# transmitted was ever demodulated by them.
#
# This patch adds an exported sx1302_set_tx_syncword() override that the
# Python wrapper calls at startup with the same sync word as RX. It
# replaces an earlier version of this patch (static peaks captured
# inside sx1302_lora_syncword()) that silently stopped working when
# lorawan_public=True became the board default for LoRaWAN capture:
# lgw_start() calls sx1302_lora_syncword(public=true), so the captured
# peaks were always LoRaWAN 0x34, never 0x2B. If the old patch is
# present, the stock source is restored from git before re-patching.
#
# Run once after updating to enable Meshtastic TX. Idempotent.
# Requires HAL source at /opt/sx1302_hal (preserved from install.sh).
#
# Usage:
#   sudo /opt/meshpoint/scripts/patch_hal.sh
#

set -euo pipefail

HAL_SRC="/opt/sx1302_hal/libloragw/src/loragw_sx1302.c"
HAL_DIR="/opt/sx1302_hal"
LIB_DEST="/usr/local/lib/libloragw.so"

info()  { echo "[patch_hal] $*"; }
fail()  { echo "[patch_hal] ERROR: $*" >&2; exit 1; }

if [ "$(id -u)" -ne 0 ]; then
    fail "Must run as root (sudo)"
fi

if [ ! -f "$HAL_SRC" ]; then
    fail "HAL source not found at $HAL_SRC. Run install.sh for a fresh build."
fi

if grep -q "sx1302_set_tx_syncword" "$HAL_SRC"; then
    info "TX sync word override patch already applied"
else
    if grep -q "sx1302_tx_sw_peak1" "$HAL_SRC"; then
        info "Old (ineffective with lorawan_public=True) TX patch detected;"
        info "restoring stock source from git before re-patching..."
        git -C "$HAL_DIR" checkout -- libloragw/src/loragw_sx1302.c \
            || fail "Could not restore stock loragw_sx1302.c from git"
    fi
    info "Applying TX sync word override patch..."
    python3 - "$HAL_SRC" <<'TXPATCH'
import sys
from pathlib import Path

f = Path(sys.argv[1])
s = f.read_text()

SETTER = """\
/* TX LoRa sync word override (Meshpoint patch).

   Stock sx1302_send() can only transmit two sync words: 0x12 (private,
   lwan_public==false) or 0x34 (LoRaWAN public). Meshtastic radios use
   0x2B, which the stock HAL cannot produce -- RX-side 0x2B reception is
   handled separately via the service-channel demodulator registers, so
   without this patch the concentrator can hear Meshtastic nodes but
   nothing it transmits is ever demodulated by them.

   When >= 0, the value is used as the TX sync word for SF7-SF12 LoRa
   transmissions (PEAK1 = 2*(sw>>4), PEAK2 = 2*(sw&0xF), same nibble
   derivation as sx1302_lora_syncword's RX side). SF5/SF6 keep the fixed
   0x12 sync word their fine-sync path requires, matching stock behavior.
   -1 (default) disables the override entirely. */
static int16_t tx_syncword_override = -1;

int sx1302_set_tx_syncword(int16_t syncword) {
    if (syncword > 0xFF) {
        return LGW_REG_ERROR;
    }
    tx_syncword_override = syncword;
    return LGW_REG_SUCCESS;
}

"""

ANCHOR = "int sx1302_send(lgw_radio_type_t"
if s.count(ANCHOR) != 1:
    print("FAIL: sx1302_send anchor not found exactly once")
    sys.exit(1)
s = s.replace(ANCHOR, SETTER + ANCHOR, 1)

STOCK = """\
            /* Syncword */
            if ((lwan_public == false) || (pkt_data->datarate == DR_LORA_SF5) || (pkt_data->datarate == DR_LORA_SF6)) {
                DEBUG_MSG("Setting LoRa syncword 0x12\\n");
                err = lgw_reg_w(SX1302_REG_TX_TOP_FRAME_SYNCH_0_PEAK1_POS(pkt_data->rf_chain), 2);
                CHECK_ERR(err);
                err = lgw_reg_w(SX1302_REG_TX_TOP_FRAME_SYNCH_1_PEAK2_POS(pkt_data->rf_chain), 4);
                CHECK_ERR(err);
            } else {
                DEBUG_MSG("Setting LoRa syncword 0x34\\n");
                err = lgw_reg_w(SX1302_REG_TX_TOP_FRAME_SYNCH_0_PEAK1_POS(pkt_data->rf_chain), 6);
                CHECK_ERR(err);
                err = lgw_reg_w(SX1302_REG_TX_TOP_FRAME_SYNCH_1_PEAK2_POS(pkt_data->rf_chain), 8);
                CHECK_ERR(err);
            }
"""

NEW = """\
            /* Syncword */
            if ((pkt_data->datarate == DR_LORA_SF5) || (pkt_data->datarate == DR_LORA_SF6)) {
                DEBUG_MSG("Setting LoRa syncword 0x12\\n");
                err = lgw_reg_w(SX1302_REG_TX_TOP_FRAME_SYNCH_0_PEAK1_POS(pkt_data->rf_chain), 2);
                CHECK_ERR(err);
                err = lgw_reg_w(SX1302_REG_TX_TOP_FRAME_SYNCH_1_PEAK2_POS(pkt_data->rf_chain), 4);
                CHECK_ERR(err);
            } else if (tx_syncword_override >= 0) {
                DEBUG_PRINTF("Setting LoRa syncword override 0x%02X\\n", tx_syncword_override);
                err = lgw_reg_w(SX1302_REG_TX_TOP_FRAME_SYNCH_0_PEAK1_POS(pkt_data->rf_chain), ((tx_syncword_override >> 4) & 0x0F) * 2);
                CHECK_ERR(err);
                err = lgw_reg_w(SX1302_REG_TX_TOP_FRAME_SYNCH_1_PEAK2_POS(pkt_data->rf_chain), (tx_syncword_override & 0x0F) * 2);
                CHECK_ERR(err);
            } else if (lwan_public == false) {
                DEBUG_MSG("Setting LoRa syncword 0x12\\n");
                err = lgw_reg_w(SX1302_REG_TX_TOP_FRAME_SYNCH_0_PEAK1_POS(pkt_data->rf_chain), 2);
                CHECK_ERR(err);
                err = lgw_reg_w(SX1302_REG_TX_TOP_FRAME_SYNCH_1_PEAK2_POS(pkt_data->rf_chain), 4);
                CHECK_ERR(err);
            } else {
                DEBUG_MSG("Setting LoRa syncword 0x34\\n");
                err = lgw_reg_w(SX1302_REG_TX_TOP_FRAME_SYNCH_0_PEAK1_POS(pkt_data->rf_chain), 6);
                CHECK_ERR(err);
                err = lgw_reg_w(SX1302_REG_TX_TOP_FRAME_SYNCH_1_PEAK2_POS(pkt_data->rf_chain), 8);
                CHECK_ERR(err);
            }
"""

if STOCK not in s:
    print("FAIL: stock TX syncword block not found (HAL version mismatch?)")
    sys.exit(1)
s = s.replace(STOCK, NEW, 1)

f.write_text(s)
print("OK: TX sync word override patch applied")
TXPATCH
fi

info "Compiling libloragw (this takes a few minutes)..."
cd "$HAL_DIR"
mkdir -p pic_obj

for src in libtools/src/*.c; do
    gcc -c -O2 -fPIC -Wall -Wextra -std=c99 \
        -Ilibtools/inc -Ilibtools \
        "$src" -o "pic_obj/$(basename "${src%.c}.o")"
done

for src in libloragw/src/*.c; do
    gcc -c -O2 -fPIC -Wall -Wextra -std=c99 \
        -Ilibloragw/inc -Ilibloragw -Ilibtools/inc \
        "$src" -o "pic_obj/$(basename "${src%.c}.o")"
done

gcc -shared -o libloragw/libloragw.so pic_obj/*.o -lrt -lm -lpthread

cp libloragw/libloragw.so "$LIB_DEST"
ldconfig

if [ "${MESHPOINT_INSTALL_IN_PROGRESS:-}" = "1" ]; then
    # Called as a substep of install.sh, which has more sections left to
    # run and prints its own single, correctly-timed restart prompt at
    # the very end -- suggesting a restart here would be premature, and
    # if acted on immediately would kill this install run (see
    # install.sh's call site for why: web Terminal PTYs live in
    # meshpoint's own systemd cgroup, so a mid-install restart kills the
    # PTY along with everything left to install).
    info "Done."
else
    info "Done. Restart meshpoint: sudo systemctl restart meshpoint"
fi
