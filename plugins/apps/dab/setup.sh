#!/usr/bin/env bash
#
# DAB+ plugin dependency: welle.io, via apt.
#
# The Debian/Raspberry Pi OS `welle.io` package ships both the GUI app
# and the headless `welle-cli` binary this plugin actually drives
# (backend/listener.py spawns `welle-cli -c <channel> -w <port>` and
# talks to its embedded webserver) -- confirmed live on real hardware,
# not assumed. --no-install-recommends skips the Qt/QML GUI dependency
# chain that only the GUI app needs (~87 MB installed otherwise);
# welle-cli itself has no GUI dependencies.
#
# Idempotent: skips the apt install if welle-cli is already on PATH.
#
# Run once, with the same privileges as install.sh (needs apt):
#     sudo bash plugins/apps/dab/setup.sh
set -euo pipefail

if command -v welle-cli &>/dev/null; then
    echo "welle.io (welle-cli) already installed ($(command -v welle-cli)) -- nothing to do"
    exit 0
fi

echo "Installing welle.io (DAB+) ..."
apt-get install -y -qq --no-install-recommends welle.io

echo "welle.io installed. Enable the plugin with:"
echo "  plugins:"
echo "    dab:"
echo "      enabled: true"
