#!/usr/bin/env bash
#
# Meshpoint Installer
#
# Prepares a fresh Raspberry Pi for Meshpoint operation:
#   1. System packages and build tools
#   2. SPI / UART / GPS kernel config
#   3. SX1302 HAL (libloragw) compilation
#   4. Python virtual-env and pip dependencies
#   5. systemd service installation
#
# Usage:
#   sudo ./scripts/install.sh
#   sudo ./scripts/install.sh --skip-arduino   # skip the arduino-cli/ESP32
#                                               # toolchain (POCSAG/Pager/RF
#                                               # Environment Compile+Flash);
#                                               # otherwise prompted [y/N]
#   sudo ./scripts/install.sh --skip-rtlsdr    # skip RTL-SDR support (FM/RDS,
#                                               # P2000/Pagers/POCSAG, 433/868
#                                               # sensors, ADS-B, DAB+);
#                                               # otherwise prompted [y/N]
#   sudo ./scripts/install.sh --skip-platformio  # skip the PlatformIO toolchain
#                                               # (Reticulum companion firmware
#                                               # provision+flash); otherwise
#                                               # prompted [y/N]
#
# After completion, reboot then run:  meshpoint setup
#
set -euo pipefail

MESHPOINT_DIR="/opt/meshpoint"
HAL_BUILD_DIR="/opt/sx1302_hal"
BOOT_CONFIG="/boot/firmware/config.txt"
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

# Detect upgrade vs fresh install upfront, before the welcome banner
# below -- an existing local.yaml or an enabled meshpoint service is the
# clearest signal a previous install already completed. Used to live
# further down (near SCRIPT_DIR), which meant the banner always claimed
# to set up "a fresh Raspberry Pi" even on a repeat/upgrade run, since it
# printed before that detection had even run.
IS_UPGRADE=0
if [ -f "${MESHPOINT_DIR}/config/local.yaml" ] \
        || systemctl is-enabled meshpoint &>/dev/null; then
    IS_UPGRADE=1
fi

# ── Welcome ─────────────────────────────────────────────────────────

echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${CYAN}${BOLD}  MESHPOINT INSTALLER${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
if [ "$IS_UPGRADE" = "1" ]; then
    info "Existing installation detected: running in upgrade mode"
    echo ""
    echo "Welcome back! This updates/repairs your existing Meshpoint install"
    echo "in place: system packages, SPI/UART/GPS config, the SX1302 HAL, the"
    echo "Python venv, and the systemd service. Most steps are idempotent and"
    echo "skip straight past anything already in place, so a repeat run is"
    echo "usually much faster than the first one."
else
    echo ""
    echo "Welcome! This sets up a fresh Raspberry Pi for Meshpoint: system"
    echo "packages, SPI/UART/GPS config, the SX1302 HAL, a Python venv, and"
    echo "the systemd service. Expect this to take 15-30 minutes depending"
    echo "on your Pi and network connection."
fi
echo ""

# ── Pre-flight checks ──────────────────────────────────────────────

if [[ $EUID -ne 0 ]]; then
    fail "This script must be run as root.  Use:  sudo ./scripts/install.sh"
fi

if ! grep -qi "raspberry\|raspbian\|debian" /etc/os-release 2>/dev/null; then
    warn "This doesn't look like Raspberry Pi OS. Proceeding anyway."
fi

# Informational -- not a hard requirement, just worth knowing before a
# multi-GB run (apt packages, the SX1302 HAL build, a Python venv, and
# optionally the arduino-cli/ESP32 and/or PlatformIO toolchains below)
# starts on what might be a small SD card.
FREE_ROOT_GB="$(df -Pk / 2>/dev/null | awk 'NR==2 { printf "%.1f", $4/1024/1024 }')"
if [ -n "$FREE_ROOT_GB" ]; then
    info "Free space on /: ${FREE_ROOT_GB} GB"
    if awk -v f="$FREE_ROOT_GB" 'BEGIN { exit !(f < 4) }'; then
        warn "That's getting tight -- the HAL build, venv, and (if installed) the arduino-cli/ESP32 toolchain need real room. A larger SD card is worth considering; answering 'n' to arduino-cli below saves roughly 300-500 MB right now if you don't need POCSAG/Pager/RF Environment firmware flashing. PlatformIO's own install.sh footprint is small either way (its ESP32 toolchain downloads lazily on first build, not during this installer) -- but that later download is a similar few-hundred-MB size, worth knowing about now if space is already tight."
    fi
else
    warn "Could not determine free disk space (df failed) -- proceeding anyway."
fi

# The arduino-cli/ESP32 toolchain (section 13 below) is only needed for
# the Configuration -> Firmware page's POCSAG/Pager/RF Environment
# Compile+Flash cards -- MeshCore/Meshtastic flashing uses prebuilt
# releases + esptool instead and is unaffected either way. It's a
# genuinely large, multi-minute download (the ESP32 core + toolchain
# runs a few hundred MB), so ask upfront -- before the long unattended
# stretch of steps that follow -- rather than blocking mid-run on a
# prompt nobody's watching for. Every step in that section is
# idempotent, so re-running this installer later (without
# --skip-arduino) adds it at any time without redoing anything else.
#
# Already-installed check comes first, ahead of even showing the
# explanation: on a box that already has it (e.g. a repeat/upgrade run),
# asking again every time is just noise -- silently default to "yes"
# instead (section 13's own per-step idempotency then does the real work
# of confirming/filling in anything actually missing, and announces that
# itself when it gets there -- no need to say it twice, here too). An
# explicit --skip-arduino still wins over that, in case someone wants a
# fast run without even the idempotent checks.
INSTALL_ARDUINO=1
for arg in "$@"; do
    case "$arg" in
        --skip-arduino) INSTALL_ARDUINO=0 ;;
    esac
done
if [ "$INSTALL_ARDUINO" = "1" ] && ! command -v arduino-cli &>/dev/null && [ -t 0 ]; then
    echo ""
    echo "One optional piece before we start: Configuration -> Firmware's"
    echo "POCSAG, Pager, and RF Environment companion cards compile their"
    echo "own firmware from source via arduino-cli + the ESP32 toolchain --"
    echo "a genuinely large (few hundred MB), multi-minute download."
    echo "MeshCore/Meshtastic flashing uses prebuilt releases instead and"
    echo "needs none of this. Skip it now and re-run this installer later"
    echo "(without --skip-arduino) to add it whenever you actually need it."
    echo ""
    echo "On a RAK2287 (RAK V2) board: that concentrator has no SX1261, so"
    echo "the RF Environment page has nothing to show on its own. Fixing"
    echo "that needs a separate Heltec V3 board, flashed as an RF"
    echo "Environment companion and added under capture.rfenv_companion in"
    echo "local.yaml -- this toolchain only gets you the ability to"
    echo "compile+flash that companion's firmware from this dashboard, not"
    echo "the board itself. Say yes here if that's a path you want open."
    echo ""
    read -r -p "Include the arduino-cli/ESP32 toolchain in this install? [y/N] " arduino_reply || arduino_reply=""
    case "$arduino_reply" in
        [yY]*) INSTALL_ARDUINO=1 ;;
        *) INSTALL_ARDUINO=0 ;;
    esac
fi

# A second, separate optional toolchain: PlatformIO, needed only for the
# Reticulum companion firmware card (extra/heltec_v4_reticulum_bron) --
# that project's own platformio.ini uses per-environment custom_variant/
# littlefs/symlinked-lib_deps config arduino-cli's boards.txt system can't
# express, so it can't share arduino-cli's toolchain above. Kept as its
# own prompt/flag rather than folded into --skip-arduino: someone may want
# one companion toolchain without the other. Same already-installed
# short-circuit as arduino-cli above (and same reasoning: the actual
# install step below announces "already installed, skipping" itself).
INSTALL_PLATFORMIO=1
for arg in "$@"; do
    case "$arg" in
        --skip-platformio) INSTALL_PLATFORMIO=0 ;;
    esac
done
if [ "$INSTALL_PLATFORMIO" = "1" ] && ! command -v pio &>/dev/null && [ -t 0 ]; then
    echo ""
    echo "One more optional piece: the Reticulum companion firmware card"
    echo "(Configuration -> Firmware, extra/heltec_v4_reticulum_bron) builds"
    echo "and flashes that project via PlatformIO, not arduino-cli -- a"
    echo "separate toolchain. PlatformIO manages its own ESP32 package"
    echo "downloads lazily on first build (not during this installer), so"
    echo "this step itself is quick; the multi-hundred-MB download happens"
    echo "the first time you actually use the card."
    echo ""
    read -r -p "Include the PlatformIO toolchain in this install? [y/N] " platformio_reply || platformio_reply=""
    case "$platformio_reply" in
        [yY]*) INSTALL_PLATFORMIO=1 ;;
        *) INSTALL_PLATFORMIO=0 ;;
    esac
fi

# rnsd (the Reticulum Network Stack daemon) is genuinely optional --
# most installs will never touch Reticulum at all (config.reticulum.
# enabled defaults to false). rns/lxmf are already regular Python deps
# (requirements.txt), so rnsd itself is already installed into
# /opt/meshpoint/venv/bin/rnsd by the normal venv setup below with zero
# extra work here -- this prompt is only about whether to install and
# enable the systemd service (scripts/rnsd.service) that runs it, not
# about installing rnsd itself. "systemctl is-enabled" stands in for
# "already set up", same already-installed-short-circuit reasoning as
# PlatformIO/arduino-cli above.
INSTALL_RNSD=1
for arg in "$@"; do
    case "$arg" in
        --skip-rnsd) INSTALL_RNSD=0 ;;
    esac
done
if [ "$INSTALL_RNSD" = "1" ] && ! systemctl is-enabled rnsd &>/dev/null && [ -t 0 ]; then
    echo ""
    echo "One more optional piece: native Reticulum/LXMF messaging"
    echo "(the dashboard's Reticulum page) needs rnsd running as its own"
    echo "always-on shared instance -- meshpoint attaches to it as a"
    echo "client rather than opening the radio itself. Skip this if you"
    echo "don't have an RNode or don't plan to use Reticulum; re-run this"
    echo "installer later (without --skip-rnsd) to add it, or enable it"
    echo "manually with 'systemctl enable --now rnsd'."
    echo ""
    read -r -p "Install and enable the rnsd service in this install? [y/N] " rnsd_reply || rnsd_reply=""
    case "$rnsd_reply" in
        [yY]*) INSTALL_RNSD=1 ;;
        *) INSTALL_RNSD=0 ;;
    esac
fi

# Sections 6-10 below are all downstream of one physical USB RTL-SDR
# dongle: the rtl-sdr userspace library + kernel DVB blacklist, then
# four decoders built/installed on top of it -- redsea (RDS), multimon-ng
# (POCSAG/P2000/pager digital modes), dump1090 (ADS-B air traffic), and
# welle.io (DAB+). Every one of them is dead weight without a dongle
# plugged in, and several are from-source builds, so ask once for all of
# them rather than separate prompts -- they're only ever used together
# on the RTL-SDR tab anyway.
# (The RTL433 and ACARS decoders are plugins: plugins/apps/rtl433/setup.sh
# and plugins/apps/acars/setup.sh.)
# `rtl_sdr` (the first of the four) stands in for "already set up" here,
# same reasoning as arduino-cli/PlatformIO above -- an imperfect proxy
# for all five sub-pieces, but a safe one: skipping the prompt just
# defaults to installing, which lets each step's own idempotent check
# quietly fill in (and announce) anything actually still missing.
INSTALL_RTLSDR=1
for arg in "$@"; do
    case "$arg" in
        --skip-rtlsdr) INSTALL_RTLSDR=0 ;;
    esac
done
if [ "$INSTALL_RTLSDR" = "1" ] && ! command -v rtl_sdr &>/dev/null && [ -t 0 ]; then
    echo ""
    echo "Another optional piece: the Radio tab's RTL-SDR listeners (FM/RDS,"
    echo "P2000/Pagers/POCSAG, generic 433/868 sensors, ADS-B air traffic,"
    echo "DAB+) all need a physical USB RTL-SDR dongle -- without one,"
    echo "installing their decoders (several built from source) is just"
    echo "wasted time and disk space. Skip it now and re-run this installer"
    echo "later (without --skip-rtlsdr) to add it once you have a dongle."
    echo ""
    read -r -p "Include RTL-SDR support in this install? [y/N] " rtlsdr_reply || rtlsdr_reply=""
    case "$rtlsdr_reply" in
        [yY]*) INSTALL_RTLSDR=1 ;;
        *) INSTALL_RTLSDR=0 ;;
    esac
fi

echo ""
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
info "Source directory: ${SCRIPT_DIR}"

# IS_UPGRADE itself is already set (see the welcome banner near the top
# of this script) -- kept here only as the anchor comment for what it's
# used for below.

# Read the version we're installing for the post-install banner.
INSTALL_VERSION="$(
    grep -oP '__version__ = "\K[^"]+' "${SCRIPT_DIR}/src/version.py" \
        2>/dev/null || echo "unknown"
)"

# ── Upgrade fast path: refresh venv before apt/HAL work ───────────────
# Dashboard apply stops the service, then runs this script. Git has
# already checked out the new tree, so install requirements first so
# a slow or interrupted HAL section cannot leave the service missing
# new Python deps (e.g. cryptography on v0.7.6).

_upgrade_refresh_python_deps() {
    local req="${MESHPOINT_DIR}/requirements.txt"
    local pip="${MESHPOINT_DIR}/venv/bin/pip"
    if [ ! -x "$pip" ] || [ ! -f "$req" ]; then
        warn "Skipping early pip refresh (venv or requirements missing)"
        return 0
    fi
    info "Refreshing Python dependencies (upgrade fast path)..."
    # lgpio in requirements.txt builds a C extension: it needs swig +
    # python3-dev to compile and liblgpio-dev to link (no piwheels wheel).
    # Ensure they exist before pip runs, or set -e aborts the upgrade here.
    apt-get install -y -qq python3-dev swig liblgpio-dev 2>/dev/null \
        || warn "Could not preinstall lgpio build deps (pip may fail)"
    "$pip" install --upgrade pip -q
    "$pip" install -r "$req" -q
    "$pip" install pyserial -q
}

if [ "$IS_UPGRADE" = "1" ]; then
    _upgrade_refresh_python_deps
fi

# ── 1. System packages ─────────────────────────────────────────────

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
    swig \
    liblgpio-dev \
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
    build-essential \
    pipx

# ── 2. Enable SPI ─────────────────────────────────────────────────

info "Enabling SPI interface..."
raspi-config nonint do_spi 0 2>/dev/null || warn "raspi-config SPI failed (may already be enabled)"

# ── 3. Enable I2C ─────────────────────────────────────────────────

info "Enabling I2C interface..."
raspi-config nonint do_i2c 0 2>/dev/null || warn "raspi-config I2C failed (may already be enabled)"

# ── 4. Enable UART for GPS ────────────────────────────────────────

info "Enabling UART hardware..."
raspi-config nonint do_serial_hw 0 2>/dev/null || warn "raspi-config UART failed"

info "Disabling serial console (needed for GPS on /dev/ttyAMA0)..."
raspi-config nonint do_serial_cons 1 2>/dev/null || warn "raspi-config serial console failed"

# Disable Bluetooth on primary UART so GPS gets /dev/ttyAMA0
if [ -f "$BOOT_CONFIG" ]; then
    if ! grep -q "dtoverlay=disable-bt" "$BOOT_CONFIG"; then
        info "Adding dtoverlay=disable-bt to ${BOOT_CONFIG}"
        echo "" >> "$BOOT_CONFIG"
        echo "# Meshpoint: free primary UART for GPS" >> "$BOOT_CONFIG"
        echo "dtoverlay=disable-bt" >> "$BOOT_CONFIG"
    else
        info "dtoverlay=disable-bt already present"
    fi
fi

# ── 5. Install gpsd for USB GPS receivers ─────────────────────────
#
# Enables plug-and-play USB GPS sticks (u-blox 7/8 etc) without
# changes to local.yaml. udev auto-attaches recognized devices to
# the gpsd daemon; the Meshpoint LocationSource (source: gpsd) reads
# from gpsd's TCP socket on 127.0.0.1:2947.
#
# Idempotent: re-running install.sh does not rewrite a config that
# already matches.

info "Installing gpsd for USB GPS receivers..."
apt-get install -y -qq gpsd gpsd-clients

GPSD_DEFAULTS="/etc/default/gpsd"
if [ -f "$GPSD_DEFAULTS" ]; then
    # Desired settings:
    #   START_DAEMON="true"  -- start at boot
    #   USBAUTO="true"       -- udev auto-attaches recognized USB GPS
    #   DEVICES=""           -- empty so udev owns the device list
    #   GPSD_OPTIONS="-n"    -- no-wait mode, opens device before first client
    GPSD_NEEDS_WRITE=0
    grep -q '^START_DAEMON="true"' "$GPSD_DEFAULTS" || GPSD_NEEDS_WRITE=1
    grep -q '^USBAUTO="true"'      "$GPSD_DEFAULTS" || GPSD_NEEDS_WRITE=1
    grep -q '^DEVICES=""'          "$GPSD_DEFAULTS" || GPSD_NEEDS_WRITE=1
    grep -q '^GPSD_OPTIONS="-n"'   "$GPSD_DEFAULTS" || GPSD_NEEDS_WRITE=1

    if [ "$GPSD_NEEDS_WRITE" = "1" ]; then
        info "Configuring ${GPSD_DEFAULTS} for USB hotplug..."
        cat > "$GPSD_DEFAULTS" <<'_GPSD_DEFAULTS'
# Default settings for the gpsd init script and the hotplug wrapper.
# Managed by Meshpoint installer. Re-run scripts/install.sh to reset.

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

# ── 6. Install RTL-SDR support (USB SDR dongle, Radio tab listener) ─
#
# Two things a stock Raspberry Pi OS image is missing for an RTL-SDR
# dongle to work: the kernel's own DVB driver claims the RTL2832U chip
# before rtl-sdr's userspace tools can open it, and there's no rtl-sdr
# package installed at all. Built from source (osmocom upstream) rather
# than `apt install rtl-sdr`, matching what a from-source install lets
# you swap in a vendor fork later (e.g. RTL-SDR Blog's own fork for
# their V4/R828D dongle) without an apt package fighting it.
#
# Idempotent: skips the kernel blacklist if already present, skips the
# clone+build if librtlsdr is already installed.

if [ "$INSTALL_RTLSDR" = "1" ]; then
    RTLSDR_BUILD_DIR="/opt/rtl-sdr"
    DVB_BLACKLIST_FILE="/etc/modprobe.d/blacklist-rtlsdr-dvb.conf"

    info "Blacklisting the kernel DVB-T stack (conflicts with rtl-sdr userspace tools)..."
    if [ -f "$DVB_BLACKLIST_FILE" ] && grep -q '^blacklist dvb_usb_rtl28xxu' "$DVB_BLACKLIST_FILE"; then
        info "DVB-T stack already blacklisted"
    else
        cat > "$DVB_BLACKLIST_FILE" <<'_DVB_BLACKLIST'
# Managed by Meshpoint installer. The kernel's DVB-T driver stack
# (usb bridge + demodulator + tuner-support modules) claims the
# RTL2832U chip on boot, which then can't be opened by rtl-sdr's own
# userspace driver (rtl_fm, rtl_test, etc). Re-run scripts/install.sh
# to restore this file if removed.
blacklist dvb_usb_rtl28xxu
blacklist rtl_2832
blacklist rtl_2830
_DVB_BLACKLIST
    fi
    # Also unload them right now if a dongle was already plugged in this
    # boot -- the blacklist file alone only takes effect on the NEXT boot.
    # Unload order matters: the usb bridge module depends on the
    # demodulator modules, so it must go first or -r fails with "in use".
    modprobe -r dvb_usb_rtl28xxu 2>/dev/null || true
    modprobe -r rtl_2832 2>/dev/null || true
    modprobe -r rtl_2830 2>/dev/null || true

    if command -v rtl_sdr &>/dev/null; then
        info "librtlsdr already installed, skipping RTL-SDR build"
    else
        info "Cloning and building rtl-sdr..."
        rm -rf "$RTLSDR_BUILD_DIR"
        git clone --depth 1 git://git.osmocom.org/rtl-sdr.git "$RTLSDR_BUILD_DIR"
        mkdir -p "${RTLSDR_BUILD_DIR}/build"
        (
            cd "${RTLSDR_BUILD_DIR}/build"
            cmake ../ -DINSTALL_UDEV_RULES=ON
            make -j"$(nproc)"
            make install
            ldconfig
        )
    fi

    # ── 7. Install redsea (RTL-SDR RDS decoder) ───────────────────────
    #
    # Decodes RDS (station name, radio text, PI code) out of FM broadcast
    # capture, on top of the librtlsdr built in 3c. Built from source
    # (windytan/redsea upstream) via meson, same rationale as rtl-sdr:
    # no distro package tracks upstream closely enough.
    #
    # Idempotent: skips the clone+build if the redsea binary already exists.

    REDSEA_BUILD_DIR="/opt/redsea"

    if command -v redsea &>/dev/null; then
        info "redsea already installed, skipping build"
    else
        info "Cloning and building redsea..."
        rm -rf "$REDSEA_BUILD_DIR"
        git clone --depth 1 https://github.com/windytan/redsea.git "$REDSEA_BUILD_DIR"
        (
            cd "$REDSEA_BUILD_DIR"
            meson setup build
            cd build
            meson compile
            meson install
            ldconfig
        )
    fi

    # ── 8. Install multimon-ng (RTL-SDR digital mode decoder) ─────────
    #
    # Decodes POCSAG/AFSK/DTMF/etc out of demodulated audio, fed from
    # `rtl_fm` piped in. Built from source (EliasOenal/multimon-ng
    # upstream) via CMake -- the project dropped its old qt4-qmake build
    # system entirely, so no Qt4 packages are needed (and qt4-qmake isn't
    # even in current Raspberry Pi OS repos anymore).
    #
    # Idempotent: skips the clone+build if the multimon-ng binary already
    # exists.

    MULTIMON_BUILD_DIR="/opt/multimon-ng"

    if command -v multimon-ng &>/dev/null; then
        info "multimon-ng already installed, skipping build"
    else
        info "Cloning and building multimon-ng..."
        rm -rf "$MULTIMON_BUILD_DIR"
        git clone --depth 1 https://github.com/EliasOenal/multimon-ng.git "$MULTIMON_BUILD_DIR"
        (
            cd "$MULTIMON_BUILD_DIR"
            cmake -S . -B build
            cmake --build build --parallel "$(nproc)"
            cmake --install build
            ldconfig
        )
    fi

    # ── 9. Install dump1090 (RTL-SDR ADS-B air traffic decoder) ──────
    #
    # Decodes 1090ES ADS-B squitters from aircraft transponders off the
    # RTL-SDR dongle, on top of the librtlsdr built in section 6. Built
    # from source (MalcolmRobb/dump1090 fork -- adds interactive mode and
    # network output on top of the original antirez/dump1090). Upstream's
    # Makefile has no `install` target, so the binaries are copied to
    # /usr/local/bin by hand after the build. EXTRACFLAGS=-fcommon works
    # around this 2016-era codebase's tentative global definitions (Modes,
    # tDF, etc. declared without `extern` in dump1090.h) hitting multiple
    # definition link errors under GCC 10+, which defaults to -fno-common.
    #
    # Idempotent: skips the clone+build if the dump1090 binary already
    # exists.

    DUMP1090_BUILD_DIR="/opt/dump1090"

    if command -v dump1090 &>/dev/null; then
        info "dump1090 already installed, skipping build"
    else
        info "Cloning and building dump1090..."
        rm -rf "$DUMP1090_BUILD_DIR"
        git clone --depth 1 https://github.com/MalcolmRobb/dump1090.git "$DUMP1090_BUILD_DIR"
        (
            cd "$DUMP1090_BUILD_DIR"
            make -j"$(nproc)" EXTRACFLAGS=-fcommon
            install -m 755 dump1090 view1090 /usr/local/bin/
        )
    fi

    # ── 10. Install welle.io (DAB+ tab) ───────────────────────────────
    #
    # The Debian/Raspberry Pi OS `welle.io` package ships both the GUI
    # app and the headless `welle-cli` binary Meshpoint's DAB+ tab
    # actually drives (src/audio/dab_listener.py spawns
    # `welle-cli -c <channel> -w <port>` and talks to its embedded
    # webserver) -- confirmed live on this hardware, not assumed.
    # --no-install-recommends skips the Qt/QML GUI dependency chain that
    # only the GUI app needs (~87 MB installed otherwise); welle-cli
    # itself has no GUI dependencies.
    #
    # Idempotent: skips the apt install if welle-cli already exists.

    if command -v welle-cli &>/dev/null; then
        info "welle.io (welle-cli) already installed, skipping"
    else
        info "Installing welle.io (DAB+)..."
        apt-get install -y -qq --no-install-recommends welle.io
    fi

    # RTL433 (generic 433/868 OOK/FSK decoder) and ACARS (aircraft VHF
    # datalink) are plugins, not part of core -- their installs live in
    # plugins/apps/rtl433/setup.sh and plugins/apps/acars/setup.sh. Run
    # those separately if you want the RTL433 / ACARS tabs.
else
    info "Skipping RTL-SDR support (sections 6-11) -- re-run without --skip-rtlsdr, or answer Y next time, to add it later"
fi

# ── 12. Install Meshtastic and MeshCore CLI tools ─────────────────
#
# Optional command-line tools for poking at connected radios directly
# from the shell -- not used by Meshpoint itself (which talks to them
# via meshtastic-python/meshcore-python instead), just handy for admin
# debugging on the Pi. meshtastic-cli via pip3 (needs
# --break-system-packages since Debian's system Python is PEP
# 668-protected); meshcore-cli via pipx (isolated venv per tool,
# already installed as a system package in section 1).
#
# Idempotent: each tool skips its own install if its binary already
# exists, same as sections 7-9 above.

if command -v meshtastic &>/dev/null; then
    info "Meshtastic CLI already installed, skipping"
else
    info "Installing Meshtastic CLI..."
    pip3 install --upgrade "meshtastic[cli]" --break-system-packages
fi

# esptool as a bare system command -- NOT the copy arduino-cli's esp32
# core already bundles (buried inside /opt/arduino-cli/data/packages/
# esp32/tools/esptool_py/<version>/, never on PATH). Meshtastic's own
# official flashing scripts (device-install.sh/device-update.sh) and
# manual `esptool` invocations both expect a plain `esptool` command,
# same as arduino-cli itself needed its own install rather than reusing
# some other copy.
if command -v esptool &>/dev/null; then
    info "esptool already installed, skipping"
else
    info "Installing esptool..."
    pip3 install --upgrade esptool --break-system-packages
fi

# command -v alone isn't reliable here: pipx symlinks into
# ~/.local/bin, which `pipx ensurepath` only adds to *future* login
# shells' rc files -- not this script's own current PATH, and not
# necessarily the next run's either. Without the second check, a
# successfully-installed meshcore-cli still looks "missing" and gets
# reinstalled on every single run. Also check pipx's own install
# record directly (same idea as the rtl-sdr fix: test the real
# installed thing, not a proxy for it).
if command -v meshcore-cli &>/dev/null || [ -d "$HOME/.local/share/pipx/venvs/meshcore-cli" ]; then
    info "MeshCore CLI already installed, skipping"
else
    info "Installing MeshCore CLI..."
    pipx install meshcore-cli
    pipx ensurepath
fi

# ── 13. Install arduino-cli + ESP32 toolchain (companion firmware flashing) ──
#
# General-purpose ESP32 build+flash toolchain -- not specific to any one
# companion. arduino-cli plus the esp32:esp32 board core (which bundles
# esptool underneath) can compile+upload any Arduino-sketch firmware for
# any ESP32 target, and esptool alone can write any pre-built .bin
# straight to a connected board regardless of what produced it. First
# concrete use planned on top of this is a Networks > DAPNET "flash
# firmware" button for extra/pocsag_companion/pocsag_companion.ino (an
# Arduino sketch, hence the sketch-specific libraries installed below),
# but the same toolchain is equally usable later for flashing official
# prebuilt Meshtastic/MeshCore firmware .bin releases via esptool, or any
# other ESP32 companion sketch this project adds down the line.
#
# Installed as a fully self-contained toolchain under /opt/arduino-cli --
# its own config file, board/library data, and downloads cache -- rather
# than the default ~/.arduino15 under a user's home: the systemd service
# that will actually invoke this at runtime runs as `meshpoint`, a
# --no-create-home system account with no $HOME of its own (see the
# user-creation section below), so a home-relative default would
# silently break the very context this is built for.
#
# Idempotent: skips each step (binary, config, core, each library) if
# already installed/present, same pattern as the other build-from-source
# sections above.

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
        # ARDUINO_CLI_HOME/cache also gets pre-created here (not just data/
        # user/downloads, which the config file itself controls) because
        # arduino-cli's build cache is a separate concept with no config-file
        # key -- it always resolves via Go's os.UserCacheDir() ($XDG_CACHE_HOME,
        # else $HOME/.cache). `meshpoint` (below) is a --no-create-home system
        # account, so without XDG_CACHE_HOME pointed here explicitly (see
        # meshpoint.service's Environment= line), a compile as that user fails
        # trying to mkdir a cache dir under a $HOME that doesn't exist.
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

    # Upfront skip check, same shape as arduino-cli/esp32 core just
    # above: arduino-cli's own `lib install` is already idempotent
    # (an "Already installed X@Y" line means no download happened --
    # nothing here ever re-fetches these on a routine re-run), but it
    # still re-ran a check per library every time with no whole-step
    # short-circuit. Folder names use arduino-cli's own library-
    # manager convention (spaces -> underscores) under
    # directories.user/libraries -- a name that doesn't match just
    # falls through to the existing always-safe install loop below,
    # same fail-open behavior as before this check existed.
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

    # The `meshpoint` system user isn't created until step 20 (it needs
    # MESHPOINT_DIR to exist first, for its own chown/group-grant work) --
    # but this chown needs it NOW, on a fresh install with no prior run.
    # Same idempotent `id -u` guard step 20 uses; that step's own guard
    # then just sees the user already exists and skips re-creating it.
    if ! id -u meshpoint &>/dev/null; then
        useradd --system --no-create-home --shell /usr/sbin/nologin meshpoint
    fi
    chown -R meshpoint:meshpoint "$ARDUINO_CLI_HOME"
else
    info "Skipping arduino-cli/ESP32 toolchain (POCSAG/Pager/RF Environment Compile+Flash won't be available) -- re-run without --skip-arduino, or answer Y next time, to add it later"
fi

# ── 14. Install PlatformIO toolchain (Reticulum companion firmware) ──
#
# Separate from arduino-cli above: extra/heltec_v4_reticulum_bron's own
# platformio.ini needs PlatformIO specifically (custom_variant/littlefs/
# symlinked lib_deps -- arduino-cli's boards.txt system can't express
# any of that). Unlike arduino-cli's board core, PlatformIO downloads
# its ESP32 platform/toolchain lazily on first `pio run`, not here --
# this step only installs the `pio` command itself, so it's quick.
#
# Installed into its own venv under /opt/platformio (not a pipx/pip
# --user install into some invoking user's $HOME): the systemd service
# that will actually invoke this at runtime runs as `meshpoint`, a
# --no-create-home system account with no $HOME of its own -- same
# reasoning as arduino-cli's /opt/arduino-cli home above. A symlink at
# /usr/local/bin/pio puts it on PATH for that account without needing
# one, and PLATFORMIO_CORE_DIR (set in meshpoint.service, mirroring
# arduino-cli's XDG_CACHE_HOME there) points PlatformIO's own downloaded-
# package/toolchain cache at a real directory that account can write to.
#
# Idempotent: skips if the venv already exists, same pattern as the
# other build-from-source sections above.

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
    info "Skipping PlatformIO toolchain (Reticulum companion firmware Compile+Flash won't be available) -- re-run without --skip-platformio, or answer Y next time, to add it later"
fi

# ── 15. Build SX1302 HAL ──────────────────────────────────────────

if [ -f "/usr/local/lib/libloragw.so" ]; then
    info "libloragw.so already installed, skipping HAL build"
else
    info "Cloning SX1302 HAL..."
    rm -rf "$HAL_BUILD_DIR"
    git clone --depth 1 https://github.com/Lora-net/sx1302_hal.git "$HAL_BUILD_DIR"

    info "Configuring HAL source..."
    python3 - "${HAL_BUILD_DIR}/libloragw/src/loragw_sx1302.c" \
              "${HAL_BUILD_DIR}/libloragw/src/loragw_hal.c" <<'_HALCFG'
import sys
from pathlib import Path

def _rd(p):
    f = Path(p)
    if not f.is_file():
        print("FAIL: " + p); sys.exit(1)
    return f, f.read_text().replace("\r\n", "\n")

f1, s1 = _rd(sys.argv[1])
f2, s2 = _rd(sys.argv[2])

_A = """\
    int err = LGW_REG_SUCCESS;

    /* Multi-SF modem configuration */
    DEBUG_MSG("INFO: configuring LoRa (Multi-SF) SF5->SF6 with syncword PRIVATE (0x12)\\n");
    err |= lgw_reg_w(SX1302_REG_RX_TOP_FRAME_SYNCH0_SF5_PEAK1_POS_SF5, 2);
    err |= lgw_reg_w(SX1302_REG_RX_TOP_FRAME_SYNCH1_SF5_PEAK2_POS_SF5, 4);
    err |= lgw_reg_w(SX1302_REG_RX_TOP_FRAME_SYNCH0_SF6_PEAK1_POS_SF6, 2);
    err |= lgw_reg_w(SX1302_REG_RX_TOP_FRAME_SYNCH1_SF6_PEAK2_POS_SF6, 4);
    if (public == true) {
        DEBUG_MSG("INFO: configuring LoRa (Multi-SF) SF7->SF12 with syncword PUBLIC (0x34)\\n");
        err |= lgw_reg_w(SX1302_REG_RX_TOP_FRAME_SYNCH0_SF7TO12_PEAK1_POS_SF7TO12, 6);
        err |= lgw_reg_w(SX1302_REG_RX_TOP_FRAME_SYNCH1_SF7TO12_PEAK2_POS_SF7TO12, 8);
    } else {
        DEBUG_MSG("INFO: configuring LoRa (Multi-SF) SF7->SF12 with syncword PRIVATE (0x12)\\n");
        err |= lgw_reg_w(SX1302_REG_RX_TOP_FRAME_SYNCH0_SF7TO12_PEAK1_POS_SF7TO12, 2);
        err |= lgw_reg_w(SX1302_REG_RX_TOP_FRAME_SYNCH1_SF7TO12_PEAK2_POS_SF7TO12, 4);
    }

    /* LoRa Service modem configuration */
    if ((public == false) || (lora_service_sf == DR_LORA_SF5) || (lora_service_sf == DR_LORA_SF6)) {
        DEBUG_PRINTF("INFO: configuring LoRa (Service) SF%u with syncword PRIVATE (0x12)\\n", lora_service_sf);
        err |= lgw_reg_w(SX1302_REG_RX_TOP_LORA_SERVICE_FSK_FRAME_SYNCH0_PEAK1_POS, 2);
        err |= lgw_reg_w(SX1302_REG_RX_TOP_LORA_SERVICE_FSK_FRAME_SYNCH1_PEAK2_POS, 4);
    } else {
        DEBUG_PRINTF("INFO: configuring LoRa (Service) SF%u with syncword PUBLIC (0x34)\\n", lora_service_sf);
        err |= lgw_reg_w(SX1302_REG_RX_TOP_LORA_SERVICE_FSK_FRAME_SYNCH0_PEAK1_POS, 6);
        err |= lgw_reg_w(SX1302_REG_RX_TOP_LORA_SERVICE_FSK_FRAME_SYNCH1_PEAK2_POS, 8);
    }

    return err;"""

_B = """\
    int err = LGW_REG_SUCCESS;

    uint8_t sw_reg1, sw_reg2;
    if (public == true) {
        sw_reg1 = 6;
        sw_reg2 = 8;
    } else if (lora_service_sf > 12) {
        sw_reg1 = ((lora_service_sf >> 4) & 0x0F) * 2;
        sw_reg2 = (lora_service_sf & 0x0F) * 2;
        DEBUG_PRINTF("INFO: sync cfg 0x%02X -> %u, %u\\n", lora_service_sf, sw_reg1, sw_reg2);
    } else {
        sw_reg1 = 2;
        sw_reg2 = 4;
    }

    sx1302_tx_sw_peak1 = sw_reg1;
    sx1302_tx_sw_peak2 = sw_reg2;

    err |= lgw_reg_w(SX1302_REG_RX_TOP_FRAME_SYNCH0_SF5_PEAK1_POS_SF5, sw_reg1);
    err |= lgw_reg_w(SX1302_REG_RX_TOP_FRAME_SYNCH1_SF5_PEAK2_POS_SF5, sw_reg2);
    err |= lgw_reg_w(SX1302_REG_RX_TOP_FRAME_SYNCH0_SF6_PEAK1_POS_SF6, sw_reg1);
    err |= lgw_reg_w(SX1302_REG_RX_TOP_FRAME_SYNCH1_SF6_PEAK2_POS_SF6, sw_reg2);

    err |= lgw_reg_w(SX1302_REG_RX_TOP_FRAME_SYNCH0_SF7TO12_PEAK1_POS_SF7TO12, sw_reg1);
    err |= lgw_reg_w(SX1302_REG_RX_TOP_FRAME_SYNCH1_SF7TO12_PEAK2_POS_SF7TO12, sw_reg2);

    err |= lgw_reg_w(SX1302_REG_RX_TOP_LORA_SERVICE_FSK_FRAME_SYNCH0_PEAK1_POS, sw_reg1);
    err |= lgw_reg_w(SX1302_REG_RX_TOP_LORA_SERVICE_FSK_FRAME_SYNCH1_PEAK2_POS, sw_reg2);

    return err;"""

if "sw_reg1" in s1:
    pass
elif _A in s1:
    s1 = s1.replace(_A, _B, 1)
else:
    print("FAIL: source mismatch in " + str(f1)); sys.exit(1)

_TX_A = """\
    /* Syncword */
    if ((lwan_public == false) || (pkt_data->datarate == DR_LORA_SF5) || (pkt_data->datarate == DR_LORA_SF6)) {
        DEBUG_MSG("Setting LoRa syncword 0x12\\n");
        err = lgw_reg_w(SX1302_REG_TX_TOP_FRAME_SYNCH_0_PEAK1_POS(pkt_data->rf_chain), 2);
        CHECK_ERR(err);
        err = lgw_reg_w(SX1302_REG_TX_TOP_FRAME_SYNCH_1_PEAK2_POS(pkt_data->rf_chain), 4);
        CHECK_ERR(err);
    } else {
        DEBUG_MSG("Setting LoRa syncword 0x34\\n");
        err = lgw_reg_w(SX1302_REG_TX_TOP_FRAME_SYNCH_0_PEAK1_POS(pkt_data->rf_chain), 6);
        CHECK_ERR(err);
        err = lgw_reg_w(SX1302_REG_TX_TOP_FRAME_SYNCH_1_PEAK2_POS(pkt_data->rf_chain), 8);
        CHECK_ERR(err);
    }"""

_TX_B = """\
    /* Syncword */
    err = lgw_reg_w(SX1302_REG_TX_TOP_FRAME_SYNCH_0_PEAK1_POS(pkt_data->rf_chain), sx1302_tx_sw_peak1);
    CHECK_ERR(err);
    err = lgw_reg_w(SX1302_REG_TX_TOP_FRAME_SYNCH_1_PEAK2_POS(pkt_data->rf_chain), sx1302_tx_sw_peak2);
    CHECK_ERR(err);"""

if "static uint8_t sx1302_tx_sw_peak1" not in s1:
    s1 = s1.replace("int sx1302_lora_syncword(", "static uint8_t sx1302_tx_sw_peak1 = 2;\nstatic uint8_t sx1302_tx_sw_peak2 = 4;\n\nint sx1302_lora_syncword(", 1)

if "sx1302_tx_sw_peak1 = sw_reg1" not in s1:
    s1 = s1.replace("    sw_reg2 = 4;\n    }\n\n    err |= lgw_reg_w(SX1302_REG_RX_TOP_FRAME_SYNCH0_SF5_PEAK1_POS_SF5", "    sw_reg2 = 4;\n    }\n\n    sx1302_tx_sw_peak1 = sw_reg1;\n    sx1302_tx_sw_peak2 = sw_reg2;\n\n    err |= lgw_reg_w(SX1302_REG_RX_TOP_FRAME_SYNCH0_SF5_PEAK1_POS_SF5", 1)

if _TX_A in s1:
    s1 = s1.replace(_TX_A, _TX_B, 1)

f1.write_text(s1, newline="\n")

_C = [
("""\
        /* Find the temperature sensor on the known supported ports */
        for (i = 0; i < (int)(sizeof I2C_PORT_TEMP_SENSOR); i++) {
            ts_addr = I2C_PORT_TEMP_SENSOR[i];
            err = i2c_linuxdev_open(I2C_DEVICE, ts_addr, &ts_fd);
            if (err != LGW_I2C_SUCCESS) {
                printf("ERROR: failed to open I2C for temperature sensor on port 0x%02X\\n", ts_addr);
                return LGW_HAL_ERROR;
            }

            err = stts751_configure(ts_fd, ts_addr);
            if (err != LGW_I2C_SUCCESS) {
                printf("INFO: no temperature sensor found on port 0x%02X\\n", ts_addr);
                i2c_linuxdev_close(ts_fd);
                ts_fd = -1;
            } else {
                printf("INFO: found temperature sensor on port 0x%02X\\n", ts_addr);
                break;
            }
        }
        if (i == sizeof I2C_PORT_TEMP_SENSOR) {
            printf("ERROR: no temperature sensor found.\\n");
            return LGW_HAL_ERROR;
        }""",
"""\
        /* Find the temperature sensor on the known supported ports */
        for (i = 0; i < (int)(sizeof I2C_PORT_TEMP_SENSOR); i++) {
            ts_addr = I2C_PORT_TEMP_SENSOR[i];
            err = i2c_linuxdev_open(I2C_DEVICE, ts_addr, &ts_fd);
            if (err != LGW_I2C_SUCCESS) {
                printf("WARNING: could not open I2C on port 0x%02X\\n", ts_addr);
                ts_fd = -1;
                continue;
            }

            err = stts751_configure(ts_fd, ts_addr);
            if (err != LGW_I2C_SUCCESS) {
                printf("INFO: no temperature sensor found on port 0x%02X\\n", ts_addr);
                i2c_linuxdev_close(ts_fd);
                ts_fd = -1;
            } else {
                printf("INFO: found temperature sensor on port 0x%02X\\n", ts_addr);
                break;
            }
        }
        if (ts_fd < 0) {
            printf("WARNING: sensor not available, using default\\n");
        }"""),
("""\
        case LGW_COM_SPI:
            err = stts751_get_temperature(ts_fd, ts_addr, temperature);
            break;""",
"""\
        case LGW_COM_SPI:
            if (ts_fd > 0) {
                err = stts751_get_temperature(ts_fd, ts_addr, temperature);
            } else {
                *temperature = 25.0;
                err = LGW_HAL_SUCCESS;
            }
            break;"""),
("""\
        DEBUG_MSG("INFO: Closing I2C for temperature sensor\\n");
        x = i2c_linuxdev_close(ts_fd);
        if (x != 0) {
            printf("ERROR: failed to close I2C temperature sensor device (err=%i)\\n", x);
            err = LGW_HAL_ERROR;
        }""",
"""\
        if (ts_fd > 0) {
            DEBUG_MSG("INFO: Closing I2C for temperature sensor\\n");
            x = i2c_linuxdev_close(ts_fd);
            if (x != 0) {
                printf("ERROR: failed to close I2C temperature sensor device (err=%i)\\n", x);
                err = LGW_HAL_ERROR;
            }
        }"""),
]

ok = True
for o, n in _C:
    if n in s2:
        continue
    if o not in s2:
        ok = False; break
    s2 = s2.replace(o, n, 1)
if ok:
    f2.write_text(s2, newline="\n")
else:
    print("FAIL: source mismatch in " + str(f2)); sys.exit(1)
_HALCFG

    info "Compiling libloragw (this takes a few minutes)..."
    cd "$HAL_BUILD_DIR"
    make clean 2>/dev/null || true
    make -j"$(nproc)"

    info "Recompiling with -fPIC for shared library..."
    mkdir -p pic_obj

    for src in libtools/src/*.c; do
        gcc -c -O2 -fPIC -Wall -Wextra -std=c99 \
            -Ilibtools/inc -Ilibtools \
            "$src" -o "pic_obj/$(basename "${src%.c}.o")"
    done

    for src in libloragw/src/*.c; do
        gcc -c -O2 -fPIC -Wall -Wextra -std=c99 \
            -Ilibloragw/inc -Ilibloragw -Ilibtools/inc \
            "$src" -o "pic_obj/$(basename "${src%.c}.o")"
    done

    info "Linking libloragw.so..."
    gcc -shared -o libloragw/libloragw.so pic_obj/*.o -lrt -lm -lpthread

    info "Installing libloragw.so..."
    cp libloragw/libloragw.so /usr/local/lib/
    ldconfig
    info "libloragw.so installed to /usr/local/lib/"
fi

# ── 16. Apply TX sync word patch ──────────────────────────────────

HAL_SRC="${HAL_BUILD_DIR}/libloragw/src/loragw_sx1302.c"
if [ -f "$HAL_SRC" ]; then
    info "Applying TX sync word patch..."
    # MESHPOINT_INSTALL_IN_PROGRESS tells patch_hal.sh to skip its own
    # "restart now" suggestion -- several install.sh sections still run
    # after this one, and this whole script may itself be running inside
    # the dashboard's web Terminal, whose PTY is a child process in
    # meshpoint's own systemd cgroup. Acting on a restart suggestion this
    # early kills that PTY (and the rest of this install run) before the
    # remaining sections (sudoers, systemd service, watchdog, CLI tools)
    # ever run -- a real SSH shell isn't in that cgroup and wouldn't be
    # affected, which is why this only ever breaks the web Terminal.
    # install.sh's own final banner is the one correctly-timed prompt.
    MESHPOINT_INSTALL_IN_PROGRESS=1 bash "${SCRIPT_DIR}/scripts/patch_hal.sh"
fi

# ── 17. Install Meshpoint application ─────────────────────────────

info "Installing Meshpoint to ${MESHPOINT_DIR}..."
mkdir -p "$MESHPOINT_DIR"

rsync -a --exclude='venv' \
         --exclude='__pycache__' \
         --exclude='cdk.out' \
         --exclude='cloud/build' \
         --exclude='data' \
         --exclude='*.pyc' \
         "${SCRIPT_DIR}/" "$MESHPOINT_DIR/"

# rsync -a --exclude='venv' \
#          --exclude='.git' \
#          --exclude='__pycache__' \
#          --exclude='cdk.out' \
#          --exclude='cloud/build' \
#          --exclude='data' \
#          --exclude='*.pyc' \
#          "${SCRIPT_DIR}/" "$MESHPOINT_DIR/"

# ── 18. Remove stale compiled core modules from prior installs ───
# Releases before 0.7.0 shipped .cpython-*.so files alongside the
# .py source. Python prefers the .so at import time, so any leftover
# binary would silently shadow the current source. rsync above does
# not delete files that are absent from the source tree, so we
# explicitly clean them up here.

if find "${MESHPOINT_DIR}/src" -name '*.cpython-*.so' -print -quit | grep -q .; then
    info "Removing stale compiled modules from previous installation..."
    find "${MESHPOINT_DIR}/src" -name '*.cpython-*.so' -delete
fi

# ── 19. Python virtual environment ────────────────────────────────

info "Setting up Python virtual environment..."
python3 -m venv "${MESHPOINT_DIR}/venv"
source "${MESHPOINT_DIR}/venv/bin/activate"

pip install --upgrade pip -q
pip install -r "${MESHPOINT_DIR}/requirements.txt" -q
pip install pyserial -q
deactivate

# ── 20. Create data directory ─────────────────────────────────────

mkdir -p "${MESHPOINT_DIR}/data"

# ── 21. Create meshpoint system user ──────────────────────────────

if ! id -u meshpoint &>/dev/null; then
    info "Creating system user 'meshpoint'..."
    useradd --system --no-create-home --shell /usr/sbin/nologin meshpoint
fi

# Grant access to SPI, UART, GPIO, and I2C
usermod -a -G spi,gpio,dialout,i2c meshpoint 2>/dev/null || true

# Grant the service user read access to its own systemd journal so the
# dashboard's `meshpoint logs` button (and `journalctl -u meshpoint`
# inside the web terminal) work without sudo. This is the same group
# Raspberry Pi OS uses to gate journal access for the `pi` user.
usermod -a -G systemd-journal,adm meshpoint 2>/dev/null || true
# Grant access to audio/video/plugdev for USB GPS and USB LoRa devices.
usermod -a -G audio,video,plugdev meshpoint 2>/dev/null || true
#
# Whole tree to the service user (not just data/ and config/): plain-git
# update checks need .git writable, and lgpio's fan-control pipe lands in
# the WorkingDirectory itself. The service unit + post_update.sh re-apply
# this after every dashboard apply (sudo git leaves root-owned files).
chown -R meshpoint:meshpoint "${MESHPOINT_DIR}"

# The apply chain still runs git as root (sudo) on the meshpoint-owned
# tree, so git would refuse with "detected dubious ownership". Trust the
# repo for every user (root, meshpoint, pi). Idempotent — no duplicates.
if [ -d "${MESHPOINT_DIR}/.git" ]; then
    git config --system --get-all safe.directory 2>/dev/null \
        | grep -qx "${MESHPOINT_DIR}" \
        || git config --system --add safe.directory "${MESHPOINT_DIR}"
fi

# Espressif USB serial devices (Heltec V3/V4, T-Beam ESP32-S3) may not
# default to dialout group on all Pi OS versions. Add a udev rule so
# the meshpoint service user can access them for relay and MeshCore.
UDEV_RULE='SUBSYSTEM=="tty", ATTRS{idVendor}=="303a", MODE="0666"'
UDEV_FILE="/etc/udev/rules.d/99-meshpoint-esp.rules"
if [ ! -f "$UDEV_FILE" ]; then
    info "Installing udev rule for Espressif USB serial devices..."
    echo "$UDEV_RULE" > "$UDEV_FILE"
    udevadm control --reload-rules 2>/dev/null || true
    udevadm trigger 2>/dev/null || true
fi

# Allow service user to restart/stop its own service (dashboard + remote commands)
info "Installing sudoers rule for service management..."
cp "${MESHPOINT_DIR}/config/sudoers-meshpoint" /etc/sudoers.d/meshpoint
chmod 440 /etc/sudoers.d/meshpoint

# ── 22. Configure journald log rotation ───────────────────────────

info "Configuring journald log limits (100M, 7-day retention)..."
mkdir -p /etc/systemd/journald.conf.d
cp "${MESHPOINT_DIR}/config/journald-meshpoint.conf" /etc/systemd/journald.conf.d/meshpoint.conf
systemctl restart systemd-journald 2>/dev/null || warn "Could not restart journald"

# ── 23. Install systemd service ───────────────────────────────────

info "Installing systemd service..."
cp "${MESHPOINT_DIR}/${SERVICE_FILE}" /etc/systemd/system/meshpoint.service
systemctl daemon-reload
systemctl enable meshpoint
info "Service enabled (will start after 'meshpoint setup')"

# ── 24. Install rnsd service (Reticulum, opt-in) ──────────────────
#
# Deliberately NOT a dependency of meshpoint.service (see that unit's
# own After=rnsd.service comment) -- installed and enabled
# independently so meshpoint's core service never requires this to
# exist or succeed. write_rnsd_config.py (rnsd.service's own
# ExecStartPre) generates rnsd's config from local.yaml's reticulum:
# section on every start, so nothing needs configuring here beyond the
# service itself -- the RNode serial port etc. get set later via
# local.yaml/the dashboard.

if [ "$INSTALL_RNSD" = "1" ]; then
    info "Installing rnsd service..."
    cp "${MESHPOINT_DIR}/scripts/rnsd.service" /etc/systemd/system/rnsd.service
    systemctl daemon-reload
    systemctl enable rnsd
    info "rnsd service enabled (will start on next boot, or 'systemctl start rnsd' now)"
else
    info "Skipping rnsd service (Reticulum/LXMF messaging won't be available) -- re-run without --skip-rnsd, or answer Y next time, to add it later"
fi

# ── 25. Install network watchdog ──────────────────────────────────

info "Installing WiFi network watchdog..."
cp "${MESHPOINT_DIR}/${WATCHDOG_SERVICE_FILE}" /etc/systemd/system/network-watchdog.service
systemctl daemon-reload
systemctl enable network-watchdog
systemctl start network-watchdog 2>/dev/null || warn "Could not start network-watchdog (will start on next boot)"
info "Network watchdog enabled"

# ── 26. Install mDNS (Avahi) for meshpoint.local discovery ────────
#
# Lets the Pi be reached as meshpoint.local (or <hostname>.local) on
# the LAN without knowing its IP -- useful right after a fresh flash
# before a static IP/DHCP reservation is set up, and for the Home
# Assistant integration's setup step (enter host/IP) when the user
# doesn't know the IP yet either.
#
# Idempotent: skips the apt install if avahi-daemon is already present;
# enable --now is safe to re-run either way (systemd no-ops if already
# enabled and running).

if command -v avahi-daemon &>/dev/null; then
    info "avahi-daemon already installed, skipping"
else
    info "Installing mDNS (Avahi) for meshpoint.local discovery..."
    apt-get install -y -qq avahi-daemon avahi-utils
fi

systemctl enable --now avahi-daemon

# ── 27. Install CLI tool ───────────────────────────────────────────

info "Installing meshpoint CLI..."
chmod +x "${MESHPOINT_DIR}/${CLI_SCRIPT}"
ln -sf "${MESHPOINT_DIR}/${CLI_SCRIPT}" /usr/local/bin/meshpoint

# ── 28. Add fastfetch login banner ────────────────────────────────
#
# Shows a system-info banner on every interactive login shell for the
# `pi` user. Idempotent: skips if already present.

PI_BASHRC="/home/pi/.bashrc"

if [ -f "$PI_BASHRC" ]; then
    if grep -qx "fastfetch" "$PI_BASHRC"; then
        info "fastfetch login banner already configured"
    else
        info "Adding fastfetch login banner to ${PI_BASHRC}..."
        echo "fastfetch" >> "$PI_BASHRC"
    fi
else
    warn "${PI_BASHRC} not found, skipping fastfetch login banner"
fi

# ── Done ────────────────────────────────────────────────────────────

echo ""
echo "==========================================="
if [ "$IS_UPGRADE" = "1" ]; then
    echo "  Meshpoint upgrade to v${INSTALL_VERSION} complete!"
    echo "==========================================="
    echo ""
    echo "  Restart the service to apply changes:"
    echo "       sudo systemctl restart meshpoint"
    echo ""
    echo "  A reboot is NOT required: SPI/UART/I2C are"
    echo "  already configured from the original install."
    echo ""
else
    echo "  Meshpoint installation complete!"
    echo "==========================================="
    echo ""
    echo "  Next steps:"
    echo ""
    echo "  1. Reboot to apply SPI/UART changes:"
    echo "       sudo reboot"
    echo ""
    echo "  2. After reboot, run the setup wizard:"
    echo "       sudo meshpoint setup"
    echo ""
    echo "  3. The wizard will walk you through:"
    echo "       - Hardware detection"
    echo "       - API key configuration"
    echo "       - Device naming and GPS"
    echo "       - Starting the service"
    echo ""
    echo "  IMPORTANT: Never yank the power cable"
    echo "  without shutting down first. Always run:"
    echo "       sudo poweroff"
    echo "  and wait for the LED to go dark."
    echo ""
fi
echo "==========================================="
