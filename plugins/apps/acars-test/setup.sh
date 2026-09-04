#!/usr/bin/env bash
#
# ACARS plugin dependencies: acarsdec + libacars, both from source.
#
#   * f00b4r0/acarsdec -- the maintained fork (TLeconte/acarsdec was
#     archived in 2025 and its RTL code stalls with "No data from the SDR").
#     Needs libcjson (json output) + libacars (decode standard message
#     types) + libsndfile (build dep).
#   * szpajder/libacars 2.x -- not packaged for Debian; expands
#     CPDLC / ADS-C / media-advisory / ARINC formats to plain text.
#
# Builds on the librtlsdr that scripts/install.sh's RTL-SDR section already
# installs. Idempotent: skips the clone + build if `acarsdec` is on PATH.
#
# Run once, with the same privileges as install.sh (needs apt + make install):
#     sudo bash plugins/apps/acars/setup.sh
set -euo pipefail

if command -v acarsdec &>/dev/null; then
    echo "acarsdec already installed ($(command -v acarsdec)) -- nothing to do"
    exit 0
fi

echo "Installing acarsdec + libacars ..."
apt-get install -y -qq --no-install-recommends \
    cmake pkg-config libcjson-dev zlib1g-dev libxml2-dev libsndfile1-dev

rm -rf /opt/libacars
git clone --depth 1 https://github.com/szpajder/libacars.git /opt/libacars
(
    cd /opt/libacars
    mkdir -p build && cd build
    cmake .. -DCMAKE_BUILD_TYPE=Release
    make -j"$(nproc)"
    make install
)
ldconfig

rm -rf /opt/acarsdec
git clone --depth 1 https://github.com/f00b4r0/acarsdec.git /opt/acarsdec
(
    cd /opt/acarsdec
    mkdir -p build && cd build
    cmake .. -DCMAKE_C_FLAGS="-O2"
    make -j"$(nproc)"
    make install
)
ldconfig

echo "acarsdec installed. Enable the plugin with:"
echo "  plugins:"
echo "    acars:"
echo "      enabled: true"
