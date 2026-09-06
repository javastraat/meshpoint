#!/usr/bin/env bash
#
# Reticulum plugin setup.
#
# Two things, both idempotent:
#
#  1. `lxmf` into the venv. `rns` (the Reticulum stack + the `rnsd`
#     binary + `rnodeconf`) stays in requirements.txt because core's
#     RNode firmware flasher needs it too; `lxmf` is Reticulum-only, so
#     it lives here.
#
#  2. The `rnsd` systemd unit. meshpoint's LxmfService attaches to a
#     locally-running `rnsd` shared instance as a client -- it never
#     opens a radio interface itself. `rnsd` runs as its own unit
#     (rnsd.service, in this folder), deliberately NOT a dependency of
#     meshpoint.service. rnsd.service's ExecStartPre regenerates rnsd's
#     interfaces config from `plugins.reticulum.*` on every start
#     (write_rnsd_config.py, also in this folder).
#
# Run once, with the same privileges as install.sh:
#     sudo bash /opt/meshpoint/plugins/apps/reticulum/setup.sh
#   or
#     sudo meshpoint plugin setup reticulum
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "${HERE}/../../.." && pwd)"
VENV_PIP="${REPO}/venv/bin/pip"
UNIT_SRC="${HERE}/rnsd.service"
UNIT_DST="/etc/systemd/system/rnsd.service"

# ── 1. lxmf ──────────────────────────────────────────────────────────
if "${REPO}/venv/bin/python3" -c "import LXMF" &>/dev/null; then
    echo "lxmf already installed -- skipping"
else
    echo "Installing lxmf into the venv ..."
    "${VENV_PIP}" install --quiet 'lxmf>=1.0.1'
fi

# ── 2. rnsd systemd unit ─────────────────────────────────────────────
if [ -f "${UNIT_DST}" ] && cmp -s "${UNIT_SRC}" "${UNIT_DST}"; then
    echo "rnsd.service already installed and up to date -- skipping"
else
    echo "Installing ${UNIT_DST} ..."
    cp "${UNIT_SRC}" "${UNIT_DST}"
    systemctl daemon-reload
fi

if systemctl is-enabled rnsd &>/dev/null; then
    echo "rnsd.service already enabled"
else
    systemctl enable rnsd
    echo "rnsd.service enabled -- will start on next boot, or 'sudo systemctl start rnsd' now"
fi

echo
echo "Done. Enable the plugin with:"
echo "  plugins:"
echo "    reticulum:"
echo "      enabled: true"
echo "then restart meshpoint. Reticulum config (RNode radio, TCP backbone) is the"
echo "Settings tab on the Reticulum page."
