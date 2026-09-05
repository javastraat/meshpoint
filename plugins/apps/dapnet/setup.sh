#!/usr/bin/env bash
#
# DAPNET plugin dependencies.
#
# The capture side (pyserial) is already pulled in transitively by the
# meshtastic/meshcore packages requirements.txt already installs -- nothing
# extra to build or apt-install here.
#
# Firmware compile/flash for pocsag_companion (the companion board's
# own sketch) uses the SAME shared arduino-cli + ESP32 toolchain the
# Meshtastic/MeshCore companion flashing already depends on
# (scripts/install.sh's own "Install arduino-cli + ESP32 toolchain"
# section) -- not a per-plugin build, so this script only checks it's
# there rather than installing it itself.
#
# Run once, with the same privileges as install.sh:
#     sudo bash plugins/apps/dapnet/setup.sh
set -euo pipefail

if command -v arduino-cli &>/dev/null; then
    echo "arduino-cli already installed ($(command -v arduino-cli)) -- firmware compile/flash ready"
else
    echo "arduino-cli not found -- Configuration -> Firmware's POCSAG companion"
    echo "compile/flash card won't work until it's installed. Re-run"
    echo "scripts/install.sh (its arduino-cli/ESP32 toolchain section) to add it."
fi

echo "Nothing else to install. Enable the plugin with:"
echo "  plugins:"
echo "    dapnet:"
echo "      enabled: true"
