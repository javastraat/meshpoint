#!/usr/bin/env bash
#
# ACARS plugin dependency check.
#
# Unprivileged probe run by meshpoint at boot (and on demand from
# Settings -> Plugins). Mirrors setup.sh's own idempotency check.
#
#   exit 0        -- deps satisfied, nothing to do
#   exit non-zero -- setup needed; stdout says what's missing
#
# No sudo: `command -v` needs no privileges.
set -uo pipefail

if command -v acarsdec &>/dev/null; then
    echo "acarsdec installed ($(command -v acarsdec))"
    exit 0
fi

echo "acarsdec is not installed (built from source by setup.sh, with libacars)"
echo "run: sudo meshpoint plugin setup acars"
exit 1
