#!/bin/bash
# Post-update migration hook: runs after git pull, before restart.
# All checks are idempotent: safe to run on every update.
set -e

MESHPOINT_DIR="/opt/meshpoint"
HAL_SRC="/opt/sx1302_hal/libloragw/src/loragw_sx1302.c"

info() { echo "[post_update] $*"; }

CHANGED=0

# ── 1. Sudoers rule ─────────────────────────────────────────────────
SUDOERS_SRC="${MESHPOINT_DIR}/config/sudoers-meshpoint"
SUDOERS_DST="/etc/sudoers.d/meshpoint"
if [ -f "$SUDOERS_SRC" ]; then
    if ! diff -q "$SUDOERS_SRC" "$SUDOERS_DST" >/dev/null 2>&1; then
        # Validate before installing -- a malformed drop-in breaks sudo
        # for the whole box, and this file is edited as the sudo surface
        # gets tightened over time.
        if visudo -cf "$SUDOERS_SRC" >/dev/null 2>&1; then
            info "Updating sudoers rule..."
            install -m 440 -o root -g root "$SUDOERS_SRC" "$SUDOERS_DST"
            CHANGED=1
        else
            info "WARNING: $SUDOERS_SRC failed visudo -c; keeping the existing rule"
        fi
    fi
fi

# ── 1a. Git safe.directory (system-wide) ────────────────────────────
# /opt/meshpoint ownership differs from the users running git (root via
# sudo, meshpoint service user), so git's dubious-ownership check blocks
# them unless the tree is trusted system-wide. install.sh does this on
# fresh installs; upgraded boxes need it here.
if [ -d "${MESHPOINT_DIR}/.git" ]; then
    git config --system --get-all safe.directory 2>/dev/null \
        | grep -qx "${MESHPOINT_DIR}" \
        || { git config --system --add safe.directory "${MESHPOINT_DIR}"; \
             info "Added ${MESHPOINT_DIR} to system git safe.directory"; \
             CHANGED=1; }
fi

# ── 2. Service file ─────────────────────────────────────────────────
SERVICE_SRC="${MESHPOINT_DIR}/scripts/meshpoint.service"
SERVICE_DST="/etc/systemd/system/meshpoint.service"
if [ -f "$SERVICE_SRC" ]; then
    if ! diff -q "$SERVICE_SRC" "$SERVICE_DST" >/dev/null 2>&1; then
        info "Updating service file..."
        cp "$SERVICE_SRC" "$SERVICE_DST"
        systemctl daemon-reload
        CHANGED=1
    fi
fi

# ── 3. Install tree ownership ────────────────────────────────────────
# Whole tree, recursive: the apply chain's `sudo git fetch/reset` (which
# runs right before this script) leaves root-owned files in .git and the
# working tree; hand everything back to the service user so plain git
# (Check for updates) and lgpio's WorkingDirectory pipe keep working.
chown -R meshpoint:meshpoint "${MESHPOINT_DIR}" 2>/dev/null || true

# ── 3a. Service-user group membership (idempotent) ──────────────────
# v0.7.4+: meshpoint user needs systemd-journal + adm to read its own
# logs from the dashboard without sudo. Existing installs upgraded
# from <=v0.7.3 won't have this until we re-run usermod here.
for grp in systemd-journal adm; do
    if ! id -nG meshpoint 2>/dev/null | grep -qw "$grp"; then
        info "Adding meshpoint to '$grp' group for journal access..."
        usermod -a -G "$grp" meshpoint 2>/dev/null || true
        CHANGED=1
    fi
done

# ── 3b. Espressif udev rule: 0666 → 0660 (idempotent) ──────────────
# Installs before 2026-09 shipped MODE="0666" (world-writable) for
# idVendor 303a devices. The meshpoint user is in dialout, so 0660 +
# GROUP="dialout" is enough; tighten any box still carrying the old rule.
UDEV_RULE_ESP='SUBSYSTEM=="tty", ATTRS{idVendor}=="303a", MODE="0660", GROUP="dialout"'
UDEV_FILE_ESP="/etc/udev/rules.d/99-meshpoint-esp.rules"
if [ -f "$UDEV_FILE_ESP" ] && [ "$(cat "$UDEV_FILE_ESP")" != "$UDEV_RULE_ESP" ]; then
    info "Tightening Espressif udev rule (was world-writable)..."
    echo "$UDEV_RULE_ESP" > "$UDEV_FILE_ESP"
    udevadm control --reload-rules 2>/dev/null || true
    udevadm trigger 2>/dev/null || true
    CHANGED=1
fi

# ── 4. HAL TX sync word patch (one-time, ~2 minutes if needed) ──────
# Marker is the NEW explicit-setter patch (sx1302_set_tx_syncword); Pis
# carrying only the old static-peaks patch (sx1302_tx_sw_peak1, which
# silently transmitted LoRaWAN 0x34 once lorawan_public=True became the
# board default) re-patch here automatically.
if [ -f "$HAL_SRC" ]; then
    if ! grep -q "sx1302_set_tx_syncword" "$HAL_SRC"; then
        info "TX sync word patch needed (this takes ~2 minutes)..."
        bash "${MESHPOINT_DIR}/scripts/patch_hal.sh"
        CHANGED=1
    fi
fi

if [ "$CHANGED" -eq 0 ]; then
    info "No migrations needed"
else
    info "Migrations applied"
fi
