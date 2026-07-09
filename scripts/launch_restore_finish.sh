#!/bin/bash
# Launch restore_finish outside the meshpoint service cgroup.
#
# restore_finish must call systemctl stop meshpoint. If this script were
# spawned directly from the API handler, stop would kill the unit cgroup
# and terminate restore_finish before it can extract the archive and start
# the service again. systemd-run starts a transient unit that outlives stop.
set -euo pipefail

ARCHIVE_PATH="${1:-}"
if [[ -z "$ARCHIVE_PATH" || ! -f "$ARCHIVE_PATH" ]]; then
    echo "usage: launch_restore_finish.sh <archive.tar.gz>" >&2
    exit 1
fi

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
UNIT="meshpoint-restore-finish-${STAMP}"

log() {
    echo "[launch_restore_finish] $*"
    logger -t meshpoint-restore-finish "$*" 2>/dev/null || true
}

log "scheduling unit=${UNIT} archive=${ARCHIVE_PATH}"

if ! /usr/bin/systemd-run \
    --unit="$UNIT" \
    --description="Meshpoint backup restore ${STAMP}" \
    --collect \
    /bin/bash /opt/meshpoint/scripts/restore_finish.sh "$ARCHIVE_PATH"; then
    log "systemd-run failed for unit=${UNIT}"
    exit 1
fi

log "queued unit=${UNIT}"
