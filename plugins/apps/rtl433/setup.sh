#!/usr/bin/env bash
#
# RTL433 plugin dependency: rtl_433, via apt.
#
# The Raspberry Pi OS `rtl-433` package is small (~500 KB) and current
# enough for this -- no from-source build needed (unlike acarsdec/libacars
# in plugins/apps/acars/setup.sh). --no-install-recommends skips the
# optional soapysdr module packages, which nothing here uses.
#
# Idempotent: skips the apt install if the rtl_433 binary already exists.
#
# Run once, with the same privileges as install.sh (needs apt):
#     sudo bash plugins/apps/rtl433/setup.sh
set -euo pipefail

if command -v rtl_433 &>/dev/null; then
    echo "rtl_433 already installed ($(command -v rtl_433)) -- nothing to do"
    exit 0
fi

echo "Installing rtl_433 ..."
apt-get install -y -qq --no-install-recommends rtl-433

echo "rtl_433 installed. Enable the plugin with:"
echo "  plugins:"
echo "    rtl433:"
echo "      enabled: true"
