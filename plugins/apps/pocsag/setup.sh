#!/usr/bin/env bash
#
# POCSAG plugin dependency: multimon-ng, built from source.
#
#   * EliasOenal/multimon-ng -- decodes POCSAG512/1200/2400 out of
#     demodulated audio piped in from rtl_fm. Built via CMake -- the
#     project dropped its old qt4-qmake build system entirely, so no Qt4
#     packages are needed.
#   * Its own build deps (cmake, libpulse-dev, libx11-dev) are already
#     covered by scripts/install.sh's base system-package install, so
#     nothing extra to apt-get here.
#
# NOTE: Pagers (still built into core, not yet a plugin) uses this exact
# same multimon-ng binary -- scripts/install.sh already builds it
# unconditionally as part of RTL-SDR setup, so on a normal Pi install
# this script is a no-op. It stays self-contained anyway so the POCSAG
# plugin doesn't silently depend on Pagers still being core.
#
# Idempotent: skips the clone + build if multimon-ng is already on PATH.
#
# Run once, with the same privileges as install.sh (needs make install):
#     sudo bash plugins/apps/pocsag/setup.sh
set -euo pipefail

if command -v multimon-ng &>/dev/null; then
    echo "multimon-ng already installed ($(command -v multimon-ng)) -- nothing to do"
    exit 0
fi

echo "Cloning and building multimon-ng ..."
MULTIMON_BUILD_DIR="/opt/multimon-ng"
rm -rf "$MULTIMON_BUILD_DIR"
git clone --depth 1 https://github.com/EliasOenal/multimon-ng.git "$MULTIMON_BUILD_DIR"
(
    cd "$MULTIMON_BUILD_DIR"
    cmake -S . -B build
    cmake --build build --parallel "$(nproc)"
    cmake --install build
    ldconfig
)

echo "multimon-ng installed. Enable the plugin with:"
echo "  plugins:"
echo "    pocsag:"
echo "      enabled: true"
