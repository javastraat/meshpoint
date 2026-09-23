# Troubleshooting

### Service won't start

```bash
meshpoint logs
```

Common issues:
- **"No module named 'src'"**: Check that `/opt/meshpoint` contains the source code.
- **"Permission denied: /dev/spidev0.0"**: Run `sudo usermod -a -G spi meshpoint`
- **"No module named 'psutil'"**: Run `sudo -u meshpoint /opt/meshpoint/venv/bin/pip install psutil`
- **"no GPIO tool found (pinctrl or gpioset)"**: This means the concentrator reset script can't toggle GPIO. Raspberry Pi OS Lite (64-bit) includes `pinctrl` by default. If you're on a non-standard image, install `gpiod`: `sudo apt install -y gpiod`
- **"fan control enabled but gpiozero is not installed"**: `fan.enabled: true` is set but the Meshpoint **venv** doesn't have `gpiozero` (Raspberry Pi OS ships it system-wide, which is a different Python environment). Run `sudo -u meshpoint /opt/meshpoint/venv/bin/pip install gpiozero` and restart. The fan is simply not driven while this is missing -- the app still starts normally.
- **"GPIO13 PWM unsupported on gpiozero's fallback pin factory"** (or a raw `gpiozero.exc.PinPWMUnsupported` traceback): `gpiozero` is installed but none of `lgpio`/`RPi.GPIO`/`pigpio` are, so it fell back to its pure-Python `NativeFactory`, which only allows PWM on pins from a hardcoded per-Pi-model table -- a custom carrier board's repurposed GPIO isn't in it, even though it's a real PWM-capable pin on the SoC. `lgpio` is the Raspberry Pi Foundation's current recommended backend (Bookworm/Pi4/Pi5, no daemon needed) and doesn't have that restriction, but `pip install lgpio` builds a C extension from source (piwheels has no prebuilt wheel for every Python/OS combination) and needs three things first -- on a fresh Bookworm/trixie image expect to install all three:
  ```bash
  sudo apt install -y python3-dev swig liblgpio-dev
  sudo -u meshpoint /opt/meshpoint/venv/bin/pip install lgpio
  sudo systemctl restart meshpoint
  ```
  `python3-dev` (headers) and `swig` (generates the C wrapper) get the build itself running; `liblgpio-dev` provides the compiled `liblgpio.so` the extension links against (`/usr/bin/ld: cannot find -llgpio` if missing). Confirm with `meshpoint logs`: `Fan control started on GPIO13` with no exception.

  If instead the logs show `xCreatePipe: Can't set permissions ... for /opt/meshpoint/.lgd-nfy0, Operation not permitted` followed by the same `PinPWMUnsupported` fallback: `lgpio` is installed correctly, but it creates a notification pipe directly in `WorkingDirectory` (`/opt/meshpoint`), and the `meshpoint` service user can't write there -- the unit's `ExecStartPre` chowns only `config/` and `data/`, never the top-level directory. Fix immediately with `sudo chown meshpoint:meshpoint /opt/meshpoint` and restart; current `scripts/meshpoint.service` also chowns this automatically on every start, so a fresh install/redeploy from this version won't hit it.

### Concentrator fails to start

If logs show `lgw_start() failed` or `Failed to set SX1250_0 in STANDBY_RC mode`:

The SPI bus latched due to a hard power cut. `sudo reboot` and `meshpoint restart` normally prevent this, but a hard power loss (yanked cable, outage) can still cause it. Do a full power cycle:

1. `sudo poweroff`
2. Wait for the green LED to stop blinking
3. Unplug power for 10+ seconds, then plug back in

### RAK Hotspot V2 (RAK7248) specific issues

Some RAK7248 carriers (especially enclosed Helium Hotspot V2 units) are more
sensitive to reset timing than standard RAK Pi HATs.

**Symptoms**
- `lgw_start()` returns -1 with "chip version is 0x00" or "0x05"
- "Failed to set SX1250_0 in STANDBY_RC mode" even after a full power cycle
- Works when running manually as the `pi` user but fails under the `meshpoint` service user

**Common fixes**

1. **Increase reset hold time** (most effective for many users):

   Add this to your systemd service (or the environment section):

   ```ini
   Environment=CONCENTRATOR_RESET_HOLD_SEC=1.0
   ```

   This makes the Python-side reset use a longer pulse (the shell pre-script
   still runs with its default timing).

2. **SPI device-tree overlay conflict**:

   On some RAK7248 boards the line `dtoverlay=spi0-0cs` in `/boot/firmware/config.txt`
   produces the kernel error:

   ```
   spi-bcm2835 ... there is not valid maps for state default
   ```

   Try commenting it out:

   ```bash
   sudo sed -i 's/^dtoverlay=spi0-0cs/#dtoverlay=spi0-0cs/' /boot/firmware/config.txt
   sudo reboot
   ```

3. **GPIO 25 behavior**:

   On certain RAK7248 carriers GPIO 25 is part of the reset circuit rather than
   (or in addition to) a power-enable line. Using it as a separate "power GPIO"
   in custom reset sequences can hold the chip in reset.

4. **Reset pin isn't 17 or 25 at all** (a different carrier board entirely):

   A `sudo reboot` reliably fixing it while a plain `sudo systemctl restart
   meshpoint` never does is a strong hint — a real reboot resets the
   kernel's own SPI/GPIO state regardless of which pin gets toggled, so it
   can "work" independently of whether the GPIO reset ever hit the right
   pin. Confirmed on a **COTX X3 Helium Miner** repurposed as a Meshpoint
   (see the Hardware Matrix's own COTX X3 notes): its reset line is GPIO
   **22**, not 17/25.

   **But a failed reboot does NOT rule this out** — confirmed on a
   **Pisces P100** (see its own Hardware Matrix notes): even `sudo reboot`
   failed there on the wrong pin, yet the real problem was still just the
   wrong reset pin (GPIO **23**), not a deeper power/kernel issue. Don't
   use reboot-vs-restart behavior alone to decide whether this is worth
   pursuing — if you have several unclaimed GPIOs to try and no
   documentation for the board, `scripts/test_concentrator_reset.py` (added
   for the Pisces P100 investigation) sweeps candidates properly: it drives
   the real `SX1302Wrapper` bring-up sequence Meshpoint itself uses, and
   tests each candidate TWICE back-to-back with no power cycle in between
   — the only test that actually catches this bug, since almost any pin
   "works" once, right after a real power-up.

   Once you have a candidate, override with:

   ```ini
   Environment=RESET_GPIO=23
   ```

   (substitute your board's actual pin — space-separated for more than one).
   This one setting drives both the systemd-level reset
   (`scripts/reset_concentrator.sh`) and Meshpoint's own in-app fallback
   (`SX1302Wrapper.reset()`), so a candidate pin gets a clean, consistent
   test.

After making changes, do a full physical power cycle (unplug 15–20 s) before testing.

### UART GPS reports "ANTENNA OPEN" despite a physically connected antenna

Applies to boards where `location.source: uart` reads an onboard GPS
module directly (see [Configuration → Using UART](CONFIGURATION.md#using-uart-on-board-gps)),
confirmed on a **Pisces P100** (GreenPalm "Bothum V4.3" carrier board,
GPS wired to a dedicated GPS-In SMA connector, separate from the LoRa
and BLE antenna ports).

**Symptom**

The GPS card shows a live connection and real NMEA sentences (correct
GGA/GSA/GLL/RMC, sometimes multi-constellation GPS+GLONASS), but never
gets a fix, and a raw serial capture shows:

```
$GPTXT,01,01,01,ANTENNA OPEN*25
```

repeating on every report cycle — with a real, correctly-seated
antenna physically connected, ruling out the obvious "wrong port" or
"not plugged in" explanations.

**What this message actually means**

It's the GNSS chip's own antenna-supervisor diagnostic: the chip
watches for DC current draw on the antenna feed line to confirm
something is connected, and reports "open" when it sees none. This
sentence is emitted autonomously by the chip itself — it needs no
host-side configuration to appear, so a stock vendor firmware that
never even reads the GPS UART (Helium miner firmware only asserts
location once via the phone app; it never has a live-GPS feature at
all) would never surface this, even though the chip has likely been
reporting it since the unit left the factory. Meshpoint's UART GPS
source may be the first thing that's ever actually listened to this
port.

**Diagnosis that rules this in, in order (all confirmed on the P100
case above)**

1. Confirm bytes are actually arriving at all first (rules out a
   silent connection):
   ```bash
   sudo systemctl stop meshpoint
   sudo stty -F /dev/serial0 9600 raw -echo
   sudo timeout 10 cat /dev/serial0 | strings | head -20
   sudo systemctl start meshpoint
   ```
   If this shows real `$GxGGA`/`$GxGSA`/etc sentences (even all-empty,
   no-fix ones) plus the `ANTENNA OPEN` line, the receiver is alive
   and talking — the fault is specifically the antenna sense circuit,
   not the UART link, GPIO enable sequence, or `UartSource` parsing
   (all already working correctly at this point).
2. **Measure DC voltage on the antenna connector's center pin**
   (antenna unscrewed, multimeter on DC volts, black probe to any
   ground point, red probe to the center pin) — the decisive test:
   - **~3.3V or ~5V present**: the board is actively supplying
     bias-tee power. If "open" persists, the fault is in the antenna
     or its cable specifically (open circuit, bad crimp/solder) —
     try a different antenna.
   - **~0V**: the board is not supplying any bias-tee power on that
     line **at all** — confirmed on the P100. No antenna, active or
     passive, stock or spare, can fix this on its own; the problem is
     upstream of the antenna.
3. If 0V: rule out software/firmware config before assuming a
   hardware limitation.
   - Sending a UBX-MON-VER poll (`b5 62 0a 04 00 00 0e 34`) over the
     same serial link is a safe, read-only "identify yourself" that
     every genuine u-blox chip answers. On the P100 it came back with
     a valid **UBX-ACK-NAK** (`b5 62 05 00 02 00 0a 04 15 3e`) —
     correctly-framed UBX communication, but an explicit rejection of
     a command real u-blox silicon always supports. That's a strong
     sign of a non-genuine/partial-UBX-implementation GNSS chip, which
     means standard u-blox `CFG-ANT` documentation can't be trusted to
     apply here, and guessing at a config command risks the chip
     silently ignoring it.
   - A GPIO sweep of every unused Pi header pin (driving each high
     individually, in isolation, while watching the same multimeter
     reading) came back clean on the P100 — none of them affect the
     antenna line. This also confirms the antenna bias-tee is a
     **separate circuit from the module-power GPIOs** (see the reset
     pin section above and `docs/HARDWARE-MATRIX.md`'s Pisces P100
     notes for GPIO 12/20/16 — those get the GNSS chip talking at
     all, but don't touch the antenna line).

**Where this leaves it, if you hit the same wall**

If a voltage/UBX/GPIO investigation like the above comes back clean
(bias line stays at 0V, no GPIO moves it, the chip rejects standard
UBX identification), this is genuinely past what's reverse-engineerable
without the board's real schematic — likely an I2C-controlled power
sequencer, a switch internal to the LoRaWAN/GNSS combo module itself,
or a physical jumper/solder bridge that isn't populated by default.
Contact the board vendor/reseller directly with the specific evidence
above (they can usually answer in one message with the real
schematic in hand) rather than continuing to guess blind.

### Database errors after update

If logs show `sqlite3.OperationalError: table nodes has no column named <column>`:

The database schema is older than the current code. The service runs automatic migrations on startup. If it fails with `attempt to write a readonly database`, fix permissions:

```bash
sudo chmod 777 /opt/meshpoint/data
sudo chmod 666 /opt/meshpoint/data/*.db
sudo systemctl restart meshpoint
```

### Concentrator starts but receives no packets

If the logs show `SX1302 concentrator started` and `Sync word set to 0x2B` but the receive loop consistently reports `0 pkt this cycle`, the SX1250 radio's analog front-end may be damaged. This typically happens after:

- Repeated power loss events (storms, breaker trips, yanked cables)
- SPI bus latch events (the `lgw_start() failed` error, even if resolved by power cycling)

The SX1250's digital SPI interface can recover while the RF receive path remains non-functional. To confirm: test a known-working Meshtastic device within a few meters. If still zero packets, the RAK2287 module needs replacement (~$50-60). The Pi and carrier board are unaffected.

**Partial variant — one RF chain silent, not the whole concentrator:** the same SPI-latch class of issue can also present as only RF1 (Meshtastic ch8, Pager ch9) going deaf while RF0 (LoRaWAN) keeps working normally — the dashboard still shows every channel correctly configured ("ON", right frequency/sync word) since that's just the software-side channel plan, not a live RF confirmation. Seen on a RAK V2 unit: pager showed "sent" in the web UI with nothing received on the physical pager (and nothing received back from it either), while LoRaWAN kept working. A full power cycle (as above) resolved it without any module replacement — try that first before assuming hardware damage when only one RF chain is affected.

### No LoRa packets captured

- Verify the concentrator is detected: `ls /dev/spidev0.*`
- Verify libloragw is installed: `ls /usr/local/lib/libloragw.so`
- Check that there are Meshtastic/MeshCore devices transmitting in your area
- Verify the antenna is connected

### MeshCore companion not receiving packets

- Verify the device is detected: `ls /dev/ttyUSB* /dev/ttyACM* 2>/dev/null`
- Check that the companion is running USB companion firmware (not BLE)
- Verify radio frequency matches your region: re-run `sudo meshpoint setup` to reconfigure
- Check logs: `meshpoint logs | grep -i meshcore`
- If the device was recently plugged in, unplug and re-plug to reset the serial connection

### TX not working (messages not received by other nodes)

1. Verify TX is enabled in the Radio settings page on the dashboard
2. Confirm the HAL TX sync word patch was applied (this happens automatically when you run `install.sh`): `meshpoint logs | grep -i "tx\|transmit"`. If TX is silently failing, re-run `sudo bash /opt/meshpoint/scripts/install.sh` to re-apply the patch idempotently.
3. Verify the modem preset matches the mesh network you're targeting (e.g. LongFast)
4. Check that the antenna is connected: transmitting without an antenna damages the radio

### Not appearing on cloud dashboard

1. Check that `upstream.enabled` is `true` in your local config
2. Verify your API key is correct
3. Check logs: `meshpoint logs | grep -i upstream`
4. Make sure the Pi has internet access: `ping google.com`

### Remote commands not working

1. Check the fleet view on meshradar.io: device should show as "Online"
2. Try a Ping command from the fleet panel
3. Check logs: `meshpoint logs | grep -i "command\|response"`

### Recovering from a corrupted install

If `meshpoint logs` shows `SyntaxError: source code string cannot contain null bytes` or `git pull` fails with `error: inflate` / `fatal: loose object is corrupt`, the SD card took a bad write (usually from a hard power cut).

#### Disaster recovery with a saved backup (recommended)

Use this when you have a **Settings → System → Download backup** `.tar.gz` saved on your PC or NAS (not only on the Pi).

**Before you start**

1. Keep the backup file **off the Pi**. A dead SD card takes the on-device copy with it.
2. Do **not** delete or rotate the Meshradar API key in the backup until upstream reconnects after restore, or be ready to paste a new key for the same `device_id` (see [COMMON-ERRORS.md](COMMON-ERRORS.md#upstream-http-403-after-restore)).

**Steps (dashboard user path)**

1. Flash a fresh SD card (or wipe and reinstall on the same card):
   ```bash
   sudo git clone https://github.com/KMX415/meshpoint.git /opt/meshpoint
   cd /opt/meshpoint
   sudo bash scripts/install.sh
   ```
2. **Bootstrap activation (SSH, required on a blank install).** The dashboard will not load until `config/local.yaml` has a valid Meshradar API key. The service exits with `Meshpoint is not activated` until then. Run the setup wizard once:
   ```bash
   sudo meshpoint setup
   ```
   Paste **any** valid API key from [meshradar.io](https://meshradar.io). Accept defaults for the rest if you are about to restore: restore overwrites this throwaway config.
3. Start the service:
   ```bash
   sudo systemctl restart meshpoint
   ```
4. Open the dashboard. Complete **`/setup`** with any admin password (also replaced by restore).
5. **Settings → System → Restore backup** and upload your saved `.tar.gz`. Wait for the service to restart.
6. Sign in with the **password from before the disaster** (restore puts back `web_auth` from the archive).
7. Confirm local data: nodes and packets should match the backup snapshot. Check upstream:
   ```bash
   meshpoint logs | grep -i upstream
   ```
   You should see `connected to wss://api.meshradar.io`. If you see `HTTP 403`, the API key in the backup was revoked on Meshradar: generate a new key for the restored `device_id`, then run `sudo meshpoint setup` and paste it (or edit `upstream.auth_token` in `config/local.yaml`), and restart.

**What restore brings back:** `device_id`, channel keys, PKI keys, SQLite database (nodes, packets, messages), dashboard password, and the API key that was in the archive at backup time.

**What restore does not fix:** A Meshradar API key you deleted in the cloud after taking the backup. Local restore can succeed while upstream stays on `HTTP 403` until you update the key.

#### SSH restore when the dashboard will not load

If the service will not stay up long enough for the upload UI, copy the archive to the Pi and finish from SSH:

```bash
scp meshpoint-backup-*.tar.gz pi@<pi-ip>:/tmp/meshpoint-restore.tar.gz
ssh pi@<pi-ip>
sudo bash /opt/meshpoint/scripts/restore_finish.sh /tmp/meshpoint-restore.tar.gz
```

See [COMMON-ERRORS.md](COMMON-ERRORS.md#restore-backup-stopped-the-service-and-it-never-came-back) if restore stops the service and does not restart it.

#### Manual re-clone without a backup file

**SSH fallback** when you have no `.tar.gz` backup:

```bash
cd /opt/meshpoint
sudo cp -r data/ /tmp/meshpoint-data-backup
sudo cp config/local.yaml /tmp/local-yaml-backup
cd /home/pi
sudo rm -rf /opt/meshpoint
sudo git clone https://github.com/javastraat/meshpoint.git /opt/meshpoint
sudo cp -r /tmp/meshpoint-data-backup /opt/meshpoint/data/
sudo cp /tmp/local-yaml-backup /opt/meshpoint/config/local.yaml
sudo chmod 777 /opt/meshpoint/data
sudo chmod 666 /opt/meshpoint/data/*.db
sudo python3 -m venv /opt/meshpoint/venv
sudo -u meshpoint /opt/meshpoint/venv/bin/pip install -r /opt/meshpoint/requirements.txt
sudo systemctl restart meshpoint
```

This preserves your packet database and device config. The venv must be recreated since it is not tracked by git.

### Backup before SD card trouble

On a healthy Meshpoint, open **Settings → System → Download backup** and save the file to your PC or NAS.

The archive contains `config/local.yaml` (API key, `device_id`, web auth hashes, radio and MQTT settings) and the full `data/` tree (SQLite database, PKI private keys, rollback state). It is **not encrypted**. Treat it like a password vault: offline storage only.

Download a fresh backup:

- Before flashing or replacing the SD card
- Before **Clear database** or other destructive actions (restore can still roll back, but an off-Pi copy is safer)
- When root disk use climbs above 90% (the System page also suggests it at that threshold)

Restore always returns the Pi to the **backup snapshot**, even if you cleared the database or changed config after that backup was taken.

### Using pip on Raspberry Pi OS

Raspberry Pi OS (Bookworm and later) uses PEP 668 externally-managed environments. Never use the system `pip` directly: always use the venv:

```bash
sudo -u meshpoint /opt/meshpoint/venv/bin/pip install -r requirements.txt
```

Running `sudo pip install ...` without the venv path will fail with `error: externally-managed-environment`.
