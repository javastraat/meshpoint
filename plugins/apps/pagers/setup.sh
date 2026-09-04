#!/usr/bin/env bash
#
# Pagers plugin dependency: multimon-ng, built from source.
#
#   * EliasOenal/multimon-ng -- decodes POCSAG512/1200/2400 out of
#     demodulated audio piped in from rtl_fm. Built via CMake -- the
#     project dropped its old qt4-qmake build system entirely, so no Qt4
#     packages are needed.
#   * Its own build deps (cmake, libpulse-dev, libx11-dev) are already
#     covered by scripts/install.sh's base system-package install, so
#     nothing extra to apt-get here.
#
# Unlike when this plugin's P2000/POCSAG siblings were split out, Pagers
# is the LAST of the three former pager kinds still needing this binary
# -- scripts/install.sh no longer builds multimon-ng at all once Pagers
# itself is a plugin, so this setup.sh is the one that actually does the
# work now (P2000's/POCSAG's copies of this same script remain in place
# too, each independently idempotent, for whichever of the three you
# enable first).
#
# Idempotent: skips the clone + build if multimon-ng is already on PATH.
#
# Run once, with the same privileges as install.sh (needs make install):
#     sudo bash plugins/apps/pagers/setup.sh
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
echo "    pagers:"
echo "      enabled: true"
