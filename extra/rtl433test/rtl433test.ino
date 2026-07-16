/*
  TTGO LoRa32 V2.1.6 -- fake LaCrosse TX141TH-Bv2 + Nexus TH sensors for rtl_433

  Emulates two real rtl_433-supported sensor protocols well enough that
  plain `rtl_433` decodes both with NO extra flags. Round-robins a fleet
  of virtual sensors across both protocols -- see the FakeSensor struct
  and the buildLacrossePacket()/buildNexusPacket() sections below for
  each protocol's own detailed notes (pulled directly from this repo's
  local rtl_433 source checkout, not guessed, same rigor for both).

  LaCrosse TX141TH-Bv2 details (src/devices/lacrosse_tx141x.c upstream,
  and src/bit_util.c's lfsr_digest8_reflect()):

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

  Nexus needs its OWN, slower chip rate (1000 baud, not LaCrosse's 4800)
  to fit the same 63-byte ceiling -- see the "Nexus temperature/humidity
  packet builder" section below for the full reasoning. loop() calls
  radio.setBitRate() before each burst to switch between the two.

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

// ---------- Test tuning knobs ----------
//
// Turn a sensor's `enabled` flag off in the fleet table below to isolate
// one protocol while debugging, without commenting out array entries.
// Turn the delays down for fast iteration while actively testing, back
// up to realistic values otherwise -- these replace what used to be
// hardcoded 8000/10000 literals in loop().
#define TX_INTERVAL_MS 1000   // delay between each sensor's own burst
#define ROUND_PAUSE_MS 5000  // extra pause after a full round through the fleet

// One named on/off switch per fake sensor -- flip any of these to 0 to
// isolate a single protocol/instance while debugging, instead of
// counting positions in the sensors[] table below.
const bool lacrosse1On = 1;
const bool lacrosse2On = 1;
const bool lacrosse3On = 1;
const bool nexus1On    = 1;
const bool nexus2On    = 1;
const bool ambient1On  = 1;
const bool ambient2On  = 1;
const bool rubicson1On = 1;
const bool rubicson2On = 1;
const bool wgpb1On     = 1;
const bool cotech1On   = 1;

enum SensorProtocol { PROTO_LACROSSE, PROTO_NEXUS, PROTO_AMBIENT, PROTO_RUBICSON, PROTO_WGPB12, PROTO_COTECH };

struct FakeSensor {
  SensorProtocol protocol;
  bool enabled;       // flip to false to skip this sensor entirely (no TX, no delay)
  uint8_t id;         // assigned at boot, see setup()
  uint8_t channel;
  bool batteryOk;
  float tempOffsetC;
  int humidity;       // persists across cycles, random-walked per sensor
};

// All six protocols' ids are independent namespaces (different decoders
// -- a collision between two different protocols' ids can never happen
// in practice), so id uniqueness is only enforced within the whole
// fleet as a simple, slightly-more-conservative-than-necessary blanket
// rule -- see the assignment loop in setup().
FakeSensor sensors[] = {
  { PROTO_LACROSSE, lacrosse1On, 0, 0, true,  0.0f,  45 },
  { PROTO_LACROSSE, lacrosse2On, 0, 1, true,  -1.5f, 55 },
  { PROTO_LACROSSE, lacrosse3On, 0, 2, false, 2.0f,  60 }, // battery low
  { PROTO_NEXUS,    nexus1On,    0, 0, true,  1.0f,  50 },
  { PROTO_NEXUS,    nexus2On,    0, 1, false, -0.5f, 65 }, // battery low
  { PROTO_AMBIENT,  ambient1On,  0, 0, true,  0.5f,  40 },
  { PROTO_AMBIENT,  ambient2On,  0, 1, false, -2.0f, 70 }, // battery low
  { PROTO_RUBICSON, rubicson1On, 0, 0, true,  1.5f,  0 },  // Rubicson has no humidity field, ignored
  { PROTO_RUBICSON, rubicson2On, 0, 1, false, -1.0f, 0 },  // battery low
  { PROTO_WGPB12,   wgpb1On,     0, 0, true,  3.0f,  0 },  // WG-PB12V1 has no channel/humidity field, ignored
  { PROTO_COTECH,   cotech1On,   0, 0, true,  -0.2f, 55 },
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
int buildLacrossePacket(uint8_t id, bool batteryOk, bool test, uint8_t channel,
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


// ---------- Nexus temperature/humidity packet builder ----------
//
// rtl_433's nexus.c (real r_device struct fields, not the file's rounded
// header prose): OOK_PULSE_PPM, short_width=1000us, long_width=2000us,
// gap_limit=3000us, reset_limit=5000us. pulse_slicer_ppm (src/pulse_slicer.c)
// classifies PURELY by the GAP after each pulse -- pulse WIDTH is never
// read at all -- so the pulse just needs to register above the receiver's
// own minimum on-time; it doesn't need to match any specific real-world
// value. With no .tolerance/.sync_width set, the actual decode buckets
// (worked out from pulse_slicer_ppm's math, not assumed) are:
//   gap <1501us            -> bit 0
//   gap in (1500,3000)us   -> bit 1
//   gap in [3000,5000)us   -> row boundary (bitbuffer_add_row)
//   gap >=5000us           -> end of message
//
// 9 nibbles (36 bits) per row, 3 identical rows needed (same
// bitbuffer_find_repeated_row(.., 3, 36) minimum as LaCrosse), byte
// layout confirmed against nexus_decode()'s own bit-shift math:
//   b[0] = id
//   b[1] = [battery(1) test(1) channel(2)] [temp_hi_nibble(4)]
//   b[2] = temp_mid_byte (temp is a signed 12-bit value = tempC*10,
//          split hi-nibble/b[1] + this byte, exactly like nexus_decode's
//          own (b[1]<<12)|(b[2]<<4) reconstruction, verified by hand)
//   b[3] = [const 0xF (4)] [humidity_hi_nibble(4)]
//   b[4] = [humidity_lo_nibble(4)] [0000 padding -- matches nexus_decode's
//          own "there might be a trailing 0 bit" comment]
// Channel 3 (0-indexed) is explicitly rejected by nexus_decode's own
// "(b[1]&0x30)==0x30" guard, so it's clamped away below, same reasoning
// as LaCrosse's own id==0 guard a few lines up.
//
// Real nominal timing (500us pulse / 1000-2000us gap / 4000us row gap)
// encoded at LaCrosse's fine 208.33us/chip (4800 baud) blows past
// RadioLib's 63-byte FSK/OOK ceiling (36 bits x 3 repeats, worst case
// all-1-bits, comes out to ~70 bytes -- verified by hand, not assumed).
// Since pulse width doesn't matter to the decoder at all, Nexus instead
// transmits at its OWN coarser 1000 baud (1000us/chip): pulse=1 chip,
// bit-0 gap=1 chip(1000us), bit-1 gap=2 chips(2000us), inter-row
// boundary=1 pulse chip + 4 gap chips(4000us) -- still lands safely
// inside the real bucket math above, just lower time-resolution than
// the real sensor's exact values. loop() calls radio.setBitRate() to
// switch between this and LaCrosse's 4800 baud before each burst --
// reusing the same shared BitWriter/PACKET_BUF_BYTES buffer from the
// LaCrosse builder above.
//
// 4 repeats, not 3 -- confirmed live via `rtl_433 -A`: the intended gap
// pattern (1000/2000/4004us) showed up exactly right, but a couple of
// pulses came out double-width (~1996us instead of ~996us), corrupting
// one row. With only 3 repeats and zero redundancy margin (same
// bare-minimum tradeoff LaCrosse's own header comment already flags),
// a single glitched row means bitbuffer_find_repeated_row can never
// find its required 3 identical rows and the whole packet gets
// silently dropped. Nexus has real byte budget to spare (3 repeats
// used ~43 of the 63-byte ceiling, vs LaCrosse's ~57), so 4 repeats
// (worst case 57 bytes -- 5 would hit 71, over the limit) buys real
// redundancy: one bad row out of 4 still leaves 3 clean matching ones.
#define NEXUS_REPEATS 4
#define NEXUS_BAUD_KBPS 1.0f

int buildNexusPacket(uint8_t id, bool batteryOk, bool test, uint8_t channel,
                      float tempC, uint8_t humidity) {
  int traw = (int)lroundf(tempC * 10.0f);
  if (traw < -2048) traw = -2048;
  if (traw > 2047) traw = 2047;
  if (humidity > 100) humidity = 100;
  if (id == 0) id = 1;              // 0 fails the receiver's sanity check
  uint8_t ch2 = channel & 0x03;
  if (ch2 == 0x03) ch2 = 0x02;       // channel 3 (0b11) is explicitly rejected by the decoder

  uint8_t b[5];
  b[0] = id;
  // Battery bit polarity is Nexus's OWN convention (1=OK, 0=LOW per
  // nexus_decode()'s "battery_ok" field, confirmed against the real
  // source) -- opposite of LaCrosse's, which is why this can't just
  // reuse LaCrosse's bit-packing expression verbatim (an earlier
  // version of this code did exactly that and got it backwards, caught
  // live: a fake battery-LOW sensor decoded as "Battery: 1"/OK).
  b[1] = ((batteryOk ? 1 : 0) << 7) | ((test ? 1 : 0) << 6)
       | (ch2 << 4) | ((traw >> 8) & 0x0F);
  b[2] = traw & 0xFF;
  b[3] = 0xF0 | ((humidity >> 4) & 0x0F);
  b[4] = (humidity & 0x0F) << 4;    // low nibble left as padding

  bw.reset();
  // Sacrificial dummy pulse before any real data -- confirmed live via
  // repeated `rtl_433 -A` captures: EVERY Nexus burst showed exactly one
  // anomalously wide pulse near the start and 1-2 more total pulses than
  // the clean expected count, consistent every single time (not random
  // noise, which would vary in position/frequency). Most likely the
  // SX1276's PA ramp-up at burst start stretching the very first pulse.
  // LaCrosse never shows this because its own 4-cycle preamble is
  // meaningless filler that silently absorbs exactly this kind of
  // startup glitch -- Nexus had no equivalent, so real row 0 took the
  // hit directly. Gap sized to land in the row-boundary bucket (3000-
  // 5000us, not a bit-0/bit-1 range), so even if THIS pulse survives
  // uncorrupted, the decoder cleanly reads it as a boundary/reset event
  // rather than accidentally prepending a spurious bit onto real row 0.
  bw.pushChips(1, 4);
  for (int r = 0; r < NEXUS_REPEATS; r++) {
    for (int bitPos = 0; bitPos < 36; bitPos++) {
      int byteIdx = bitPos / 8;
      int bitIdx = 7 - (bitPos % 8); // MSB first, matches BitWriter's own convention
      int bitVal = (b[byteIdx] >> bitIdx) & 1;
      // One pulse chip (the pulse itself), then the gap chip(s) that
      // encode this bit's value -- pulse width is irrelevant to the
      // decoder, so folding both into one pushChips() call is safe.
      bw.pushChips(1, bitVal ? 2 : 1);
    }
    if (r < NEXUS_REPEATS - 1) {
      // Row-boundary pulse + ~4000us gap, connecting to the next repeat.
      // The last repeat needs no trailing boundary -- transmission just
      // ends there, same convention as the LaCrosse builder above.
      bw.pushChips(1, 4);
    }
  }
  return bw.numBytes();
}


// ---------- Ambient Weather F007TH packet builder ----------
//
// rtl_433's ambient_weather.c: 48-bit (6 byte) payload, Manchester
// encoding (OOK_PULSE_MANCHESTER_ZEROBIT, short_width=500us half-bit),
// decoded via a totally different mechanism than LaCrosse/Nexus's
// row-repetition voting -- ambient_weather_callback() SEARCHES for a
// fixed 12-bit preamble pattern (0x01,0x45 taken as 12 bits) anywhere
// in the row and decodes+checksums EVERY occurrence independently, so
// (unlike the other two) only ONE clean copy is strictly required, not
// 3 identical rows. The real sensor still sends "three repeats without
// gap" per the source's own comment, so this mirrors that for realism
// and glitch-redundancy even though it isn't strictly load-bearing here.
//
// Byte layout (confirmed against ambient_weather_decode()'s own
// bit-shift math, not guessed):
//   b[0] = 0x45 fixed (high nibble "unknown"=0x4, low nibble "model"=0x5)
//   b[1] = id
//   b[2] = [battery_low(1) channel-1(3)] [temp_hi_nibble(4)]
//   b[3] = temp_lo_byte (temp is UNSIGNED 12-bit = tempF*10 + 400,
//          unlike LaCrosse/Nexus's signed values -- confirmed via
//          ambient_weather_decode's own (temp_raw-400)*0.1f, no sign
//          extension trick like the other two)
//   b[4] = humidity (whole byte, sanity-checked <=100 by the decoder)
//   b[5] = lfsr_digest8(b, 5, 0x98, 0x3e) ^ 0x64 -- a DIFFERENT LFSR
//          variant than LaCrosse's lfsr_digest8_reflect() (forward byte
//          order + right-rolling key, not reversed -- ported byte for
//          byte from bit_util.c's real lfsr_digest8(), not reused from
//          LaCrosse's lfsrDigest8Reflect() above, since the two are
//          genuinely different algorithms, not just parameter swaps).
//
// Battery bit is LaCrosse's polarity again (1=LOW), NOT Nexus's (1=OK)
// -- re-derived from ambient_weather_decode's own `battery_low =
// (b[2]&0x80)!=0` this time rather than assumed, after getting exactly
// this wrong for Nexus earlier by copying LaCrosse's expression blind.
//
// The over-the-air bit sequence is an 8-bit sync prefix (0x01) followed
// immediately by the 48-bit payload -- confirmed via the callback's own
// `bitpos + 8` offset into its 12-bit search pattern: the search
// pattern's last 4 bits (0100) are literally b[0]'s own fixed high
// nibble (0x4), not a separate field, so the real transmitted preamble
// is just the leading 0x01 byte, nothing more.
//
// Manchester encode: each real bit becomes 2 half-bit chips -- bit=0 ->
// [low,high] (rising edge mid-bit), bit=1 -> [high,low] (falling edge
// mid-bit) -- derived directly from pulse_slicer_manchester_zerobit's
// own edge-classification logic (rising edge = data 0, falling edge =
// data 1), not assumed. Concatenating these 2-chip symbols back to back
// naturally produces the correct merged-or-separate transition pattern
// with no special-casing needed, since our raw bit-pushing BitWriter
// doesn't optimize consecutive same-level chips away.
//
// The real decoder also hardcodes "first rising edge is always counted
// as a zero" (its own comment, verbatim) as a fixed policy for wherever
// decoding happens to start -- same class of startup-alignment risk
// that caused Nexus's glitch, so this sends one throwaway low half-bit
// before the real sync/payload starts, same sacrificial-pulse fix.
//
// Chip rate: 500us/half-bit = 2000 baud. 3 repeats of (8+48)*2=112
// half-bit chips + 1 dummy = 337 chips = ~43 bytes, comfortably under
// the 63-byte ceiling with no redundancy pressure like Nexus had.
#define AMBIENT_REPEATS 3
#define AMBIENT_BAUD_KBPS 2.0f

uint8_t lfsrDigest8(const uint8_t *message, int bytes, uint8_t gen, uint8_t key) {
  uint8_t sum = 0;
  for (int k = 0; k < bytes; k++) {
    uint8_t data = message[k];
    for (int i = 7; i >= 0; i--) {
      if ((data >> i) & 1) sum ^= key;
      if (key & 1) key = (key >> 1) ^ gen;
      else         key = (key >> 1);
    }
  }
  return sum;
}

int buildAmbientPacket(uint8_t id, bool batteryOk, uint8_t channel,
                        float tempF, uint8_t humidity) {
  int traw = (int)lroundf(tempF * 10.0f) + 400;
  if (traw < 0) traw = 0;
  // Keep well inside the decoder's own sanity window (temp_f -40..344,
  // humidity <=100) so a fake reading never gets silently rejected --
  // 3839 corresponds to just under 344F: (3839-400)/10 = 343.9F.
  if (traw > 3839) traw = 3839;
  if (humidity > 100) humidity = 100;
  if (id == 0) id = 1;
  uint8_t ch3 = (channel) & 0x07; // 0-indexed here (matches LaCrosse/Nexus convention); decoder adds its own +1

  uint8_t b[6];
  b[0] = 0x45;
  b[1] = id;
  b[2] = ((batteryOk ? 0 : 1) << 7) | (ch3 << 4) | ((traw >> 8) & 0x0F);
  b[3] = traw & 0xFF;
  b[4] = humidity;
  b[5] = lfsrDigest8(b, 5, 0x98, 0x3e) ^ 0x64;

  uint8_t full[7];
  full[0] = 0x01; // sync prefix
  for (int i = 0; i < 6; i++) full[i + 1] = b[i];

  bw.reset();
  bw.pushBit(0); // sacrificial dummy half-bit, see comment block above
  for (int r = 0; r < AMBIENT_REPEATS; r++) {
    for (int bitPos = 0; bitPos < 56; bitPos++) {
      int byteIdx = bitPos / 8;
      int bitIdx = 7 - (bitPos % 8);
      int bitVal = (full[byteIdx] >> bitIdx) & 1;
      if (bitVal) { bw.pushBit(1); bw.pushBit(0); }
      else        { bw.pushBit(0); bw.pushBit(1); }
    }
  }
  return bw.numBytes();
}


// ---------- Shared CRC-8 (bit_util.c's real crc8(), ported byte for
// byte) -- used by Rubicson, WG-PB12V1, and Cotech below. A different
// algorithm from LaCrosse/Ambient's lfsr_digest8 family (MSB-first
// message order, remainder XOR'd with each byte BEFORE shifting, no
// key-rolling) -- confirmed from bit_util.c directly, not assumed to
// match just because both are "8-bit checksums".
uint8_t crc8(const uint8_t *message, int nBytes, uint8_t polynomial, uint8_t init) {
  uint8_t remainder = init;
  for (int byte = 0; byte < nBytes; byte++) {
    remainder ^= message[byte];
    for (int bit = 0; bit < 8; bit++) {
      if (remainder & 0x80) remainder = (remainder << 1) ^ polynomial;
      else                  remainder = (remainder << 1);
    }
  }
  return remainder;
}


// ---------- Rubicson / TFA 30.3197 / InFactory PT-310 packet builder ----------
//
// rtl_433's rubicson.c: OOK_PULSE_PPM, short_width=1000/long_width=2000/
// gap_limit=3000/reset_limit=4800 -- same bucket math as Nexus (zero
// <1501us, one in (1500,3000)us, row-boundary in [3000,4800)us this
// time, narrower ceiling than Nexus's 5000 but our 4000us boundary
// still lands safely inside it), same 36-bit/3-repeat-minimum voting,
// so this reuses Nexus's exact chip scheme (1000 baud, pulse=1 chip,
// bit-0 gap=1 chip, bit-1 gap=2 chips, boundary=1 pulse+4 gap chips)
// and its dummy-startup-pulse fix rather than re-deriving from scratch.
//
// Byte layout (confirmed against rubicson_callback's own CRC/bit-shift
// math): b[0]=id, b[1]=[battery(1) channel-1(2) pad(1)][temp_hi(4)],
// b[2]=temp_mid_byte, b[3]=[const 0xF][crc_hi_nibble], b[4]=[crc_lo_nibble][pad].
// Battery polarity is Nexus's (1=OK), confirmed via rubicson_callback's
// own `!!battery` -- re-derived per-protocol again, not assumed.
// CRC is the "self-verifying" style: crc8(all 5 bytes)==0 for a valid
// packet (confirmed by hand: appending crc8(first4) as the 5th byte
// always zeroes the remainder, a standard property of this crc8()),
// so the builder computes check=crc8(b[0..3],4,...) and splits it into
// b[3]'s low nibble + b[4]'s high nibble to match the decoder's own
// `tmp[4] = (b[3]&0xf)<<4 | (b[4]&0xf0)>>4` reconstruction.
// No humidity field on this device at all (temperature-only sensor).
#define RUBICSON_REPEATS 4

int buildRubicsonPacket(uint8_t id, bool batteryOk, uint8_t channel, float tempC) {
  int traw = (int)lroundf(tempC * 10.0f);
  if (traw < -2048) traw = -2048;
  if (traw > 2047) traw = 2047;
  if (id == 0) id = 1;
  uint8_t ch2 = channel & 0x03;
  if (ch2 == 0x03) ch2 = 0x02;

  uint8_t b[5];
  b[0] = id;
  b[1] = ((batteryOk ? 1 : 0) << 7) | (ch2 << 4) | ((traw >> 8) & 0x0F);
  b[2] = traw & 0xFF;
  b[3] = 0xF0;
  uint8_t check = crc8(b, 4, 0x31, 0x6c);
  b[3] |= (check >> 4) & 0x0F;
  b[4] = (check & 0x0F) << 4;

  bw.reset();
  bw.pushChips(1, 4); // sacrificial dummy pulse, see comment block above
  for (int r = 0; r < RUBICSON_REPEATS; r++) {
    for (int bitPos = 0; bitPos < 36; bitPos++) {
      int byteIdx = bitPos / 8;
      int bitIdx = 7 - (bitPos % 8);
      int bitVal = (b[byteIdx] >> bitIdx) & 1;
      bw.pushChips(1, bitVal ? 2 : 1);
    }
    if (r < RUBICSON_REPEATS - 1) bw.pushChips(1, 4);
  }
  return bw.numBytes();
}


// ---------- WG-PB12V1 packet builder ----------
//
// rtl_433's wg_pb12v1.c: OOK_PULSE_PWM, short_width=564/long_width=1476,
// classified by PULSE width with NO bitbuffer_invert() call (unlike
// LaCrosse) -- so this is the RAW pulse_slicer_pwm convention directly:
// short pulse=bit 1, long pulse=bit 0 (opposite of how LaCrosse's own
// invert-then-slice combo works out). Decoder reads `bitbuffer->bb[0]`
// directly with NO row-repeat search at all ("we just want 1 package"
// per its own comment) -- genuinely single-shot, zero redundancy
// available from the protocol itself, so the leading dummy pulse below
// is the ONLY defense against a startup glitch for this one.
//
// Real widths (564/1476, threshold at their midpoint ~1020us) would
// cost far more chips than needed if matched at fine resolution -- since
// PWM only checks PULSE width (any value clearly under/over 1020us
// works, exact real-world timing not required), this uses a coarser
// 500us chip: short/bit1=1 chip(500us), long/bit0=3 chips(1500us),
// fixed inter-bit gap=2 chips(1000us, comfortably under the 2500us
// reset_limit). Worst case (all 0/long bits): 48*(3+2)=240 chips=~30
// bytes, well under the ceiling.
//
// Byte layout (confirmed against wg_pb12v1_decode): b[0]=0xFF fixed
// preamble, b[1]=[0x3 fixed type nibble][temp_hi(4)], b[2]=temp_lo_byte,
// b[3]=id (only low 5 bits read), b[4]=0xFF fixed/unused ("humidity"
// byte the real device never actually uses), b[5]=crc8(b[1..4],4,0x31,0)
// -- a plain expected-vs-computed check this time, not the
// self-verifying style Rubicson/Cotech use. No channel field at all.
#define WGPB_CHIP_KBPS 2.0f

int buildWgPb12Packet(uint8_t id, float tempC) {
  int traw = (int)lroundf(tempC * 10.0f) + 400;
  if (traw < 0) traw = 0;
  if (traw > 0x0FFF) traw = 0x0FFF;

  uint8_t b[6];
  b[0] = 0xFF;
  b[1] = 0x30 | ((traw >> 8) & 0x0F);
  b[2] = traw & 0xFF;
  b[3] = id & 0x1F;
  b[4] = 0xFF;
  b[5] = crc8(&b[1], 4, 0x31, 0);

  bw.reset();
  // NO leading dummy pulse here, unlike every other builder in this file
  // -- and deliberately so. wg_pb12v1_decode() reads bitbuffer->bb[0] at
  // FIXED byte offsets with no preamble search (unlike Ambient/Cotech)
  // and no row-repeat voting (unlike Nexus/Rubicson), so it has no
  // mechanism to distinguish "throwaway settling pulse" from "real data
  // bit" -- pulse_slicer_pwm classifies EVERY pulse as bit 0 or 1, no
  // exceptions, unlike the PPM/Manchester decoders where a dummy's GAP
  // can be tuned to land in a structural "row boundary" bucket instead.
  // A dummy pulse here would silently shift every real bit by one
  // position, permanently corrupting b[0]'s 0xFF preamble check --
  // confirmed live: adding one caused 100% consistent decode failure
  // even after the real root cause (RadioLib's length-byte framing,
  // fixed via fixedPacketLengthMode() in loop()) was already resolved.
  for (int bitPos = 0; bitPos < 48; bitPos++) {
    int byteIdx = bitPos / 8;
    int bitIdx = 7 - (bitPos % 8);
    int bitVal = (b[byteIdx] >> bitIdx) & 1;
    bw.pushChips(bitVal ? 1 : 3, 2); // short(1chip)=bit1, long(3chips)=bit0, fixed 2-chip gap
  }
  return bw.numBytes();
}


// ---------- Cotech 36-7959 Weatherstation packet builder ----------
//
// rtl_433's cotech_36_7959.c: OOK_PULSE_MANCHESTER_ZEROBIT, half-bit
// 500us -- exact same mechanic/chip-rate as Ambient Weather above, just
// a much bigger 112-bit (14-byte) payload with lots of weather-station
// fields we don't have real values for (wind/gust/direction/rain/light/
// UV). Those are all zeroed/fixed below -- only id/battery/temperature/
// humidity actually vary, matching this rig's scope; the checksum
// covers the whole frame regardless so it stays valid either way.
//
// Unlike Ambient's `bitpos+8` overlap trick, this decoder's preamble
// search (`{0x01,0x40}`, 12 bits) is NOT overlapped with the payload --
// extraction starts exactly at `pos` right after the full 12-bit match
// (confirmed via cotech_36_7959_decode's own `pos += 12` before
// `bitbuffer_extract_bytes`), so the real over-the-air prefix is simply
// the full 0x01,0x40-as-12-bits pattern, transmitted in full.
//
// Byte layout (confirmed against the decoder's own bit-shift math):
//   b[0] = [type(4), fixed 0x0][id_hi(4)]
//   b[1] = [id_lo(4)][battery_low(1) wind_dir_msb(1) gust_msb(1) wind_msb(1)]
//   b[2..4] = wind/gust/wind_dir low bytes (all fixed 0 here)
//   b[5..6] = rain (12 bits, fixed 0 here)
//   b[7] = [flag nibble, ALWAYS 0b1000 per the source's own docstring --
//           also doubles as light_lux's MSB, not a free field][temp_hi(4)]
//   b[8] = temp_lo_byte
//   b[9] = humidity
//   b[10..11] = light_lux low bytes (fixed 0 -- combined with b[7]'s
//               forced top bit this still nets a real 16-bit-ish
//               reading, not that it matters for our purposes)
//   b[12] = uvi (fixed 0, keeps `light_is_valid` true since uvi<=150)
//   b[13] = crc8(b[0..12], 13, 0x31, 0xc0) -- self-verifying style,
//           same technique as Rubicson (crc8 over all 14 bytes lands
//           on 0 for a valid frame; the builder computes it over the
//           first 13 and drops it straight into its own byte, no
//           nibble-straddling needed this time since it's byte-aligned).
// Battery polarity is LaCrosse/Ambient's (1=LOW), confirmed via
// `battery_ok = !batt_low` in the real decoder.
#define COTECH_TYPE_NIBBLE 0x0

int buildCotechPacket(uint8_t id, bool batteryOk, float tempF, uint8_t humidity) {
  int traw = (int)lroundf(tempF * 10.0f) + 400;
  if (traw < 0) traw = 0;
  if (traw > 0x0FFF) traw = 0x0FFF;
  if (humidity > 100) humidity = 100;

  uint8_t b[14] = {0};
  b[0] = (COTECH_TYPE_NIBBLE << 4) | ((id >> 4) & 0x0F);
  b[1] = ((id & 0x0F) << 4) | ((batteryOk ? 0 : 1) << 3); // wind/gust/dir MSBs left 0
  // b[2..6] wind/gust/wind_dir/rain -- left as 0, not modeled
  b[7] = 0x80 | ((traw >> 8) & 0x0F); // top bit is the fixed "1000" flag nibble
  b[8] = traw & 0xFF;
  b[9] = humidity;
  // b[10..11] light_lux, b[12] uvi -- left as 0
  b[13] = crc8(b, 13, 0x31, 0xc0);

  uint8_t full[16];
  full[0] = 0x01;
  full[1] = 0x40; // 12-bit preamble, only the first 12 bits of these 2 bytes are real
  for (int i = 0; i < 14; i++) full[i + 2] = b[i];

  bw.reset();
  bw.pushBit(0); // sacrificial dummy half-bit, see Ambient Weather's comment block
  // 12-bit preamble
  for (int bitPos = 0; bitPos < 12; bitPos++) {
    int byteIdx = bitPos / 8;
    int bitIdx = 7 - (bitPos % 8);
    int bitVal = (full[byteIdx] >> bitIdx) & 1;
    if (bitVal) { bw.pushBit(1); bw.pushBit(0); }
    else        { bw.pushBit(0); bw.pushBit(1); }
  }
  // 112-bit payload
  for (int bitPos = 0; bitPos < 112; bitPos++) {
    int byteIdx = 2 + bitPos / 8;
    int bitIdx = 7 - (bitPos % 8);
    int bitVal = (full[byteIdx] >> bitIdx) & 1;
    if (bitVal) { bw.pushBit(1); bw.pushBit(0); }
    else        { bw.pushBit(0); bw.pushBit(1); }
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
  centerText("LaCrosse+Nexus+Ambient", 38);
  centerText("433.92 MHz  OOK", 50);

  display.display();
  delay(2000);
}

// Short display/Serial label for whichever protocol is currently up.
const char *protocolLabel(SensorProtocol p) {
  switch (p) {
    case PROTO_LACROSSE: return "LaCrosse TX141THBv2";
    case PROTO_NEXUS:    return "Nexus TH";
    case PROTO_AMBIENT:  return "Ambient F007TH";
    case PROTO_RUBICSON: return "Rubicson";
    case PROTO_WGPB12:   return "WG-PB12V1";
    case PROTO_COTECH:   return "Cotech 36-7959";
  }
  return "Unknown";
}

// Live stats screen, redrawn after every TX attempt.
void showStats(const FakeSensor &s, int sensorIdx, float tempC, int numBytes) {
  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);

  display.setTextSize(1);
  display.setCursor(0, 0);
  display.print(protocolLabel(s.protocol));
  display.print(" ");
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

  // FSK/OOK init instead of LoRa: freq 433.92 MHz, initial bitrate 4.8
  // kbps (LaCrosse's rate -- loop() calls radio.setBitRate() before
  // every burst to switch to whichever protocol is up next, so this is
  // just the boot-time default, not fixed for the whole sketch),
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
  // The SX127x packet engine transmits [preamble][sync word][payload] --
  // setPreambleLength(0) above only zeroes the FIRST of those. Missing
  // this one is a real, likely long-standing gap: LaCrosse never showed
  // it because its own real 4-cycle preamble is redundant padding that
  // absorbs a few corrupted/extra leading bits without breaking decode,
  // but Nexus has NO leading preamble at all -- its first pulse IS real
  // data -- so a few extra sync-word bits directly corrupt the start of
  // its first repeat. Confirmed live via `rtl_433 -A`: every Nexus
  // capture showed ~7 more pulses than the clean expected count (147 for
  // 4 repeats) and exactly one anomalously wide pulse near the start of
  // each burst, both consistent with a short default sync word being
  // silently prepended once per transmit() call.
  radio.setSyncWord(NULL, 0);
  radio.setOutputPower(10);

  Serial.println("Radio OK");
  Serial.println("Fake sensor fleet:");
  for (int i = 0; i < NUM_SENSORS; i++) {
    Serial.print(sensors[i].enabled ? "  #" : "  (disabled) #"); Serial.print(i);
    Serial.print(" "); Serial.print(protocolLabel(sensors[i].protocol));
    Serial.print(" id=0x"); Serial.print(sensors[i].id, HEX);
    Serial.print(" ch="); Serial.print(sensors[i].channel);
    Serial.println(sensors[i].batteryOk ? " battery=OK" : " battery=LOW");
  }

  oled("Radio OK", String(NUM_SENSORS) + " fake sensors ready");
}


void loop() {
  FakeSensor &s = sensors[currentSensorIdx];

  if (!s.enabled) {
    // Skip entirely -- no TX, no delay -- so disabling sensors while
    // debugging actually speeds the round up instead of just leaving
    // dead air where their slot used to be. Still runs the round-complete
    // check below: if a disabled sensor happens to be the LAST one in
    // the fleet, the end-of-round pause must still fire, not get
    // silently skipped along with the (nonexistent) transmission.
    bool roundComplete = (currentSensorIdx == NUM_SENSORS - 1);
    currentSensorIdx = (currentSensorIdx + 1) % NUM_SENSORS;
    if (roundComplete) {
      Serial.println("-- round complete (last sensor disabled), pausing before next sequence --");
      delay(ROUND_PAUSE_MS);
    }
    return;
  }

  float tempC = readFakeTempC() + s.tempOffsetC;
  s.humidity = nextHumidity(s.humidity); // random-walks from its own last value

  int numBytes;
  int brState;
  switch (s.protocol) {
    case PROTO_LACROSSE:
      brState = radio.setBitRate(4.8);
      numBytes = buildLacrossePacket(s.id, s.batteryOk, /*test=*/false,
                                      s.channel, tempC, s.humidity);
      break;
    case PROTO_NEXUS:
      brState = radio.setBitRate(NEXUS_BAUD_KBPS);
      numBytes = buildNexusPacket(s.id, s.batteryOk, /*test=*/false,
                                   s.channel, tempC, s.humidity);
      break;
    case PROTO_AMBIENT:
      brState = radio.setBitRate(AMBIENT_BAUD_KBPS);
      // Ambient Weather's real protocol is Fahrenheit-native (see the
      // builder's own comment block) -- converted here, at the call
      // site, rather than inside readFakeTempC(), since that helper is
      // shared by all six protocols and most of them are Celsius.
      numBytes = buildAmbientPacket(s.id, s.batteryOk, s.channel,
                                     tempC * 1.8f + 32.0f, s.humidity);
      break;
    case PROTO_RUBICSON:
      brState = radio.setBitRate(NEXUS_BAUD_KBPS); // same 1000-baud PPM scheme as Nexus
      numBytes = buildRubicsonPacket(s.id, s.batteryOk, s.channel, tempC);
      break;
    case PROTO_WGPB12:
      brState = radio.setBitRate(WGPB_CHIP_KBPS);
      numBytes = buildWgPb12Packet(s.id, tempC); // no channel/battery/humidity field on this device
      break;
    case PROTO_COTECH:
    default:
      brState = radio.setBitRate(AMBIENT_BAUD_KBPS); // same 2000-baud Manchester scheme as Ambient
      numBytes = buildCotechPacket(s.id, s.batteryOk, tempC * 1.8f + 32.0f, s.humidity); // also Fahrenheit-native
      break;
  }
  // Was previously unchecked -- if this fails, the chip silently keeps
  // whatever bitrate it already had (the OTHER protocol's rate), and
  // everything downstream (the built buffer, the log line, the OLED)
  // looks completely normal even though the actual on-air timing is
  // now wrong for whichever protocol is really about to transmit.
  if (brState != RADIOLIB_ERR_NONE) {
    Serial.print("setBitRate FAILED, code=");
    Serial.println(brState);
  }
  // Settling delay for the PLL/clock divider after a live bitrate
  // change -- LaCrosse never needs this since consecutive LaCrosse
  // bursts leave the rate unchanged, but the very first bits sent
  // right after switching rate could be affected if the SX1276 needs
  // a brief moment to stabilize on the new BitRate register value.
  // Confirmed live via `rtl_433 -A`: Nexus's gap timing (1000/2000/
  // 4004us) was landing exactly right, but a couple of PULSES per
  // burst came out double- or 5x-width, as if a low chip between two
  // highs occasionally vanished -- this delay tests that theory
  // directly rather than guessing at the protocol encoding again.
  delay(5);

  Serial.print("TX ");
  Serial.print(protocolLabel(s.protocol));
  Serial.print(" [");
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

  // Theory being tested: RadioLib's SX127x FSK/OOK engine may default to
  // variable-length packet mode, silently prepending a length byte ahead
  // of the payload -- setup() already disables preamble/sync/CRC but
  // never addressed this. Live `rtl_433 -A` showed WG-PB12V1 (the one
  // truly zero-redundancy protocol here) consistently getting exactly
  // one extra pulse near the start regardless of dummy-pulse size,
  // ruling out a PA-settling explanation. Called per-transmission
  // (not once in setup()) since numBytes genuinely varies by protocol.
  radio.fixedPacketLengthMode(numBytes);
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

  // Real TX141TH-Bv2 bursts repeat every ~50s; TX_INTERVAL_MS is
  // shortened by default for quick iteration -- tune it at the top of
  // the file.
  delay(TX_INTERVAL_MS);

  // Extra breather after a full round through the fleet (i.e. right
  // after the last sensor), before starting the next round from
  // sensor #1 again -- ROUND_PAUSE_MS, also tunable at the top.
  if (roundComplete) {
    Serial.println("-- round complete, pausing before next sequence --");
    delay(ROUND_PAUSE_MS);
  }
}
