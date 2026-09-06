/*
 * Lumina IoT - ESP32 LED Controller
 *
 * Connects to WiFi and MQTT broker, listens for commands.
 * Local-only version (no Azure).
 *
 * Required Libraries:
 * - PubSubClient (Nick O'Leary)
 * - ArduinoJson (Benoit Blanchon)
 * - FastLED (Daniel Garcia) - for actual LED control
 */

#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <FastLED.h>
#include "secrets.h"

// ===================
// LED Configuration
// ===================
#define LED_PIN     5
//#define NUM_LEDS    173
#define NUM_LEDS    91
#define LED_TYPE    WS2815
#define COLOR_ORDER GRB

CRGB leds[NUM_LEDS];

// ===================
// Configuration
// ===================
const char* wifi_ssid = WIFI_SSID;
const char* wifi_password = WIFI_PASSWORD;
const char* mqtt_broker = MQTT_BROKER_IP;
const int mqtt_port = MQTT_PORT;

// Device ID - generated from ESP32's unique chip ID
String device_id;

// MQTT Topics
String TOPIC_SET;
String TOPIC_STATE;
const char* TOPIC_ANNOUNCE = "devices/announce";

// ===================
// State
// ===================
bool powerOn = true;
int currentBrightness = 100;
int currentR = 255;
int currentG = 255;
int currentB = 255;
String currentEffect = "none";

// Clients
WiFiClient wifiClient;
PubSubClient mqtt(wifiClient);

// Heartbeat
unsigned long lastHeartbeat = 0;
const unsigned long HEARTBEAT_INTERVAL = 60000;  // 60 seconds

// Effect animation state
uint8_t effectHue = 0;
int effectPos = 0;
int effectDirection = 1;

// ===================
// Generate Device ID from Chip ID
// ===================
String getChipId() {
  uint64_t chipid = ESP.getEfuseMac();
  // Use last 4 bytes (32 bits) for a shorter ID
  uint32_t id = (uint32_t)(chipid >> 16);
  char idStr[9];
  snprintf(idStr, sizeof(idStr), "%08X", id);
  return String(idStr);
}

// ===================
// Status Indicator (LED 0)
// ===================
void showStatus(CRGB color) {
  fill_solid(leds, NUM_LEDS, CRGB::Black);
  uint8_t pulse = beatsin8(30, 40, 255);
  for (int i = 0; i < 5; i++) {
    leds[i] = color;
    leds[i].fadeToBlackBy(255 - pulse);
  }
  FastLED.setBrightness(255);
  FastLED.show();
}

void flashGreen() {
  for (int i = 0; i < 3; i++) {
    fill_solid(leds, 5, CRGB::Green);
    FastLED.setBrightness(255);
    FastLED.show();
    delay(150);
    fill_solid(leds, 5, CRGB::Black);
    FastLED.show();
    delay(150);
  }
}

// ===================
// Update LEDs
// ===================
void updateLeds() {
  fill_solid(leds, NUM_LEDS, CRGB(currentR, currentG, currentB));
  FastLED.setBrightness(map(currentBrightness, 0, 100, 0, 255));
  FastLED.show();
}

// ===================
// Effects
// ===================

// CLASSICS
void effectRainbow() {
  fill_rainbow(leds, NUM_LEDS, effectHue, 7);
  FastLED.show();
  effectHue++;
}

void effectBreathing() {
  uint8_t breath = beatsin8(12, 20, 255);
  fill_solid(leds, NUM_LEDS, CRGB(currentR, currentG, currentB));
  FastLED.setBrightness(map(breath * currentBrightness / 100, 0, 255, 0, 255));
  FastLED.show();
}

void effectChase() {
  fadeToBlackBy(leds, NUM_LEDS, 40);
  leds[effectPos] = CRGB(currentR, currentG, currentB);
  FastLED.show();
  effectPos++;
  if (effectPos >= NUM_LEDS) effectPos = 0;
}

void effectSparkle() {
  fadeToBlackBy(leds, NUM_LEDS, 20);
  if (random8() < 80) {
    leds[random16(NUM_LEDS)] = CRGB(currentR, currentG, currentB);
  }
  FastLED.show();
}

// PARTY
void effectFire() {
  // Fire simulation - heat rises from bottom
  static byte heat[NUM_LEDS];

  // Cool down
  for (int i = 0; i < NUM_LEDS; i++) {
    heat[i] = qsub8(heat[i], random8(0, 35));
  }

  // Heat rises
  for (int i = NUM_LEDS - 1; i >= 2; i--) {
    heat[i] = (heat[i - 1] + heat[i - 2] + heat[i - 2]) / 3;
  }

  // Random sparks at bottom
  if (random8() < 120) {
    heat[random8(7)] = qadd8(heat[random8(7)], random8(160, 255));
  }

  // Map heat to colors
  for (int i = 0; i < NUM_LEDS; i++) {
    leds[i] = HeatColor(heat[i]);
  }
  FastLED.show();
}

void effectConfetti() {
  fadeToBlackBy(leds, NUM_LEDS, 10);
  leds[random16(NUM_LEDS)] += CHSV(effectHue + random8(64), 200, 255);
  effectHue++;
  FastLED.show();
}

void effectCylon() {
  fadeToBlackBy(leds, NUM_LEDS, 20);
  leds[effectPos] = CRGB(currentR, currentG, currentB);
  FastLED.show();

  effectPos += effectDirection;
  if (effectPos >= NUM_LEDS - 1 || effectPos <= 0) {
    effectDirection *= -1;
  }
}

void effectStrobe() {
  static bool on = false;
  if (on) {
    fill_solid(leds, NUM_LEDS, CRGB(currentR, currentG, currentB));
  } else {
    fill_solid(leds, NUM_LEDS, CRGB::Black);
  }
  on = !on;
  FastLED.show();
}

// CHILL / AMBIENT
void effectOcean() {
  for (int i = 0; i < NUM_LEDS; i++) {
    uint8_t wave = beatsin8(6 + (i % 5), 100, 255, 0, i * 10);
    leds[i] = CRGB(0, wave / 3, wave);
  }
  FastLED.show();
}

void effectAurora() {
  for (int i = 0; i < NUM_LEDS; i++) {
    uint8_t hue = effectHue + (i * 2);
    uint8_t brightness = beatsin8(3 + (i % 4), 50, 255, 0, i * 5);
    leds[i] = CHSV(96 + (sin8(hue) / 8), 255, brightness);  // Greens and blues
  }
  effectHue++;
  FastLED.show();
}

void effectCandle() {
  for (int i = 0; i < NUM_LEDS; i++) {
    uint8_t flicker = random8(180, 255);
    leds[i] = CRGB(flicker, flicker / 3, 0);  // Warm orange/yellow
  }
  FastLED.show();
}

// HOLIDAY
void effectChristmas() {
  fadeToBlackBy(leds, NUM_LEDS, 5);
  // Alternating red and green with occasional twinkle
  for (int i = 0; i < NUM_LEDS; i++) {
    if (leds[i].getLuma() < 20) {
      leds[i] = (i % 2 == 0) ? CRGB(50, 0, 0) : CRGB(0, 50, 0);
    }
  }
  // Random twinkle
  if (random8() < 60) {
    int pos = random16(NUM_LEDS);
    leds[pos] = (pos % 2 == 0) ? CRGB::Red : CRGB::Green;
  }
  FastLED.show();
}

void effectUSA() {
  int section = NUM_LEDS / 3;
  for (int i = 0; i < NUM_LEDS; i++) {
    if (i < section) {
      leds[i] = CRGB::Red;
    } else if (i < section * 2) {
      leds[i] = CRGB::White;
    } else {
      leds[i] = CRGB::Blue;
    }
  }
  // Add shimmer
  leds[random16(NUM_LEDS)].fadeToBlackBy(random8(50, 150));
  FastLED.show();
}

void runEffect() {
  // Classics
  if (currentEffect == "rainbow") {
    effectRainbow();
    delay(20);
  } else if (currentEffect == "breathing") {
    effectBreathing();
    delay(10);
  } else if (currentEffect == "chase") {
    effectChase();
    delay(30);
  } else if (currentEffect == "sparkle") {
    effectSparkle();
    delay(30);
  }
  // Party
  else if (currentEffect == "fire") {
    effectFire();
    delay(30);
  } else if (currentEffect == "confetti") {
    effectConfetti();
    delay(20);
  } else if (currentEffect == "cylon") {
    effectCylon();
    delay(20);
  } else if (currentEffect == "strobe") {
    effectStrobe();
    delay(80);
  }
  // Chill
  else if (currentEffect == "ocean") {
    effectOcean();
    delay(20);
  } else if (currentEffect == "aurora") {
    effectAurora();
    delay(30);
  } else if (currentEffect == "candle") {
    effectCandle();
    delay(50);
  }
  // Holiday
  else if (currentEffect == "christmas") {
    effectChristmas();
    delay(30);
  } else if (currentEffect == "usa") {
    effectUSA();
    delay(30);
  }
}

// ===================
// Get State as JSON String
// ===================
String getStateJson() {
  JsonDocument doc;
  doc["device_id"] = device_id;
  doc["power"] = powerOn;
  doc["brightness"] = currentBrightness;
  doc["color"]["r"] = currentR;
  doc["color"]["g"] = currentG;
  doc["color"]["b"] = currentB;
  doc["effect"] = currentEffect;

  String output;
  serializeJson(doc, output);
  return output;
}

// ===================
// Process Command
// ===================
void processCommand(String message) {
  Serial.println();
  Serial.println("========== RECEIVED COMMAND ==========");
  Serial.print("Message: ");
  Serial.println(message);

  JsonDocument doc;
  DeserializationError error = deserializeJson(doc, message);

  if (error) {
    Serial.print("JSON parse error: ");
    Serial.println(error.c_str());
    return;
  }

  // Handle power command
  if (doc.containsKey("power")) {
    powerOn = doc["power"].as<bool>();

    Serial.println("--- LED ACTION ---");
    Serial.print("Power: ");
    Serial.println(powerOn ? "ON" : "OFF");

    if (!powerOn) {
      fill_solid(leds, NUM_LEDS, CRGB::Black);
      FastLED.show();
    } else {
      updateLeds();
    }
  }

  // Handle color command
  if (doc.containsKey("color")) {
    JsonObject color = doc["color"];
    currentR = color["r"] | currentR;
    currentG = color["g"] | currentG;
    currentB = color["b"] | currentB;

    Serial.println("--- LED ACTION ---");
    Serial.print("Set color to RGB(");
    Serial.print(currentR);
    Serial.print(", ");
    Serial.print(currentG);
    Serial.print(", ");
    Serial.print(currentB);
    Serial.println(")");

    updateLeds();
  }

  // Handle brightness command
  if (doc.containsKey("brightness")) {
    currentBrightness = doc["brightness"];

    Serial.println("--- LED ACTION ---");
    Serial.print("Set brightness to ");
    Serial.print(currentBrightness);
    Serial.println("%");

    updateLeds();
  }

  // Handle effect command
  if (doc.containsKey("effect")) {
    currentEffect = doc["effect"].as<String>();

    Serial.println("--- LED ACTION ---");
    Serial.print("Start effect: ");
    Serial.println(currentEffect);

    // Reset effect state
    effectHue = 0;
    effectPos = 0;

    // If "none", go back to solid color
    if (currentEffect == "none") {
      updateLeds();
    }
  }

  Serial.println("=======================================");
  publishState();
}

// ===================
// MQTT Callback
// ===================
void onMqttMessage(char* topic, byte* payload, unsigned int length) {
  String message;
  for (unsigned int i = 0; i < length; i++) {
    message += (char)payload[i];
  }
  Serial.print("Topic: ");
  Serial.println(topic);
  processCommand(message);
}

// ===================
// Publish State
// ===================
void publishState() {
  String output = getStateJson();
  mqtt.publish(TOPIC_STATE.c_str(), output.c_str());
  Serial.print("State published: ");
  Serial.println(output);
}

// ===================
// Announce Device
// ===================
void announceDevice() {
  JsonDocument doc;
  doc["device_id"] = device_id;
  doc["type"] = "led_strip";
  doc["ip"] = WiFi.localIP().toString();
  doc["capabilities"][0] = "color";
  doc["capabilities"][1] = "brightness";
  doc["capabilities"][2] = "effects";

  String output;
  serializeJson(doc, output);

  mqtt.publish(TOPIC_ANNOUNCE, output.c_str());
  Serial.println("Device announced to broker");
}

// ===================
// WiFi Connection
// ===================
void connectWiFi() {
  Serial.print("Connecting to WiFi");
  WiFi.begin(wifi_ssid, wifi_password);

  while (WiFi.status() != WL_CONNECTED) {
    showStatus(CRGB::Red);
    delay(20);
  }

  Serial.println();
  Serial.print("Connected! IP: ");
  Serial.println(WiFi.localIP());
}

// ===================
// MQTT Connection
// ===================
void connectMqtt() {
  mqtt.setServer(mqtt_broker, mqtt_port);

  while (!mqtt.connected()) {
    Serial.print("Connecting to MQTT broker at ");
    Serial.print(mqtt_broker);
    Serial.print("...");

    if (mqtt.connect(device_id.c_str())) {
      Serial.println(" connected!");
      mqtt.subscribe(TOPIC_SET.c_str());
      Serial.print("Subscribed to: ");
      Serial.println(TOPIC_SET);
      announceDevice();
      flashGreen();
    } else {
      Serial.print(" failed (rc=");
      Serial.print(mqtt.state());
      Serial.println("). Retrying in 5 seconds...");

      // Pulse yellow for 5 seconds
      unsigned long start = millis();
      while (millis() - start < 5000) {
        showStatus(CRGB::Yellow);
        delay(20);
      }
    }
  }
}

// ===================
// Setup
// ===================
void setup() {
  Serial.begin(115200);
  delay(1000);

  // Generate device ID from chip ID
  device_id = getChipId();

  Serial.println();
  Serial.println("================================");
  Serial.println("Lumina IoT - LED Controller");
  Serial.print("Device ID: ");
  Serial.println(device_id);
  Serial.println("================================");

  // Initialize FastLED
  FastLED.addLeds<LED_TYPE, LED_PIN, COLOR_ORDER>(leds, NUM_LEDS);
  FastLED.setBrightness(255);
  fill_solid(leds, NUM_LEDS, CRGB::Black);
  FastLED.show();
  Serial.println("LEDs initialized");

  // Set up topics based on device ID
  TOPIC_SET = String("lights/") + device_id + "/set";
  TOPIC_STATE = String("lights/") + device_id + "/state";

  // Connect to WiFi
  connectWiFi();

  // Configure MQTT callback
  mqtt.setCallback(onMqttMessage);

  // Connect to MQTT
  connectMqtt();
}

// ===================
// Main Loop
// ===================
void loop() {
  if (!mqtt.connected()) {
    connectMqtt();
  }
  mqtt.loop();

  // Heartbeat - publish state every 60 seconds to stay "online"
  unsigned long now = millis();
  if (now - lastHeartbeat >= HEARTBEAT_INTERVAL) {
    lastHeartbeat = now;
    publishState();
    Serial.println("Heartbeat sent");
  }

  // Run effect animation (only if power is on)
  if (powerOn && currentEffect != "none") {
    runEffect();
  }
}
