# Syncrobit Chameleon: CM4 Recovery and Meshpoint Install

Guide for repurposing a **Syncrobit Chameleon** LoRa miner as a Meshpoint.
The Chameleon uses a **Compute Module 4 (eMMC)** and an onboard **SX1302**
concentrator. Meshpoint replaces the factory OS; the same `install.sh` and
`meshpoint setup` flow applies after you flash 64-bit OS to eMMC.

**Validated (May 2026):** aarch64 Raspbian 13 (Trixie) Lite, Meshpoint
v0.7.4+, live Meshtastic RX/TX. Compare with RAK V2 and SenseCap M1 in
[Hardware Matrix](HARDWARE-MATRIX.md).

For the standard Pi 4 + microSD path, see the [Onboarding Guide](ONBOARDING.md).

---

## What you need (one-time recovery)

| Item | Purpose |
|------|---------|
| **Waveshare CM4-IO-BASE-B** (or similar CM4 carrier) | USB access to eMMC for flashing (only for initial setup) |
| **Linux host** (NUC, laptop, etc.) | Runs `rpiboot` and writes the OS image |
| **Micro-USB or USB-C data cable** | Host to carrier (data, not charge-only) |
| **Chameleon** (CM4 + SX1302 board) | Final deployment hardware |
| **LoRa antenna** | Connect before applying power to the concentrator |

---

## Step 1: Flash CM4 eMMC over USB (on the carrier board)

1. On the Linux host, install build tools and clone Raspberry Pi `usbboot`:

```bash
sudo apt install -y git libusb-1.0-0-dev build-essential pkg-config
cd ~ && git clone --depth=1 https://github.com/raspberrypi/usbboot.git
cd usbboot && make
```

2. On the **Waveshare carrier**: set the **BOOT jumper to ON** (USB boot),
   seat the CM4, connect USB from the host to the carrier, and apply 5 V power.

3. On the host, start mass-storage mode (leave this running):

```bash
cd ~/usbboot && sudo ./rpiboot -d msd -v
```

4. In a second terminal, confirm the eMMC block device (often `/dev/sdb`):

```bash
lsblk -o NAME,SIZE,MODEL,TRAN
```

5. Download **Raspberry Pi OS Lite (64-bit)** or Raspbian Lite 64-bit for
   CM4 from [Raspberry Pi OS downloads](https://www.raspberrypi.com/software/operating-systems/).
   Flash to the eMMC (replace `/dev/sdX` with your device):

```bash
xzcat ~/raspios-*-arm64-lite.img.xz | sudo dd of=/dev/sdX bs=4M status=progress conv=fsync
```

6. Configure first boot (SSH + WiFi) using Raspberry Pi Imager's advanced
   options on a separate SD workflow, **or** mount the boot partition after
   `dd` and add cloud-init `user-data` plus an empty `ssh` file on the boot
   partition. Use a strong password.

7. Stop `rpiboot` (Ctrl+C), remove USB, set **BOOT jumper OFF** (eMMC boot),
   and boot the CM4 on the carrier. Find the device on your network via DHCP
   and `ssh pi@<device-ip>`.

---

## Step 2: Install Meshpoint on the carrier (optional check)

You can verify SPI and networking on the Waveshare board before moving the
CM4 to the Chameleon:

```bash
sudo apt update && sudo apt install -y git
sudo git clone https://github.com/javastraat/meshpoint.git /opt/meshpoint
sudo bash /opt/meshpoint/scripts/install.sh
sudo reboot
```

After reboot: `sudo meshpoint setup`, then open `http://<device-ip>:8080`.

Continue with [Onboarding > Step 7](ONBOARDING.md#step-7-get-your-api-key) for
API key and wizard steps if you have not run setup yet.

---

## Step 3: Move CM4 into the Chameleon and deploy

1. `sudo poweroff` on the CM4 and wait for shutdown.
2. Move the CM4 module from the Waveshare carrier into the Chameleon SODIMM
   socket.
3. Connect the **LoRa antenna** to the concentrator SMA port.
4. Power via **PoE** or Ethernet + injector (per your hardware).

Wait about 60 seconds, SSH in at the same or new DHCP address, and confirm
the service:

```bash
sudo systemctl status meshpoint
grep sw_reg1 /opt/sx1302_hal/libloragw/src/loragw_sx1302.c
```

Non-empty `sw_reg1` output means the Meshtastic HAL patch is present. If
`install.sh` was already run on the carrier, you do not need to re-run it
unless you changed OS or HAL paths.

---

## Chameleon-specific notes

- **`/opt/meshpoint` and git:** `sudo git clone` into `/opt/meshpoint` keeps
  a git checkout for `sudo git pull` updates. Cloning elsewhere and running
  `install.sh` only rsyncs files: `/opt/meshpoint` has no `.git`. Use
  **Settings > Updates** on the dashboard (v0.7.3+) or re-clone to
  `/opt/meshpoint` and run `install.sh` again.
- **Dashboard port:** `http://<device-ip>:8080` (not port 5000).
- **SPI latch:** Same guidance as RAK2287: use `sudo poweroff` before
  unplugging PoE or power. See [Hardware Matrix](HARDWARE-MATRIX.md).
- **Vendor firmware:** Reflashing erases the original Chameleon image. Back
  up eMMC first if you need to restore vendor software.
- **PoE:** Ensure your injector or switch supplies enough current for CM4 +
  concentrator (plan for up to ~2-3 A at 5 V equivalent).

---

## Troubleshooting

| Symptom | Things to try |
|---------|----------------|
| eMMC not visible during `rpiboot` | Data-capable USB cable; BOOT jumper ON; power-cycle carrier with USB connected |
| No network after flash | Check cloud-init or netplan; `cloud-init status --long`; verify WiFi credentials |
| `install.sh` fails | `uname -m` must be `aarch64`; need ~1 GB free on eMMC; check internet for apt/pip |
| No packets on dashboard | Antenna connected; region matches local mesh; nodes in range |
| `lgw_start()` failed after hard power cut | `sudo poweroff`, unplug 10+ seconds, power on (SPI latch) |

See also [Common Errors](COMMON-ERRORS.md) and [Troubleshooting](TROUBLESHOOTING.md).

---

## References

- [Meshpoint Onboarding](ONBOARDING.md)
- [Hardware Matrix](HARDWARE-MATRIX.md)
- [Raspberry Pi CM4 documentation](https://www.raspberrypi.com/documentation/computers/compute-module.html)
- [Waveshare CM4-IO-BASE-B wiki](https://www.waveshare.com/wiki/CM4-IO-BASE-B)
