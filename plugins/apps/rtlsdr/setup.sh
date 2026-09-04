#!/usr/bin/env bash
#
# RTL-SDR plugin dependency: librtlsdr + kernel DVB-T blacklist.
#
# Every RTL-SDR plugin (Radio, DAB+, P2000, Pagers, POCSAG, RTL433, ADS-B,
# ACARS) talks to the dongle through this shared userspace library --
# this is the one genuinely shared, hardware-level setup step all of them
# depend on, which is why it lives here (the host page) rather than in
# any one of those plugins' own setup.sh. Used to live in
# scripts/install.sh's own RTL-SDR section, moved here once every
# RTL-SDR plugin (Radio included) had migrated off the built-in Listener
# page onto this one -- see plugins/apps/rtlsdr/README.md for that
# history.
#
# Two things a stock Raspberry Pi OS image is missing for an RTL-SDR
# dongle to work: the kernel's own DVB driver claims the RTL2832U chip
# before rtl-sdr's userspace tools can open it, and there's no rtl-sdr
# package installed at all. Built from source (osmocom upstream) rather
# than `apt install rtl-sdr`, matching what a from-source install lets
# you swap in a vendor fork later (e.g. RTL-SDR Blog's own fork for
# their V4/R828D dongle) without an apt package fighting it.
#
# Idempotent: skips the kernel blacklist if already present, skips the
# clone+build if librtlsdr is already installed.
#
# Run once, with the same privileges as install.sh (needs apt + build
# tools -- already installed by scripts/install.sh's own base packages):
#     sudo bash plugins/apps/rtlsdr/setup.sh
set -euo pipefail

RTLSDR_BUILD_DIR="/opt/rtl-sdr"
DVB_BLACKLIST_FILE="/etc/modprobe.d/blacklist-rtlsdr-dvb.conf"

echo "Blacklisting the kernel DVB-T stack (conflicts with rtl-sdr userspace tools)..."
if [ -f "$DVB_BLACKLIST_FILE" ] && grep -q '^blacklist dvb_usb_rtl28xxu' "$DVB_BLACKLIST_FILE"; then
    echo "DVB-T stack already blacklisted"
else
    cat > "$DVB_BLACKLIST_FILE" <<'_DVB_BLACKLIST'
# Managed by the rtlsdr plugin's setup.sh. The kernel's DVB-T driver
# stack (usb bridge + demodulator + tuner-support modules) claims the
# RTL2832U chip on boot, which then can't be opened by rtl-sdr's own
# userspace driver (rtl_fm, rtl_test, etc). Re-run this script to
# restore this file if removed.
blacklist dvb_usb_rtl28xxu
blacklist rtl_2832
blacklist rtl_2830
_DVB_BLACKLIST
fi
# Also unload them right now if a dongle was already plugged in this
# boot -- the blacklist file alone only takes effect on the NEXT boot.
# Unload order matters: the usb bridge module depends on the
# demodulator modules, so it must go first or -r fails with "in use".
modprobe -r dvb_usb_rtl28xxu 2>/dev/null || true
modprobe -r rtl_2832 2>/dev/null || true
modprobe -r rtl_2830 2>/dev/null || true

if command -v rtl_sdr &>/dev/null; then
    echo "librtlsdr already installed ($(command -v rtl_sdr)) -- skipping build"
else
    echo "Cloning and building rtl-sdr..."
    rm -rf "$RTLSDR_BUILD_DIR"
    git clone --depth 1 git://git.osmocom.org/rtl-sdr.git "$RTLSDR_BUILD_DIR"
    mkdir -p "${RTLSDR_BUILD_DIR}/build"
    (
        cd "${RTLSDR_BUILD_DIR}/build"
        cmake ../ -DINSTALL_UDEV_RULES=ON
        make -j"$(nproc)"
        make install
        ldconfig
    )
fi

echo "librtlsdr installed. Enable the plugin with:"
echo "  plugins:"
echo "    rtlsdr:"
echo "      enabled: true"
