/*
  ================================================================
  LICENSING WARNING -- READ BEFORE USING THE TX (SEND) FEATURES
  ================================================================
  This sketch transmits real RF on 439.9875 MHz, DAPNET's real POCSAG
  paging frequency. Transmitting there is regulated radio transmission
  on amateur radio spectrum, not a toy/ISM-band experiment: you must
  hold a valid amateur radio license covering this band and its
  station self-identification requirements in your jurisdiction
  before using TX. RX (listening only) needs no license at all --
  only TX is gated.

  As of the callsign feature below, this sketch enforces its own part
  of that: it refuses to transmit anything until a callsign is
  configured (web dashboard's "Callsign" card), and prefixes every
  outgoing message with that callsign for on-air identification.
  That's a courtesy/reminder mechanism, NOT a substitute for actually
  being licensed -- a correctly-prefixed transmission from an
  unlicensed operator is still an unlicensed transmission.
  ================================================================

  TTGO LoRa32 V2.1.6 -- bidirectional POCSAG companion: listens
  continuously for real POCSAG traffic and prints one JSON line per
  decoded page over Serial, while also accepting JSON lines over Serial
  to transmit a page live. Aimed at eventually being driven by
  meshpoint itself over USB serial, the same shape as the existing
  Meshtastic/MeshCore USB companion sources in
  src/audio/pager_listener.py's siblings (capture.meshtastic_usb /
  capture.meshcore_usb already talk to a USB-attached radio over
  serial for those protocols) -- a `capture.pocsag_usb`-style source
  reusing that same pattern is the natural next step from here.

  Sibling of extra/pocsag_test/pocsag_test.ino, not a replacement for
  it: pocsag_test.ino is a fake pager fleet built to test meshpoint's
  OWN dashboard decoder (rtl_fm | multimon-ng) and stays exactly as it
  is for that purpose. This file is a different tool with a different
  job -- a real send/receive companion, no fake fleet, no dashboard
  test scaffolding. Every piece of protocol logic below (alpha
  auto-padding, RX packet-mode decode) was ported over already-verified
  from pocsag_test.ino, not re-derived from scratch.

  ---- TX (send) ----
  Uses RadioLib's PagerClient (src/protocols/Pager/Pager.{h,cpp}) the
  same way pocsag_test.ino does: builds the whole preamble/sync/idle/
  BCH(31,21)-FEC frame and transmits it via the chip's DIRECT mode (raw
  SPI carrier-frequency writes per bit, software-timed) -- no DIO2
  needed for TX, see pocsag_test.ino's own header for why.

  ---- RX (receive) ----
  RadioLib's own receive-side PagerClient::startReceive() needs a GPIO
  wired to the SX1276's DIO2 (continuous-mode raw-bit output), which
  isn't broken out on this board. Instead, this uses the chip's
  STANDARD FSK packet engine entirely over SPI:
    - setSyncWord() configured to POCSAG's own frame-sync code word
      (0x7CD215D8) -- the hardware bit-correlator finds it for us.
    - fixedPacketLengthMode(64) -- 64 bytes = 16 code words = exactly
      one POCSAG batch's worth of DATA code words (the sync word itself
      is consumed by the correlator match, never delivered as
      payload). 64 also happens to be RADIOLIB_SX127X_MAX_PACKET_LENGTH_FSK
      (SX127x.h) -- the FSK FIFO's own physical size -- so this needs
      no mid-packet FIFO-refill handling, the numbers just line up.
    - setCrcFiltering(false) -- POCSAG uses its own BCH(31,21), not the
      chip's built-in CRC.
  No BCH error correction on decode (RadioLib's own
  PagerClient::readData() doesn't do this either -- its own literal
  "TODO BCH error correction here" comment in Pager.cpp). A code word
  with enough bit errors just fails to look like a valid address, or
  decodes to garbled text, and gets skipped/shown as-is -- the same
  tradeoff multimon-ng makes without a full BCH decoder.

  ---- Half-duplex switching ----
  One antenna, one chip -- can't TX and RX at once. Normally sits
  configured for RX and listens continuously; when a JSON send line
  arrives over Serial, configureForTx() reconfigures the radio,
  pager.transmit() sends it, then configureForRx() switches straight
  back and listening resumes. Both configure functions do a full
  radio.beginFSK() re-init every switch -- a little wasteful, but sends
  are infrequent relative to idle listening, and correctness matters
  far more here than shaving a few milliseconds off a switch that
  happens on-demand, not in a tight loop.

  LIVE-VERIFIED 2026-07-29: the combined switch-back-and-forth works --
  a serial-triggered send completed correctly (SENT OK) while RX was
  active, and RX resumed decoding real DAPNET traffic normally
  afterward, no hang or state corruption. Real pages decoded correctly
  across many capcodes/message types before and after the switch,
  including a full ISS pass (rise/maximum/set bulletins on capcode 1051)
  and the user's own sent test messages/callsign.

  Serial protocol -- one JSON object per line, in both directions:
    IN  (send):     {"text": "Hello"}  or  {"capcode": 112, "text": "Hello"}
    OUT (received): {"capcode":2041152,"function":3,"type":"alpha","text":"Hello"}

  ---- WiFi / NTP / OTA ----
  All three best-effort, none of them block core POCSAG operation if
  unavailable: WiFi connect is attempted once at boot with a bounded
  timeout (WIFI_CONNECT_TIMEOUT_MS below) -- if it fails or no
  credentials are configured, the sketch carries on RX/TX-only exactly
  as before, no WiFi/NTP/OTA/mDNS. Once WiFi is up, mDNS is started
  under MDNS_HOSTNAME (below), so the device is reachable at
  pocsag-companion.local without needing to know its DHCP address --
  that same MDNS_HOSTNAME is reused verbatim as the ArduinoOTA hostname,
  so there's one name for the device network-wide, not two different
  ones. NTP (configTime()) only runs after a successful WiFi connect,
  and just sets the ESP32's own RTC so decoded-page JSON could carry a
  real "time" field later if that's ever needed. OTA (ArduinoOTA)
  likewise only starts if WiFi came up, and needs its own password
  (also in secrets.h) -- an unauthenticated OTA listener on a device
  that's also decoding a real amateur radio network would be a bad
  idea.

  WiFi/OTA credentials live in secrets.h, INTENTIONALLY NOT INCLUDED IN
  THIS FILE and gitignored (see .gitignore) -- never hardcode real
  credentials directly in a tracked .ino. See secrets.h itself (created
  alongside this file with placeholder values) for what to fill in.

  ---- Display power ----
  The OLED was staying on indefinitely, which isn't great for an
  always-on companion device sitting on a desk. Auto-blanks after
  DISPLAY_TIMEOUT_MS of no new screen content (uses the panel's own
  real DISPLAYOFF/DISPLAYON command, not just clearing pixels, so it
  actually saves power) and the physical BOOT button (GPIO0, already
  present on this board, no extra wiring) toggles it manually at any
  time -- a manual toggle also resets the idle timer.

  ---- Web dashboard ----
  Once WiFi is up, a small password-gated single-page UI is served at
  http://pocsag-companion.local/ (styled after meshpoint's own dashboard
  color scheme). Three cards: a live in/outgoing log (same ring buffer
  and housekeeping-page filter as the Serial JSON stream), a capcode +
  message send form (POSTs to /api/send, which stages the request for
  loop() to actually transmit -- see the web dashboard section's own
  comment for why a web request can't call sendPocsagAlpha() directly),
  and a screen-timeout setting (POSTs to /api/timeout, backs the same
  displayTimeoutMs the physical button/idle-blank logic already uses, 0
  = never blank). Login password is WEB_PASSWORD in secrets.h -- a
  client-side modal collects it and every API call carries it in an
  X-Auth-Password header, checked server-side on every request, not just
  used to hide the page.

  ---- Multi-board support ----
  Pick exactly one board with the BOARD_* #define right below this comment.
  Everything pin-related and the radio chip class follow from that choice
  (see the "Radio" section further down).

  Both TTGO (SX1276) and Heltec WiFi LoRa32 V3 (SX1262) do RX+TX --
  LIVE-VERIFIED on real hardware for both, including real DAPNET traffic
  decoded and a full TX-with-callsign-prefix round trip cross-checked
  against the independent RTL-SDR/multimon-ng dashboard chain (see
  project memory for the exact confirmation log). RX bypasses
  PagerClient's own (broken-on-SX126x) direct-mode RX entirely on both
  chips -- it talks to the chip's standard FSK packet engine directly
  (setSyncWord()/fixedPacketLengthMode()/readData()), which both SX1276
  and SX1262 have. The SX1276-specific bit-inversion quirk
  (POCSAG_SYNC_BYTES/PAYLOAD_INVERT below) turned out to carry over to
  SX1262 completely unchanged -- worked on the very first flash, no
  repeat of the TTGO's own live-debugging saga needed.

  TTGO LoRa32 V2.1.6 (SX1276) -- same board as
  extra/pocsag_test/pocsag_test.ino:
  SPI:  SCK 5, MISO 19, MOSI 27, CS 18
  LoRa: RST 14, DIO0 26
  OLED: SDA 21, SCL 22
  Button: GPIO0 -- wait, see BUTTON_GPIO's own comment below, this file's
    copy currently uses GPIO38 (changed from GPIO0 during testing; if
    your TTGO's BOOT button is on GPIO0 like most, change it back)

  Heltec WiFi LoRa32 V3 (HTIT-WB32LA(F), ESP32-S3 + SX1262):
  SPI:  SCK 9, MISO 11, MOSI 10, CS 8
  LoRa: RST 12, BUSY 13, DIO1 14
  OLED: SDA 17, SCL 18, RST 21 (its own DEDICATED pin, NOT shared with
    LORA_RST -- see the `display` object's own comment, Radio section
    below, for the two real, live-hardware-confirmed pin bugs this file
    had before checking the ESP32 core's own board file: GPIO21 was
    wrongly believed to be Vext and held permanently LOW, i.e. the OLED
    permanently in reset; the real Vext, GPIO36, was never touched)
  VEXT_PIN GPIO36: external power switch for the OLED + onboard sensors,
    active LOW = powered on.
  Button: GPIO0 (USER_SW / PRG, per Heltec's own published pin-map)
  RX+TX LIVE-CONFIRMED working on real hardware 2026-07-29; the OLED pin
  fixes above have NOT been re-flashed/confirmed yet as of this comment.

  Network (once WiFi connects, see secrets.h): pocsag-companion.local
*/

// ==== BOARD SELECT ====
// Uncomment exactly one of these before compiling.
//#define BOARD_TTGO_LORA32
#define BOARD_HELTEC_WIFI_LORA32_V3

#if defined(BOARD_TTGO_LORA32) && defined(BOARD_HELTEC_WIFI_LORA32_V3)
  #error "Uncomment only ONE board in the BOARD SELECT block above"
#elif !defined(BOARD_TTGO_LORA32) && !defined(BOARD_HELTEC_WIFI_LORA32_V3)
  #error "Uncomment exactly ONE board in the BOARD SELECT block above"
#endif

// Short board identifier, reused by the boot banner and the serial
// {"cmd":"status"} reply -- one place to keep in sync if a third board
// is ever added.
#if defined(BOARD_TTGO_LORA32)
  #define BOARD_NAME_STR "ttgo"
#elif defined(BOARD_HELTEC_WIFI_LORA32_V3)
  #define BOARD_NAME_STR "heltec"
#endif

#include <Arduino.h>
#include <SPI.h>
#include <Wire.h>
#include <time.h>

#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

#include <RadioLib.h>
#include <ArduinoJson.h> // v7.4.3 -- JsonDocument/deserializeJson v7 API

#include <WiFi.h>
#include <ESPmDNS.h>
#include <ArduinoOTA.h>
#include <AsyncTCP.h>
#include <ESPAsyncWebServer.h>
#include <freertos/semphr.h>
#include <Preferences.h> // ESP32 core, NVS-backed key/value store -- persists the
                          // callsign and screen timeout across reboots
#include "secrets.h" // gitignored -- WIFI_SSID/WIFI_PASSWORD/OTA_PASSWORD/WEB_PASSWORD, see that file

// Turns a macro's expanded VALUE into a string literal (two-step indirection
// needed so e.g. BUTTON_GPIO expands to its number before stringifying --
// STRINGIFY(BUTTON_GPIO) alone would produce the literal text "BUTTON_GPIO").
// Used below to bake the per-board BUTTON_GPIO value into INDEX_HTML at
// compile time, so the web UI's hint text doesn't hardcode a pin number
// that's only right for one of the two boards.
#define STRINGIFY(x) #x
#define TOSTRING(x) STRINGIFY(x)

// ---------- Tuning knobs ----------
#define POCSAG_FREQ_MHZ 439.9875f // DAPNET's real German transmitter frequency --
                                   // see pocsag_test.ino's own POCSAG_BAUD comment
                                   // for why this isn't just an arbitrary test pick
#define POCSAG_BAUD 1200           // LIVE-VERIFIED correct for TX in pocsag_test.ino;
                                   // NORMAL polarity, DAPNET-compatible
#define POCSAG_RX_BANDWIDTH_KHZ 20.8f // Carson's rule for 1200bps/4.5kHz deviation is
                                   // ~11.4kHz; picked wider for tolerance to real-world
                                   // frequency error. RadioLib rounds to the nearest
                                   // hardware-supported value regardless.
#define POCSAG_RX_BATCH_BYTES 64  // 16 code words -- see the file header for why
#define SERIAL_DEFAULT_CAPCODE 2041152UL // used when an incoming send JSON line omits "capcode"

#define MDNS_HOSTNAME "pocsag-companion" // reachable at pocsag-companion.local once WiFi
                                   // connects; also used verbatim as the ArduinoOTA
                                   // hostname below so both point at the same device
#define WIFI_CONNECT_TIMEOUT_MS 10000UL // bounded -- never hang core POCSAG RX/TX
                                   // waiting on WiFi that isn't there
#define DISPLAY_TIMEOUT_MS_DEFAULT 10000UL // startup value for the runtime
                                   // displayTimeoutMs below (settable live from the
                                   // web UI's "Screen Timeout" card, 0 = never blank)
// BUTTON_GPIO is defined per-board in the "Radio" section below (it isn't
// the same pin on both boards).
#define WEB_LOG_SIZE 40            // ring buffer size backing the web UI's log card
#define CALLSIGN_MAX_LEN 8         // real amateur callsigns top out around here even
                                   // for the rare extra-long ones (e.g. a Dutch
                                   // anniversary novice callsign like "PD750AMS" is
                                   // 8 characters) -- generous, not arbitrary
#define PREFS_NAMESPACE "pocsag"  // NVS namespace for the callsign + screen timeout

// Flip to true to bring back the live RSSI/DIO0 trace that was used to
// find and confirm the RX fixes documented above (kept, not deleted --
// still genuinely useful if RX ever regresses or moves to new hardware).
// Off by default now that real pages are decoding correctly; the log
// spam isn't needed for normal use.
bool DEBUG_RX = false;

// BITWISE-INVERTED RADIOLIB_PAGER_FRAME_SYNC_CODE_WORD (0x7CD215D8), not the
// plain value -- confirmed against RadioLib's own direct-mode receive code
// (PagerClient::startReceiveCommon() in Pager.cpp): "the logic here is
// inverted, because modules like SX1278 assume high frequency to be logic 1,
// which is opposite to POCSAG" -- it searches for
// ~RADIOLIB_PAGER_FRAME_SYNC_CODE_WORD when invert=false (our default, same
// as our own TX side uses), and its read() function inverts every full
// codeword the same way (`codeWord = ~codeWord`) -- see PAYLOAD_INVERT below,
// applied to every received byte for the identical reason. Live-confirmed
// necessary: real strong signal spikes (RSSI up to -17dBm from a ~-85dBm
// floor) never triggered DIO0/PayloadReady at all against the plain
// (non-inverted) sync word, no matter how strong the real signal was.
const uint8_t POCSAG_SYNC_BYTES[4] = { 0x83, 0x2D, 0xEA, 0x27 };


// ---------- OLED ----------

#define OLED_WIDTH 128
#define OLED_HEIGHT 64

// The `display` object itself is declared after the "Radio" section below
// (see its own comment there for why), not here.


// ---------- Radio ----------
//
// Pin values and the RX-support flag come from the BOARD SELECT block at
// the top of the file -- see its comment there for the full reasoning
// (RX is TTGO/SX1276-only, never attempted on the Heltec/SX1262 build).

#if defined(BOARD_TTGO_LORA32)
  #define LORA_SCK  5
  #define LORA_MISO 19
  #define LORA_MOSI 27
  #define LORA_CS   18
  #define LORA_RST  14
  #define LORA_DIO0 26
  #define LORA_IRQ_PIN LORA_DIO0 // pin loop() polls for "packet received"
  #define OLED_SDA_PIN 21
  #define OLED_SCL_PIN 22
  #define BUTTON_GPIO 38 // BOOT button -- see the header comment's own note;
                          // most TTGO boards have this on GPIO0
  #define POCSAG_RX_SUPPORTED 1 // LIVE-VERIFIED, see project memory

  SX1276 radio = new Module(LORA_CS, LORA_DIO0, LORA_RST, -1);

#elif defined(BOARD_HELTEC_WIFI_LORA32_V3)
  #define LORA_SCK  9
  #define LORA_MISO 11
  #define LORA_MOSI 10
  #define LORA_CS   8
  #define LORA_RST  12
  #define LORA_BUSY 13
  #define LORA_DIO1 14
  #define LORA_IRQ_PIN LORA_DIO1 // SX126x's single IRQ pin -- radio.startReceive()
                                  // routes RX_DONE here the same way SX127x's
                                  // packet mode routes PayloadReady to DIO0
  #define OLED_SDA_PIN 17
  #define OLED_SCL_PIN 18
  // GROUND TRUTH for these two, from the ESP32 core's own board file
  // (~/Library/Arduino15/.../variants/heltec_wifi_lora_32_V3/pins_arduino.h,
  // the exact file arduino-cli already compiles against) and cross-checked
  // against Meshtastic's heltec_v3 variant.h -- this file had BOTH of
  // these wrong in earlier drafts (a diagram-based guess claimed GPIO21
  // was Vext and OLED reset was shared with LORA_RST; neither was true):
  #define OLED_RST_PIN 21 // OLED's own DEDICATED reset pin (RST_OLED in the
                           // board file) -- NOT shared with LORA_RST (12) at
                           // all. LIVE BUG from the previous draft: this pin
                           // was being driven LOW and left there thinking it
                           // was a Vext power switch -- holding the OLED in
                           // permanent hardware reset the entire time, which
                           // alone fully explains the blank screen.
  #define VEXT_PIN 36 // the REAL Vext power switch (Vext in the board file) --
                      // active LOW = powered on. Never touched at all in the
                      // previous draft (GPIO21 was wrongly used for this
                      // instead), so the OLED's power rail may not even have
                      // been enabled on top of the reset bug above.
  #define BUTTON_GPIO 0 // USER_SW / PRG, per Heltec's pin-map
  #define POCSAG_RX_SUPPORTED 1 // LIVE-VERIFIED 2026-07-29 -- real DAPNET traffic
                                 // decoded correctly on first flash, no debugging
                                 // needed. The SX1276 bit-inversion assumption
                                 // (POCSAG_SYNC_BYTES/payload inversion) carried
                                 // over to SX1262 unchanged. Full TX+prefix+RX
                                 // round trip also confirmed (see project memory).

  SX1262 radio = new Module(LORA_CS, LORA_DIO1, LORA_RST, LORA_BUSY);
#endif

// TTGO: the OLED has no dedicated reset pin at all, so -1 ("Adafruit_SSD1306
// doesn't drive a reset pin"). Heltec: OLED_RST_PIN (GPIO21) IS a real,
// dedicated reset pin, confirmed against the ESP32 core's own board file
// (RST_OLED) and cross-checked against Meshtastic's heltec_v3 variant.h --
// completely separate from LORA_RST (GPIO12), not shared with anything, so
// it's safe to hand to Adafruit_SSD1306 unlike the earlier (wrong) belief
// that it was shared with the radio. Two real, live-hardware-confirmed bugs
// existed in earlier drafts of this board's OLED setup, both from acting on
// incorrect pin information before this ground truth was found:
//   1. GPIO21 was believed to be the "Vext" power switch and driven LOW then
//      left there -- but GPIO21 is actually OLED_RST, so this held the OLED
//      in permanent hardware reset the whole time. Alone sufficient to
//      explain a permanently blank screen.
//   2. The REAL Vext (GPIO36) was never touched at all, so the OLED's power
//      rail may not have even been switched on.
// See VEXT_PIN's own comment and setup() for the power-on fix.
#if defined(BOARD_TTGO_LORA32)
  Adafruit_SSD1306 display(OLED_WIDTH, OLED_HEIGHT, &Wire, -1);
#elif defined(BOARD_HELTEC_WIFI_LORA32_V3)
  Adafruit_SSD1306 display(OLED_WIDTH, OLED_HEIGHT, &Wire, OLED_RST_PIN);
#endif

// PagerClient wraps the radio module for TX -- see the file header for
// what it handles internally. TX (transmitDirect()) is implemented
// uniformly across RadioLib chip classes, so this works unchanged on
// either board. RX below (TTGO/SX1276 only) talks to `radio` directly
// (the chip's standard packet engine), bypassing PagerClient entirely.
PagerClient pager(&radio);

bool radioInRxMode = false; // tracks current hardware config so configureForRx()/
                             // configureForTx() know whether a switch is actually needed
bool rxContinuousStarted = false; // whether radio.startReceive() has been (re-)armed
                             // since the last configureForRx() -- see loop()


// ---------- Forward declarations ----------
//
// Arduino's auto-prototype generator (a brace-counting heuristic, not a
// real parser) loses track of scope inside the web dashboard section's
// raw HTML/CSS/JS string literal further down this file, so it fails to
// auto-declare anything defined after that point. These are called from
// functions defined earlier in the file (setupWifiNtpOta(),
// decodeBatchAndEmit(), sendPocsagAlpha()), so they need explicit
// prototypes here instead of relying on the auto-generated ones.
void oled(const String &line1, const String &line2);
void showListeningScreen();
void showIncomingScreen(uint32_t capcode, const String &type, const String &text);
void showSentScreen(uint32_t capcode, const String &text, int state);
void setupWebServer();

// Same forward-reference problem, but for a global VARIABLE rather than
// a function -- Arduino's auto-prototyping only ever covers functions,
// so `prefs` (declared further down, right before getCallsign()/
// setCallsign()) needs an explicit extern here for handleSetCallsignCommand()
// (defined earlier in the file, alongside handleSerialJsonLine()) to
// persist a serial-set callsign to NVS the same way /api/callsign does.
extern Preferences prefs;
// Same reason -- txCount/lastTxOk are declared right before
// sendPocsagAlpha(), further down than sendStatusReply() (which reports
// them for the dashboard's periodic status poll).
extern int txCount;
extern bool lastTxOk;
// Same reason -- rebootRequested/rebootRequestedAt are declared much
// further down (right before the web dashboard's /api/reboot handler),
// needed by handleRebootCommand() defined up near the other serial
// command handlers.
extern bool rebootRequested;
extern unsigned long rebootRequestedAt;


// ---------- WiFi / NTP / OTA ----------
//
// All best-effort -- see the file header for the full rationale. Runs once
// at boot, after the radio's already configured for RX, so a slow/failed
// WiFi connect only adds a bounded delay before the "ready" banner, never
// blocks it outright.

bool wifiConnected = false;

void setupWifiNtpOta() {
  // Reads via the runtime getters (NVS override if set via {"cmd":"set_wifi"},
  // else the secrets.h compile-time default loaded into them at boot) --
  // never the raw WIFI_SSID/WIFI_PASSWORD macros directly, so a serial-set
  // override actually takes effect on the next reboot.
  String ssid = getWifiSsid();
  String pass = getWifiPassword();

  if (ssid.length() == 0 || ssid == "YOUR_WIFI_SSID") {
    Serial.println("[wifi] no credentials configured, skipping WiFi/NTP/OTA");
    return;
  }

  WiFi.mode(WIFI_STA);
  WiFi.setHostname(MDNS_HOSTNAME);
  WiFi.begin(ssid.c_str(), pass.c_str());

  Serial.print("[wifi] connecting to "); Serial.print(ssid);
  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < WIFI_CONNECT_TIMEOUT_MS) {
    delay(250);
    Serial.print(".");
  }
  Serial.println();

  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[wifi] connect timed out, continuing RX/TX-only");
    return;
  }

  wifiConnected = true;
  Serial.print("[wifi] connected, IP="); Serial.println(WiFi.localIP());

  if (MDNS.begin(MDNS_HOSTNAME)) {
    Serial.print("[mdns] reachable at "); Serial.print(MDNS_HOSTNAME); Serial.println(".local");
  } else {
    Serial.println("[mdns] begin() failed");
  }

  // UTC, no DST -- decoded-page timestamps (if added later) or Serial logs
  // showing wall-clock time don't need a specific local offset to be useful.
  configTime(0, 0, "ntp.time.nl", "pool.ntp.org", "time.nist.gov");
  Serial.print("[ntp] syncing");
  struct tm timeinfo;
  unsigned long ntpStart = millis();
  while (!getLocalTime(&timeinfo, 0) && millis() - ntpStart < 10000) {
    delay(250);
    Serial.print(".");
  }
  Serial.println();
  Serial.println(getLocalTime(&timeinfo, 0) ? "[ntp] synced" : "[ntp] sync timed out (non-fatal)");

  // Same hostname as WiFi/mDNS above, so "what is this device called on the
  // network" has one answer everywhere, not three different ones.
  ArduinoOTA.setHostname(MDNS_HOSTNAME);
  ArduinoOTA.setPassword(OTA_PASSWORD);
  ArduinoOTA.onStart([]() {
    Serial.println("[ota] update starting");
    oled("OTA update", "starting...");
  });
  ArduinoOTA.onEnd([]() {
    Serial.println("[ota] update complete");
    oled("OTA update", "done, rebooting");
  });
  ArduinoOTA.onProgress([](unsigned int progress, unsigned int total) {
    Serial.printf("[ota] progress: %u%%\n", (progress * 100) / total);
  });
  ArduinoOTA.onError([](ota_error_t error) {
    Serial.print("[ota] error "); Serial.println((int)error);
  });
  ArduinoOTA.begin();
  Serial.println("[ota] ready");

  setupWebServer(); // only reachable at all once WiFi is up, so started here
}


// ---------- Display power ----------
//
// The OLED was staying on indefinitely -- not great for an always-on
// desk companion. Auto-blanks via the panel's own real DISPLAYOFF command
// (not just clearing pixels, so it actually saves power) after
// displayTimeoutMs with no new screen content, and the physical BOOT
// button (GPIO0, already present on this board) toggles it manually at
// any time. Every show*()/oled() call below routes through wakeDisplay()
// first, so any real screen update both wakes the panel if it was off and
// resets the idle timer -- callers don't need to think about display
// power at all.

bool displayOn = true;
unsigned long lastDisplayActivity = 0;
// Runtime-settable (starts at DISPLAY_TIMEOUT_MS_DEFAULT, changeable live from
// the web UI's "Screen Timeout" card via POST /api/timeout) -- a plain
// uint32_t read/write is effectively atomic on ESP32 for this purpose, no
// mutex needed the way the web log/send handoff below genuinely require one
// (those move Strings across tasks, this is a single aligned word). 0 means
// "never auto-blank."
uint32_t displayTimeoutMs = DISPLAY_TIMEOUT_MS_DEFAULT;

void wakeDisplay() {
  if (!displayOn) {
    display.ssd1306_command(SSD1306_DISPLAYON);
    displayOn = true;
  }
  lastDisplayActivity = millis();
}

void toggleDisplay() {
  displayOn = !displayOn;
  display.ssd1306_command(displayOn ? SSD1306_DISPLAYON : SSD1306_DISPLAYOFF);
  lastDisplayActivity = millis(); // manual toggle also resets the idle timer
}

// Simple time-based debounce (50ms) -- GPIO0 is active-low with an internal
// pull-up, so idle reads HIGH and a press reads LOW.
void checkButton() {
  static bool lastReading = HIGH;
  static unsigned long lastChangeAt = 0;

  bool reading = digitalRead(BUTTON_GPIO);
  if (reading != lastReading) {
    lastChangeAt = millis();
    lastReading = reading;
  }
  if (millis() - lastChangeAt > 50) {
    static bool debouncedState = HIGH;
    if (reading != debouncedState) {
      debouncedState = reading;
      if (debouncedState == LOW) toggleDisplay(); // pressed
    }
  }
}


// ---------- Alpha auto-padding for outgoing messages ----------
//
// Verbatim port of the same simBuild()/simDecode()/padAlphaForCleanDecode()
// logic already verified in pocsag_test.ino against RadioLib's real
// encode+decode algorithm (see that file's long comment on its pagers[]
// array for how the underlying bug -- RadioLib's ASCII encoder leaving
// un-padded zero bits that arrive as embedded NULs -- was found and
// confirmed). Reused here unchanged; nothing about it is TX/RX-mode
// specific.
RadioLibBCH padSimBch;

uint32_t *simBuild(const uint8_t *data, size_t len, uint32_t addr, size_t *outMsgLen, uint8_t *outFramePos) {
  const uint8_t symbolLength = 7; // ASCII only -- this helper is alpha-specific
  uint8_t framePos = 2 * (addr & 0x07);
  *outFramePos = framePos;

  size_t numDataBlocks = (len * symbolLength) / RADIOLIB_PAGER_MESSAGE_BITS_LENGTH;
  if ((len * symbolLength) % RADIOLIB_PAGER_MESSAGE_BITS_LENGTH > 0) numDataBlocks += 1;
  size_t numBatches = (framePos + numDataBlocks + RADIOLIB_PAGER_BATCH_LEN) / RADIOLIB_PAGER_BATCH_LEN;
  size_t msgLen = RADIOLIB_PAGER_PREAMBLE_LENGTH + (1 + RADIOLIB_PAGER_BATCH_LEN) * numBatches;

  uint32_t *msg = new uint32_t[msgLen];
  memset(msg, 0x00, msgLen * sizeof(uint32_t));
  for (size_t i = 0; i < RADIOLIB_PAGER_PREAMBLE_LENGTH; i++) msg[i] = RADIOLIB_PAGER_PREAMBLE_CODE_WORD;
  for (size_t i = RADIOLIB_PAGER_PREAMBLE_LENGTH; i < msgLen; i++) msg[i] = RADIOLIB_PAGER_IDLE_CODE_WORD;
  for (size_t i = 0; i < numBatches; i++) {
    msg[RADIOLIB_PAGER_PREAMBLE_LENGTH + i * (1 + RADIOLIB_PAGER_BATCH_LEN)] = RADIOLIB_PAGER_FRAME_SYNC_CODE_WORD;
  }

  uint32_t frameAddr = ((addr >> 3) << RADIOLIB_PAGER_ADDRESS_POS) | (RADIOLIB_PAGER_FUNC_BITS_ALPHA << RADIOLIB_PAGER_FUNC_BITS_POS);
  msg[RADIOLIB_PAGER_PREAMBLE_LENGTH + 1 + framePos] = padSimBch.encode(frameAddr);

  if (len > 0) {
    int8_t remBits = 0;
    size_t dataPos = 0;
    for (size_t i = 0; i < numDataBlocks + numBatches - 1; i++) {
      uint8_t blockPos = RADIOLIB_PAGER_PREAMBLE_LENGTH + 1 + framePos + 1 + i;
      if (((blockPos - RADIOLIB_PAGER_PREAMBLE_LENGTH) % (RADIOLIB_PAGER_BATCH_LEN + 1)) == 0) {
        blockPos++;
        i++;
      }
      msg[blockPos] = RADIOLIB_PAGER_MESSAGE_CODE_WORD << (RADIOLIB_PAGER_CODE_WORD_LEN - 1);
      if (remBits > 0) {
        uint8_t prev = rlb_reflect(data[dataPos - 1], 8);
        prev >>= 1;
        msg[blockPos] |= (uint32_t)prev << (RADIOLIB_PAGER_CODE_WORD_LEN - 1 - remBits);
      }
      int8_t symbolPos = RADIOLIB_PAGER_CODE_WORD_LEN - 1 - symbolLength - remBits;
      while (symbolPos > (RADIOLIB_PAGER_FUNC_BITS_POS - symbolLength)) {
        uint8_t symbol = data[dataPos++];
        symbol = rlb_reflect(symbol, 8);
        symbol >>= (8 - symbolLength);
        msg[blockPos] |= (uint32_t)symbol << symbolPos;
        symbolPos -= symbolLength;
        if (dataPos >= len) break;
      }
      msg[blockPos] &= ~(RADIOLIB_PAGER_BCH_BITS_MASK);
      remBits = RADIOLIB_PAGER_FUNC_BITS_POS - symbolPos - symbolLength;
      msg[blockPos] = padSimBch.encode(msg[blockPos]);
    }
  }

  *outMsgLen = msgLen;
  return msg;
}

String simDecode(uint32_t *codewords, size_t numCodewords, size_t startIdx) {
  const uint8_t symbolLength = 7;
  String out;
  uint32_t prevCw = 0;
  bool overflow = false;
  int8_t ovfBits = 0;

  for (size_t idx = startIdx; idx < numCodewords; idx++) {
    uint32_t cw = codewords[idx];
    if (cw == RADIOLIB_PAGER_IDLE_CODE_WORD) break;
    if (cw == RADIOLIB_PAGER_FRAME_SYNC_CODE_WORD) continue;

    uint8_t bitPos = RADIOLIB_PAGER_CODE_WORD_LEN - 1 - symbolLength;
    if (overflow) {
      overflow = false;
      uint8_t currPos = RADIOLIB_PAGER_CODE_WORD_LEN - 1 - symbolLength + ovfBits;
      uint8_t prevPos = RADIOLIB_PAGER_MESSAGE_END_POS;
      uint32_t prevMask = (0x7FUL << prevPos) & ~((uint32_t)0x7FUL << (RADIOLIB_PAGER_MESSAGE_END_POS + ovfBits));
      uint32_t currMask = (0x7FUL << currPos) & ~((uint32_t)1 << (RADIOLIB_PAGER_CODE_WORD_LEN - 1));
      uint8_t prevSymbol = (prevCw & prevMask) >> prevPos;
      uint8_t currSymbol = (cw & currMask) >> currPos;
      uint32_t symbol = prevSymbol << (symbolLength - ovfBits) | currSymbol;
      symbol = rlb_reflect((uint8_t)symbol, 8);
      symbol >>= (8 - symbolLength);
      out += (char)symbol;
      bitPos += ovfBits;
      bitPos -= symbolLength;
    }

    while (bitPos >= RADIOLIB_PAGER_MESSAGE_END_POS) {
      uint32_t symbol = (cw & (0x7FUL << bitPos)) >> bitPos;
      symbol = rlb_reflect((uint8_t)symbol, 8);
      symbol >>= (8 - symbolLength);
      out += (char)symbol;
      int8_t remBits = bitPos - RADIOLIB_PAGER_MESSAGE_END_POS;
      if (remBits < symbolLength) {
        prevCw = cw;
        overflow = true;
        ovfBits = remBits;
      }
      bitPos -= symbolLength;
    }
  }
  return out;
}

String padAlphaForCleanDecode(const String &text, uint32_t addr) {
  for (int pad = 0; pad <= 19; pad++) {
    String candidate = text;
    for (int i = 0; i < pad; i++) candidate += ' ';

    size_t msgLen; uint8_t framePos;
    uint32_t *msg = simBuild((const uint8_t *)candidate.c_str(), candidate.length(), addr, &msgLen, &framePos);
    size_t addrIdx = RADIOLIB_PAGER_PREAMBLE_LENGTH + 1 + framePos;
    String decoded = simDecode(msg, msgLen, addrIdx + 1);
    delete[] msg;

    if (decoded == candidate) {
      if (pad > 0) {
        Serial.print("  (auto-padded with "); Serial.print(pad); Serial.println(" trailing space(s) for a clean decode)");
      }
      return candidate;
    }
  }
  Serial.println("  WARNING: no clean padding found in 0..19 -- sending unpadded, may decode with trailing garbage");
  return text;
}


// ---------- RX decode ----------
//
// Verbatim port of the same decodeBcdChar()/decodeMessageSymbols()/
// decodeBatchAndEmit() logic already verified (compiled and reasoned
// through against RadioLib's own readData() source, see the comments
// inline) in pocsag_test.ino's RX-mode branch.

char decodeBcdChar(uint8_t b) {
  switch (b) {
    case 0x0A: return '*';
    case 0x0B: return 'U';
    case 0x0C: return ' ';
    case 0x0D: return '-';
    case 0x0E: return ')';
    case 0x0F: return '(';
  }
  return (char)(b + '0');
}

String decodeMessageSymbols(uint32_t *codewords, size_t n, size_t startIdx, uint8_t symbolLength, bool bcd, size_t *outConsumed) {
  String out;
  uint32_t prevCw = 0;
  bool overflow = false;
  int8_t ovfBits = 0;
  size_t idx = startIdx;

  for (; idx < n; idx++) {
    uint32_t cw = codewords[idx];
    bool isMessage = (cw & (RADIOLIB_PAGER_MESSAGE_CODE_WORD << (RADIOLIB_PAGER_CODE_WORD_LEN - 1))) != 0;
    if (cw == RADIOLIB_PAGER_IDLE_CODE_WORD || cw == RADIOLIB_PAGER_FRAME_SYNC_CODE_WORD || !isMessage) break;

    uint8_t bitPos = RADIOLIB_PAGER_CODE_WORD_LEN - 1 - symbolLength;
    if (overflow) {
      overflow = false;
      uint8_t currPos = RADIOLIB_PAGER_CODE_WORD_LEN - 1 - symbolLength + ovfBits;
      uint8_t prevPos = RADIOLIB_PAGER_MESSAGE_END_POS;
      uint32_t prevMask = (0x7FUL << prevPos) & ~((uint32_t)0x7FUL << (RADIOLIB_PAGER_MESSAGE_END_POS + ovfBits));
      uint32_t currMask = (0x7FUL << currPos) & ~((uint32_t)1 << (RADIOLIB_PAGER_CODE_WORD_LEN - 1));
      uint8_t prevSymbol = (prevCw & prevMask) >> prevPos;
      uint8_t currSymbol = (cw & currMask) >> currPos;
      uint32_t symbol = prevSymbol << (symbolLength - ovfBits) | currSymbol;
      symbol = rlb_reflect((uint8_t)symbol, 8);
      symbol >>= (8 - symbolLength);
      out += bcd ? decodeBcdChar((uint8_t)symbol) : (char)symbol;
      bitPos += ovfBits;
      bitPos -= symbolLength;
    }

    while (bitPos >= RADIOLIB_PAGER_MESSAGE_END_POS) {
      uint32_t symbol = (cw & (0x7FUL << bitPos)) >> bitPos;
      symbol = rlb_reflect((uint8_t)symbol, 8);
      symbol >>= (8 - symbolLength);
      out += bcd ? decodeBcdChar((uint8_t)symbol) : (char)symbol;
      int8_t remBits = bitPos - RADIOLIB_PAGER_MESSAGE_END_POS;
      if (remBits < symbolLength) {
        prevCw = cw;
        overflow = true;
        ovfBits = remBits;
      }
      bitPos -= symbolLength;
    }
  }
  *outConsumed = idx - startIdx;
  return out;
}

// POCSAG has no message-length field, so the last code word's leftover,
// unused symbol slots decode as whatever bit pattern is actually there --
// LIVE-CONFIRMED trailing NUL byte(s) on real DAPNET traffic (e.g.
// "Test message1\0", "XTIME=...\0\0"). Same ambiguity
// src/audio/pager_listener.py already works around for multimon-ng's own
// decode ("multimon-ng pads POCSAG alpha messages with literal '<NUL>'
// tokens ... strip trailing ones for a clean display") -- mirrored here.
void trimTrailingPadding(String &s) {
  while (s.length() > 0 && s[s.length() - 1] == '\0') {
    s.remove(s.length() - 1);
  }
  s.trim();
}

// Walks one full 16-code-word batch and prints one JSON line per
// decoded page found in it (a batch can carry pages for up to 8
// different capcodes at once, one per frame position). See
// pocsag_test.ino's RX-mode comment for how the capcode/framePos
// reconstruction was confirmed against PagerClient::readData().
int rxBatchCount = 0;

void decodeBatchAndEmit(uint32_t *cw, size_t n) {
  for (size_t i = 0; i < n; i++) {
    uint32_t w = cw[i];
    if (w == RADIOLIB_PAGER_IDLE_CODE_WORD || w == RADIOLIB_PAGER_FRAME_SYNC_CODE_WORD) continue;
    bool isAddress = (w & (RADIOLIB_PAGER_MESSAGE_CODE_WORD << (RADIOLIB_PAGER_CODE_WORD_LEN - 1))) == 0;
    if (!isAddress) continue;

    uint32_t addrField = (w & RADIOLIB_PAGER_ADDRESS_BITS_MASK) >> (RADIOLIB_PAGER_ADDRESS_POS - 3);
    uint32_t capcode = addrField | (i / 2);
    uint8_t function = (w & RADIOLIB_PAGER_FUNCTION_BITS_MASK) >> RADIOLIB_PAGER_FUNC_BITS_POS;
    bool bcd = (function == RADIOLIB_PAGER_FUNC_BITS_NUMERIC);
    uint8_t symbolLength = bcd ? 4 : 7;

    size_t consumed = 0;
    String text = decodeMessageSymbols(cw, n, i + 1, symbolLength, bcd, &consumed);
    trimTrailingPadding(text);

    String typeLabel;
    switch (function) {
      case RADIOLIB_PAGER_FUNC_BITS_NUMERIC:    typeLabel = "numeric";    break;
      case RADIOLIB_PAGER_FUNC_BITS_TONE:       typeLabel = "tone";       break;
      case RADIOLIB_PAGER_FUNC_BITS_ACTIVATION: typeLabel = "activation"; break;
      default:                                  typeLabel = "alpha";     break;
    }

    // A numeric-function page with no digits at all -- live-observed as
    // capcode 2007671 appearing intermittently alongside real messages,
    // always identical and content-less, most likely a recurring
    // network housekeeping/keepalive page rather than a decode error
    // (see the file's own project memory for the full reasoning). Not
    // matched on that specific capcode -- matched on the general shape
    // (NUMERIC function, zero digits), since that's what actually makes
    // it noise for a companion feed, and it covers any other capcode
    // doing the same thing. Tone-only pages are deliberately NOT
    // filtered here even though they also have no text -- a tone page
    // is a real, meaningful alert on its own, unlike an empty numeric.
    bool isHousekeeping = (function == RADIOLIB_PAGER_FUNC_BITS_NUMERIC && text.length() == 0);

    JsonDocument out;
    out["capcode"] = capcode;
    out["function"] = function;
    out["type"] = typeLabel;
    if (text.length() > 0) out["text"] = text;
    // Suppressed from Serial in normal (DEBUG_RX=false) operation so the
    // JSON stream stays clean for meshpoint to consume later -- still
    // printed when DEBUG_RX=true, matching that flag's existing "show me
    // everything" purpose for the RSSI/DIO0 trace above.
    if (DEBUG_RX || !isHousekeeping) {
      serializeJson(out, Serial);
      Serial.println();
      pushWebLog(capcode, function, typeLabel, text, "rx"); // same housekeeping filter as Serial
    }

    // Only update the display for pages that actually have something to
    // show -- content-less pages (tone-only by design, or a numeric page
    // that happens to carry no digits, e.g. capcode 2007671 seen live
    // alongside every real message so far, most likely a recurring
    // network housekeeping/keepalive page rather than a decode error)
    // would otherwise overwrite a just-shown real message with a blank
    // "(no text)" screen a moment later. Still emitted as JSON above
    // either way -- this only affects what's shown on the OLED. A batch
    // can carry more than one real page (up to 8, one per frame
    // position); if so, the screen flashes through each with real text
    // as this loop finds them, ending on whichever was decoded last.
    if (text.length() > 0) showIncomingScreen(capcode, typeLabel, text);

    i += consumed;
  }
}


// ---------- Half-duplex mode switching ----------

void configureForRx() {
  // beginFSK()'s signature differs per chip family (SX1276 has a trailing
  // enableOOK bool, SX1262's has tcxoVoltage/useRegulatorLDO instead, left
  // at their RadioLib defaults) -- see the BOARD SELECT block's comment.
#if defined(BOARD_TTGO_LORA32)
  radio.beginFSK(POCSAG_FREQ_MHZ, POCSAG_BAUD / 1000.0f, 4.5, POCSAG_RX_BANDWIDTH_KHZ, 17, 16, false);
#elif defined(BOARD_HELTEC_WIFI_LORA32_V3)
  radio.beginFSK(POCSAG_FREQ_MHZ, POCSAG_BAUD / 1000.0f, 4.5, POCSAG_RX_BANDWIDTH_KHZ, 17, 16);
#endif
  radio.setSyncWord((uint8_t *)POCSAG_SYNC_BYTES, sizeof(POCSAG_SYNC_BYTES));
  // POCSAG uses its own BCH, not the chip's CRC -- SX127x exposes this as
  // setCrcFiltering(false); SX126x has no such method, CRC is instead
  // configured via setCRC(len), where len=0 means "no CRC" (RadioLib's own
  // beginFSK() calls setCRC(2) internally, so this overrides that default).
#if defined(BOARD_TTGO_LORA32)
  radio.setCrcFiltering(false);
#elif defined(BOARD_HELTEC_WIFI_LORA32_V3)
  radio.setCRC(0);
#endif
  radio.fixedPacketLengthMode(POCSAG_RX_BATCH_BYTES);
  radio.setEncoding(RADIOLIB_ENCODING_NRZ);
  radio.setDataShaping(RADIOLIB_SHAPING_NONE);
  radioInRxMode = true;
}

void configureForTx() {
  // br/freqDev/rxBw here just need to be valid register values --
  // PagerClient::write() bit-bangs its own timing via transmitDirect()
  // and never reads the chip's own bitrate/deviation registers for TX,
  // unlike RX above where they're genuinely load-bearing.
#if defined(BOARD_TTGO_LORA32)
  radio.beginFSK(POCSAG_FREQ_MHZ, 4.8, 5.0, 125.0, 17, 16, false);
#elif defined(BOARD_HELTEC_WIFI_LORA32_V3)
  radio.beginFSK(POCSAG_FREQ_MHZ, 4.8, 5.0, 125.0, 17, 16);
#endif
  radio.setOutputPower(17);
  pager.begin(POCSAG_FREQ_MHZ, POCSAG_BAUD);
  radioInRxMode = false;
}


// ---------- Serial input: JSON-in to send a message live ----------
//
// Same line-accumulation and JSON parsing already verified in
// pocsag_test.ino (including the \r/\n line-ending fix -- see that
// file's own comment for why both are treated as "line complete").

String serialLineBuf;

void checkSerialInput() {
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\n' || c == '\r') {
      serialLineBuf.trim();
      if (serialLineBuf.length() > 0) {
        // set_web_password/set_wifi both carry a real secret in
        // cleartext (same as every other command on this line) -- this
        // log line is the one place that would otherwise echo it back
        // verbatim, so redact specifically these two instead of
        // logging their raw contents like every other line.
        if (serialLineBuf.indexOf("set_web_password") >= 0 ||
            serialLineBuf.indexOf("set_wifi") >= 0) {
          Serial.println("[serial] received line: (credential command, redacted)");
        } else {
          Serial.print("[serial] received line: \""); Serial.print(serialLineBuf); Serial.println("\"");
        }
        handleSerialJsonLine(serialLineBuf);
      }
      serialLineBuf = "";
    } else {
      serialLineBuf += c;
    }
  }
}

// Status reply for a Meshpoint-side capture source to query -- once at
// connect, and again periodically (dapnet.status_poll_interval_s,
// default 60s) so tx_count/last_tx_ok/uptime_ms stay current. Still
// strictly request/response, never an unsolicited broadcast -- the
// Meshpoint side decides the cadence and sends {"cmd":"status"} each
// time, keeping this shared serial line free of chatter that could be
// mistaken for a decoded page.
void sendStatusReply() {
  JsonDocument out;
  out["type"] = "status";
  out["board"] = BOARD_NAME_STR;
  out["callsign"] = getCallsign();
  out["freq"] = POCSAG_FREQ_MHZ;
  out["hostname"] = MDNS_HOSTNAME;
  out["wifi_ssid"] = wifiConnected ? WiFi.SSID() : "";
  out["wifi_ip"] = wifiConnected ? WiFi.localIP().toString() : "";
  // Genuinely live values -- meaningful now that Meshpoint re-queries
  // this periodically instead of only once at connect. uptime_ms wraps
  // to a small number every ~49.7 days (uint32_t millis() overflow) --
  // a real ESP32 limitation, not a bug here; not worth working around
  // for a device that gets power-cycled far more often than that.
  out["tx_count"] = txCount;
  out["last_tx_ok"] = lastTxOk;
  out["uptime_ms"] = millis();
  serializeJson(out, Serial);
  Serial.println();
}

// Sets the operator callsign over the same JSON serial link the web
// dashboard's own /api/callsign already uses -- same validation
// cascade, same NVS persistence (prefs.putString), so a Meshpoint-side
// dashboard save behaves identically to a save made directly on the
// companion's own WiFi page. Always replies exactly once (ok+callsign,
// or ok:false+error) so the caller isn't left guessing whether a
// rejected value silently "sort of" saved.
void handleSetCallsignCommand(JsonDocument &doc) {
  String cs = doc["callsign"] | "";
  cs.trim();
  cs.toUpperCase(); // ham convention -- also what every outgoing TX prefix uses

  JsonDocument out;
  out["type"] = "set_callsign_result";

  if (cs.length() == 0) {
    out["ok"] = false;
    out["error"] = "callsign is required";
  } else if (cs.length() > CALLSIGN_MAX_LEN) {
    out["ok"] = false;
    out["error"] = "callsign too long (max " + String(CALLSIGN_MAX_LEN) + ")";
  } else if (cs.equalsIgnoreCase("N0CALL")) {
    out["ok"] = false;
    out["error"] = "N0CALL is a placeholder, not a real callsign";
  } else if (!isValidCallsign(cs)) {
    out["ok"] = false;
    out["error"] = "not a valid callsign -- must include a digit";
  } else {
    setCallsign(cs);
    prefs.putString("callsign", cs);
    out["ok"] = true;
    out["callsign"] = cs;
  }

  serializeJson(out, Serial);
  Serial.println();
}

// Sets the web dashboard's login password (checkAuth()'s X-Auth-Password
// comparison) over serial. Unlike the callsign command, the reply never
// echoes the new value back -- nothing about a password should appear
// in a JSON line, even on success, when the incoming command already
// had to be redacted from checkSerialInput()'s own log line above.
// Deliberately not trimmed/case-folded like callsign -- a password's
// exact characters (including case) are the point; only rejects empty.
void handleSetWebPasswordCommand(JsonDocument &doc) {
  String pw = doc["password"] | "";

  JsonDocument out;
  out["type"] = "set_web_password_result";

  if (pw.length() == 0) {
    out["ok"] = false;
    out["error"] = "password is required";
  } else {
    setWebPassword(pw);
    prefs.putString("web_password", pw);
    out["ok"] = true;
  }

  serializeJson(out, Serial);
  Serial.println();
}

// Resets callsign + web password back to their defaults (empty, and the
// secrets.h WEB_PASSWORD respectively) -- a Meshpoint-triggerable
// equivalent to a slice of the web dashboard's own "Clear Settings"
// button, deliberately narrower: unlike that button this does NOT touch
// displayTimeoutMs, since only credentials were asked for here.
// prefs.remove() (not prefs.clear(), which would wipe the whole
// namespace) so screen-timeout persistence is left untouched.
void handleResetCredentialsCommand() {
  prefs.remove("callsign");
  prefs.remove("web_password");
  setCallsign("");
  setWebPassword(WEB_PASSWORD);

  JsonDocument out;
  out["type"] = "reset_credentials_result";
  out["ok"] = true;
  serializeJson(out, Serial);
  Serial.println();
}

// Saves new WiFi credentials for the NEXT reboot -- setupWifiNtpOta()
// only ever runs once, in setup(), so this alone does not reconnect;
// pair with {"cmd":"reboot"} below to actually apply it. SSID is
// echoed back on success (not sensitive, unlike a password); the
// password itself never is, and this command's line is redacted from
// checkSerialInput()'s log the same way set_web_password's is.
void handleSetWifiCommand(JsonDocument &doc) {
  String ssid = doc["ssid"] | "";
  String pass = doc["password"] | ""; // empty is valid -- open networks have no password
  ssid.trim();

  JsonDocument out;
  out["type"] = "set_wifi_result";

  if (ssid.length() == 0) {
    out["ok"] = false;
    out["error"] = "ssid is required";
  } else {
    setWifiCredentials(ssid, pass);
    prefs.putString("wifi_ssid", ssid);
    prefs.putString("wifi_pass", pass);
    out["ok"] = true;
    out["ssid"] = ssid;
  }

  serializeJson(out, Serial);
  Serial.println();
}

// Lets Meshpoint trigger a reboot over serial -- e.g. right after
// saving new WiFi credentials above -- without needing the web
// dashboard's own Reboot button, which is the whole point: bad WiFi
// credentials could otherwise make the web dashboard unreachable too,
// while the USB serial connection keeps working regardless of WiFi
// state. Same delayed-restart mechanism /api/reboot already uses:
// send the reply first, let loop() call ESP.restart() a little later
// (REBOOT_DELAY_MS), so this reply actually reaches Meshpoint over
// serial before the reboot happens.
void handleRebootCommand() {
  JsonDocument out;
  out["type"] = "reboot_result";
  out["ok"] = true;
  serializeJson(out, Serial);
  Serial.println();
  rebootRequested = true;
  rebootRequestedAt = millis();
}

void handleSerialJsonLine(const String &line) {
  JsonDocument doc;
  DeserializationError err = deserializeJson(doc, line);
  if (err) {
    Serial.print("[serial] JSON parse error: "); Serial.println(err.c_str());
    Serial.println("[serial] expected e.g. {\"text\": \"hello\"} or {\"capcode\": 112, \"text\": \"hello\"}");
    return;
  }

  String cmd = doc["cmd"] | "";
  if (cmd == "status") {
    sendStatusReply();
    return;
  }
  if (cmd == "set_callsign") {
    handleSetCallsignCommand(doc);
    return;
  }
  if (cmd == "set_web_password") {
    handleSetWebPasswordCommand(doc);
    return;
  }
  if (cmd == "reset_credentials") {
    handleResetCredentialsCommand();
    return;
  }
  if (cmd == "set_wifi") {
    handleSetWifiCommand(doc);
    return;
  }
  if (cmd == "reboot") {
    handleRebootCommand();
    return;
  }

  uint32_t capcode = doc["capcode"] | SERIAL_DEFAULT_CAPCODE;
  String text = doc["text"] | "";
  text.trim();

  if (text.length() == 0) {
    Serial.println("[serial] no (non-empty) \"text\" field, ignored");
    return;
  }
  if (capcode == 0 || capcode > RADIOLIB_PAGER_ADDRESS_MAX) {
    Serial.print("[serial] capcode "); Serial.print(capcode);
    Serial.print(" out of range (1-"); Serial.print(RADIOLIB_PAGER_ADDRESS_MAX); Serial.println("), ignored");
    return;
  }

  String result = sendPocsagAlpha(capcode, text);
  // Dedicated, unambiguous reply for a serial-triggered send -- distinct
  // from the "echo as an alpha page" JSON a *successful* send already
  // emits inside sendPocsagAlpha() (deliberately shaped like a received
  // page, so Meshpoint's packet feed shows it for free). That echo alone
  // isn't enough for Meshpoint's Send tab to know success/failure though:
  // a real incoming page could coincidentally arrive with type "alpha" at
  // the same moment, and there was never any reply at all for "blocked"/
  // "failed". This type is never ambiguous with a received page.
  JsonDocument outResult;
  outResult["type"] = "send_result";
  outResult["ok"] = (result == "ok");
  if (result != "ok") outResult["reason"] = result;
  serializeJson(outResult, Serial);
  Serial.println();
}

int txCount = 0;
bool lastTxOk = false;

// Pauses RX, sends, resumes RX -- the actual half-duplex switch. Every
// other caller in this file (handleSerialJsonLine() and the web
// dashboard's /api/send, via checkWebSendPending()) gets the mode switch
// for free by going through this function rather than calling
// pager.transmit() directly. Also the single enforcement point for the
// callsign requirement (see the file header's licensing warning) --
// /api/send does its own pre-check too for a faster web UI error, but
// this is the one that actually can't be bypassed, since every send path
// in the file funnels through here.
// Returns "ok", "blocked", or "failed" -- the serial JSON handler uses this
// to emit a definitive {"type":"send_result",...} reply (see below); the
// web dashboard's checkWebSendPending() ignores it, since /api/send has its
// own separate JSON response already (see the request-flow comment there).
String sendPocsagAlpha(uint32_t capcode, const String &text) {
  String cs = getCallsign();
  if (!isValidCallsign(cs)) {
    Serial.println("========================================");
    Serial.println("[serial] SEND BLOCKED -- no valid callsign configured (set one in the web dashboard's Callsign card first)");
    Serial.println("========================================");
    pushWebLog(capcode, RADIOLIB_PAGER_FUNC_BITS_ALPHA, "alpha", text, "blocked");
    return "blocked";
  }

  // Station self-identification -- see the file header's licensing
  // warning. Every real over-the-air message this sketch ever sends
  // carries this prefix; there is no way to send without it once a
  // callsign is configured.
  String prefixedText = cs + ": " + text;

  Serial.println("========================================");
  Serial.print("[serial] SENDING  capcode="); Serial.print(capcode);
  Serial.print("  text=\""); Serial.print(prefixedText); Serial.println("\"");

  configureForTx();
  String padded = padAlphaForCleanDecode(prefixedText, capcode);
  int state = pager.transmit(padded.c_str(), capcode, RADIOLIB_PAGER_ASCII);
  configureForRx(); // back to listening immediately, regardless of TX result
  rxContinuousStarted = false; // loop() re-arms radio.startReceive() on its next pass

  lastTxOk = (state == RADIOLIB_ERR_NONE);
  txCount++;

  if (lastTxOk) {
    Serial.println("[serial] SENT OK");
    // Echo the send in the exact same shape as a received page
    // (function 3 / "alpha" is RADIOLIB_PAGER_FUNC_BITS_ALPHA -- this
    // sketch only ever sends alpha pages, never numeric/tone) so a
    // consumer reading the JSON stream doesn't need a separate code
    // path for "what did I just transmit" vs. "what did I just hear."
    // Reports prefixedText (callsign + original text), not the further
    // auto-padded wire version -- trimTrailingPadding() on the RX side
    // would strip that padding right back off anyway, so prefixedText is
    // what a receiver (including this device's own RX) actually sees.
    JsonDocument outTx;
    outTx["capcode"] = capcode;
    outTx["function"] = RADIOLIB_PAGER_FUNC_BITS_ALPHA;
    outTx["type"] = "alpha";
    outTx["text"] = prefixedText;
    serializeJson(outTx, Serial);
    Serial.println();
    pushWebLog(capcode, RADIOLIB_PAGER_FUNC_BITS_ALPHA, "alpha", prefixedText, "tx");
  } else {
    Serial.print("[serial] SEND FAILED, code="); Serial.println(state);
  }
  Serial.println("========================================");

  showSentScreen(capcode, padded, state);
  return lastTxOk ? "ok" : "failed";
}


// ---------- Web dashboard ----------
//
// A small password-gated single-page UI served straight from flash (no
// filesystem, no external assets/fonts/CDN -- this device may only have
// LAN access, not real internet), styled to match meshpoint's own dark
// dashboard theme (frontend/css/dashboard.css's :root color variables,
// copied here since the ESP32 obviously can't @import that file). Three
// cards: a live in/outgoing log, a capcode+message send form, and a
// screen-timeout setting -- the same three things the serial protocol
// already does (receive JSON, send JSON) plus the runtime displayTimeoutMs
// knob above, just reachable from a browser instead of a serial monitor.
//
// AsyncWebServer's request/body callbacks run on AsyncTCP's own FreeRTOS
// task, NOT on the same thread as loop() -- this matters a lot here
// because loop() is the only thread anything else in this file assumes
// touches the radio (`radio`/`pager`) or mutates Strings. Two things are
// done about that:
//   1. A send from the web UI never calls sendPocsagAlpha() directly from
//      the web task -- it only stages a request (queueWebSend()) that
//      loop() picks up and runs itself (checkWebSendPending()), so the
//      radio is still only ever touched from one thread, exactly as
//      before webserver support existed.
//   2. The log ring buffer (read by /api/log on the web task, written by
//      decodeBatchAndEmit()/sendPocsagAlpha() on the loop() thread) holds
//      Strings, and concurrent String mutation across FreeRTOS tasks on
//      ESP32 is a real heap-corruption risk, not just stale data -- so
//      all reads and writes of it go through stateMutex. A real
//      SemaphoreHandle_t mutex is used rather than a portENTER_CRITICAL()
//      spinlock, since the latter disables interrupts on both cores for
//      its duration and String assignment can allocate -- not something
//      you want to do inside a spinlock.

AsyncWebServer server(80);
SemaphoreHandle_t stateMutex;

struct LogEntry {
  uint32_t capcode;
  uint8_t function;
  String type;
  String text;
  String dir; // "rx" | "tx" | "blocked" (a TX refused for lack of a configured callsign)
  unsigned long ts; // millis() when logged
};
LogEntry webLog[WEB_LOG_SIZE];
int webLogHead = 0;  // next slot to write
int webLogCount = 0; // how many of the ring's slots are populated so far

void pushWebLog(uint32_t capcode, uint8_t function, const String &type, const String &text, const String &dir) {
  xSemaphoreTake(stateMutex, portMAX_DELAY);
  LogEntry &e = webLog[webLogHead];
  e.capcode = capcode;
  e.function = function;
  e.type = type;
  e.text = text;
  e.dir = dir;
  e.ts = millis();
  webLogHead = (webLogHead + 1) % WEB_LOG_SIZE;
  if (webLogCount < WEB_LOG_SIZE) webLogCount++;
  xSemaphoreGive(stateMutex);
}

// Web-triggered TX handoff -- see the section comment above for why this
// exists instead of just calling sendPocsagAlpha() from the web handler.
volatile bool webSendPending = false;
uint32_t webSendCapcode = 0;
String webSendText;

bool queueWebSend(uint32_t capcode, const String &text) {
  bool queued = false;
  xSemaphoreTake(stateMutex, portMAX_DELAY);
  if (!webSendPending) {
    webSendCapcode = capcode;
    webSendText = text;
    webSendPending = true;
    queued = true;
  }
  xSemaphoreGive(stateMutex);
  return queued;
}

// Reboot handoff (from /api/reboot) -- a single scalar+timestamp, not a
// String, so unlike webSendText above this doesn't need the mutex (no
// heap-corruption risk from concurrent access, just a plain word read/
// write). loop() waits REBOOT_DELAY_MS after the flag is set before
// actually calling ESP.restart() -- restarting synchronously inside the
// web handler risks AsyncTCP never getting a chance to flush the HTTP
// response, leaving the browser hanging with no confirmation.
#define REBOOT_DELAY_MS 500UL
bool rebootRequested = false;
unsigned long rebootRequestedAt = 0;

// Operator callsign -- required before sendPocsagAlpha() will transmit
// anything (see its own comment), persisted in NVS via Preferences so it
// survives a reboot. Read/written from both the loop() thread and the web
// task (web dashboard's Callsign card, plus /api/send's pre-check), so it
// goes through the same mutex as webLog/webSend above rather than being
// touched directly.
Preferences prefs;
String callsign = "";

String getCallsign() {
  String c;
  xSemaphoreTake(stateMutex, portMAX_DELAY);
  c = callsign;
  xSemaphoreGive(stateMutex);
  return c;
}

void setCallsign(const String &newCallsign) {
  xSemaphoreTake(stateMutex, portMAX_DELAY);
  callsign = newCallsign;
  xSemaphoreGive(stateMutex);
}

// Web dashboard login password -- starts as the secrets.h compile-time
// default (WEB_PASSWORD), overridable at runtime via NVS the same way
// callsign is, so a serial-set password survives a reboot and doesn't
// require reflashing to change from the shared default. checkAuth()
// compares against this, not the raw WEB_PASSWORD macro, once set.
String webPassword = WEB_PASSWORD;

String getWebPassword() {
  String p;
  xSemaphoreTake(stateMutex, portMAX_DELAY);
  p = webPassword;
  xSemaphoreGive(stateMutex);
  return p;
}

void setWebPassword(const String &newPassword) {
  xSemaphoreTake(stateMutex, portMAX_DELAY);
  webPassword = newPassword;
  xSemaphoreGive(stateMutex);
}

// WiFi credentials -- start as the secrets.h compile-time defaults,
// overridable at runtime via NVS the same way callsign/web password
// are. Unlike those two, a change here does NOT take effect
// immediately: setupWifiNtpOta() only ever runs once, in setup(), so
// a new SSID/password needs a reboot to actually connect with (see
// handleRebootCommand() below, which lets Meshpoint trigger that
// without needing the web dashboard at all -- the whole point, since
// bad WiFi credentials could otherwise make the web dashboard
// unreachable too).
String wifiSsid = WIFI_SSID;
String wifiPass = WIFI_PASSWORD;

String getWifiSsid() {
  String s;
  xSemaphoreTake(stateMutex, portMAX_DELAY);
  s = wifiSsid;
  xSemaphoreGive(stateMutex);
  return s;
}

String getWifiPassword() {
  String p;
  xSemaphoreTake(stateMutex, portMAX_DELAY);
  p = wifiPass;
  xSemaphoreGive(stateMutex);
  return p;
}

void setWifiCredentials(const String &ssid, const String &pass) {
  xSemaphoreTake(stateMutex, portMAX_DELAY);
  wifiSsid = ssid;
  wifiPass = pass;
  xSemaphoreGive(stateMutex);
}

// Rejects two things that would otherwise pass the "non-empty" check but
// aren't a real callsign: "N0CALL" (the well-known ham-radio placeholder/
// example callsign -- if someone saves it, TX should stay blocked exactly
// as if nothing were configured, not silently start transmitting under a
// fake identity) and anything with no digit in it at all -- every real
// amateur callsign format worldwide includes at least one digit (that part
// IS universal, unlike full format validation, which varies too much by
// country to check reliably -- see CALLSIGN_MAX_LEN's own comment). Used
// both to gate /api/callsign's save (reject bad values outright, rather
// than accepting a "Saved" that then silently blocks every future send)
// and as an extra defense-in-depth check in sendPocsagAlpha()/`/api/send`
// itself, in case `callsign` is ever populated by anything other than a
// validated save (e.g. NVS state written by a future firmware version
// without this check).
bool isValidCallsign(const String &cs) {
  if (cs.length() == 0) return false;
  if (cs.equalsIgnoreCase("N0CALL")) return false;
  bool hasDigit = false;
  for (size_t i = 0; i < cs.length(); i++) {
    if (isDigit(cs[i])) { hasDigit = true; break; }
  }
  return hasDigit;
}

// Called every loop() pass. Cheap when nothing's pending (one bool check).
void checkWebSendPending() {
  if (!webSendPending) return;
  uint32_t capcode;
  String text;
  xSemaphoreTake(stateMutex, portMAX_DELAY);
  capcode = webSendCapcode;
  text = webSendText;
  webSendPending = false;
  xSemaphoreGive(stateMutex);
  sendPocsagAlpha(capcode, text);
}

// Every API route (not the static page itself, which has nothing sensitive
// in its shell) requires this header. Plain string comparison is plenty --
// this is a LAN-local hobby device's login, not a target worth building
// constant-time comparison for.
bool checkAuth(AsyncWebServerRequest *request) {
  if (!request->hasHeader("X-Auth-Password") ||
      request->getHeader("X-Auth-Password")->value() != getWebPassword()) {
    request->send(401, "application/json", "{\"ok\":false,\"error\":\"unauthorized\"}");
    return false;
  }
  return true;
}

const char INDEX_HTML[] = R"HTMLPAGE(
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>POCSAG Companion</title>
<style>
  :root {
    --bg-primary: #0a0e17;
    --bg-card: #162033;
    --border: #233049;
    --text-primary: #e2e8f0;
    --text-secondary: #94a3b8;
    --text-muted: #64748b;
    --accent-green: #00e5a0;
    --accent-cyan: #06b6d4;
    --accent-amber: #f59e0b;
    --accent-red: #ef4444;
    --radius: 8px;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    background: var(--bg-primary);
    color: var(--text-primary);
    font-family: 'JetBrains Mono', 'Courier New', monospace;
    padding: 16px;
  }
  header { display:flex; align-items:center; justify-content:space-between; margin-bottom:16px; flex-wrap:wrap; gap:8px; }
  h1 { font-size: 18px; margin:0; color: var(--accent-cyan); letter-spacing: 0.5px; }
  .status { font-size:12px; color: var(--text-secondary); display:flex; gap:14px; align-items:center; }
  .dot { width:8px; height:8px; border-radius:50%; display:inline-block; margin-right:5px; }
  .dot.on { background: var(--accent-green); box-shadow:0 0 6px var(--accent-green); }
  .dot.off { background: var(--accent-red); }
  .grid { display:grid; grid-template-columns: repeat(2, 1fr); gap:16px; }
  @media (max-width: 700px) { .grid { grid-template-columns: 1fr; } }
  .card { background: var(--bg-card); border:1px solid var(--border); border-radius: var(--radius); padding:14px; }
  .card h2 { font-size:13px; text-transform:uppercase; letter-spacing:1px; color: var(--text-secondary); margin:0 0 10px 0; }
  #log { height:320px; overflow-y:auto; font-size:12px; display:flex; flex-direction:column; gap:6px; }
  .row { border-left:2px solid var(--border); padding:4px 8px; border-radius:4px; background: rgba(255,255,255,0.02); }
  .row.rx { border-left-color: var(--accent-cyan); }
  .row.tx { border-left-color: var(--accent-green); }
  .row.blocked { border-left-color: var(--accent-red); }
  .row .meta { color: var(--text-muted); font-size:10px; }
  .row .cap { color: var(--accent-amber); }
  .row .txt { color: var(--text-primary); word-break: break-word; }
  label { font-size:11px; color: var(--text-secondary); display:block; margin-bottom:4px; margin-top:10px; }
  input[type=text], input[type=number], input[type=password] {
    width:100%; background: var(--bg-primary); border:1px solid var(--border); color: var(--text-primary);
    padding:8px; border-radius:4px; font-family:inherit; font-size:13px;
  }
  button {
    margin-top:12px; width:100%; background: var(--accent-cyan); color:#04121a; border:none; border-radius:4px;
    padding:10px; font-family:inherit; font-weight:600; font-size:13px; cursor:pointer; letter-spacing:0.5px;
  }
  button:active { opacity:0.8; }
  button:disabled { opacity:0.5; cursor:default; }
  .hint { font-size:11px; color: var(--text-muted); margin-top:8px; }
  .kv { display:flex; justify-content:space-between; gap:8px; font-size:12px; padding:3px 0; border-bottom:1px solid rgba(255,255,255,0.04); }
  .kv span:first-child { color: var(--text-secondary); }
  .kv span:last-child { color: var(--text-primary); text-align:right; word-break:break-all; }
  #whoami { font-size:11px; color: var(--text-muted); margin: -4px 0 10px 0; }
  .result { font-size:12px; margin-top:8px; min-height:14px; }
  .result.ok { color: var(--accent-green); }
  .result.err { color: var(--accent-red); }
  .modal-overlay {
    position:fixed; inset:0; background: rgba(10,14,23,0.92); display:flex; align-items:center; justify-content:center; z-index:100;
  }
  .modal-overlay .card { width:280px; }
  .modal-overlay h2 { color: var(--accent-cyan); font-size:14px; }
  .modal-overlay p { font-size:12px; color: var(--text-secondary); line-height:1.5; }
  .hidden { display:none !important; }
  button.danger { background: var(--accent-red); color: #fff; }
  button.secondary { background: var(--bg-primary); color: var(--text-secondary); border:1px solid var(--border); }
</style>
</head>
<body>

<div id="authOverlay" class="modal-overlay">
  <div class="card">
    <h2>POCSAG COMPANION</h2>
    <div id="whoami">--</div>
    <label for="pw">Password</label>
    <input type="password" id="pw" autocomplete="off" spellcheck="false">
    <button onclick="tryLogin()">Unlock</button>
    <div class="result err" id="authErr"></div>
  </div>
</div>

<div id="clearConfirmModal" class="modal-overlay hidden">
  <div class="card">
    <h2 style="color:var(--accent-red)">CLEAR ALL SETTINGS?</h2>
    <p>Wipes callsign, web password, and screen timeout back to defaults. This cannot be undone.</p>
    <button class="danger" onclick="confirmClearSettings()">Clear Settings</button>
    <button class="secondary" onclick="document.getElementById('clearConfirmModal').classList.add('hidden')">Cancel</button>
    <div class="result" id="clearConfirmResult"></div>
  </div>
</div>

<div id="rebootModal" class="modal-overlay hidden">
  <div class="card">
    <h2 style="color:var(--accent-red)">SETTINGS CLEARED</h2>
    <p>Callsign, web password, and screen timeout were reset to defaults. Reboot now to test a clean boot, or reboot later yourself.</p>
    <button onclick="rebootNow()">Reboot Now</button>
    <button class="secondary" onclick="document.getElementById('rebootModal').classList.add('hidden')">Later</button>
    <div class="result" id="rebootResult"></div>
  </div>
</div>

<div id="app" class="hidden">
  <header>
    <h1>POCSAG COMPANION</h1>
    <div class="status">
      <span><span class="dot" id="wifiDot"></span><span id="hostname">--</span></span>
      <span>RX <span id="rxCount">0</span></span>
      <span>TX <span id="txCount">0</span></span>
    </div>
  </header>

  <div class="grid">
    <div class="card">
      <h2>Hardware</h2>
      <div class="kv"><span>Board</span><span id="hwBoard">--</span></div>
      <div class="kv"><span>Chip</span><span id="hwChip">--</span></div>
      <div class="kv"><span>Cores / Freq</span><span id="hwCores">--</span></div>
      <div class="kv"><span>Flash</span><span id="hwFlash">--</span></div>
      <div class="kv"><span>Free Heap</span><span id="hwHeap">--</span></div>
      <div class="kv"><span>Sketch Used / Free</span><span id="hwSketch">--</span></div>
      <div class="kv"><span>SDK</span><span id="hwSdk">--</span></div>
    </div>

    <div class="card">
      <h2>Connection</h2>
      <div class="kv"><span>SSID</span><span id="connSsid">--</span></div>
      <div class="kv"><span>IP</span><span id="connIp">--</span></div>
      <div class="kv"><span>Gateway</span><span id="connGw">--</span></div>
      <div class="kv"><span>Subnet</span><span id="connSubnet">--</span></div>
      <div class="kv"><span>DNS</span><span id="connDns">--</span></div>
      <div class="kv"><span>MAC</span><span id="connMac">--</span></div>
      <div class="kv"><span>RSSI</span><span id="connRssi">--</span></div>
      <div class="kv"><span>Hostname</span><span id="connHost">--</span></div>
    </div>

    <div class="card">
      <h2>In / Outgoing Log</h2>
      <div id="log"></div>
    </div>

    <div class="card">
      <h2>Send Page</h2>
      <label for="capcode">Capcode</label>
      <input type="number" id="capcode" placeholder="123456">
      <label for="text">Message</label>
      <input type="text" id="text" placeholder="Hello from meshpoint" maxlength="80">
      <button id="sendBtn" onclick="sendPage()">Send</button>
      <div class="result" id="sendResult"></div>
      <div class="hint" id="noCallsignHint">Set your callsign (Operator card) before you can send -- required by TX, see the file's licensing note.</div>
    </div>

    <div class="card">
      <h2>Operator Callsign</h2>
      <label for="callsign">Prefixed to every outgoing message, e.g. <span id="callsignExample">N0CALL</span>: your text</label>
      <input type="text" id="callsign" placeholder="N0CALL" maxlength="8" style="text-transform:uppercase">
      <button onclick="saveCallsign()">Save</button>
      <div class="result" id="callsignResult"></div>
      <button class="danger" onclick="clearSettings()">Clear Settings</button>
      <div class="hint">Wipes callsign, web password, + screen timeout back to defaults -- for testing a clean install.</div>
    </div>

    <div class="card">
      <h2>Screen Timeout</h2>
      <label for="timeout">Seconds idle before auto-off (0 = never)</label>
      <input type="number" id="timeout" min="0" step="1">
      <button onclick="applyTimeout()">Apply</button>
      <div class="result" id="timeoutResult"></div>
      <div class="hint">GPIO)HTMLPAGE" TOSTRING(BUTTON_GPIO) R"HTMLPAGE( (BOOT button) also toggles the display manually at any time.</div>
    </div>
  </div>
</div>

<script>
let pw = sessionStorage.getItem('pocsagPw') || '';
let timeoutTouched = false;
let callsignTouched = false;

// Unauthenticated -- lets multiple companions on the same network be
// told apart at a glance, before a password is even entered. Neither
// field is sensitive: callsign is public ham-radio info by definition,
// hostname is already broadcast in the clear via mDNS anyway.
fetch('/api/whoami').then(r => r.json()).then(d => {
  document.getElementById('whoami').textContent =
    (d.callsign || 'No callsign set') + ' · ' + d.hostname + '.local';
}).catch(() => {});

function authHeaders() {
  return { 'X-Auth-Password': pw };
}

async function checkAuth() {
  try {
    const r = await fetch('/api/status', { headers: authHeaders() });
    return r.ok;
  } catch (e) { return false; }
}

async function tryLogin() {
  pw = document.getElementById('pw').value;
  const ok = await checkAuth();
  if (ok) {
    sessionStorage.setItem('pocsagPw', pw);
    enterApp();
  } else {
    document.getElementById('authErr').textContent = 'Wrong password';
  }
}

function enterApp() {
  document.getElementById('authOverlay').classList.add('hidden');
  document.getElementById('app').classList.remove('hidden');
  pollStatus();
  pollLog();
  setInterval(pollStatus, 5000);
  setInterval(pollLog, 3000);
}

async function apiGet(path) {
  const r = await fetch(path, { headers: authHeaders() });
  if (r.status === 401) { sessionStorage.removeItem('pocsagPw'); location.reload(); throw new Error('unauthorized'); }
  return r.json();
}

async function apiPost(path, body) {
  const r = await fetch(path, {
    method: 'POST',
    headers: Object.assign({ 'Content-Type': 'application/json' }, authHeaders()),
    body: JSON.stringify(body)
  });
  if (r.status === 401) { sessionStorage.removeItem('pocsagPw'); location.reload(); throw new Error('unauthorized'); }
  return r.json();
}

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function fmtRow(e) {
  const dirLabel = { tx: 'TX', rx: 'RX', blocked: 'BLOCKED' }[e.dir] || e.dir.toUpperCase();
  const secsAgo = Math.round(e.ms_ago / 1000);
  return '<div class="row ' + e.dir + '">' +
    '<div class="meta">' + dirLabel + ' &middot; ' + secsAgo + 's ago &middot; ' + e.type + '</div>' +
    '<div><span class="cap">#' + e.capcode + '</span> <span class="txt">' + escapeHtml(e.text || '(no text)') + '</span></div>' +
    '</div>';
}

async function pollLog() {
  try {
    const entries = await apiGet('/api/log'); // oldest-first from the server
    const log = document.getElementById('log');
    const atTop = log.scrollTop <= 10;
    // Newest-first display -- reverse client-side rather than changing the
    // server's ring-buffer order, which is simplest kept chronological.
    log.innerHTML = entries.slice().reverse().map(fmtRow).join('');
    // Only snap back to the top (latest entry) if the user was already
    // there -- if they've scrolled down to read older messages, leave
    // them where they are instead of yanking the view on every poll.
    if (atTop) log.scrollTop = 0;
  } catch (e) {}
}

async function pollStatus() {
  try {
    const s = await apiGet('/api/status');
    document.getElementById('hostname').textContent = s.hostname;
    document.getElementById('wifiDot').className = 'dot ' + (s.wifi ? 'on' : 'off');
    document.getElementById('rxCount').textContent = s.rxBatchCount;
    document.getElementById('txCount').textContent = s.txCount;
    if (!timeoutTouched) document.getElementById('timeout').value = Math.round(s.displayTimeoutMs / 1000);
    if (!callsignTouched) document.getElementById('callsign').value = s.callsign || '';
    document.getElementById('callsignExample').textContent = s.callsign || 'N0CALL';
    // Server-side (sendPocsagAlpha()) is the real guard -- this is just UX,
    // so the button doesn't invite a doomed send.
    document.getElementById('sendBtn').disabled = !s.callsign;
    document.getElementById('noCallsignHint').style.display = s.callsign ? 'none' : 'block';

    document.getElementById('hwBoard').textContent = s.board;
    document.getElementById('hwChip').textContent = s.chipModel + ' rev' + s.chipRevision;
    document.getElementById('hwCores').textContent = s.chipCores + ' / ' + s.cpuFreqMHz + ' MHz';
    document.getElementById('hwFlash').textContent = s.flashSizeMB + ' MB';
    document.getElementById('hwHeap').textContent = Math.round(s.freeHeap / 1024) + ' KB free';
    document.getElementById('hwSketch').textContent = s.sketchSizeKB + ' KB / ' + s.freeSketchSpaceKB + ' KB';
    document.getElementById('hwSdk').textContent = s.sdkVersion;

    document.getElementById('connSsid').textContent = s.wifiSsid || '--';
    document.getElementById('connIp').textContent = s.wifiIp || '--';
    document.getElementById('connGw').textContent = s.wifiGateway || '--';
    document.getElementById('connSubnet').textContent = s.wifiSubnet || '--';
    document.getElementById('connDns').textContent = s.wifiDns || '--';
    document.getElementById('connMac').textContent = s.wifiMac || '--';
    document.getElementById('connRssi').textContent = s.wifi ? (s.wifiRssi + ' dBm') : '--';
    document.getElementById('connHost').textContent = s.hostname + '.local';
  } catch (e) {}
}

async function sendPage() {
  const capInput = document.getElementById('capcode');
  const textInput = document.getElementById('text');
  const btn = document.getElementById('sendBtn');
  const result = document.getElementById('sendResult');
  const text = textInput.value.trim();
  if (!text) { result.className = 'result err'; result.textContent = 'Enter a message'; return; }
  const body = { text };
  if (capInput.value) body.capcode = parseInt(capInput.value, 10);
  btn.disabled = true;
  result.className = 'result'; result.textContent = 'Sending...';
  try {
    const r = await apiPost('/api/send', body);
    if (r.ok) {
      result.className = 'result ok'; result.textContent = 'Queued';
      textInput.value = '';
      setTimeout(pollLog, 1500);
    } else {
      result.className = 'result err'; result.textContent = r.error || 'Failed';
    }
  } catch (e) {
    result.className = 'result err'; result.textContent = 'Request failed';
  }
  btn.disabled = false;
}

async function saveCallsign() {
  const input = document.getElementById('callsign');
  const cs = input.value.trim().toUpperCase();
  const result = document.getElementById('callsignResult');
  if (!cs) { result.className = 'result err'; result.textContent = 'Callsign is required'; return; }
  if (cs === 'N0CALL') { result.className = 'result err'; result.textContent = 'N0CALL is a placeholder, not a real callsign'; return; }
  if (!/\d/.test(cs)) { result.className = 'result err'; result.textContent = 'Must include a digit -- every real callsign format does'; return; }
  // Server (/api/callsign) re-validates the same rules -- this is just
  // instant feedback without a round trip, not the real enforcement.
  try {
    const r = await apiPost('/api/callsign', { callsign: cs });
    result.className = r.ok ? 'result ok' : 'result err';
    result.textContent = r.ok ? 'Saved' : (r.error || 'Failed');
    if (r.ok) { callsignTouched = false; pollStatus(); }
  } catch (e) {
    result.className = 'result err'; result.textContent = 'Request failed';
  }
}

function clearSettings() {
  document.getElementById('clearConfirmResult').textContent = '';
  document.getElementById('clearConfirmModal').classList.remove('hidden');
}

async function confirmClearSettings() {
  const result = document.getElementById('clearConfirmResult');
  try {
    const r = await apiPost('/api/clear-settings', {});
    if (r.ok) {
      callsignTouched = false; timeoutTouched = false;
      pollStatus();
      document.getElementById('clearConfirmModal').classList.add('hidden');
      document.getElementById('rebootModal').classList.remove('hidden');
    } else {
      result.className = 'result err'; result.textContent = r.error || 'Failed';
    }
  } catch (e) {
    result.className = 'result err'; result.textContent = 'Request failed';
  }
}

async function rebootNow() {
  const result = document.getElementById('rebootResult');
  result.className = 'result'; result.textContent = 'Rebooting...';
  try {
    await apiPost('/api/reboot', {});
  } catch (e) {
    // Expected -- the device drops the connection as it restarts, this
    // isn't a real failure.
  }
  result.className = 'result ok';
  result.textContent = 'Reconnecting...';
  setTimeout(() => location.reload(), 6000); // rough guess at boot+WiFi-reconnect time
}

async function applyTimeout() {
  const seconds = parseInt(document.getElementById('timeout').value, 10) || 0;
  const result = document.getElementById('timeoutResult');
  try {
    const r = await apiPost('/api/timeout', { ms: seconds * 1000 });
    result.className = r.ok ? 'result ok' : 'result err';
    result.textContent = r.ok ? 'Saved' : (r.error || 'Failed');
    timeoutTouched = false;
  } catch (e) {
    result.className = 'result err'; result.textContent = 'Request failed';
  }
}

document.getElementById('timeout').addEventListener('input', () => timeoutTouched = true);
document.getElementById('callsign').addEventListener('input', () => callsignTouched = true);
document.getElementById('pw').addEventListener('keydown', e => { if (e.key === 'Enter') tryLogin(); });

if (pw) checkAuth().then(ok => { if (ok) enterApp(); });
</script>
</body>
</html>
)HTMLPAGE";

void setupWebServer() {
  server.on("/", HTTP_GET, [](AsyncWebServerRequest *request) {
    request->send(200, "text/html", INDEX_HTML);
  });

  server.on("/api/status", HTTP_GET, [](AsyncWebServerRequest *request) {
    if (!checkAuth(request)) return;
    JsonDocument doc;
    doc["ok"] = true;
    doc["hostname"] = MDNS_HOSTNAME;
    doc["wifi"] = wifiConnected;
    doc["rxBatchCount"] = rxBatchCount;
    doc["txCount"] = txCount;
    doc["displayTimeoutMs"] = displayTimeoutMs;
    doc["callsign"] = getCallsign();

    // Hardware card -- static for the board's lifetime except freeHeap,
    // cheap to read every poll (all built into the ESP32 core, no new
    // dependency).
    doc["board"] = BOARD_NAME_STR;
    doc["chipModel"] = ESP.getChipModel();
    doc["chipRevision"] = ESP.getChipRevision();
    doc["chipCores"] = ESP.getChipCores();
    doc["cpuFreqMHz"] = ESP.getCpuFreqMHz();
    doc["flashSizeMB"] = ESP.getFlashChipSize() / (1024.0 * 1024.0);
    doc["freeHeap"] = ESP.getFreeHeap();
    doc["sketchSizeKB"] = ESP.getSketchSize() / 1024;
    doc["freeSketchSpaceKB"] = ESP.getFreeSketchSpace() / 1024;
    doc["sdkVersion"] = ESP.getSdkVersion();

    // Connection card -- lets a WiFi credential change (set over serial
    // from Meshpoint, see handleSetWifiCommand) actually be VERIFIED
    // here rather than just assumed. Blank when not connected, same
    // convention sendStatusReply()'s own wifi_ip already uses.
    doc["wifiSsid"] = wifiConnected ? WiFi.SSID() : "";
    doc["wifiIp"] = wifiConnected ? WiFi.localIP().toString() : "";
    doc["wifiGateway"] = wifiConnected ? WiFi.gatewayIP().toString() : "";
    doc["wifiSubnet"] = wifiConnected ? WiFi.subnetMask().toString() : "";
    doc["wifiDns"] = wifiConnected ? WiFi.dnsIP().toString() : "";
    doc["wifiMac"] = WiFi.macAddress();
    doc["wifiRssi"] = wifiConnected ? WiFi.RSSI() : 0;

    String json;
    serializeJson(doc, json);
    request->send(200, "application/json", json);
  });

  // Deliberately NOT gated by checkAuth() -- shown on the login screen
  // itself, before a password is entered. Neither field is sensitive:
  // callsign is public ham-radio info by definition, hostname is
  // already broadcast in the clear via mDNS anyway.
  server.on("/api/whoami", HTTP_GET, [](AsyncWebServerRequest *request) {
    JsonDocument doc;
    doc["callsign"] = getCallsign();
    doc["hostname"] = MDNS_HOSTNAME;
    String json;
    serializeJson(doc, json);
    request->send(200, "application/json", json);
  });

  server.on("/api/log", HTTP_GET, [](AsyncWebServerRequest *request) {
    if (!checkAuth(request)) return;
    JsonDocument doc;
    JsonArray arr = doc.to<JsonArray>();
    unsigned long now = millis();
    xSemaphoreTake(stateMutex, portMAX_DELAY);
    int start = (webLogHead - webLogCount + WEB_LOG_SIZE) % WEB_LOG_SIZE;
    for (int i = 0; i < webLogCount; i++) {
      int idx = (start + i) % WEB_LOG_SIZE;
      JsonObject o = arr.add<JsonObject>();
      o["capcode"] = webLog[idx].capcode;
      o["function"] = webLog[idx].function;
      o["type"] = webLog[idx].type;
      o["text"] = webLog[idx].text;
      o["dir"] = webLog[idx].dir;
      o["ms_ago"] = now - webLog[idx].ts;
    }
    xSemaphoreGive(stateMutex);
    String json;
    serializeJson(doc, json);
    request->send(200, "application/json", json);
  });

  server.on("/api/send", HTTP_POST, [](AsyncWebServerRequest *request) {
    // Body is handled by the callback below; nothing to do on the
    // "request known, body not yet received" pass.
  }, nullptr, [](AsyncWebServerRequest *request, uint8_t *data, size_t len, size_t index, size_t total) {
    if (!checkAuth(request)) return;
    JsonDocument doc;
    if (deserializeJson(doc, data, len)) {
      request->send(400, "application/json", "{\"ok\":false,\"error\":\"bad json\"}");
      return;
    }
    uint32_t capcode = doc["capcode"] | SERIAL_DEFAULT_CAPCODE;
    String text = doc["text"] | "";
    text.trim();
    if (text.length() == 0) {
      request->send(400, "application/json", "{\"ok\":false,\"error\":\"text is required\"}");
      return;
    }
    if (capcode == 0 || capcode > RADIOLIB_PAGER_ADDRESS_MAX) {
      request->send(400, "application/json", "{\"ok\":false,\"error\":\"capcode out of range\"}");
      return;
    }
    if (!isValidCallsign(getCallsign())) {
      // Fast, synchronous feedback for the web UI -- sendPocsagAlpha()
      // (via checkWebSendPending()) would refuse this too and log it the
      // same way, but that only happens after a round trip through
      // loop(); this gives an immediate error instead of a 202 that
      // silently goes nowhere. In practice this should be unreachable
      // once /api/callsign's own validation is in place (a bad value can
      // no longer be saved), but it's cheap defense-in-depth to keep --
      // see isValidCallsign()'s own comment for why.
      Serial.println("[web] SEND BLOCKED -- no valid callsign configured");
      pushWebLog(capcode, RADIOLIB_PAGER_FUNC_BITS_ALPHA, "alpha", text, "blocked");
      request->send(400, "application/json", "{\"ok\":false,\"error\":\"no valid callsign configured -- set one in the Callsign card first\"}");
      return;
    }
    if (!queueWebSend(capcode, text)) {
      request->send(429, "application/json", "{\"ok\":false,\"error\":\"a send is already in progress\"}");
      return;
    }
    // Queued, not yet transmitted -- loop() runs the actual send shortly
    // after this returns (see checkWebSendPending()); the log card will
    // show it once it lands.
    request->send(202, "application/json", "{\"ok\":true,\"queued\":true}");
  });

  server.on("/api/timeout", HTTP_POST, [](AsyncWebServerRequest *request) {
  }, nullptr, [](AsyncWebServerRequest *request, uint8_t *data, size_t len, size_t index, size_t total) {
    if (!checkAuth(request)) return;
    JsonDocument doc;
    if (deserializeJson(doc, data, len)) {
      request->send(400, "application/json", "{\"ok\":false,\"error\":\"bad json\"}");
      return;
    }
    long ms = doc["ms"] | -1;
    if (ms < 0 || ms > 24UL * 60 * 60 * 1000) { // 0 = disabled, up to 24h
      request->send(400, "application/json", "{\"ok\":false,\"error\":\"ms out of range (0-86400000)\"}");
      return;
    }
    displayTimeoutMs = (uint32_t)ms;
    prefs.putUInt("dispTimeoutMs", displayTimeoutMs);
    if (displayTimeoutMs > 0) lastDisplayActivity = millis(); // don't blank immediately on a fresh, longer setting
    request->send(200, "application/json", "{\"ok\":true}");
  });

  server.on("/api/callsign", HTTP_POST, [](AsyncWebServerRequest *request) {
  }, nullptr, [](AsyncWebServerRequest *request, uint8_t *data, size_t len, size_t index, size_t total) {
    if (!checkAuth(request)) return;
    JsonDocument doc;
    if (deserializeJson(doc, data, len)) {
      request->send(400, "application/json", "{\"ok\":false,\"error\":\"bad json\"}");
      return;
    }
    String cs = doc["callsign"] | "";
    cs.trim();
    cs.toUpperCase(); // ham convention -- also what every outgoing TX prefix uses
    if (cs.length() == 0) {
      request->send(400, "application/json", "{\"ok\":false,\"error\":\"callsign is required\"}");
      return;
    }
    if (cs.length() > CALLSIGN_MAX_LEN) {
      request->send(400, "application/json", "{\"ok\":false,\"error\":\"callsign too long (max " + String(CALLSIGN_MAX_LEN) + ")\"}");
      return;
    }
    if (cs.equalsIgnoreCase("N0CALL")) {
      request->send(400, "application/json", "{\"ok\":false,\"error\":\"N0CALL is a placeholder, not a real callsign\"}");
      return;
    }
    if (!isValidCallsign(cs)) {
      request->send(400, "application/json", "{\"ok\":false,\"error\":\"not a valid callsign -- must include a digit (every real amateur callsign format does)\"}");
      return;
    }
    setCallsign(cs);
    prefs.putString("callsign", cs);
    request->send(200, "application/json", "{\"ok\":true}");
  });

  server.on("/api/clear-settings", HTTP_POST, [](AsyncWebServerRequest *request) {
    if (!checkAuth(request)) return;
    prefs.clear(); // wipes the whole "pocsag" NVS namespace -- callsign,
                    // dispTimeoutMs, and web_password, nothing else stored under it
    setCallsign("");
    setWebPassword(WEB_PASSWORD);
    displayTimeoutMs = DISPLAY_TIMEOUT_MS_DEFAULT;
    lastDisplayActivity = millis();
    Serial.println("[web] settings cleared -- callsign, web password, and screen timeout reset to defaults");
    request->send(200, "application/json", "{\"ok\":true}");
  });

  server.on("/api/reboot", HTTP_POST, [](AsyncWebServerRequest *request) {
    if (!checkAuth(request)) return;
    Serial.println("[web] reboot requested via dashboard");
    request->send(200, "application/json", "{\"ok\":true}");
    rebootRequested = true;
    rebootRequestedAt = millis(); // loop() does the actual ESP.restart() -- see its own comment
  });

  server.begin();
  Serial.print("[web] dashboard ready at http://"); Serial.print(MDNS_HOSTNAME); Serial.println(".local/");
}


// ---------- OLED ----------

void oled(const String &line1, const String &line2) {
  wakeDisplay();
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(0, 0);
  display.println(line1);
  display.setCursor(0, 20);
  display.println(line2);
  display.display();
}

void showListeningScreen() {
  wakeDisplay();
  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);
  display.setTextSize(2);
  display.setCursor(0, 0);
  display.print("RX #");
  display.print(rxBatchCount);
  display.drawFastHLine(0, 20, OLED_WIDTH, SSD1306_WHITE);
  display.setTextSize(1);
  display.setCursor(0, 26);
  display.print("439.9875MHz  ");
  display.print(POCSAG_BAUD);
  display.print("bps");
  display.setCursor(0, 38);
  display.print("Listening... TX#");
  display.print(txCount);
  display.display();
}

// Shows an actual received page's content -- capcode, type, message text --
// instead of just a generic "listening" screen with a bumped counter.
// Persists until the next real event (another incoming page, or a serial
// send) overwrites it, same convention as showSentScreen() below.
void showIncomingScreen(uint32_t capcode, const String &type, const String &text) {
  wakeDisplay();
  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);

  display.setTextSize(1);
  display.setCursor(0, 0);
  display.print("INCOMING ");
  display.print(type);
  display.drawFastHLine(0, 10, OLED_WIDTH, SSD1306_WHITE);

  display.setCursor(0, 14);
  display.print("Cap:"); display.print(capcode);
  display.print(" RX#"); display.print(rxBatchCount);

  display.setCursor(0, 26);
  if (text.length() == 0) {
    display.println("(no text)");
  } else {
    display.println(text.substring(0, 21));
    if (text.length() > 21) display.println(text.substring(21, 42));
  }

  display.drawFastHLine(0, 46, OLED_WIDTH, SSD1306_WHITE);
  display.setCursor(0, 50);
  display.print("439.9875MHz  ");
  display.print(POCSAG_BAUD);
  display.print("bps");

  display.display();
}

void showSentScreen(uint32_t capcode, const String &text, int state) {
  wakeDisplay();
  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);
  display.setTextSize(1);
  display.setCursor(0, 0);
  display.print("SERIAL SEND");
  display.drawFastHLine(0, 10, OLED_WIDTH, SSD1306_WHITE);

  display.setCursor(0, 14);
  display.print("Cap:"); display.print(capcode);
  display.print(" TX#"); display.print(txCount);

  display.setCursor(0, 26);
  display.println(text.substring(0, 21));
  if (text.length() > 21) display.println(text.substring(21, 42));

  display.drawFastHLine(0, 46, OLED_WIDTH, SSD1306_WHITE);
  display.setCursor(10, 58);
  if (lastTxOk) display.fillCircle(3, 60, 2, SSD1306_WHITE);
  else          display.drawCircle(3, 60, 2, SSD1306_WHITE);
  display.print(lastTxOk ? "Last TX OK" : String("Last TX FAILED (") + state + ")");
  display.display();
}


void setup() {
  Serial.begin(115200);
  delay(1000);

#if defined(BOARD_HELTEC_WIFI_LORA32_V3)
  // Heltec V3's OLED (and onboard sensors) sit behind an external power
  // switch, Vext (GPIO36, confirmed against the ESP32 core's own board
  // file -- an earlier draft of this file used GPIO21 here, which is
  // actually the OLED's own dedicated RESET pin, not Vext; see
  // OLED_RST_PIN/VEXT_PIN's own comments in the Radio section for the
  // full story). Pulled LOW before anything on that rail will respond,
  // left LOW for the rest of the session. The actual OLED reset pulse
  // happens separately, inside display.begin() below, via OLED_RST_PIN
  // (GPIO21) passed into the Adafruit_SSD1306 constructor.
  pinMode(VEXT_PIN, OUTPUT);
  digitalWrite(VEXT_PIN, LOW); // power ON
  delay(100); // let the display's power rail stabilize before I2C traffic
#endif

  Wire.begin(OLED_SDA_PIN, OLED_SCL_PIN);
  if (!display.begin(SSD1306_SWITCHCAPVCC, 0x3C)) {
    Serial.println("OLED FAIL");
  }
  display.setRotation(2); // 0=normal, 2=180 degrees (Adafruit_GFX)
  oled("POCSAG companion", "starting...");

  SPI.begin(LORA_SCK, LORA_MISO, LORA_MOSI, LORA_CS);

  padSimBch.begin(RADIOLIB_PAGER_BCH_N, RADIOLIB_PAGER_BCH_K, RADIOLIB_PAGER_BCH_PRIMITIVE_POLY);

  pinMode(BUTTON_GPIO, INPUT_PULLUP);
  lastDisplayActivity = millis();
  stateMutex = xSemaphoreCreateMutex(); // guards webLog[]/webSend*/callsign -- see the
                                         // web dashboard section's own comment for why

  prefs.begin(PREFS_NAMESPACE, false);
  setCallsign(prefs.getString("callsign", ""));
  setWebPassword(prefs.getString("web_password", WEB_PASSWORD));
  setWifiCredentials(
    prefs.getString("wifi_ssid", WIFI_SSID),
    prefs.getString("wifi_pass", WIFI_PASSWORD)
  );
  displayTimeoutMs = prefs.getUInt("dispTimeoutMs", DISPLAY_TIMEOUT_MS_DEFAULT);

  configureForRx();
  setupWifiNtpOta(); // best-effort, bounded timeout -- see its own comment

  Serial.println("========================================");
#if defined(BOARD_TTGO_LORA32)
  Serial.println("Board: TTGO LoRa32 (SX1276) -- RX+TX, LIVE-VERIFIED");
#elif defined(BOARD_HELTEC_WIFI_LORA32_V3)
  Serial.println("Board: Heltec WiFi LoRa32 V3 (SX1262) -- RX+TX, both LIVE-VERIFIED");
#endif
  Serial.println("POCSAG companion ready -- 439.9875 MHz, no DIO2 needed");
  if (wifiConnected) {
    Serial.print("WiFi/OTA up -- "); Serial.print(MDNS_HOSTNAME); Serial.println(".local");
  } else {
    Serial.println("WiFi/OTA not connected -- RX/TX-only");
  }
  Serial.println("Listening continuously. Received pages print as JSON, e.g.:");
  Serial.println("  {\"capcode\":2041152,\"function\":3,\"type\":\"alpha\",\"text\":\"Hello\"}");
  Serial.println();
  Serial.println("Send a JSON line + Enter to transmit it live (pauses RX briefly):");
  Serial.print("  {\"text\": \"Hello from meshpoint\"}                -> sent to default capcode ");
  Serial.println(SERIAL_DEFAULT_CAPCODE);
  Serial.println("  {\"capcode\": 112, \"text\": \"Hello\"}  -> sent to that specific capcode instead");
  Serial.println("========================================");

  showListeningScreen();
}

void loop() {
  checkSerialInput(); // may call sendPocsagAlpha(), which pauses/resumes RX internally
  checkButton();       // GPIO0 BOOT button -- manual display on/off toggle
  if (wifiConnected) ArduinoOTA.handle();
  checkWebSendPending(); // picks up a send staged by the web UI's /api/send handler --
                          // see that function's own comment for why the handoff, not a
                          // direct call, is required from an AsyncWebServer callback

  if (rebootRequested && millis() - rebootRequestedAt >= REBOOT_DELAY_MS) {
    ESP.restart();
  }

  if (displayOn && displayTimeoutMs > 0 && millis() - lastDisplayActivity >= displayTimeoutMs) {
    display.ssd1306_command(SSD1306_DISPLAYOFF);
    displayOn = false;
  }

  if (!radioInRxMode) return; // mid-send (shouldn't normally observe this -- sendPocsagAlpha() is synchronous -- but guard anyway)

#if !POCSAG_RX_SUPPORTED
  return; // this board (see BOARD SELECT above) has no RX support -- TX + web dashboard only
#else
  // FIXED a real flaw in the previous version: radio.receive(...) is a
  // BLOCKING call that puts the chip into STANDBY internally before
  // returning on timeout (SX127x::finishReceive()) -- so reading RSSI
  // right after it returned was reading a value from AFTER the
  // receiver had already left active RX mode, not a live sample.
  // Three deliberately-timed real DAPNET sends still showed a flat
  // RSSI trace against that flawed version, which is suggestive but
  // not conclusive given the sampling bug. This uses non-blocking
  // continuous RX (radio.startReceive(), returns immediately) and
  // polls RSSI at ~5x/sec while genuinely still listening, checking
  // DIO0 directly (same pin+meaning SX127x::receive()'s own blocking
  // wait polls internally -- PayloadReady goes high on a real packet
  // match) for an actual packet without ever leaving RX mode in
  // between samples.
  if (!rxContinuousStarted) {
    // Never checked this return value before -- if startReceive() itself
    // is silently failing, the chip just sits in standby the whole time
    // and getRSSI() returns a frozen value, which would exactly explain
    // a perfectly static reading across many samples (real RF noise
    // essentially never holds bit-identical that long).
    int rxState = radio.startReceive();
    if (rxState != RADIOLIB_ERR_NONE) {
      Serial.print("[rx] startReceive() FAILED, code="); Serial.println(rxState);
    }
    rxContinuousStarted = true;
  }

  static unsigned long lastRssiPrint = 0;
  if (DEBUG_RX && millis() - lastRssiPrint >= 200) {
    lastRssiPrint = millis();
#if defined(BOARD_TTGO_LORA32)
    // skipReceive=true is load-bearing, not cosmetic -- see POCSAG_SYNC_BYTES'
    // own comment above for the getRSSICommon() gotcha this works around.
    float rssi = radio.getRSSI(false, true);
#elif defined(BOARD_HELTEC_WIFI_LORA32_V3)
    // SX126x's getRSSI() has no skipReceive-equivalent overload in RadioLib --
    // UNVERIFIED whether it has the same "silently restarts RX" side effect
    // the SX127x overload had (see the TTGO comment above). If RX looks like
    // it never fires despite strong RSSI here, this is the first thing to
    // suspect -- it was the actual root cause the one time this exact
    // symptom showed up on the TTGO.
    float rssi = radio.getRSSI();
#endif
    // Quiet the log down to just the interesting moments -- printing
    // every ~85dBm noise-floor sample was drowning out the real spikes
    // we're actually looking for. -80dBm is comfortably above the
    // observed ~-80 to -89dBm noise floor and comfortably below the
    // real signal spikes we've confirmed (-17 to -21dBm) on the TTGO --
    // unverified whether -80dBm is still a sensible cutoff on the Heltec's
    // different RF front-end, but a reasonable starting point.
    if (rssi > -80.0f) {
      Serial.print("[rx] live RSSI="); Serial.print(rssi);
      Serial.print(" dBm  IRQ="); Serial.println(digitalRead(LORA_IRQ_PIN));
    }
  }

  if (digitalRead(LORA_IRQ_PIN)) {
    uint8_t payload[POCSAG_RX_BATCH_BYTES];
    int state = radio.readData(payload, sizeof(payload));
    rxContinuousStarted = false; // re-armed via startReceive() next loop() call

    if (state == RADIOLIB_ERR_NONE) {
      uint32_t cw[16];
      for (int i = 0; i < 16; i++) {
        // Invert every payload byte before use -- same reason
        // POCSAG_SYNC_BYTES is the inverted sync word (see its own
        // comment): the chip's hardware demodulator's bit sense is
        // backwards relative to POCSAG's real convention, and
        // RadioLib's own PagerClient::read() inverts the whole
        // codeword (`codeWord = ~codeWord`) for the identical reason.
        uint8_t b0 = ~payload[i * 4], b1 = ~payload[i * 4 + 1], b2 = ~payload[i * 4 + 2], b3 = ~payload[i * 4 + 3];
        cw[i] = ((uint32_t)b0 << 24) | ((uint32_t)b1 << 16) | ((uint32_t)b2 << 8) | (uint32_t)b3;
      }
      rxBatchCount++;
      Serial.println("[rx] PACKET RECEIVED");
      // decodeBatchAndEmit() shows the actual decoded content itself
      // (capcode/type/text) via showIncomingScreen() per page found --
      // no showListeningScreen() call here, that would immediately
      // overwrite it with the generic idle screen.
      decodeBatchAndEmit(cw, 16);
    } else {
      Serial.print("[rx] readData error "); Serial.println(state);
    }
  }
#endif // POCSAG_RX_SUPPORTED
}
