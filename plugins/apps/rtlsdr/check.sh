#!/usr/bin/env bash
#
# RTL-SDR host-plugin dependency check.
#
# Unprivileged probe run by meshpoint at boot (and on demand from
# Settings -> Plugins). Mirrors setup.sh's two idempotency checks:
#   1. librtlsdr built + installed (rtl_sdr / rtl_fm on PATH)
#   2. the kernel DVB-T stack blacklisted, so it doesn't claim the dongle
#
#   exit 0        -- both in place
#   exit non-zero -- setup needed; stdout says which
#
# No sudo: `command -v` and reading /etc/modprobe.d both work unprivileged.
set -uo pipefail

DVB_BLACKLIST_FILE="/etc/modprobe.d/blacklist-rtlsdr-dvb.conf"
missing=()

command -v rtl_sdr &>/dev/null \
    || missing+=("librtlsdr is not installed (rtl_sdr/rtl_fm -- built from source by setup.sh)")

if ! { [ -f "${DVB_BLACKLIST_FILE}" ] && grep -q '^blacklist dvb_usb_rtl28xxu' "${DVB_BLACKLIST_FILE}"; }; then
    missing+=("kernel DVB-T stack not blacklisted (${DVB_BLACKLIST_FILE}) -- it will claim the dongle on boot")
fi

if [ "${#missing[@]}" -eq 0 ]; then
    echo "librtlsdr installed; DVB-T stack blacklisted"
    exit 0
fi

printf '%s\n' "${missing[@]}"
echo "run: sudo meshpoint plugin setup rtlsdr"
exit 1
