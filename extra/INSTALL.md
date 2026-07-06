# Install — Sencap M1 / SX1303 on Raspberry Pi

Tested on Raspberry Pi OS (Bookworm/Bullseye 64-bit).

## 1. Enable SPI

```bash
sudo raspi-config
# Interface Options → SPI → Enable
```

Or directly:
```bash
echo "dtparam=spi=on" | sudo tee -a /boot/config.txt
sudo reboot
```

Verify after reboot:
```bash
ls /dev/spi*
# should show /dev/spidev0.0  /dev/spidev0.1
```

## 2. System dependencies

```bash
sudo apt update
sudo apt install -y git build-essential libusb-1.0-0-dev pkg-config libssl-dev
```

`libssl-dev` is required for the AES-128-CTR / AES-256-CTR Meshtastic decryption built into
the sniffer (OpenSSL EVP API, links as `-lcrypto`).

## 3. Clone sx1302_hal

The HAL must be cloned next to `sniffer.c` — the Makefile expects `$(CURDIR)/sx1302_hal`.

```bash
cd /path/to/this/directory
git clone https://github.com/Lora-net/sx1302_hal.git sx1302_hal
cd sx1302_hal && make
cd ..
```

Verify the build:
```bash
ls sx1302_hal/libloragw/libloragw.a
```

## 4. Quick hardware test with lora_pkt_fwd

Before building the sniffer, confirm the M1 is wired and responding:

```bash
cd sx1302_hal/packet_forwarder

# Edit global_conf.json.sx1250.EU868 — ensure SPI path is correct:
#   "spidev_path": "/dev/spidev0.0"

bash reset_lgw.sh start
./lora_pkt_fwd -c global_conf.json.sx1250.EU868
```

You should see the concentrator start up and log chip version `0x12` (SX1303).
If it fails with SPI errors, check wiring and that SPI is enabled (step 1).

## 5. Sencap M1 hardware notes

The Sencap M1 (WM1303) pin mapping on the Pi GPIO header:

| Signal | BCM GPIO | Physical pin |
|--------|----------|--------------|
| SPI MOSI | GPIO 10 | Pin 19 |
| SPI MISO | GPIO 9  | Pin 21 |
| SPI CLK  | GPIO 11 | Pin 23 |
| SPI CS0  | GPIO 8  | Pin 24 |
| RESET    | GPIO 23 | Pin 16 |
| POWER EN | GPIO 18 | Pin 12 |

The `reset_m1.sh` script pulses GPIO 23 to reset the concentrator.
**Always run it before starting the sniffer** — without reset, `lgw_start()` will fail.

## 6. Build the sniffer

```bash
make
```

The Makefile points to `$(CURDIR)/sx1302_hal` automatically — no editing needed.
It links `-lcrypto` (OpenSSL) for the Meshtastic AES-128-CTR / AES-256-CTR decrypt.

## 7. Run the sniffer

```bash
bash reset_m1.sh
sudo ./sniffer
```

`sudo` is needed for SPI/GPIO access. Press Ctrl+C to stop.

Expected startup output:
```
EU868 + Meshtastic Sniffer — Sencap M1 / SX1303
=================================================
Meshtastic: 869525000 Hz BW250 SF11 (ch8)
EU868 scan: 867.9–869.825 MHz BW125 multi-SF (ch0–ch7)

Channels:
  ch0: 867.9 MHz BW125 multi-SF — EU868 optional, sub-band L (1%, 25mW)
  ch1: 868.1 MHz BW125 multi-SF — EU868 mandatory ch1 (LoRaWAN)
  ch2: 868.3 MHz BW125 multi-SF — EU868 mandatory ch2 (LoRaWAN)
  ch3: 868.5 MHz BW125 multi-SF — EU868 mandatory ch3 (LoRaWAN)
  ch4: 869.225 MHz BW125 multi-SF — EU868 sub-band N edge (0.1%, 25mW)
  ch5: 869.425 MHz BW125 multi-SF — EU868 sub-band P (10%, 500mW)
  ch6: 869.625 MHz BW125 multi-SF — EU868 sub-band P/Q edge
  ch7: 869.825 MHz BW125 multi-SF — EU868 sub-band Q (1%, 25mW)
  ch8: 869.525 MHz BW250 SF11 [MESHTASTIC]
  ch9: FSK disabled

Listening... (Ctrl+C to stop)
```

## 8. Understanding the output

### EU868 / LoRaWAN packets (ch1–ch3, sync word 0x34)

The MAC header is unencrypted and fully decoded. Join Requests are entirely in the clear.
Data frame payloads (FRMPayload) are encrypted with per-device session keys — length shown only.

```
[14:31:44] 868100000 Hz SF9  RSSI=-98.4 SNR=+1.1  len=23
  [LoRaWAN]  Join-Request
  JoinEUI=70-B3-D5-7E-D0-00-01-70  DevEUI=70-B3-D5-49-8E-00-01-A4  DevNonce=0xB200

[14:32:03] 868300000 Hz SF7  RSSI=-95.2 SNR=+3.2  len=26
  [LoRaWAN]  Unconfirmed-Data-Up
  DevAddr=78563412  FCnt=1  FPort=2  payload=13B[encrypted]  MIC=AABBCCDD
```

### Meshtastic LongFast packets (ch8, 869.525 MHz)

After AES-CTR decryption (AES-128 or AES-256 depending on key length) all common portnum
types are fully decoded.
The sender's name (from `nodes.csv`) appears in the header on first sight of the packet.

```
[14:32:01] 869525000 Hz SF11  RSSI=-87.3 SNR=+2.0  len=41  ← MESHTASTIC
  dest=broadcast   src=a1b2c3d4  id=67452301  hops=3/3  ch=0x08  [Ruud Smeets]
  portnum=1   (TEXT_MESSAGE)
  "Hello from NL!"

[14:32:14] 869525000 Hz SF11  RSSI=-89.1 SNR=+1.4  len=43  ← MESHTASTIC
  dest=broadcast   src=a1b2c3d4  id=67452303  hops=3/3  ch=0x08  [Ruud Smeets]
  portnum=3   (POSITION)
  lat=52.370216  lon=4.895168  alt=5m

[14:33:15] 869525000 Hz SF11  RSSI=-92.1 SNR=+0.8  len=58  ← MESHTASTIC
  dest=broadcast   src=a1b2c3d4  id=67452304  hops=3/3  ch=0x08
  portnum=4   (NODEINFO)
  id=!a1b2c3d4  name="Ruud Smeets"  short="RUUD"  hw=Heltec-V3  role=ROUTER  pkey=d4f1bb3a…

[14:34:02] 869525000 Hz SF11  RSSI=-88.5 SNR=+1.9  len=46  ← MESHTASTIC
  dest=broadcast   src=a1b2c3d4  id=67452305  hops=3/3  ch=0x08  [Ruud Smeets]
  portnum=67  (TELEMETRY)
  [DeviceMetrics]  battery=82%  voltage=3.91V  chan_util=2.3%  air_util=0.8%  uptime=86400s

[14:34:45] 869525000 Hz SF11  RSSI=-91.0 SNR=+0.5  len=44  ← MESHTASTIC
  dest=broadcast   src=a1b2c3d4  id=67452306  hops=3/3  ch=0x08  [Ruud Smeets]
  portnum=67  (TELEMETRY)
  [EnvMetrics]  temp=21.4C  humidity=58.0%  pressure=1013.2hPa

[14:34:55] 869525000 Hz SF11  RSSI=-88.0 SNR=+2.1  len=38  ← MESHTASTIC
  dest=broadcast   src=a1b2c3d4  id=67452309  hops=3/3  ch=0x08  [Ruud Smeets]
  portnum=67  (TELEMETRY)
  [LocalStats]  uptime=3600s  chan_util=4.1%  air_util=1.2%  tx=14  rx=87  online=12  total=31

[14:35:00] 869525000 Hz SF11  RSSI=-90.0 SNR=+1.5  len=32  ← MESHTASTIC
  dest=broadcast   src=a1b2c3d4  id=67452310  hops=3/3  ch=0x08  [Ruud Smeets]
  portnum=67  (TELEMETRY)
  [PowerMetrics]  ch1=3.71V/142mA  ch2=5.02V/0mA

[14:35:10] 869525000 Hz SF11  RSSI=-86.2 SNR=+3.1  len=22  ← MESHTASTIC
  dest=b2c3d4e5   src=a1b2c3d4  id=67452307  hops=2/3  ch=0x08  ACK  [Ruud Smeets]
  portnum=5   (ROUTING)
  error=NONE (ACK)

[14:35:30] 869525000 Hz SF11  RSSI=-87.0 SNR=+2.5  len=52  ← MESHTASTIC
  dest=broadcast   src=a1b2c3d4  id=67452311  hops=3/3  ch=0x08  [Ruud Smeets]
  portnum=70  (TRACEROUTE)
  route: a1b2c3d4(6.3dB) b2c3d4e5(4.8dB) c3d4e5f6
  route_back: c3d4e5f6(5.0dB) b2c3d4e5(3.3dB) a1b2c3d4

[14:35:55] 869525000 Hz SF11  RSSI=-90.3 SNR=+1.2  len=48  ← MESHTASTIC
  dest=broadcast   src=a1b2c3d4  id=67452308  hops=3/3  ch=0x08  [Ruud Smeets]
  portnum=71  (NEIGHBORINFO)
  neighbors: b2c3d4e5(8dB) c3d4e5f6(5dB) d4e5f6a7(2dB)  [total=3]

[14:36:10] 869525000 Hz SF11  RSSI=-89.0 SNR=+1.8  len=44  ← MESHTASTIC
  dest=broadcast   src=a1b2c3d4  id=67452312  hops=3/3  ch=0x08  [Ruud Smeets]
  portnum=8   (WAYPOINT)
  id=42  name="Bakkerij"  desc="Open 08:00-18:00"  lat=52.370216  lon=4.895168

[14:36:20] 869525000 Hz SF11  RSSI=-88.5 SNR=+2.0  len=28  ← MESHTASTIC
  dest=broadcast   src=a1b2c3d4  id=67452313  hops=3/3  ch=0x08  [Ruud Smeets]
  portnum=34  (PAXCOUNTER)
  wifi=12  ble=7  uptime=3600s

[14:36:30] 869525000 Hz SF11  RSSI=-91.0 SNR=+1.0  len=30  ← MESHTASTIC
  dest=broadcast   src=a1b2c3d4  id=67452314  hops=3/3  ch=0x08  [Ruud Smeets]
  portnum=65  (STORE_FORWARD)
  rr=ROUTER_HEARTBEAT  hb_period=900s  secondary=0

[14:36:35] 869525000 Hz SF11  RSSI=-90.0 SNR=+1.3  len=18  ← MESHTASTIC
  dest=broadcast   src=a1b2c3d4  id=67452315  hops=3/3  ch=0x08  [Ruud Smeets]
  portnum=66  (RANGE_TEST)
  "1/1"

[14:36:40] 869525000 Hz SF11  RSSI=-89.5 SNR=+1.6  len=60  ← MESHTASTIC
  dest=broadcast   src=a1b2c3d4  id=67452316  hops=3/3  ch=0x08  [Ruud Smeets]
  portnum=73  (MAP_REPORT)
  name="Ruud Smeets"  short="RUUD"  hw=Heltec-V3  fw=2.5.18  region=11  lat=52.370216  lon=4.895168  online=12
```

### Private channel (wrong key)

```
  dest=broadcast   src=12345678  id=abcdef01  hops=2/3  ch=0x7f
  [encrypted / wrong key]
```

If the sender uses a private channel PSK not listed in `keys.txt`, the portnum check catches
the garbage and prints `[encrypted / wrong key]` rather than showing misleading data.
Add the base64 PSK to `keys.txt` to decrypt that channel. 16-byte keys use AES-128-CTR;
32-byte keys use AES-256-CTR — the sniffer selects the correct cipher automatically.

## Troubleshooting

**`lgw_start()` fails / SPI error**
- Check `ls /dev/spidev*` — SPI must be enabled
- Run `bash reset_m1.sh` before starting
- Check GPIO wiring (RESET on GPIO 23)
- Run as root (`sudo`)

**No packets received**
- Confirm antenna is connected before powering on
- Run `lora_pkt_fwd` (step 4) to verify the hardware responds
- Check you are in an area with EU868 LoRa or Meshtastic traffic

**Chip version `0x00`**
- Concentrator not responding — full power cycle (unplug 10+ seconds), then run `reset_m1.sh` again
- Normal version for SX1303 is `0x12`

**`libloragw.a: No such file`**
- Build the HAL first: `cd sx1302_hal && make`

**`openssl/evp.h: No such file`**
- Install OpenSSL dev headers: `sudo apt install libssl-dev`

**All packets show `[encrypted / wrong key]`**
- On ch8: the sync word override may not have taken effect — check `lgw_reg_w` calls compiled with `-I$(LORAGW_PATH)/libloragw/inc`
- On ch1–ch3: expected — those are LoRaWAN packets, not Meshtastic
