#include <SPI.h>
#include <RadioLib.h>

#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>


// ---------- TTGO LoRa32 OLED pins ----------

#define LORA_SCK   5
#define LORA_MISO 19
#define LORA_MOSI 27
#define LORA_CS   18
#define LORA_RST  14
#define LORA_DIO0 26


// OLED
#define OLED_SDA 4
#define OLED_SCL 15

#define SCREEN_WIDTH 128
#define SCREEN_HEIGHT 64


Adafruit_SSD1306 display(
  SCREEN_WIDTH,
  SCREEN_HEIGHT,
  &Wire,
  -1
);


// ---------- SX1278 ----------

SX1278 radio = new Module(
  LORA_CS,
  LORA_DIO0,
  LORA_RST,
  -1
);


// ---------- Sensor data ----------

uint32_t sensorID = 12345;

uint32_t counter = 0;



float readTemperature()
{
  // Placeholder
  // Replace later with MCU temperature
  return 23.5;
}



// ---------- OLED ----------

void oledText(String line1, String line2, String line3)
{
  display.clearDisplay();

  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);

  display.setCursor(0,0);
  display.println(line1);

  display.setCursor(0,20);
  display.println(line2);

  display.setCursor(0,40);
  display.println(line3);

  display.display();
}



// ---------- Send OOK ----------

void sendSensor()
{

  float temp = readTemperature();


  uint8_t packet[8];


  packet[0] = 0xAA;
  packet[1] = 0x55;


  packet[2] = sensorID >> 8;
  packet[3] = sensorID & 0xff;


  int16_t t =
      (int16_t)(temp * 10);


  packet[4] = t >> 8;
  packet[5] = t & 0xff;


  packet[6] = 55;   // humidity


  packet[7] = counter;


  Serial.println();
  Serial.println("TX packet");

  for(int i=0;i<8;i++)
  {
    Serial.printf("%02X ", packet[i]);
  }

  Serial.println();


  int state =
    radio.transmit(packet, sizeof(packet));


  if(state == RADIOLIB_ERR_NONE)
  {
    Serial.println("TX OK");

    oledText(
      "TTGO 433 OOK",
      "Temp: " + String(temp),
      "TX #" + String(counter)
    );

  }
  else
  {
    Serial.print("TX error ");
    Serial.println(state);

    oledText(
      "TX ERROR",
      String(state),
      ""
    );
  }


  counter++;
}



// ---------- Setup ----------

void setup()
{

  Serial.begin(115200);

  delay(2000);


  // OLED

  Wire.begin(
    OLED_SDA,
    OLED_SCL
  );


  if(!display.begin(
      SSD1306_SWITCHCAPVCC,
      0x3C))
  {
    Serial.println("OLED failed");
  }


  oledText(
    "TTGO LoRa32",
    "433 MHz OOK",
    "Starting..."
  );



  SPI.begin(
    LORA_SCK,
    LORA_MISO,
    LORA_MOSI,
    LORA_CS
  );


  int state =
    radio.beginFSK(
      433.92,
      4.8,
      2.4,
      250
    );


  if(state != RADIOLIB_ERR_NONE)
  {

    Serial.print("Radio error ");
    Serial.println(state);

    oledText(
      "RADIO ERROR",
      String(state),
      ""
    );

    while(true);
  }


  radio.setOOK(true);


  radio.setOutputPower(17);


  Serial.println("Radio ready");


  oledText(
    "Radio OK",
    "433.92MHz",
    "Ready"
  );


}



// ---------- Loop ----------

void loop()
{

  sendSensor();

  delay(10000);

}