#!/usr/bin/env bash
#
# RTL-SDR plugin dependency setup -- currently a no-op.
#
# This plugin is a staging ground for the RTL-SDR host page (the sidebar
# page other RTL-SDR plugins will eventually hook their own content into,
# replacing the built-in Listener page's tabbar). It doesn't drive any
# hardware itself yet, so there's nothing to install.
#
# The real RTL-SDR dongle support (librtlsdr build from source, kernel DVB
# blacklist) still lives in scripts/install.sh's own RTL-SDR section for
# now -- every RTL-SDR plugin (P2000, Pagers, POCSAG, RTL433, ADS-B, ACARS,
# DAB+) still depends on that, not on this plugin being enabled. Once this
# page becomes the real host, that install step moves here.
#
# Run once, with the same privileges as install.sh (no-op today, kept for
# the pattern every plugin's setup.sh follows):
#     sudo bash plugins/apps/rtlsdr/setup.sh
set -euo pipefail

echo "rtlsdr plugin: nothing to install yet -- enable it with:"
echo "  plugins:"
echo "    rtlsdr:"
echo "      enabled: true"
