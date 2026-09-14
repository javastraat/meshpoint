#!/usr/bin/env bash
#
# Meshpoint Installer -- generic Debian, NO concentrator
#
# UNOFFICIAL / UNSUPPORTED. scripts/install.sh (and Meshpoint's README) only
# support Raspberry Pi 4/CM4 hardware with the SX1302 LoRaWAN concentrator
# HAT. This variant is for running the *software-only* parts of Meshpoint --
# RTL-SDR plugins, Reticulum, MeshCore/Meshtastic over a USB companion, the
# dashboard, self-update, plugin sources -- on a plain Debian box (VM, VPS,
# a spare machine) that has none of that hardware. It skips everything that
# needs it:
#
#   - SPI/I2C/UART enablement (raspi-config, /boot/firmware/config.txt)
#   - the SX1302 HAL build + its TX sync-word patch
#   - the concentrator GPIO reset hooks in meshpoint.service
#   - liblgpio-dev / gpiozero / lgpio (Pi GPIO fan/LED/button control --
#     off by default anyway; nothing imports them unless fan.enabled /
#     led.enabled / button.enabled is set true, which only makes sense on
#     a SenseCap M1)
#
# Everything else -- system packages, the Python venv, arduino-cli/
# PlatformIO (for flashing separate ESP32 companion boards over USB, no Pi
# hardware involved), gpsd, the systemd service/sudoers/udev/journald
# setup, avahi/mDNS, the CLI tool -- is identical in spirit to install.sh,
# just with the Pi-only pieces removed.
#
# After this finishes, set `capture.sources` in config/local.yaml to
# whatever you actually have (e.g. ["meshcore_usb"], ["meshtastic_usb"],
# or leave the default ["mock"]) -- NOT "concentrator", there's no HAL
# here to back it.
#
# Usage:
#   sudo ./scripts/install-debian.sh
#   sudo ./scripts/install-debian.sh --skip-arduino
#   sudo ./scripts/install-debian.sh --skip-platformio
#
set -euo pipefail

MESHPOINT_DIR="/opt/meshpoint"
SERVICE_FILE="scripts/meshpoint.service"
WATCHDOG_SERVICE_FILE="scripts/network-watchdog.service"
CLI_SCRIPT="scripts/meshpoint"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
fail()  { echo -e "${RED}[FAIL]${NC}  $*"; exit 1; }

IS_UPGRADE=0
if [ -f "${MESHPOINT_DIR}/config/local.yaml" ] \
        || systemctl is-enabled meshpoint &>/dev/null; then
    IS_UPGRADE=1
fi

# ── Welcome ─────────────────────────────────────────────────────────

echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${CYAN}${BOLD}  MESHPOINT INSTALLER -- generic Debian, no concentrator${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "UNOFFICIAL: only scripts/install.sh on a real Pi 4/CM4 is a"
echo "supported combination. This installs the software-only parts --"
echo "no SPI/I2C/UART, no SX1302 HAL, no GPIO fan/LED/button."
echo ""
if [ "$IS_UPGRADE" = "1" ]; then
    info "Existing installation detected: running in upgrade mode"
else
    echo "Expect 5-15 minutes depending on the machine and network."
fi
echo ""

# ── Pre-flight checks ──────────────────────────────────────────────

if [[ $EUID -ne 0 ]]; then
    fail "This script must be run as root.  Use:  sudo ./scripts/install-debian.sh"
fi

if ! command -v apt-get &>/dev/null; then
    fail "No apt-get found -- this script is Debian/Ubuntu-family only."
fi

FREE_ROOT_GB="$(df -Pk / 2>/dev/null | awk 'NR==2 { printf "%.1f", $4/1024/1024 }')"
if [ -n "$FREE_ROOT_GB" ]; then
    info "Free space on /: ${FREE_ROOT_GB} GB"
fi

INSTALL_ARDUINO=1
for arg in "$@"; do
    case "$arg" in
        --skip-arduino) INSTALL_ARDUINO=0 ;;
    esac
done
if [ "$INSTALL_ARDUINO" = "1" ] && ! command -v arduino-cli &>/dev/null && [ -t 0 ]; then
    echo ""
    echo "Optional: Configuration -> Firmware's POCSAG/Pager/RF Environment"
    echo "companion cards compile firmware via arduino-cli + the ESP32"
    echo "toolchain (a few hundred MB download). Only needed if you'll"
    echo "flash one of those companion boards from this box over USB --"
    echo "unrelated to the concentrator."
    echo ""
    read -r -p "Include the arduino-cli/ESP32 toolchain in this install? [y/N] " arduino_reply || arduino_reply=""
    case "$arduino_reply" in
        [yY]*) INSTALL_ARDUINO=1 ;;
        *) INSTALL_ARDUINO=0 ;;
    esac
fi

INSTALL_PLATFORMIO=1
for arg in "$@"; do
    case "$arg" in
        --skip-platformio) INSTALL_PLATFORMIO=0 ;;
    esac
done
if [ "$INSTALL_PLATFORMIO" = "1" ] && ! command -v pio &>/dev/null && [ -t 0 ]; then
    echo ""
    echo "Optional: the Reticulum companion firmware card uses PlatformIO"
    echo "(separate from arduino-cli above). Quick to install; its own"
    echo "ESP32 toolchain downloads lazily on first build."
    echo ""
    read -r -p "Include the PlatformIO toolchain in this install? [y/N] " platformio_reply || platformio_reply=""
    case "$platformio_reply" in
        [yY]*) INSTALL_PLATFORMIO=1 ;;
        *) INSTALL_PLATFORMIO=0 ;;
    esac
fi

echo ""
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
info "Source directory: ${SCRIPT_DIR}"

INSTALL_VERSION="$(
    grep -oP '__version__ = "\K[^"]+' "${SCRIPT_DIR}/src/version.py" \
        2>/dev/null || echo "unknown"
)"

# ── Upgrade fast path ──────────────────────────────────────────────

_upgrade_refresh_python_deps() {
    local req="${MESHPOINT_DIR}/requirements.txt"
    local pip="${MESHPOINT_DIR}/venv/bin/pip"
    if [ ! -x "$pip" ] || [ ! -f "$req" ]; then
        warn "Skipping early pip refresh (venv or requirements missing)"
        return 0
    fi
    info "Refreshing Python dependencies (upgrade fast path)..."
    "$pip" install --upgrade pip -q
    grep -viE '^(gpiozero|lgpio)([><=!].*)?$' "$req" | "$pip" install -r /dev/stdin -q
    "$pip" install pyserial -q
}

if [ "$IS_UPGRADE" = "1" ]; then
    _upgrade_refresh_python_deps
fi

# ── 1. System packages (no liblgpio-dev/swig -- Pi GPIO build deps) ──

info "Updating system packages..."
apt-get update -qq
apt-get upgrade -y -qq

info "Installing build tools and dependencies..."
apt-get install -y -qq \
    build-essential \
    git \
    curl \
    python3 \
    python3-venv \
    python3-pip \
    python3-dev \
    libsqlite3-dev \
    ffmpeg \
    i2c-tools \
    mc \
    make \
    htop \
    btop \
    fastfetch \
    cmake \
    libusb-1.0-0-dev \
    meson \
    libsndfile1-dev \
    libliquid-dev \
    libpulse-dev \
    libx11-dev \
    pipx

# ── 2. gpsd for USB GPS receivers (generic, no Pi-specific step) ───

info "Installing gpsd for USB GPS receivers..."
apt-get install -y -qq gpsd gpsd-clients

GPSD_DEFAULTS="/etc/default/gpsd"
if [ -f "$GPSD_DEFAULTS" ]; then
    GPSD_NEEDS_WRITE=0
    grep -q '^START_DAEMON="true"' "$GPSD_DEFAULTS" || GPSD_NEEDS_WRITE=1
    grep -q '^USBAUTO="true"'      "$GPSD_DEFAULTS" || GPSD_NEEDS_WRITE=1
    grep -q '^DEVICES=""'          "$GPSD_DEFAULTS" || GPSD_NEEDS_WRITE=1
    grep -q '^GPSD_OPTIONS="-n"'   "$GPSD_DEFAULTS" || GPSD_NEEDS_WRITE=1

    if [ "$GPSD_NEEDS_WRITE" = "1" ]; then
        info "Configuring ${GPSD_DEFAULTS} for USB hotplug..."
        cat > "$GPSD_DEFAULTS" <<'_GPSD_DEFAULTS'
START_DAEMON="true"
USBAUTO="true"
DEVICES=""
GPSD_OPTIONS="-n"
_GPSD_DEFAULTS
    else
        info "${GPSD_DEFAULTS} already configured"
    fi
fi

systemctl enable gpsd.socket 2>/dev/null || warn "Could not enable gpsd.socket"
systemctl restart gpsd.socket 2>/dev/null || warn "Could not start gpsd.socket"

# ── 3. Meshtastic / MeshCore CLI tools (optional, admin convenience) ─

if command -v meshtastic &>/dev/null; then
    info "Meshtastic CLI already installed, skipping"
else
    info "Installing Meshtastic CLI..."
    pip3 install --upgrade "meshtastic[cli]" --break-system-packages
fi

if command -v esptool &>/dev/null; then
    info "esptool already installed, skipping"
else
    info "Installing esptool..."
    pip3 install --upgrade esptool --break-system-packages
fi

if command -v meshcore-cli &>/dev/null || [ -d "$HOME/.local/share/pipx/venvs/meshcore-cli" ]; then
    info "MeshCore CLI already installed, skipping"
else
    info "Installing MeshCore CLI..."
    pipx install meshcore-cli
    pipx ensurepath
fi

# ── 4. arduino-cli + ESP32 toolchain (companion firmware flashing) ──
# Same as install.sh's section 7 -- no Pi/concentrator hardware involved,
# this only ever touches a separate ESP32 board over USB.

if [ "$INSTALL_ARDUINO" = "1" ]; then
    ARDUINO_CLI_HOME="/opt/arduino-cli"
    ARDUINO_CLI_BIN="/usr/local/bin/arduino-cli"
    ARDUINO_CLI_CONFIG="${ARDUINO_CLI_HOME}/arduino-cli.yaml"
    ESP32_CORE_VERSION="3.3.10"

    if [ -x "$ARDUINO_CLI_BIN" ]; then
        info "arduino-cli already installed, skipping"
    else
        info "Installing arduino-cli..."
        mkdir -p "${ARDUINO_CLI_HOME}/bin"
        curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh \
            | BINDIR="${ARDUINO_CLI_HOME}/bin" sh
        ln -sf "${ARDUINO_CLI_HOME}/bin/arduino-cli" "$ARDUINO_CLI_BIN"
    fi

    if [ ! -f "$ARDUINO_CLI_CONFIG" ]; then
        info "Writing arduino-cli config (${ARDUINO_CLI_CONFIG})..."
        mkdir -p "${ARDUINO_CLI_HOME}/data" "${ARDUINO_CLI_HOME}/user" "${ARDUINO_CLI_HOME}/downloads" "${ARDUINO_CLI_HOME}/cache"
        arduino-cli config init --dest-file "$ARDUINO_CLI_CONFIG" --overwrite
        arduino-cli --config-file "$ARDUINO_CLI_CONFIG" config set directories.data "${ARDUINO_CLI_HOME}/data"
        arduino-cli --config-file "$ARDUINO_CLI_CONFIG" config set directories.user "${ARDUINO_CLI_HOME}/user"
        arduino-cli --config-file "$ARDUINO_CLI_CONFIG" config set directories.downloads "${ARDUINO_CLI_HOME}/downloads"
        arduino-cli --config-file "$ARDUINO_CLI_CONFIG" config add board_manager.additional_urls \
            https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
    else
        info "arduino-cli config already present, skipping"
    fi

    info "Updating arduino-cli board index..."
    arduino-cli --config-file "$ARDUINO_CLI_CONFIG" core update-index

    if arduino-cli --config-file "$ARDUINO_CLI_CONFIG" core list | grep -q "^esp32:esp32 "; then
        info "esp32:esp32 core already installed, skipping"
    else
        info "Installing ESP32 board core ${ESP32_CORE_VERSION} (this takes a few minutes)..."
        arduino-cli --config-file "$ARDUINO_CLI_CONFIG" core install "esp32:esp32@${ESP32_CORE_VERSION}"
    fi

    _POCSAG_LIB_DIRS=(
        "Adafruit_GFX_Library" "Adafruit_SSD1306" "RadioLib"
        "ArduinoJson" "Async_TCP" "ESP_Async_WebServer"
    )
    _pocsag_libs_present=1
    for lib_dir in "${_POCSAG_LIB_DIRS[@]}"; do
        if [ ! -d "${ARDUINO_CLI_HOME}/user/libraries/${lib_dir}" ]; then
            _pocsag_libs_present=0
            break
        fi
    done

    if [ "$_pocsag_libs_present" = "1" ]; then
        info "pocsag_companion sketch libraries already installed, skipping"
    else
        info "Installing pocsag_companion sketch libraries..."
        for lib in \
            "Adafruit GFX Library@1.12.6" \
            "Adafruit SSD1306@2.5.17" \
            "RadioLib@7.7.1" \
            "ArduinoJson@7.4.3" \
            "Async TCP" \
            "ESP Async WebServer@3.12.0"
        do
            arduino-cli --config-file "$ARDUINO_CLI_CONFIG" lib install "$lib" \
                || warn "Could not install library: ${lib}"
        done
    fi

    if ! id -u meshpoint &>/dev/null; then
        useradd --system --no-create-home --shell /usr/sbin/nologin meshpoint
    fi
    chown -R meshpoint:meshpoint "$ARDUINO_CLI_HOME"
else
    info "Skipping arduino-cli/ESP32 toolchain -- re-run without --skip-arduino to add it later"
fi

# ── 5. PlatformIO toolchain (Reticulum companion firmware) ─────────

if [ "$INSTALL_PLATFORMIO" = "1" ]; then
    PLATFORMIO_HOME="/opt/platformio"
    PIO_BIN="/usr/local/bin/pio"

    if [ -x "${PLATFORMIO_HOME}/venv/bin/pio" ]; then
        info "PlatformIO already installed, skipping"
    else
        info "Installing PlatformIO..."
        mkdir -p "${PLATFORMIO_HOME}/core"
        python3 -m venv "${PLATFORMIO_HOME}/venv"
        "${PLATFORMIO_HOME}/venv/bin/pip" install --upgrade pip -q
        "${PLATFORMIO_HOME}/venv/bin/pip" install platformio -q
        ln -sf "${PLATFORMIO_HOME}/venv/bin/pio" "$PIO_BIN"
    fi

    if ! id -u meshpoint &>/dev/null; then
        useradd --system --no-create-home --shell /usr/sbin/nologin meshpoint
    fi
    chown -R meshpoint:meshpoint "$PLATFORMIO_HOME"
else
    info "Skipping PlatformIO toolchain -- re-run without --skip-platformio to add it later"
fi

# ── 6. Install Meshpoint application ────────────────────────────────
# NOTE: no SX1302 HAL build, no TX sync-word patch -- there's no
# concentrator here for either of those to matter to.

info "Installing Meshpoint to ${MESHPOINT_DIR}..."
mkdir -p "$MESHPOINT_DIR"

rsync -a --exclude='venv' \
         --exclude='__pycache__' \
         --exclude='cdk.out' \
         --exclude='cloud/build' \
         --exclude='data' \
         --exclude='*.pyc' \
         "${SCRIPT_DIR}/" "$MESHPOINT_DIR/"

if find "${MESHPOINT_DIR}/src" -name '*.cpython-*.so' -print -quit | grep -q .; then
    info "Removing stale compiled modules from previous installation..."
    find "${MESHPOINT_DIR}/src" -name '*.cpython-*.so' -delete
fi

# ── 7. Python virtual environment (skip gpiozero/lgpio) ────────────
# Neither is needed: fan.enabled/led.enabled/button.enabled all default
# false, and fan_control.py/led_status.py/button_control.py only
# `import gpiozero` lazily inside the code path that runs when enabled.

info "Setting up Python virtual environment..."
python3 -m venv "${MESHPOINT_DIR}/venv"
"${MESHPOINT_DIR}/venv/bin/pip" install --upgrade pip -q
grep -viE '^(gpiozero|lgpio)([><=!].*)?$' "${MESHPOINT_DIR}/requirements.txt" \
    | "${MESHPOINT_DIR}/venv/bin/pip" install -r /dev/stdin -q
"${MESHPOINT_DIR}/venv/bin/pip" install pyserial -q

# ── 8. Data directory ────────────────────────────────────────────────

mkdir -p "${MESHPOINT_DIR}/data"

# ── 9. meshpoint system user (no spi/gpio/i2c groups -- don't exist) ─

if ! id -u meshpoint &>/dev/null; then
    info "Creating system user 'meshpoint'..."
    useradd --system --no-create-home --shell /usr/sbin/nologin meshpoint
fi

# dialout (USB serial: MeshCore/Meshtastic companions, GPS, RTL-SDR
# devices that need it) on its own line -- unlike the spi/gpio/i2c
# groups install.sh adds, this one always exists on Debian and must not
# be skipped alongside groups that don't.
usermod -a -G dialout meshpoint 2>/dev/null || true
usermod -a -G systemd-journal,adm meshpoint 2>/dev/null || true
usermod -a -G audio,video,plugdev meshpoint 2>/dev/null || true

chown -R meshpoint:meshpoint "${MESHPOINT_DIR}"

if [ -d "${MESHPOINT_DIR}/.git" ]; then
    git config --system --get-all safe.directory 2>/dev/null \
        | grep -qx "${MESHPOINT_DIR}" \
        || git config --system --add safe.directory "${MESHPOINT_DIR}"
fi

# Espressif USB serial devices (Heltec V3/V4, T-Beam ESP32-S3) --
# generic USB, nothing Pi-specific about this rule.
UDEV_RULE='SUBSYSTEM=="tty", ATTRS{idVendor}=="303a", MODE="0660", GROUP="dialout"'
UDEV_FILE="/etc/udev/rules.d/99-meshpoint-esp.rules"
if [ "$(cat "$UDEV_FILE" 2>/dev/null)" != "$UDEV_RULE" ]; then
    info "Installing/updating udev rule for Espressif USB serial devices..."
    echo "$UDEV_RULE" > "$UDEV_FILE"
    udevadm control --reload-rules 2>/dev/null || true
    udevadm trigger 2>/dev/null || true
fi

info "Installing sudoers rule for service management..."
if visudo -cf "${MESHPOINT_DIR}/config/sudoers-meshpoint" >/dev/null 2>&1; then
    install -m 440 -o root -g root \
        "${MESHPOINT_DIR}/config/sudoers-meshpoint" /etc/sudoers.d/meshpoint
else
    fail "config/sudoers-meshpoint failed 'visudo -c' -- not installing it (would break sudo)"
fi

# ── 10. journald log rotation ───────────────────────────────────────

info "Configuring journald log limits (100M, 7-day retention)..."
mkdir -p /etc/systemd/journald.conf.d
cp "${MESHPOINT_DIR}/config/journald-meshpoint.conf" /etc/systemd/journald.conf.d/meshpoint.conf
systemctl restart systemd-journald 2>/dev/null || warn "Could not restart journald"

# ── 11. systemd service, WITHOUT the concentrator GPIO reset hooks ──
# meshpoint.service's ExecStartPre/ExecStopPost call
# scripts/reset_concentrator.sh, which toggles GPIO pins for the
# SX1302's reset line via `pinctrl`/`gpioset`. On a box with neither
# tool (any non-Pi Debian without gpiod installed) that script exits 1,
# which fails the ExecStartPre and the *whole service* refuses to
# start. There's no concentrator here for it to reset anyway, so those
# two lines are stripped from the installed unit.

info "Installing systemd service (concentrator reset hooks stripped)..."
sed -e '/reset_concentrator\.sh/d' \
    "${MESHPOINT_DIR}/${SERVICE_FILE}" > /etc/systemd/system/meshpoint.service
systemctl daemon-reload
systemctl enable meshpoint
info "Service enabled (will start after 'meshpoint setup')"

# ── 12. Network watchdog (WiFi-oriented; harmless on wired boxes) ──
# `systemctl disable network-watchdog` afterwards if this machine has
# no WiFi interface at all and you'd rather not run it.

info "Installing network watchdog..."
cp "${MESHPOINT_DIR}/${WATCHDOG_SERVICE_FILE}" /etc/systemd/system/network-watchdog.service
systemctl daemon-reload
systemctl enable network-watchdog
systemctl start network-watchdog 2>/dev/null || warn "Could not start network-watchdog (will start on next boot)"

# ── 13. mDNS (Avahi) ────────────────────────────────────────────────

if command -v avahi-daemon &>/dev/null; then
    info "avahi-daemon already installed, skipping"
else
    info "Installing mDNS (Avahi)..."
    apt-get install -y -qq avahi-daemon avahi-utils
fi
systemctl enable --now avahi-daemon

# ── 14. CLI tool ─────────────────────────────────────────────────────

info "Installing meshpoint CLI..."
chmod +x "${MESHPOINT_DIR}/${CLI_SCRIPT}"
ln -sf "${MESHPOINT_DIR}/${CLI_SCRIPT}" /usr/local/bin/meshpoint

# ── 15. fastfetch login banner for the invoking (sudo) user ────────

INVOKING_USER="${SUDO_USER:-}"
if [ -n "$INVOKING_USER" ]; then
    INVOKING_BASHRC="$(eval echo "~${INVOKING_USER}")/.bashrc"
    if [ -f "$INVOKING_BASHRC" ]; then
        if grep -qx "fastfetch" "$INVOKING_BASHRC"; then
            info "fastfetch login banner already configured"
        else
            info "Adding fastfetch login banner to ${INVOKING_BASHRC}..."
            echo "fastfetch" >> "$INVOKING_BASHRC"
        fi
    fi
fi

# ── Done ────────────────────────────────────────────────────────────

echo ""
echo "==========================================="
if [ "$IS_UPGRADE" = "1" ]; then
    echo "  Meshpoint upgrade to v${INSTALL_VERSION} complete!"
else
    echo "  Meshpoint installation complete! (no concentrator)"
fi
echo "==========================================="
echo ""
echo "  No reboot needed -- nothing here touched SPI/UART/boot config."
echo ""
echo "  Before starting the service, edit config/local.yaml:"
echo "       capture:"
echo "         sources: []   # or [\"meshcore_usb\"] / [\"meshtastic_usb\"] --"
echo "                       # NOT \"concentrator\", there's no HAL here"
echo ""
echo "  Then:"
echo "       sudo meshpoint setup"
echo ""
echo "==========================================="
