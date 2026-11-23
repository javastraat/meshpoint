#!/usr/bin/env bash
# Shim so Semtech's vendored test tools (test_loragw_hal_tx, etc.) work on
# this board. They call `./reset_lgw.sh start|stop` relative to their own
# cwd (this directory) using the legacy sysfs GPIO convention, which this
# Pi's kernel doesn't support (see extra/sniffer.c's own reset_m1.sh, which
# had the same problem). Real logic lives in scripts/reset_concentrator.sh
# (pinctrl/gpioset-based). RESET_GPIO=22 is the COTX X3's concentrator
# reset pin -- see docs/HARDWARE-MATRIX.md -- override via env var if this
# ever runs against different hardware.
#
# Usage: ./reset_lgw.sh start   (full reset cycle, before lgw_start())
#        ./reset_lgw.sh stop    (hold in reset, after lgw_stop())

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESET_SCRIPT="$HERE/../../../scripts/reset_concentrator.sh"
RESET_GPIO="${RESET_GPIO:-22}"

case "${1:-}" in
    start) RESET_GPIO="$RESET_GPIO" bash "$RESET_SCRIPT" ;;
    stop)  RESET_GPIO="$RESET_GPIO" bash "$RESET_SCRIPT" --hold ;;
    *) echo "Usage: $0 {start|stop}" >&2; exit 1 ;;
esac
