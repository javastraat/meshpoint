#!/usr/bin/env bash
#
# RTL433 plugin dependency check.
#
# Unprivileged probe run by meshpoint at boot (and on demand from
# Settings -> Plugins). Mirrors setup.sh's own idempotency check.
#
#   exit 0        -- deps satisfied, nothing to do
#   exit non-zero -- setup needed; stdout says what's missing
#
# No sudo: `command -v` needs no privileges.
set -uo pipefail

if command -v rtl_433 &>/dev/null; then
    echo "rtl_433 installed ($(command -v rtl_433))"
    exit 0
fi

echo "rtl_433 is not installed (apt package rtl-433, installed by setup.sh)"
echo "run: sudo meshpoint plugin setup rtl433"
exit 1
