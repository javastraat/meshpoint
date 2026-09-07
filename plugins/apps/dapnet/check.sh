#!/usr/bin/env bash
#
# DAPNET plugin dependency check.
#
# Unprivileged probe run by meshpoint at boot (and on demand from
# Settings -> Plugins).
#
#   exit 0        -- deps satisfied
#   exit non-zero -- setup needed; stdout says what's missing
#
# DAPNET has no build/apt step of its own: the capture side (pyserial)
# is pulled in transitively by the meshtastic/meshcore packages in
# requirements.txt, and the POCSAG-companion firmware card reuses the
# shared arduino-cli + ESP32 toolchain (scripts/install.sh). So the only
# hard requirement to check is pyserial; arduino-cli is reported as
# info -- missing it only disables the firmware compile/flash card.
#
# No sudo needed.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "${HERE}/../../.." && pwd)"
VENV_PY="${REPO}/venv/bin/python3"

if ! "${VENV_PY}" -c "import serial" &>/dev/null; then
    echo "pyserial is not importable in the venv (normally pulled in by"
    echo "meshtastic/meshcore in requirements.txt -- re-run scripts/install.sh)"
    exit 1
fi

if command -v arduino-cli &>/dev/null; then
    echo "pyserial present; arduino-cli present (firmware compile/flash ready)"
else
    echo "pyserial present; arduino-cli NOT found -- the POCSAG companion"
    echo "compile/flash card won't work until scripts/install.sh's arduino-cli"
    echo "section is re-run (the DAPNET decoder itself is unaffected)"
fi
exit 0
