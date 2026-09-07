#!/usr/bin/env bash
#
# p2000 plugin dependency check.
#
# Unprivileged probe run by meshpoint at boot (and on demand from
# Settings -> Plugins). Mirrors setup.sh's own idempotency check.
#
#   exit 0        -- deps satisfied, nothing to do
#   exit non-zero -- setup needed; stdout says what's missing
#
# No sudo: `command -v` needs no privileges.
set -uo pipefail

if command -v multimon-ng &>/dev/null; then
    echo "multimon-ng installed ($(command -v multimon-ng))"
    exit 0
fi

echo "multimon-ng is not installed (built from source by setup.sh)"
echo "run: sudo meshpoint plugin setup p2000"
exit 1
