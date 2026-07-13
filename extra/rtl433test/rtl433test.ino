/*
  TTGO LoRa32 V2.1.6 -- fake LaCrosse TX141TH-Bv2 sensor for rtl_433

  Emulates a real LaCrosse TX141TH-Bv2 temperature/humidity sensor well
  enough that plain `rtl_433` decodes it with NO extra flags -- it has
  a built-in decoder for this exact protocol (src/devices/lacrosse_tx141x.c
  upstream). Protocol details below were pulled directly from that file
  and from src/bit_util.c's lfsr_digest8_reflect(), not guessed:

    - OOK, PWM-encoded, 40 data bits (5 bytes) per packet:
        [id 8b] [batt1 test1 chan2 tempHi4] [tempLo8] [humidity8] [crc8]
      temp_raw = temp_C*10 + 500 (12 bits, spans byte1's low nibble + byte2)
      crc = lfsr_digest8_reflect(bytes 0..3, gen=0x31, key=0xf4)
    - Preamble: 833us high + 833us low, x4, immediately before each
      packet's 40 data bits.
    - Bit 1 = 417us high + 208us low. Bit 0 = 208us high + 417us low.
      No inversion needed when transmitting: the generic bit-slicer
      this decoder rides on (pulse_slicer_pwm) hardcodes short(208us)
      pulses to a raw bit of 1 and long(417us) to raw 0, and the
      decoder's own bitbuffer_invert() flips that again -- the two
      cancel out, so long=1/short=0 is already what comes out the
      other end. (An earlier version of this file inverted on top of
      that anyway, a leftover from only reasoning about
      bitbuffer_invert() in isolation -- confirmed live: real pulses
      matched target timing almost exactly, but nothing ever decoded,
      exactly what a double inversion would cause.)
    - Decoder wants >=3 identical repeats out of up to 4-5 captured
      rows; we send exactly 3 back-to-back packets per burst -- the
      bare minimum, no redundancy margin (a real sensor sends 4-12).
      Forced by a hard RadioLib constraint, see below.

  Rather than drive the SX1276's continuous-mode data pin (DIO2 --
  not broken out to the ESP32 on most LoRa32 boards, including this
  one), the whole PWM waveform is pre-rendered as an oversampled NRZ
  bitstream and sent through the chip's normal packet-mode transmit(),
  using the exact same SPI pins already confirmed working by the
  earlier LoRa-mode test sketch. Chip rate is 4800 baud (208.33us/chip)
  -- NOT the originally-planned 9600 baud/6-chips-per-bit encoding,
  which produced a 152-byte packet and hit RadioLib's SX127x transmit()
  ceiling of 63 bytes in FSK/OOK mode (vs 255 for LoRa) -- confirmed
  live: that version returned RADIOLIB_ERR_TX_TIMEOUT (-5) every time.
  This encoding uses half as many chips per bit (3 instead of 6) at
  half the baud rate, landing on the exact same real microsecond
  timings with less wasted padding, so 3 full repeats fit in 57 bytes:
    - preamble half-cycle (833us)    = 4 chips (833.3us at 4800 baud)
    - data bit 1 (417us hi/208us lo) = 2 hi chips + 1 lo chip
    - data bit 0 (208us hi/417us lo) = 1 hi chip + 2 lo chips

  Pins (TTGO LoRa32 V2.1.6):
  SPI:
    SCK  5
    MISO 19
    MOSI 27
    CS   18

  LoRa:
    RST 14
    DIO0 26

  OLED:
    SDA 21
    SCL 22
*/

#include <Arduino.h>
#include <SPI.h>
#include <Wire.h>
#include <math.h>

#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

#include <RadioLib.h>


// ---------- Multiple virtual sensors ----------
//
// Round-robins through a small fleet of fake devices, one TX burst per
// loop() cycle, each with its own stable ID/channel/battery status and
// independently random-walking humidity. Different tempOffsetC values
// keep them from all reporting the exact same reading (they all read
// the one physical ESP32 die sensor underneath). One sensor is
// deliberately battery-low so that field gets exercised too, instead
// of every device always reporting "OK".
//
// Defined this early (right after the includes, before anything else)
// on purpose: the Arduino IDE auto-generates function prototypes and
// inserts them near the top of the file, before most other code --
// if this struct were defined further down (as it originally was),
// showStats()'s auto-generated prototype would reference FakeSensor
// before it existed, a real compile error ("does not name a type").

struct FakeSensor {
  uint8_t id;         // assigned at boot, see setup()
  uint8_t channel;
  bool batteryOk;
  float tempOffsetC;
  int humidity;       // persists across cycles, random-walked per sensor
};

FakeSensor sensors[] = {
  { 0, 0, true,  0.0f,  45 },
  { 0, 1, true,  -1.5f, 55 },
  { 0, 2, false, 2.0f,  60 }, // battery low
};
const int NUM_SENSORS = sizeof(sensors) / sizeof(sensors[0]);
int currentSensorIdx = 0;


// ---------- OLED ----------

#define OLED_WIDTH 128
#define OLED_HEIGHT 64

Adafruit_SSD1306 display(
  OLED_WIDTH,
  OLED_HEIGHT,
  &Wire,
  -1
);


// ---------- Radio ----------

#define LORA_CS   18
#define LORA_RST  14
#define LORA_DIO0 26

SX1276 radio = new Module(
  LORA_CS,
  LORA_DIO0,
  LORA_RST,
  -1
);


// ---------- LaCrosse TX141TH-Bv2 packet builder ----------

// Repeats per burst -- decoder wants >=3 identical rows out of <=4-5
// captured. 3 is the bare minimum (no redundancy margin for a
// corrupted repeat), forced by RadioLib's 63-byte FSK/OOK transmit()
// ceiling -- see the file header comment for how that was discovered.
#define LACROSSE_REPEATS 3

// Max bits per burst: 3 repeats * (32 preamble bits + 40*3 data-bit
// chips) = 3 * (32 + 120) = 456 bits = 57 bytes. Rounded up a bit for
// headroom, but must stay under RadioLib's 63-byte FSK/OOK ceiling.
#define PACKET_BUF_BYTES 60

struct BitWriter {
  uint8_t buf[PACKET_BUF_BYTES];
  int bitPos;

  void reset() {
    memset(buf, 0, sizeof(buf));
    bitPos = 0;
  }

  void pushBit(int bit) {
    if (bitPos >= PACKET_BUF_BYTES * 8) return; // safety, shouldn't happen
    int byteIdx = bitPos / 8;
    int bitIdx = 7 - (bitPos % 8); // MSB first, matches how rtl_433's
                                   // bitbuffer stores captured bits
    if (bit) buf[byteIdx] |= (1 << bitIdx);
    bitPos++;
  }

  void pushChips(int hiChips, int loChips) {
    for (int i = 0; i < hiChips; i++) pushBit(1);
    for (int i = 0; i < loChips; i++) pushBit(0);
  }

  // PWM data bit at 4800 baud (208.33us/chip): 1 = long-high/short-low
  // (2 hi chips + 1 lo chip), 0 = short-high/long-low (1 hi + 2 lo).
  void pushDataBit(int bit) {
    if (bit) pushChips(2, 1);
    else     pushChips(1, 2);
  }

  // 833us high + 833us low, x4 -- one full preamble train (4 chips per
  // half-cycle at 4800 baud = 833.3us).
  void pushPreamble() {
    for (int i = 0; i < 4; i++) pushChips(4, 4);
  }

  int numBytes() {
    return (bitPos + 7) / 8;
  }
};

BitWriter bw;

// Same LFSR digest rtl_433 itself uses to verify the checksum
// (src/bit_util.c, lfsr_digest8_reflect) -- ported byte for byte.
uint8_t lfsrDigest8Reflect(const uint8_t *message, int bytes, uint8_t gen, uint8_t key) {
  uint8_t sum = 0;
  for (int k = bytes - 1; k >= 0; --k) {
    uint8_t data = message[k];
    for (int i = 0; i < 8; ++i) {
      if ((data >> i) & 1) sum ^= key;
      if (key & 0x80) key = (key << 1) ^ gen;
      else            key = (key << 1);
    }
  }
  return sum;
}

// Builds `LACROSSE_REPEATS` back-to-back packets into the global bit
// writer and returns the number of bytes to transmit.
int buildPacket(uint8_t id, bool batteryOk, bool test, uint8_t channel,
                float tempC, uint8_t humidity) {
  int tempRaw = (int)lroundf(tempC * 10.0f) + 500;
  if (tempRaw < 0) tempRaw = 0;
  if (tempRaw > 0x0FFF) tempRaw = 0x0FFF;
  if (humidity < 1) humidity = 1;     // 0 fails the receiver's sanity check
  if (humidity > 100) humidity = 100;
  if (id == 0) id = 1;                // 0 fails the receiver's sanity check

  uint8_t b[5];
  b[0] = id;
  b[1] = ((batteryOk ? 0 : 1) << 7) | ((test ? 1 : 0) << 6)
       | ((channel & 0x03) << 4) | ((tempRaw >> 8) & 0x0F);
  b[2] = tempRaw & 0xFF;
  b[3] = humidity;
  b[4] = lfsrDigest8Reflect(b, 4, 0x31, 0xf4);

  bw.reset();
  for (int r = 0; r < LACROSSE_REPEATS; r++) {
    bw.pushPreamble();
    for (int byteIdx = 0; byteIdx < 5; byteIdx++) {
      // NOT inverted -- pulse_slicer_pwm() (the generic bit-slicer
      // this decoder rides on) hardcodes short(208us)=raw bit 1,
      // long(417us)=raw bit 0; bitbuffer_invert() then flips that, so
      // chaining the two already gives long=1/short=0 with zero net
      // inversion needed. An earlier version of this code additionally
      // inverted b[] here on top of that, which double-flipped every
      // bit -- confirmed live: real pulses matched target timing
      // almost exactly (rtl_433 -A showed the right widths and
      // counts) but plain `rtl_433` never decoded it, which is exactly
      // what this bug would cause.
      uint8_t txByte = b[byteIdx];
      for (int bitIdx = 7; bitIdx >= 0; bitIdx--) {
        bw.pushDataBit((txByte >> bitIdx) & 1);
      }
    }
  }
  return bw.numBytes();
}


// ---------- OLED screens ----------

uint32_t txCount = 0;
bool lastTxOk = false;

// Small text-only helper for one-off status/error screens (radio init
// failure, etc) -- the boot logo and per-TX stats screens below have
// their own dedicated, richer layouts.
void oled(String line1, String line2) {
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(0, 0);
  display.println(line1);
  display.setCursor(0, 20);
  display.println(line2);
  display.display();
}

void centerText(const String &text, int y) {
  int16_t x1, y1;
  uint16_t w, h;
  display.getTextBounds(text, 0, y, &x1, &y1, &w, &h);
  display.setCursor((OLED_WIDTH - w) / 2, y);
  display.print(text);
}

// Simple mast + splayed arms + junction dot + base stand -- same
// antenna glyph used for the Meshpoint dashboard's RTL-SDR sidebar
// icon, drawn here with plain GFX primitives (no bitmap asset needed).
void drawAntennaIcon(int cx, int topY, int height) {
  int jointY = topY + height * 2 / 3;
  int baseY = topY + height;
  int armSpread = height / 3;
  display.drawLine(cx, baseY, cx, jointY, SSD1306_WHITE);           // mast
  display.drawLine(cx, jointY, cx - armSpread, topY, SSD1306_WHITE); // left arm
  display.drawLine(cx, jointY, cx + armSpread, topY, SSD1306_WHITE); // right arm
  display.fillCircle(cx, jointY, 2, SSD1306_WHITE);                  // junction dot
  display.drawLine(cx - armSpread / 2, baseY, cx + armSpread / 2, baseY, SSD1306_WHITE); // base
}

void showBootLogo() {
  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);

  drawAntennaIcon(64, 2, 18);

  display.setTextSize(1);
  centerText("RTL_433 FAKE SENSOR", 26);
  centerText("LaCrosse TX141TH-Bv2", 38);
  centerText("433.92 MHz  OOK/PWM", 50);

  display.display();
  delay(2000);
}

// Live stats screen, redrawn after every TX attempt.
void showStats(const FakeSensor &s, int sensorIdx, float tempC, int numBytes) {
  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);

  display.setTextSize(1);
  display.setCursor(0, 0);
  display.print("LaCrosse TX141THBv2 ");
  display.print(sensorIdx + 1);
  display.print("/");
  display.print(NUM_SENSORS);
  display.drawFastHLine(0, 10, OLED_WIDTH, SSD1306_WHITE);

  display.setCursor(0, 14);
  display.print("ID:0x");
  display.print(s.id, HEX);
  display.print(" CH:");
  display.print(s.channel);
  display.print(" TX#");
  display.print(txCount);

  // Big temperature readout, small humidity + battery alongside.
  display.setTextSize(2);
  display.setCursor(0, 26);
  display.print(tempC, 1);
  display.print("C");

  display.setTextSize(1);
  display.setCursor(90, 20);
  display.print("Hum ");
  display.print(s.humidity);
  display.print("%");
  display.setCursor(90, 30);
  display.print(s.batteryOk ? "Batt OK" : "Batt LOW");

  display.drawFastHLine(0, 46, OLED_WIDTH, SSD1306_WHITE);

  display.setCursor(0, 50);
  display.print("433.920MHz  ");
  display.print(numBytes);
  display.print("B");

  display.setCursor(10, 58);
  // Filled dot = last TX OK, hollow = last TX failed.
  if (lastTxOk) display.fillCircle(3, 60, 2, SSD1306_WHITE);
  else          display.drawCircle(3, 60, 2, SSD1306_WHITE);
  display.print(lastTxOk ? "Last TX OK" : "Last TX FAILED");

  display.display();
}

// ESP32's internal die temperature sensor, raw -- no offset. This is
// the SoC die temperature, not ambient air (typically well above room
// temperature from self-heating, and not well calibrated across chip
// revisions), but it's live, real, changing data straight from the
// MCU rather than a hardcoded number.
float readFakeTempC() {
  return temperatureRead();
}

// Humidity random-walks from wherever it last was instead of staying
// fixed or jumping to a fresh random value every cycle -- nudges by a
// small +/-HUMIDITY_MAX_STEP delta each call, clamped to a plausible
// indoor range so a long-running session can't wander off to 1% or
// 100%. Each sensor in the `sensors[]` fleet walks independently from
// its own starting value (set in the array above).
#define HUMIDITY_MIN      20
#define HUMIDITY_MAX      80
#define HUMIDITY_MAX_STEP 3

int nextHumidity(int current) {
  int delta = random(-HUMIDITY_MAX_STEP, HUMIDITY_MAX_STEP + 1); // upper bound exclusive
  int h = current + delta;
  if (h < HUMIDITY_MIN) h = HUMIDITY_MIN;
  if (h > HUMIDITY_MAX) h = HUMIDITY_MAX;
  return h;
}


void setup() {
  Serial.begin(115200);
  delay(1000);

  randomSeed(esp_random());

  // Assign each virtual sensor a distinct, non-zero, non-colliding
  // random ID (small fleet, so a simple retry-on-collision loop is
  // plenty cheap).
  for (int i = 0; i < NUM_SENSORS; i++) {
    uint8_t candidate;
    bool collides;
    do {
      candidate = random(1, 256);
      collides = false;
      for (int j = 0; j < i; j++) {
        if (sensors[j].id == candidate) { collides = true; break; }
      }
    } while (collides);
    sensors[i].id = candidate;
  }

  // OLED
  Wire.begin(21, 22);
  if (!display.begin(SSD1306_SWITCHCAPVCC, 0x3C)) {
    Serial.println("OLED FAIL");
  }
  showBootLogo();

  // SPI
  SPI.begin(5, 19, 27, 18);

  Serial.println("Radio init (FSK/OOK mode)");

  // FSK/OOK init instead of LoRa: freq 433.92 MHz, bitrate 4.8 kbps
  // (matches the 4800-baud chip period the packet builder assumes),
  // freqDev irrelevant for OOK (no frequency shift), rxBw 125 kHz
  // (unused for TX-only), power 10 dBm, preamble handled by us so
  // asking the chip for 0 of its own.
  int state = radio.beginFSK(433.92, 4.8, 5.0, 125.0, 10, 0);

  if (state != RADIOLIB_ERR_NONE) {
    Serial.print("Radio error: ");
    Serial.println(state);
    oled("Radio FAIL", String(state));
    while (true) { delay(1000); }
  }

  // OOK, no hardware CRC/whitening/Manchester -- we've already built
  // the exact raw bit pattern rtl_433 expects; anything the chip adds
  // on top would corrupt it.
  radio.setOOK(true);
  radio.setCRC(false);
  radio.setEncoding(RADIOLIB_ENCODING_NRZ);
  radio.setDataShaping(RADIOLIB_SHAPING_NONE);
  radio.setPreambleLength(0);
  radio.setOutputPower(10);

  Serial.println("Radio OK");
  Serial.println("Fake sensor fleet:");
  for (int i = 0; i < NUM_SENSORS; i++) {
    Serial.print("  #"); Serial.print(i);
    Serial.print(" id=0x"); Serial.print(sensors[i].id, HEX);
    Serial.print(" ch="); Serial.print(sensors[i].channel);
    Serial.println(sensors[i].batteryOk ? " battery=OK" : " battery=LOW");
  }

  oled("Radio OK", String(NUM_SENSORS) + " fake sensors ready");
}


void loop() {
  FakeSensor &s = sensors[currentSensorIdx];

  float tempC = readFakeTempC() + s.tempOffsetC;
  s.humidity = nextHumidity(s.humidity); // random-walks from its own last value

  int numBytes = buildPacket(s.id, s.batteryOk, /*test=*/false,
                              s.channel, tempC, s.humidity);

  Serial.print("TX LaCrosse-TX141THBv2 [");
  Serial.print(currentSensorIdx + 1);
  Serial.print("/");
  Serial.print(NUM_SENSORS);
  Serial.print("] id=0x");
  Serial.print(s.id, HEX);
  Serial.print(" ch=");
  Serial.print(s.channel);
  Serial.print(" batt=");
  Serial.print(s.batteryOk ? "OK" : "LOW");
  Serial.print(" temp=");
  Serial.print(tempC, 1);
  Serial.print("C hum=");
  Serial.print(s.humidity);
  Serial.print("% (");
  Serial.print(numBytes);
  Serial.println(" bytes on air)");

  int state = radio.transmit(bw.buf, numBytes);
  lastTxOk = (state == RADIOLIB_ERR_NONE);
  txCount++;

  if (lastTxOk) {
    Serial.println("TX OK");
  } else {
    Serial.print("TX error ");
    Serial.println(state);
  }

  showStats(s, currentSensorIdx, tempC, numBytes);

  bool roundComplete = (currentSensorIdx == NUM_SENSORS - 1);
  currentSensorIdx = (currentSensorIdx + 1) % NUM_SENSORS;

  // Real TX141TH-Bv2 bursts repeat every ~50s; shortened here for
  // quick iteration while verifying against `rtl_433 -f 433920000`.
  delay(8000);

  // Extra breather after a full round through the fleet (i.e. right
  // after the battery-low sensor, the last one), before starting the
  // next round from sensor #1 again.
  if (roundComplete) {
    Serial.println("-- round complete, pausing before next sequence --");
    delay(10000);
  }
}
