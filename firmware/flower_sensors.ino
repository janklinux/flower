#include <Wire.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_BME280.h>

#define Pin1 A0
#define Pin2 A1
#define Pin3 A2
#define Pin4 A3
//#define Pin5 A4

// #define soil_wet 220  // wet towel
// #define soil_dry 530  // in air


Adafruit_BME280 bme;

int read_one() {
  int val = analogRead(Pin1);
  return val;
}
int read_two() {
  int val = analogRead(Pin2);
  return val;
}
int read_thr() {
  int val = analogRead(Pin3);
  return val;
}
int read_fou() {
  int val = analogRead(Pin4);
  return val;
}
int read_fiv() {
  int val = 0; //analogRead(Pin5);
  return val;
}
float read_rh() {
  float val = bme.readHumidity();
  return val;
}
float read_temp() {
  float val = bme.readTemperature();
  return val;
}
float read_p() {
  float val = bme.readPressure() / 100;
  return val;
}

void setup() {
    bme.begin(0x76);
    Serial.begin(9600);
}


void loop() {
    delay(1250);

    int val1 = read_one();
    int val2 = read_two();
    int val3 = read_thr();
    int val4 = read_fou();
    int val5 = read_fiv();

    float valrh = read_rh();
    float valt = read_temp();
    float valp = read_p();

    delay(1250);

    Serial.print(val1);
    Serial.print(" ");
    Serial.print(val2);
    Serial.print(" ");
    Serial.print(val3);
    Serial.print(" ");
    Serial.print(val4);
    Serial.print(" ");
    Serial.print(val5);
    Serial.print(" ");
    Serial.print(valrh);
    Serial.print(" ");
    Serial.print(valt);
    Serial.print(" ");
    Serial.print(valp);
    Serial.print("\n");

    delay(7500);
}
