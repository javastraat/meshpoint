#!/usr/bin/env bash
#
# Radio plugin dependency: redsea (RDS decoder), via source build.
#
# rtl_fm and ffmpeg (the plugin's own demodulation + MP3 encode pipeline)
# come from the shared librtlsdr build + base system packages -- see
# plugins/apps/rtlsdr/setup.sh and its own README for why that's a
# separate, shared step every RTL-SDR plugin depends on, not this one.
#
# redsea decodes RDS (station name, RadioText, PI code, block error rate)
# out of the FM broadcast capture -- Radio-specific, not shared with any
# other plugin, so it lives here rather than in the shared rtlsdr setup.
# Built from source (windytan/redsea upstream) via meson: no distro
# package tracks upstream closely enough. Without it, the Radio tab still
# works -- the RDS pills in the Digital/Analogue skins just stay hidden.
#
# Idempotent: skips the clone+build if the redsea binary already exists.
#
# Run once, with the same privileges as install.sh (needs apt + build
# tools -- already installed by scripts/install.sh's own base packages):
#     sudo bash plugins/apps/radio/setup.sh
set -euo pipefail

REDSEA_BUILD_DIR="/opt/redsea"

if command -v redsea &>/dev/null; then
    echo "redsea already installed ($(command -v redsea)) -- nothing to do"
    exit 0
fi

echo "Cloning and building redsea..."
rm -rf "$REDSEA_BUILD_DIR"
git clone --depth 1 https://github.com/windytan/redsea.git "$REDSEA_BUILD_DIR"
(
    cd "$REDSEA_BUILD_DIR"
    meson setup build
    cd build
    meson compile
    meson install
    ldconfig
)

echo "redsea installed. Enable the plugin with:"
echo "  plugins:"
echo "    radio:"
echo "      enabled: true"
