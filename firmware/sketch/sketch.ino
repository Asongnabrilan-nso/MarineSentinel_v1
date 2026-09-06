// SPDX-FileCopyrightText: Copyright (C) 2026 MarineSentinel Project
// SPDX-License-Identifier: MPL-2.0

#include <Arduino_RouterBridge.h>
#include <Arduino_LED_Matrix.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <Wire.h>
#include <MPU6050_light.h>

// ── Pin assignments ───────────────────────────────────────────────────────────
#define TURBIDITY_PIN   A0   // Analog turbidity sensor (SEN0189 or equivalent)
#define DS18B20_PIN     D2   // DS18B20 1-Wire data line
// MPU6050 IMU — on the QWIIC connector, default address 0x68 (AD0 low).
// The board exposes three I2C buses (devicetree order: i2c2, i2c4, i2c3),
// mapped to Wire=I2C2 (digital pins D20/D21), Wire1=I2C4 (QWIIC connector),
// Wire2=I2C3 (analog pins A4/A5) — the QWIIC connector is Wire1, NOT the
// plain default Wire.

// ── Sensor driver objects ─────────────────────────────────────────────────────
OneWire           oneWire(DS18B20_PIN);
DallasTemperature tempSensor(&oneWire);
Arduino_LED_Matrix matrix;
MPU6050            imu(Wire1);   // Wire1 = I2C4 = the QWIIC connector
bool                imuReady = false;   // false if the MPU6050 didn't ACK on I2C at boot
byte                imuStatus = 255;    // imu.begin() return code, reported to Python for diagnostics
byte                imuScanAddr = 0;    // first address that ACKed a bus scan on failure, 0 = none

// ── Sampling configuration ────────────────────────────────────────────────────
const unsigned long SAMPLE_INTERVAL_MS   = 2000;   // 2 s between turbidity/temp readings
const unsigned long IMU_SEND_INTERVAL_MS = 100;    // 10 Hz orientation updates to the MPU
const int           ADC_OVERSAMPLE       = 8;       // average N reads to reduce noise
unsigned long       lastSampleMs         = 0;
unsigned long       lastImuSendMs        = 0;

// ── LED status helpers (UNO Q LEDs are active-low) ───────────────────────────
// LED3 (RGB, MCU-controllable): use Green = OK, Red = ALERT
inline void ledNormal()  { digitalWrite(LED3_R, HIGH); digitalWrite(LED3_G, LOW);  }
inline void ledAlert()   { digitalWrite(LED3_R, LOW);  digitalWrite(LED3_G, HIGH); }

// Scan the I2C bus for any responding device (used only to diagnose a failed
// MPU6050 init). Returns the first address that ACKs, or 0 if the bus is
// empty — 0 isn't a valid 7-bit I2C device address, so it's a safe sentinel.
byte scanI2CBus() {
  for (byte addr = 1; addr < 127; addr++) {
    Wire1.beginTransmission(addr);
    if (Wire1.endTransmission() == 0) return addr;
  }
  return 0;
}

// Bridge handler: Python sets alert state to light the red LED
void setAlert(bool active) {
  active ? ledAlert() : ledNormal();
  Serial.print("[MCU] Alert state -> ");
  Serial.println(active ? "ACTIVE" : "CLEAR");
}

void setup() {
  Serial.begin(115200);

  // Status LEDs
  pinMode(LED3_R, OUTPUT);
  pinMode(LED3_G, OUTPUT);
  ledNormal();

  // Turbidity analog input
  pinMode(TURBIDITY_PIN, INPUT);

  // DS18B20 — request 12-bit resolution (0.0625 °C steps, ~750 ms conversion)
  tempSensor.begin();
  tempSensor.setResolution(12);

  // MPU6050 — accel+gyro fused into roll/pitch, gyro-integrated yaw.
  // Mount the breakout flat with its silkscreen X-axis arrow pointing toward
  // the capsule's bow: then getAngleX()=roll (about bow/stern), getAngleY()=
  // pitch (nose up/down), getAngleZ()=yaw (heading, drifts — no magnetometer).
  Wire1.begin();   // QWIIC connector — see the Wire1/I2C4 note above
  imuStatus = imu.begin();
  if (imuStatus == 0) {
    Serial.println("[MCU] MPU6050 found — calibrating (keep capsule still)...");
    delay(1000);
    imu.calcOffsets(true, true);   // gyro + accelerometer offsets
    imuReady = true;
    Serial.println("[MCU] MPU6050 ready");
  } else {
    // Don't block the rest of the sensors on a missing/faulty IMU — just
    // skip orientation reporting, same fail-open approach as DS18B20 errors.
    Serial.print("[MCU] MPU6050 init failed, status=");
    Serial.println(imuStatus);
    imuScanAddr = scanI2CBus();
    Serial.print("[MCU] I2C bus scan — first device found at: 0x");
    Serial.println(imuScanAddr, HEX);
  }

  // LED matrix — show splash pattern then clear
  matrix.begin();
  matrix.clear();

  // Router Bridge
  Bridge.begin();
  Bridge.provide("set_alert", setAlert);

  Serial.println("[MCU] MarineSentinel ready — sampling every 2 s");
}

void loop() {
  // Run the complementary filter every tick (not just every 2 s) so the
  // fused roll/pitch angles stay accurate — feeding it a large, coarse dt
  // would make the gyro-integration term dominate the fused result.
  if (imuReady) {
    imu.update();
  }

  unsigned long now = millis();

  if (now - lastImuSendMs >= IMU_SEND_INTERVAL_MS) {
    lastImuSendMs = now;
    if (imuReady) {
      Bridge.notify("imu_data", imu.getAngleX(), imu.getAngleY(), imu.getAngleZ());
    } else {
      // Keep reporting the failure once a second — a one-shot notify at boot
      // would race Python's Bridge.provide() registration (the MCU boots
      // and runs setup() well before the Python session is up) and could be
      // missed entirely. Repeating it guarantees Python sees it eventually.
      Bridge.notify("imu_status", imuStatus, imuScanAddr);
    }
  }

  if (now - lastSampleMs < SAMPLE_INTERVAL_MS) return;
  lastSampleMs = now;

  // ── Turbidity: oversample ADC and average ────────────────────────────────
  long rawSum = 0;
  for (int i = 0; i < ADC_OVERSAMPLE; i++) {
    rawSum += analogRead(TURBIDITY_PIN);
    delay(5);
  }
  int turbidityRaw = (int)(rawSum / ADC_OVERSAMPLE);

  // ── DS18B20 temperature ──────────────────────────────────────────────────
  tempSensor.requestTemperatures();
  float tempC = tempSensor.getTempCByIndex(0);

  // Log to serial (view with: arduino-app-cli monitor)
  Serial.print("[MCU] Turbidity raw=");
  Serial.print(turbidityRaw);
  Serial.print("  Temp=");
  Serial.print(tempC, 2);
  Serial.println(" C");

  // Stream readings up to Python — non-blocking fire-and-forget
  Bridge.notify("sensor_data", turbidityRaw, tempC);
}
