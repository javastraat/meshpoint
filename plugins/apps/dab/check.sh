#!/usr/bin/env bash
#
# DAB+ plugin dependency check.
#
# Unprivileged probe run by meshpoint at boot (and on demand from
# Settings -> Plugins). Mirrors setup.sh's own idempotency check.
#
#   exit 0        -- deps satisfied, nothing to do
#   exit non-zero -- setup needed; stdout says what's missing
#
# No sudo: `command -v` needs no privileges.
set -uo pipefail

if command -v welle-cli &>/dev/null; then
    echo "welle.io (welle-cli) installed ($(command -v welle-cli))"
    exit 0
fi

echo "welle-cli is not installed (apt package welle.io, installed by setup.sh)"
echo "run: sudo meshpoint plugin setup dab"
exit 1
