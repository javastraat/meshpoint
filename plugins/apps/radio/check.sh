#!/usr/bin/env bash
#
# Radio plugin dependency check.
#
# Unprivileged probe run by meshpoint at boot (and on demand from
# Settings -> Plugins).
#
#   exit 0        -- deps satisfied
#   exit non-zero -- setup needed; stdout says what's missing
#
# setup.sh only builds `redsea` (RDS decoder). `rtl_fm` comes from the
# shared rtlsdr plugin, `ffmpeg` from the base system packages -- both
# reported here too since the Radio tab can't stream audio without them,
# but neither is this setup.sh's job to install.
#
# No sudo: `command -v` needs no privileges.
set -uo pipefail

missing=()

command -v redsea &>/dev/null \
    || missing+=("redsea not built -- RDS station-name/RadioText decoding unavailable (Radio otherwise works); setup.sh builds it")
command -v rtl_fm &>/dev/null \
    || missing+=("rtl_fm not found -- run the rtlsdr plugin's setup first")
command -v ffmpeg &>/dev/null \
    || missing+=("ffmpeg not found -- 'sudo apt install ffmpeg'")

if [ "${#missing[@]}" -eq 0 ]; then
    echo "redsea, rtl_fm and ffmpeg all present"
    exit 0
fi

printf '%s\n' "${missing[@]}"
echo "run: sudo meshpoint plugin setup radio"
exit 1
