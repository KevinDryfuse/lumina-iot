/*
 * Lumina IoT - ESP32 LED Controller
 *
 * Connects to WiFi and MQTT broker, listens for commands.
 * Local-only version (no Azure).
 *
 * ONE BINARY, EVERY STRIP. Pin, chipset, colour order and length used to be
 * #defines, which meant a second strip meant a second build - and in practice
 * meant commenting out the previous strip's length and hoping you flashed the
 * right board. They are now configuration: the server sends them, the device
 * remembers them in NVS, and the same image runs on every controller in the
 * house.
 *
 * FastLED takes pin, chipset and colour order as C++ template parameters, so
 * those genuinely are compile-time. The switch in applyLedConfig() is how a
 * runtime value picks one: every supported combination is instantiated, and one
 * of them is chosen at boot. It costs a few KB of a 4 MB flash and it removes
 * the entire class of mistake where the wall strip gets the desk strip's build.
 *
 * OTA IS THE POINT OF THIS BUILD. Most of these strips are mounted somewhere
 * awkward, so every future change - including the effect engine - arrives over
 * the network. See handleOta().
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
#include <Preferences.h>
#include <HTTPUpdate.h>
#include <esp_ota_ops.h>
#include "secrets.h"

// ===================
// Firmware version
// ===================
// Bump on every build that gets published for OTA. Reported in the announce
// payload, which is how the server knows which strips are behind.
#define FW_VERSION 7

// ===================
// LED Configuration - runtime, not compile time
// ===================
// The array is the worst case; numLeds is how much of it is real. FastLED's
// addLeds() takes the count as a runtime argument - only pin, chipset and
// colour order are template parameters.
#define MAX_LEDS 300

// What a device that has never been told anything comes up as. Deliberately
// small and conservative: enough to drive the boot status indicator and no
// assumption that anything longer is attached.
#define DEFAULT_PIN    5
#define DEFAULT_COUNT  30
#define DEFAULT_TYPE   "WS2815"
#define DEFAULT_ORDER  "GRB"

CRGB leds[MAX_LEDS];

int    numLeds  = DEFAULT_COUNT;
int    ledPin   = DEFAULT_PIN;
String ledType  = DEFAULT_TYPE;
String ledOrder = DEFAULT_ORDER;
bool   ledsReady = false;

Preferences prefs;

#define MAX_PALETTE 8

enum SampleMode { S_FIXED, S_POSITION, S_SCROLL, S_NOISE, S_RANDOM };
enum LevelMode  { L_SOLID, L_WAVE, L_BLOB, L_IMPULSE, L_SQUARE, L_FLICKER };

struct Recipe {
  CRGB    pal[MAX_PALETTE];
  /*
   * A stop written as the string "device" rather than an [r,g,b] triple means
   * "whatever colour this device is set to".
   *
   * Without it, moving an effect into data cost it a feature: chase, cylon,
   * sparkle, breathing and strobe all used to render in the colour you had
   * picked, and a recipe carries its own fixed palette. Now a recipe can defer
   * that decision to the device, and it composes - ["device", [0,0,0]] is a
   * gradient from your colour down to black.
   */
  bool    palIsDevice[MAX_PALETTE] = {false};
  uint8_t palN = 0;

  SampleMode sMode = S_FIXED;
  float sAt = 0, sSpeed = 0, sSpan = 1, sScale = 3;

  LevelMode lMode = L_SOLID;
  float lMin = 0, lMax = 1, lSpeed = 0.2f, lPhase = 0, lDetune = 0;
  float lWidth = 0.1f, lTrail = 0.3f, lRate = 0.15f, lDecay = 0.85f;
  bool  lPingPong = true;

  uint16_t frameMs = 20;
};

Recipe g_recipe;
bool   g_haveRecipe = false;

/*
 * REAL OTA ROLLBACK.
 *
 * The ESP32 bootloader supports it and the Arduino core compiles it in
 * (CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE=y), but by default it is useless here:
 * initArduino() sees the image is PENDING_VERIFY and immediately calls
 * esp_ota_mark_app_valid_cancel_rollback() - BEFORE setup() runs. The image is
 * declared good before a single line of this file has executed, so a crash in
 * setup() or loop() just loops forever.
 *
 * verifyRollbackLater() is a weak symbol the core provides precisely so an
 * application can take that decision back. Returning true defers it, and the
 * image stays PENDING_VERIFY until confirmOta() below says otherwise. If it
 * never does - because the new firmware crashes, or cannot bring up the LEDs,
 * or cannot reach the network - the bootloader reverts to the previous image on
 * the next boot, with no cable involved.
 *
 * That is the difference between "the desk strip is the bench" being a rule
 * everyone has to remember and the hardware enforcing it.
 */
bool verifyRollbackLater() { return true; }

bool     g_otaConfirmed = false;
uint32_t g_bootMs = 0;

/*
 * What counts as proof.
 *
 * MQTT being up means WiFi came up, the LEDs initialised, NVS was readable and
 * the broker answered - very nearly everything that could be broken by a bad
 * build. The timeout is the escape hatch for the other case: if the BROKER is
 * down, that is not this firmware's fault, and rolling back over someone else's
 * outage would be its own bug.
 */
#define OTA_CONFIRM_TIMEOUT_MS 120000

void confirmOta() {
  if (g_otaConfirmed) return;

  const esp_partition_t *running = esp_ota_get_running_partition();
  esp_ota_img_states_t st;
  if (esp_ota_get_state_partition(running, &st) == ESP_OK &&
      st == ESP_OTA_IMG_PENDING_VERIFY) {
    esp_ota_mark_app_valid_cancel_rollback();
    Serial.println("OTA image confirmed good - rollback cancelled");
  }
  g_otaConfirmed = true;
}

/* Per-LED state for the impulse mode. Sparkle and confetti have to remember
 * which pixels are lit and how far they have faded; everything else in the
 * engine is a pure function of (p, t). */
uint8_t g_spark[MAX_LEDS];
uint8_t g_sparkHue[MAX_LEDS];


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

/*
 * An OTA request, deferred to loop().
 *
 * The first attempt ran the update inside the MQTT callback and it did not
 * work: the download never completed and the broker logged the device as
 * "exceeded timeout". Two reasons, both fatal on their own.
 *
 * The callback runs several frames deep on the Arduino loop task's 8 KB stack,
 * and HTTPClient plus Update on top of that is not a comfortable fit. And
 * because the callback blocks for the length of the download, mqtt.loop() is
 * never called, so the 15-second keepalive expires mid-transfer and the broker
 * drops the connection out from under it - which also meant the failure report
 * had nowhere to go, and the whole thing failed silently.
 *
 * So the callback does the one thing callbacks should: it writes down what was
 * asked for and returns.
 */
String pendingOta = "";

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
// LED hardware configuration
// ===================
/*
 * Every supported (chipset, pin) pair, instantiated so a runtime value can
 * choose one.
 *
 * This looks like brute force because it is. FastLED's addLeds is a template
 * over chipset, pin and colour order, so there is no way to hand it an int
 * from a config payload. The alternative - a sketch per strip - moves the
 * duplication somewhere worse, because then every engine fix has to be applied
 * once per strip and flashed to the right board.
 *
 * Colour order is handled separately below: folding it in as well would triple
 * this table for a setting that has been GRB on every strip so far.
 */
#define STRIP_PINS(CHIP)                                                        case 2:  FastLED.addLeds<CHIP, 2,  GRB>(leds, numLeds); return true;          case 4:  FastLED.addLeds<CHIP, 4,  GRB>(leds, numLeds); return true;          case 5:  FastLED.addLeds<CHIP, 5,  GRB>(leds, numLeds); return true;          case 12: FastLED.addLeds<CHIP, 12, GRB>(leds, numLeds); return true;          case 13: FastLED.addLeds<CHIP, 13, GRB>(leds, numLeds); return true;          case 14: FastLED.addLeds<CHIP, 14, GRB>(leds, numLeds); return true;          case 16: FastLED.addLeds<CHIP, 16, GRB>(leds, numLeds); return true;          case 17: FastLED.addLeds<CHIP, 17, GRB>(leds, numLeds); return true;          case 18: FastLED.addLeds<CHIP, 18, GRB>(leds, numLeds); return true;          case 19: FastLED.addLeds<CHIP, 19, GRB>(leds, numLeds); return true;          case 21: FastLED.addLeds<CHIP, 21, GRB>(leds, numLeds); return true;          case 22: FastLED.addLeds<CHIP, 22, GRB>(leds, numLeds); return true;          case 23: FastLED.addLeds<CHIP, 23, GRB>(leds, numLeds); return true;          case 25: FastLED.addLeds<CHIP, 25, GRB>(leds, numLeds); return true;          case 26: FastLED.addLeds<CHIP, 26, GRB>(leds, numLeds); return true;          case 27: FastLED.addLeds<CHIP, 27, GRB>(leds, numLeds); return true;          case 32: FastLED.addLeds<CHIP, 32, GRB>(leds, numLeds); return true;          case 33: FastLED.addLeds<CHIP, 33, GRB>(leds, numLeds); return true;

bool applyLedConfig() {
  if (numLeds < 1)        numLeds = 1;
  if (numLeds > MAX_LEDS) numLeds = MAX_LEDS;

  if (ledType == "WS2815" || ledType == "WS2812B" || ledType == "WS2812") {
    switch (ledPin) { STRIP_PINS(WS2812B) }
  } else if (ledType == "WS2811") {
    switch (ledPin) { STRIP_PINS(WS2811) }
  } else if (ledType == "SK6812") {
    switch (ledPin) { STRIP_PINS(SK6812) }
  } else {
    Serial.print("Unknown LED type '"); Serial.print(ledType);
    Serial.println("', falling back to WS2812B timing");
    switch (ledPin) { STRIP_PINS(WS2812B) }
  }

  Serial.print("Pin "); Serial.print(ledPin);
  Serial.println(" is not in the supported set - add it to STRIP_PINS");
  return false;
}

// ===================
// Config persistence
// ===================
/*
 * Cached in NVS so a strip that reboots comes back looking like itself.
 *
 * This matters more than it sounds. Once the length lives on the server, a
 * strip that boots while the Pi is down has no idea how long it is - and a
 * strip that guesses short leaves half of itself dark with no error anywhere.
 * The cache means the server is needed to CHANGE the configuration, never to
 * restore it.
 */
void loadConfig() {
  prefs.begin("lumina", true);
  numLeds  = prefs.getInt("count",  DEFAULT_COUNT);
  ledPin   = prefs.getInt("pin",    DEFAULT_PIN);
  ledType  = prefs.getString("type",  DEFAULT_TYPE);
  ledOrder = prefs.getString("order", DEFAULT_ORDER);
  prefs.end();

  Serial.print("Config: "); Serial.print(numLeds);
  Serial.print(" LEDs, pin "); Serial.print(ledPin);
  Serial.print(", "); Serial.print(ledType);
  Serial.print(" "); Serial.println(ledOrder);
}

/* Returns true if anything actually changed. */
bool saveConfig(int count, int pin, String type, String order) {
  bool changed = (count != numLeds) || (pin != ledPin) ||
                 (type != ledType)  || (order != ledOrder);
  if (!changed) return false;

  prefs.begin("lumina", false);
  prefs.putInt("count", count);
  prefs.putInt("pin", pin);
  prefs.putString("type", type);
  prefs.putString("order", order);
  prefs.end();
  return true;
}

// ===================
// Status Indicator (LED 0)
// ===================
void showStatus(CRGB color) {
  fill_solid(leds, numLeds, CRGB::Black);
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
  fill_solid(leds, numLeds, CRGB(currentR, currentG, currentB));
  FastLED.setBrightness(map(currentBrightness, 0, 100, 0, 255));
  FastLED.show();
}

// ===================
// The recipe engine
// ===================
/*
 * An effect as data, so that adding one does not mean touching this file.
 *
 * The twelve compiled effects below are not twelve different things. Each one
 * answers the same two questions, once per LED per frame:
 *
 *   1. what colour is this LED?   -> pick a point in a palette
 *   2. how bright is it?          -> a number from 0 to 1
 *
 * Aurora and Ocean are literally the same effect with different palettes and
 * numbers - both drift a colour band along the strip while a slow sine, phased
 * per LED, moves the brightness. Chase and Cylon are one bright blob with
 * different motion. Sparkle and Confetti are one impulse-and-decay with
 * different colour sources.
 *
 * So a recipe is a palette plus two slots, and the whole engine is:
 *
 *   for each LED:  colour = palette(sample(p, t)) * level(p, t)
 *
 * POSITION IS NORMALISED. p = i / (n - 1), so 0 is the start of the strip and 1
 * is the end whatever its length. That is the only place the LED count is used,
 * and it is what lets an effect authored once look the same on a 30-LED desk
 * strip and a 173-LED wall strip - rather than a chase that crawls on one and
 * sprints on the other.
 *
 * WHAT THIS DELIBERATELY CANNOT DO: fire. effectFire() diffuses heat between
 * neighbouring pixels, so a pixel depends on its neighbours' previous values
 * rather than on (p, t) alone. That is a genuinely different kind of effect and
 * it stays compiled; bending the engine around one effect would cost more than
 * it saves.
 */
static inline float frac01(float x) { return x - floorf(x); }

/* Palette lookup, wrapping. Circular so a scrolling palette loops without a
 * seam - a linear ramp would jump from the last stop back to the first. */
static inline CRGB palStop(int i) {
  return g_recipe.palIsDevice[i] ? CRGB(currentR, currentG, currentB)
                                 : g_recipe.pal[i];
}

CRGB paletteLookup(float x) {
  if (g_recipe.palN == 0) return CRGB::Black;
  if (g_recipe.palN == 1) return palStop(0);

  float f = frac01(x) * g_recipe.palN;
  int   i = (int)f;
  float m = f - i;
  const CRGB a = palStop(i % g_recipe.palN);
  const CRGB b = palStop((i + 1) % g_recipe.palN);
  return CRGB(a.r + (int)((b.r - a.r) * m),
              a.g + (int)((b.g - a.g) * m),
              a.b + (int)((b.b - a.b) * m));
}

float sampleAt(float p, float t, int i) {
  const Recipe &r = g_recipe;
  switch (r.sMode) {
    case S_POSITION: return p * r.sSpan;
    case S_SCROLL:   return p * r.sSpan + t * r.sSpeed;
    case S_NOISE:
      /* Morph, essentially: a smooth noise field read along the strip and
       * drifting in time. This is what most of LIFX's ambient themes are. */
      return inoise8((uint16_t)(p * r.sScale * 256),
                     (uint16_t)(t * r.sSpeed * 256)) / 255.0f;
    case S_RANDOM:   return g_sparkHue[i] / 255.0f;
    case S_FIXED:
    default:         return r.sAt + t * r.sSpeed;
  }
}

float levelAt(float p, float t, int i) {
  const Recipe &r = g_recipe;
  switch (r.lMode) {
    case L_WAVE: {
      /* DETUNE IS WHAT MAKES THIS LOOK ALIVE. With every LED on the same period
       * the strip breathes in unison, which reads as cheap. The original aurora
       * varied the period per LED - beatsin8(3 + (i % 4), ...) - and that small
       * dissonance is the whole difference between shimmer and a pulse. */
      float period = 1.0f + r.lDetune * (i % 5) * 0.25f;
      float phase  = t * r.lSpeed / period + p * r.lPhase;
      float v      = sin8((uint8_t)(frac01(phase) * 255)) / 255.0f;
      return r.lMin + (r.lMax - r.lMin) * v;
    }
    case L_BLOB: {
      float pos = r.lPingPong
                  ? fabsf(frac01(t * r.lSpeed) * 2.0f - 1.0f)   /* triangle: cylon */
                  : frac01(t * r.lSpeed);                        /* sawtooth: chase */
      float d = fabsf(p - pos);
      if (d > r.lWidth) {
        float tail = (d - r.lWidth) / fmaxf(r.lTrail, 0.001f);
        return tail >= 1.0f ? r.lMin : r.lMax * (1.0f - tail);
      }
      return r.lMax;
    }
    case L_IMPULSE: return r.lMin + (r.lMax - r.lMin) * (g_spark[i] / 255.0f);
    case L_SQUARE:  return (frac01(t * r.lSpeed) < 0.5f) ? r.lMax : r.lMin;
    case L_FLICKER: return r.lMin + (r.lMax - r.lMin) * (random8() / 255.0f);
    case L_SOLID:
    default:        return r.lMax;
  }
}

void runRecipe() {
  const Recipe &r = g_recipe;
  float t = millis() / 1000.0f;

  /* Impulse state advances once per frame, not once per LED. */
  if (r.lMode == L_IMPULSE) {
    for (int i = 0; i < numLeds; i++) g_spark[i] = (uint8_t)(g_spark[i] * r.lDecay);
    if (random8() < (uint8_t)(r.lRate * 255)) {
      int i = random16(numLeds);
      g_spark[i] = 255;
      g_sparkHue[i] = random8();
    }
  }

  for (int i = 0; i < numLeds; i++) {
    float p = (numLeds > 1) ? (float)i / (numLeds - 1) : 0.0f;
    CRGB  c = paletteLookup(sampleAt(p, t, i));
    float v = levelAt(p, t, i);
    if (v < 0) v = 0;
    if (v > 1) v = 1;
    c.nscale8_video((uint8_t)(v * 255));
    leds[i] = c;
  }
  FastLED.show();
}

static SampleMode parseSample(const char *m) {
  if (!m) return S_FIXED;
  if (!strcmp(m, "position")) return S_POSITION;
  if (!strcmp(m, "scroll"))   return S_SCROLL;
  if (!strcmp(m, "noise"))    return S_NOISE;
  if (!strcmp(m, "random"))   return S_RANDOM;
  return S_FIXED;
}

static LevelMode parseLevel(const char *m) {
  if (!m) return L_SOLID;
  if (!strcmp(m, "wave"))    return L_WAVE;
  if (!strcmp(m, "blob"))    return L_BLOB;
  if (!strcmp(m, "impulse")) return L_IMPULSE;
  if (!strcmp(m, "square"))  return L_SQUARE;
  if (!strcmp(m, "flicker")) return L_FLICKER;
  return L_SOLID;
}

bool parseRecipe(JsonObject j) {
  Recipe r;

  JsonArray pal = j["palette"];
  if (pal.isNull() || pal.size() == 0) {
    Serial.println("recipe: no palette");
    return false;
  }
  for (JsonVariant stop : pal) {
    if (r.palN >= MAX_PALETTE) break;
    if (stop.is<const char*>()) {
      /* "device" - resolved at render time, not here, so that changing the
       * colour takes effect without re-sending the recipe. */
      if (!strcmp(stop.as<const char*>(), "device")) {
        r.palIsDevice[r.palN] = true;
        r.pal[r.palN++] = CRGB::White;    /* only used if the string is wrong */
      }
      continue;
    }
    JsonArray c = stop.as<JsonArray>();
    if (c.isNull() || c.size() < 3) continue;
    r.palIsDevice[r.palN] = false;
    r.pal[r.palN++] = CRGB(c[0].as<int>(), c[1].as<int>(), c[2].as<int>());
  }
  if (r.palN == 0) return false;

  JsonObject sm = j["sample"];
  if (!sm.isNull()) {
    r.sMode  = parseSample(sm["mode"]);
    r.sAt    = sm["at"]    | r.sAt;
    r.sSpeed = sm["speed"] | r.sSpeed;
    r.sSpan  = sm["span"]  | r.sSpan;
    r.sScale = sm["scale"] | r.sScale;
  }

  JsonObject lv = j["level"];
  if (!lv.isNull()) {
    r.lMode     = parseLevel(lv["mode"]);
    r.lMin      = lv["min"]      | r.lMin;
    r.lMax      = lv["max"]      | r.lMax;
    r.lSpeed    = lv["speed"]    | r.lSpeed;
    r.lPhase    = lv["phase"]    | r.lPhase;
    r.lDetune   = lv["detune"]   | r.lDetune;
    r.lWidth    = lv["width"]    | r.lWidth;
    r.lTrail    = lv["trail"]    | r.lTrail;
    r.lRate     = lv["rate"]     | r.lRate;
    r.lDecay    = lv["decay"]    | r.lDecay;
    r.lPingPong = lv["pingpong"] | r.lPingPong;
  }

  r.frameMs = j["frame_ms"] | 20;
  if (r.frameMs < 5)   r.frameMs = 5;
  if (r.frameMs > 500) r.frameMs = 500;

  g_recipe = r;
  g_haveRecipe = true;
  memset(g_spark, 0, sizeof(g_spark));
  return true;
}

// ===================
// Effects
// ===================

// CLASSICS
void effectRainbow() {
  fill_rainbow(leds, numLeds, effectHue, 7);
  FastLED.show();
  effectHue++;
}

void effectBreathing() {
  uint8_t breath = beatsin8(12, 20, 255);
  fill_solid(leds, numLeds, CRGB(currentR, currentG, currentB));
  FastLED.setBrightness(map(breath * currentBrightness / 100, 0, 255, 0, 255));
  FastLED.show();
}

void effectChase() {
  fadeToBlackBy(leds, numLeds, 40);
  leds[effectPos] = CRGB(currentR, currentG, currentB);
  FastLED.show();
  effectPos++;
  if (effectPos >= numLeds) effectPos = 0;
}

void effectSparkle() {
  fadeToBlackBy(leds, numLeds, 20);
  if (random8() < 80) {
    leds[random16(numLeds)] = CRGB(currentR, currentG, currentB);
  }
  FastLED.show();
}

// PARTY
void effectFire() {
  // Fire simulation - heat rises from bottom
  static byte heat[MAX_LEDS];

  // Cool down
  for (int i = 0; i < numLeds; i++) {
    heat[i] = qsub8(heat[i], random8(0, 35));
  }

  // Heat rises
  for (int i = numLeds - 1; i >= 2; i--) {
    heat[i] = (heat[i - 1] + heat[i - 2] + heat[i - 2]) / 3;
  }

  // Random sparks at bottom
  if (random8() < 120) {
    heat[random8(7)] = qadd8(heat[random8(7)], random8(160, 255));
  }

  // Map heat to colors
  for (int i = 0; i < numLeds; i++) {
    leds[i] = HeatColor(heat[i]);
  }
  FastLED.show();
}

void effectConfetti() {
  fadeToBlackBy(leds, numLeds, 10);
  leds[random16(numLeds)] += CHSV(effectHue + random8(64), 200, 255);
  effectHue++;
  FastLED.show();
}

void effectCylon() {
  fadeToBlackBy(leds, numLeds, 20);
  leds[effectPos] = CRGB(currentR, currentG, currentB);
  FastLED.show();

  effectPos += effectDirection;
  if (effectPos >= numLeds - 1 || effectPos <= 0) {
    effectDirection *= -1;
  }
}

void effectStrobe() {
  static bool on = false;
  if (on) {
    fill_solid(leds, numLeds, CRGB(currentR, currentG, currentB));
  } else {
    fill_solid(leds, numLeds, CRGB::Black);
  }
  on = !on;
  FastLED.show();
}

// CHILL / AMBIENT
void effectOcean() {
  for (int i = 0; i < numLeds; i++) {
    uint8_t wave = beatsin8(6 + (i % 5), 100, 255, 0, i * 10);
    leds[i] = CRGB(0, wave / 3, wave);
  }
  FastLED.show();
}

void effectAurora() {
  for (int i = 0; i < numLeds; i++) {
    uint8_t hue = effectHue + (i * 2);
    uint8_t brightness = beatsin8(3 + (i % 4), 50, 255, 0, i * 5);
    leds[i] = CHSV(96 + (sin8(hue) / 8), 255, brightness);  // Greens and blues
  }
  effectHue++;
  FastLED.show();
}

void effectCandle() {
  for (int i = 0; i < numLeds; i++) {
    uint8_t flicker = random8(180, 255);
    leds[i] = CRGB(flicker, flicker / 3, 0);  // Warm orange/yellow
  }
  FastLED.show();
}

// HOLIDAY
void effectChristmas() {
  fadeToBlackBy(leds, numLeds, 5);
  // Alternating red and green with occasional twinkle
  for (int i = 0; i < numLeds; i++) {
    if (leds[i].getLuma() < 20) {
      leds[i] = (i % 2 == 0) ? CRGB(50, 0, 0) : CRGB(0, 50, 0);
    }
  }
  // Random twinkle
  if (random8() < 60) {
    int pos = random16(numLeds);
    leds[pos] = (pos % 2 == 0) ? CRGB::Red : CRGB::Green;
  }
  FastLED.show();
}

void effectUSA() {
  int section = numLeds / 3;
  for (int i = 0; i < numLeds; i++) {
    if (i < section) {
      leds[i] = CRGB::Red;
    } else if (i < section * 2) {
      leds[i] = CRGB::White;
    } else {
      leds[i] = CRGB::Blue;
    }
  }
  // Add shimmer
  leds[random16(numLeds)].fadeToBlackBy(random8(50, 150));
  FastLED.show();
}

void runEffect() {
  /* A recipe takes precedence over the compiled effects of the same name, so
   * an effect can be moved into data one at a time and compared side by side
   * against the version it is replacing. */
  if (g_haveRecipe) {
    runRecipe();
    delay(g_recipe.frameMs);
    return;
  }

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
// Over-the-air update
// ===================
/*
 * Triggered by MQTT: {"ota": "http://192.168.1.55:8080/fw/led_controller_3.bin"}
 *
 * The new image is written to the app slot that is not running, and the
 * bootloader switches over on reset.
 *
 * A download that fails leaves the current firmware untouched, because nothing
 * has been switched. An image that DOES install but then misbehaves is covered
 * separately, by the deferred rollback at the top of this file - the image stays
 * on probation until it has reached the broker or simply survived two minutes.
 *
 * The strip is the progress bar. These controllers are mounted in places where
 * a serial cable is not a realistic way to find out whether an update is
 * working, so it says so in blue, from across the room.
 */
void otaProgress(int done, int total) {
  if (!ledsReady || total <= 0) return;
  int lit = (int)((int64_t)done * numLeds / total);
  fill_solid(leds, numLeds, CRGB::Black);
  for (int i = 0; i < lit && i < numLeds; i++) leds[i] = CRGB(0, 40, 120);
  FastLED.setBrightness(255);
  FastLED.show();
}

void handleOta(String url) {
  Serial.print("OTA starting: ");
  Serial.println(url);
  Serial.print("Free heap: ");
  Serial.println(ESP.getFreeHeap());

  /* Say so before the download starts - on a slow link this is several seconds
   * of apparently nothing happening. */
  if (ledsReady) {
    fill_solid(leds, numLeds, CRGB::Black);
    for (int i = 0; i < 5 && i < numLeds; i++) leds[i] = CRGB(0, 40, 120);
    FastLED.setBrightness(255);
    FastLED.show();
  }

  JsonDocument note;
  note["device_id"] = device_id;
  note["ota"] = "started";
  note["url"] = url;
  String out; serializeJson(note, out);
  mqtt.publish(TOPIC_STATE.c_str(), out.c_str());

  /*
   * Disconnect deliberately rather than being dropped.
   *
   * The transfer takes longer than the 15-second keepalive and nothing is going
   * to service mqtt.loop() while it runs, so the connection is lost either way.
   * Ending it on purpose means the broker logs a clean disconnect instead of a
   * timeout, and loop() reconnects afterwards if the update did not happen.
   */
  mqtt.disconnect();

  WiFiClient otaClient;
  httpUpdate.onProgress(otaProgress);
  httpUpdate.rebootOnUpdate(true);

  /* The global httpUpdate carries an 8-second HTTP client timeout, set in its
   * constructor and not adjustable afterwards. Fine for a fetch off the Pi on
   * the same LAN; if a strip at the far end of the house on a weak signal ever
   * trips it, the fix is a local HTTPUpdate instance rather than the global. */
  t_httpUpdate_return ret = httpUpdate.update(otaClient, url);

  /* Only reached when the update did NOT happen - a success reboots inside
   * update() and never returns here. */
  String reason = (ret == HTTP_UPDATE_NO_UPDATES)
                    ? "server said no update"
                    : httpUpdate.getLastErrorString();

  Serial.print("OTA failed: ");
  Serial.println(reason);
  Serial.print("Free heap after: ");
  Serial.println(ESP.getFreeHeap());

  /* The broker connection was given up before the transfer; get it back so the
   * failure can actually be reported rather than disappearing. */
  if (!mqtt.connected() && mqtt.connect(device_id.c_str())) {
    mqtt.subscribe(TOPIC_SET.c_str());
  }

  JsonDocument fail;
  fail["device_id"] = device_id;
  fail["ota"] = "failed";
  fail["error"] = reason;
  String fout; serializeJson(fail, fout);
  mqtt.publish(TOPIC_STATE.c_str(), fout.c_str());

  /* Red for a beat so a failed update is visible without reading a log. */
  if (ledsReady) {
    for (int i = 0; i < 3; i++) {
      fill_solid(leds, numLeds, CRGB::Red); FastLED.show(); delay(200);
      fill_solid(leds, numLeds, CRGB::Black); FastLED.show(); delay(200);
    }
    updateLeds();
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

  /* OTA first, and it does not return on success - the device reboots into
   * the new image from inside handleOta(). Anything else in the same payload
   * would be silently dropped, so it is sent on its own. */
  if (doc["ota"].is<const char*>()) {
    pendingOta = doc["ota"].as<String>();
    Serial.print("OTA queued: ");
    Serial.println(pendingOta);
    return;
  }

  /*
   * Hardware configuration, then restart.
   *
   * FastLED has no way to un-register a strip, so re-running addLeds against a
   * different pin or length in a live sketch leaves the old controller behind
   * driving the old pin. Persisting and rebooting is two seconds of darkness
   * and avoids the entire question.
   */
  if (doc["config"].is<JsonObject>()) {
    JsonObject c = doc["config"];
    int    count = c["led_count"] | numLeds;
    int    pin   = c["pin"]       | ledPin;
    String type  = c["type"].is<const char*>()  ? c["type"].as<String>()  : ledType;
    String order = c["order"].is<const char*>() ? c["order"].as<String>() : ledOrder;

    Serial.println("--- CONFIG ---");
    if (saveConfig(count, pin, type, order)) {
      Serial.println("Configuration changed, restarting");
      if (ledsReady) {
        fill_solid(leds, numLeds, CRGB(0, 40, 120));
        FastLED.setBrightness(255);
        FastLED.show();
      }
      delay(400);
      ESP.restart();
    }
    Serial.println("Configuration unchanged");
    return;
  }

  // Handle power command
  if (doc.containsKey("power")) {
    powerOn = doc["power"].as<bool>();

    Serial.println("--- LED ACTION ---");
    Serial.print("Power: ");
    Serial.println(powerOn ? "ON" : "OFF");

    if (!powerOn) {
      fill_solid(leds, numLeds, CRGB::Black);
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

    /* A recipe with a "device" stop reads currentR/G/B every frame, so it picks
     * this up on its own. Only a solid colour needs pushing out here. */
    if (!g_haveRecipe) updateLeds();
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

  /*
   * An effect sent as data.
   *
   * Stored in NVS as the raw JSON it arrived as, rather than as unpacked
   * fields. Two reasons: the format will grow, and a device that boots before
   * the server is up should come back looking like itself rather than dark.
   */
  if (doc["recipe"].is<JsonObject>()) {
    if (parseRecipe(doc["recipe"].as<JsonObject>())) {
      String raw;
      serializeJson(doc["recipe"], raw);
      prefs.begin("lumina", false);
      prefs.putString("recipe", raw);
      prefs.putString("effect", doc["effect"] | "recipe");
      prefs.end();

      currentEffect = doc["effect"] | "recipe";
      Serial.println("--- LED ACTION ---");
      Serial.print("Recipe loaded: ");
      Serial.print(g_recipe.palN);
      Serial.print(" palette stops, sample=");
      Serial.print((int)g_recipe.sMode);
      Serial.print(" level=");
      Serial.println((int)g_recipe.lMode);
    } else {
      Serial.println("Recipe rejected - keeping the current effect");
    }
    Serial.println("=======================================");
    publishState();
    return;
  }

  // Handle effect command
  if (doc.containsKey("effect")) {
    currentEffect = doc["effect"].as<String>();

    Serial.println("--- LED ACTION ---");
    Serial.print("Start effect: ");
    Serial.println(currentEffect);

    /* A named effect supersedes a loaded recipe. Without this the recipe would
     * keep rendering and the buttons would appear to do nothing. */
    g_haveRecipe = false;
    prefs.begin("lumina", false);
    prefs.remove("recipe");
    prefs.putString("effect", currentEffect);
    prefs.end();

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
  doc["fw"] = FW_VERSION;
  doc["capabilities"][0] = "color";
  doc["capabilities"][1] = "brightness";
  doc["capabilities"][2] = "effects";
  doc["capabilities"][3] = "ota";
  doc["capabilities"][4] = "config";

  /* What this strip currently believes it is. A device announcing a length the
   * server has no record of is how a newly built strip gets registered, and how
   * a mismatch gets noticed instead of silently persisting. */
  doc["config"]["led_count"] = numLeds;
  doc["config"]["pin"]       = ledPin;
  doc["config"]["type"]      = ledType;
  doc["config"]["order"]     = ledOrder;

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
      confirmOta();
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
  g_bootMs = millis();
  delay(1000);

  // Generate device ID from chip ID
  device_id = getChipId();

  Serial.println();
  Serial.println("================================");
  Serial.println("Lumina IoT - LED Controller");
  Serial.print("Device ID: ");
  Serial.println(device_id);
  Serial.println("================================");

  // Initialize FastLED from stored configuration
  loadConfig();
  ledsReady = applyLedConfig();
  if (!ledsReady) {
    /* An unusable pin would otherwise mean a device with no status indicator
     * and no way to say why. Fall back to the default so it can at least boot,
     * announce itself and be reconfigured over the air. */
    Serial.println("Falling back to default pin so the strip can still report in");
    ledPin = DEFAULT_PIN;
    ledsReady = applyLedConfig();
  }
  FastLED.setBrightness(255);
  fill_solid(leds, numLeds, CRGB::Black);
  FastLED.show();
  Serial.print("LEDs initialized: "); Serial.print(numLeds);
  Serial.print(" on pin "); Serial.println(ledPin);

  /* Restore whatever was last running. A strip that reboots at 3am should come
   * back as itself without waiting for the server to notice and re-send. */
  prefs.begin("lumina", true);
  String savedEffect = prefs.getString("effect", "none");
  String savedRecipe = prefs.getString("recipe", "");
  prefs.end();

  if (savedRecipe.length()) {
    JsonDocument rd;
    if (!deserializeJson(rd, savedRecipe) && parseRecipe(rd.as<JsonObject>())) {
      currentEffect = savedEffect;
      Serial.print("Restored recipe: "); Serial.println(savedEffect);
    } else {
      Serial.println("Stored recipe would not parse - ignoring it");
    }
  } else if (savedEffect != "none") {
    currentEffect = savedEffect;
    Serial.print("Restored effect: "); Serial.println(savedEffect);
  }

  // Set up topics based on device ID
  TOPIC_SET = String("lights/") + device_id + "/set";
  TOPIC_STATE = String("lights/") + device_id + "/state";

  // Connect to WiFi
  connectWiFi();

  /* PubSubClient's default buffer is 256 bytes, which a config payload can
   * already brush against and an effect recipe will exceed outright. An
   * oversized message is dropped silently at the library boundary - no error,
   * no callback - so this is raised before anything depends on it. */
  mqtt.setBufferSize(2048);

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

  /* The broker being unreachable is not this firmware's fault, so surviving
   * long enough also counts as proof. See confirmOta(). */
  if (!g_otaConfirmed && millis() - g_bootMs > OTA_CONFIRM_TIMEOUT_MS) confirmOta();

  /* Deferred from the MQTT callback - see pendingOta. Cleared before the call,
   * so a request that somehow fails catastrophically is not retried forever. */
  if (pendingOta.length()) {
    String url = pendingOta;
    pendingOta = "";
    handleOta(url);
  }

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
