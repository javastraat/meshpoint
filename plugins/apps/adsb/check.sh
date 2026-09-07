#!/usr/bin/env bash
#
# ADS-B plugin dependency check.
#
# Unprivileged probe run by meshpoint at boot (and on demand from
# Settings -> Plugins). Mirrors setup.sh's own idempotency check.
#
#   exit 0        -- deps satisfied, nothing to do
#   exit non-zero -- setup needed; stdout says what's missing
#
# No sudo: `command -v` needs no privileges.
set -uo pipefail

if command -v dump1090 &>/dev/null; then
    echo "dump1090 installed ($(command -v dump1090))"
    exit 0
fi

echo "dump1090 is not installed (built from source by setup.sh)"
echo "run: sudo meshpoint plugin setup adsb"
exit 1
