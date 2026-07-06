// LoRaWAN test TX for Heltec WiFi LoRa 32 V3 (SX1262)
// Alternates between Join-Request and Unconfirmed Data Up frames
// on EU868 channels so the Meshpoint sniffer can verify both
// LoRaWAN decoder branches and the dashboard panel.
//
// Library: RadioLib  (install via Arduino Library Manager)
// Board:   Heltec WiFi LoRa 32 (V3)  in Arduino / PlatformIO

#include <RadioLib.h>

// Heltec V3 SX1262 pins
SX1262 radio = new Module(8, 14, 12, 13);  // NSS, DIO1, RST, BUSY

// Join-Request — 23 bytes
// MHDR(1) | JoinEUI(8 LSB) | DevEUI(8 LSB) | DevNonce(2 LE) | MIC(4)
uint8_t joinFrame[23] = {
  0x00,                                             // MHDR  MType=000  Join-Request
  0x70, 0xB3, 0xD5, 0x7E, 0xD0, 0x00, 0x01, 0x70,  // JoinEUI  (LSB first)
  0xFE, 0xCA, 0xDE, 0xC0, 0xAD, 0xDE, 0x00, 0x08,  // DevEUI   08:00:DE:AD:C0:DE:CA:FE (LSB first)
  0x01, 0x00,                                       // DevNonce (updated each TX)
  0xDE, 0xAD, 0xBE, 0xEF                            // MIC      (fake)
};

// Unconfirmed Data Up — 17 bytes
// MHDR(1) | DevAddr(4 LE) | FCtrl(1) | FCnt(2 LE) | FPort(1) | FRMPayload(4) | MIC(4)
uint8_t dataFrame[17] = {
  0x40,                    // MHDR  MType=010  Unconfirmed Data Up
  0xDE, 0xC0, 0xAD, 0xDE,  // DevAddr  DEADC0DE (LSB first)
  0x00,                    // FCtrl  ADR=0 ACK=0 FOptsLen=0
  0x01, 0x00,              // FCnt   (updated each TX)
  0x01,                    // FPort  1
  0xCA, 0xFE, 0xBA, 0xBE,  // FRMPayload  (fake — shows as encrypted in sniffer)
  0xDE, 0xAD, 0xBE, 0xEF   // MIC         (fake)
};

// EU868 LoRaWAN uplink channels covered by the Meshpoint sniffer's RF0
// window (867.9-868.7 MHz): 3 mandatory + 2 extra TTN channels.
const float EU868_CHANNELS[] = {867.9, 868.1, 868.3, 868.5, 868.7};
const int   NUM_CHANNELS     = sizeof(EU868_CHANNELS) / sizeof(EU868_CHANNELS[0]);
int      channelIdx = 0;
uint16_t devNonce   = 1;
uint16_t fCnt       = 1;
int      txCount    = 0;

void setup() {
  Serial.begin(115200);
  delay(1000);

  // RADIOLIB_SX126X_SYNC_WORD_PUBLIC = 0x3444
  // SX1262 two-byte form of the SX127x 0x34 LoRaWAN public syncword — identical on air.
  int state = radio.begin(
    EU868_CHANNELS[0],                // frequency (MHz)
    125.0,                            // bandwidth (kHz)
    7,                                // spreading factor
    5,                                // coding rate 4/5
    RADIOLIB_SX126X_SYNC_WORD_PUBLIC, // LoRaWAN public syncword
    14,                               // TX power (dBm)
    8                                 // preamble length (symbols)
  );

  if (state != RADIOLIB_ERR_NONE) {
    Serial.printf("[!] Radio init failed: %d\n", state);
    while (true) delay(1000);
  }

  Serial.println("[*] LoRaWAN test TX ready");
  Serial.println("[*] Alternating Join-Request / Unconfirmed Data Up every 5 s");
  Serial.println("[*] DevEUI=08:00:DE:AD:C0:DE:CA:FE  DevAddr=DEADC0DE");
  Serial.println("[*] EU868  867.9 / 868.1 / 868.3 / 868.5 / 868.7 MHz  SF7 BW125");
}

void loop() {
  float freq = EU868_CHANNELS[channelIdx % NUM_CHANNELS];
  radio.setFrequency(freq);

  int state;
  if (txCount % 2 == 0) {
    // --- Join-Request ---
    joinFrame[17] = devNonce & 0xFF;
    joinFrame[18] = (devNonce >> 8) & 0xFF;
    Serial.printf("[TX] %.1f MHz  Join-Request   DevNonce=0x%04X ... ", freq, devNonce);
    state = radio.transmit(joinFrame, sizeof(joinFrame));
    devNonce++;
  } else {
    // --- Unconfirmed Data Up ---
    dataFrame[6] = fCnt & 0xFF;
    dataFrame[7] = (fCnt >> 8) & 0xFF;
    Serial.printf("[TX] %.1f MHz  Data-Up        FCnt=0x%04X     ... ", freq, fCnt);
    state = radio.transmit(dataFrame, sizeof(dataFrame));
    fCnt++;
  }

  if (state == RADIOLIB_ERR_NONE) {
    Serial.println("OK");
  } else {
    Serial.printf("FAIL (%d)\n", state);
  }

  txCount++;
  channelIdx++;
  delay(5000);
}
