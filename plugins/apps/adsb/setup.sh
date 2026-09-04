#!/usr/bin/env bash
#
# ADS-B plugin dependency: dump1090, built from source.
#
#   * MalcolmRobb/dump1090 fork -- adds interactive mode and network output
#     on top of the original antirez/dump1090. Not packaged in Debian/
#     Raspberry Pi OS.
#   * Upstream's Makefile has no `install` target, so the binaries are
#     copied to /usr/local/bin by hand after the build.
#   * EXTRACFLAGS=-fcommon works around this 2016-era codebase's tentative
#     global definitions (Modes, tDF, etc. declared without `extern` in
#     dump1090.h) hitting multiple-definition link errors under GCC 10+,
#     which defaults to -fno-common.
#
# Builds on the librtlsdr that scripts/install.sh's RTL-SDR section already
# installs. Idempotent: skips the clone + build if `dump1090` is on PATH.
#
# Run once, with the same privileges as install.sh (needs make install):
#     sudo bash plugins/apps/adsb/setup.sh
set -euo pipefail

if command -v dump1090 &>/dev/null; then
    echo "dump1090 already installed ($(command -v dump1090)) -- nothing to do"
    exit 0
fi

echo "Cloning and building dump1090 ..."
DUMP1090_BUILD_DIR="/opt/dump1090"
rm -rf "$DUMP1090_BUILD_DIR"
git clone --depth 1 https://github.com/MalcolmRobb/dump1090.git "$DUMP1090_BUILD_DIR"
(
    cd "$DUMP1090_BUILD_DIR"
    make -j"$(nproc)" EXTRACFLAGS=-fcommon
    install -m 755 dump1090 view1090 /usr/local/bin/
)

echo "dump1090 installed. Enable the plugin with:"
echo "  plugins:"
echo "    adsb:"
echo "      enabled: true"
