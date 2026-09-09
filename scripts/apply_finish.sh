#!/bin/bash
# Finish a dashboard-driven apply or rollback after git checkout/reset.
#
# Lightweight upgrade path (not full install.sh): refresh Python deps,
# run idempotent post-update migrations (sudoers, systemd unit, HAL patch
# if needed), then restart the service. Typical runtime: about 1-2 minutes.
# Full install.sh remains for manual SSH upgrades when release notes call
# for it.
set -euo pipefail

MESHPOINT_DIR="${MESHPOINT_DIR:-/opt/meshpoint}"
SERVICE="${MESHPOINT_SERVICE:-meshpoint}"
PIP="${MESHPOINT_DIR}/venv/bin/pip"
REQ="${MESHPOINT_DIR}/requirements.txt"

log() {
    echo "[apply_finish] $*"
    logger -t meshpoint-apply-finish "$*" 2>/dev/null || true
}

_on_error() {
    log "failed near line ${1:-?}; attempting ${SERVICE} restart"
    /usr/bin/systemctl restart "${SERVICE}" || true
}
trap '_on_error ${LINENO}' ERR

# Do NOT systemctl stop here. This script is spawned from the meshpoint
# service process; stop kills the unit cgroup and terminates us before
# pip or restart can finish. Restart at the end stops the concentrator.

if [[ -x "$PIP" && -f "$REQ" ]]; then
    log "Refreshing Python dependencies"
    # This script runs as root (sudo bash), but the venv is owned by the
    # meshpoint user -- drop to meshpoint for pip so installed files stay
    # meshpoint-owned (no root-owned files in the venv for post_update.sh
    # to chown back). runuser (util-linux) is root->user with no PAM/
    # password; fall back to plain pip if it's somehow missing or we're
    # already meshpoint.
    if [[ "$(id -un)" == "meshpoint" ]] || ! command -v runuser >/dev/null; then
        run_pip() { "$PIP" "$@"; }
    else
        run_pip() { runuser -u meshpoint -- "$PIP" "$@"; }
    fi
    run_pip install --upgrade pip -q
    run_pip install -r "$REQ" -q
    run_pip install pyserial -q
fi

log "Running post_update migrations"
# post_update.sh may call patch_hal.sh; MESHPOINT_INSTALL_IN_PROGRESS
# suppresses its "restart now" suggestion since we restart automatically
# below regardless -- the suggestion would just be confusing noise here,
# not a real prompt to act on.
MESHPOINT_INSTALL_IN_PROGRESS=1 /bin/bash "${MESHPOINT_DIR}/scripts/post_update.sh"

log "Restarting ${SERVICE}"
/usr/bin/systemctl restart "${SERVICE}"
trap - ERR
log "Done"
