#!/usr/bin/env bash
#
# Reticulum plugin dependency check.
#
# Meshpoint runs this unprivileged at boot (and on demand from Settings ->
# Plugins) to decide whether the plugin's setup.sh still needs running.
#
#   exit 0        -- every dependency is in place, nothing to do
#   exit non-zero -- setup needed; stdout lists exactly what's missing
#
# Mirror of setup.sh's own idempotency checks, minus the installing:
#   1. `lxmf` importable in the venv (setup.sh pip-installs it)
#   2. rnsd.service installed under /etc/systemd/system (setup.sh copies it)
#   3. rnsd.service enabled (setup.sh enables it)
#
# Must be answerable by the unprivileged `meshpoint` service account --
# no sudo. Reading /etc/systemd/system and `systemctl is-enabled` both work
# without root.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "${HERE}/../../.." && pwd)"
VENV_PY="${REPO}/venv/bin/python3"
UNIT_DST="/etc/systemd/system/rnsd.service"

missing=()

if ! "${VENV_PY}" -c "import LXMF" &>/dev/null; then
    missing+=("lxmf is not installed in the venv")
fi

if [ ! -f "${UNIT_DST}" ]; then
    missing+=("rnsd.service is not installed under /etc/systemd/system")
elif ! systemctl is-enabled rnsd &>/dev/null; then
    missing+=("rnsd.service is installed but not enabled")
fi

if [ "${#missing[@]}" -eq 0 ]; then
    echo "lxmf installed; rnsd.service installed and enabled"
    exit 0
fi

printf '%s\n' "${missing[@]}"
echo "run: sudo meshpoint plugin setup reticulum"
exit 1
