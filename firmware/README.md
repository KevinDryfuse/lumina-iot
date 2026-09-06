# Lumina ESP32 - LED Controller Firmware

ESP32 firmware for controlling WS2815 LED strips via MQTT. It pairs with the API
in the same repository — see [../docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md).

One image runs every strip. Length, data pin, chipset and colour order are not
compiled in: they arrive from the server over MQTT and are cached in NVS, so
flashing is a one-off and everything after it happens from the UI or over the
air.

## Hardware Requirements

- ESP32-D (ESP32-WROOM-32)
- BTF-LIGHTING WS2815 LED Strip (12V, 300 LEDs, dual signal)
- BTF-LIGHTING 12V 10A 120W Power Supply
- 4-pin connectors

## Arduino Libraries

Install these via Arduino IDE Library Manager:

1. **PubSubClient** (Nick O'Leary) - MQTT client
2. **ArduinoJson** (Benoit Blanchon) - JSON parser
3. **FastLED** (Daniel Garcia) - LED strip control

## Setup

1. Copy `led_controller/secrets.h.example` to `led_controller/secrets.h`
2. Edit `secrets.h` with your configuration:

```cpp
#define WIFI_SSID "your-wifi-ssid"
#define WIFI_PASSWORD "your-wifi-password"
#define MQTT_BROKER_IP "192.168.1.100"  // Your server's static IP
```

3. Open `led_controller/led_controller.ino` in Arduino IDE
4. Select your ESP32 board and port
5. Flash to ESP32

The device ID is auto-generated from the ESP32's unique chip ID (e.g., `A1B2C3D4`).

## Network Setup

For reliable connections, set a **DHCP reservation** in your router so your server always gets the same IP. This avoids hardcoding an IP that might change.

On the machine running Docker, find your IP:

**Windows:**
```
ipconfig
```

**Linux/Mac:**
```
ip addr
```

## LED Wiring (WS2815)

GPIO 5 below is only the default a device comes up on. Any pin in the
`STRIP_PINS` macro works — 2, 4, 5, 12, 13, 14, 16-19, 21-23, 25-27, 32, 33 —
and which one a particular strip uses is set from the UI afterwards.

```
ESP32          WS2815 Strip
-----          ------------
GPIO 5   -->   Data In (Green/White)
GND      -->   GND (also connect to PSU GND)

12V PSU        WS2815 Strip
-------        ------------
+12V     -->   +12V (Red)
GND      -->   GND (Black/Blue)
```

**Important:** Connect ESP32 GND to the same GND as the LED strip power supply.

## MQTT Topics

| Topic | Direction | Description |
|-------|-----------|-------------|
| `devices/announce` | ESP32 → Server | Device registration |
| `lights/{device_id}/set` | Server → ESP32 | Commands |
| `lights/{device_id}/state` | ESP32 → Server | State updates |

## Command Format

**Power On/Off:**
```json
{"power": true}
{"power": false}
```

**Set Color:**
```json
{"color": {"r": 255, "g": 0, "b": 128}}
```

**Set Brightness:**
```json
{"brightness": 75}
```

**Set Effect:**
```json
{"effect": "rainbow"}
```

**Hardware configuration** — persisted to NVS, and the device restarts to apply
it. FastLED cannot un-register a controller, so restarting is cheaper than the
alternative:
```json
{"config": {"led_count": 91, "pin": 5, "type": "WS2815", "order": "GRB"}}
```

**Firmware update** — sent on its own, because the device reboots into the new
image and anything else in the same payload would be dropped:
```json
{"ota": "http://192.168.1.55:8001/fw/led_controller_v5.bin"}
```

**An effect as data** — a palette and two slots, documented in
[../docs/RECIPES.md](../docs/RECIPES.md). Stored in NVS as the JSON it arrived
as, so a strip that reboots comes back as itself:
```json
{"effect": "ocean", "recipe": {"palette": [[0,40,90],[0,120,200]],
 "sample": {"mode": "position"}, "level": {"mode": "wave"}, "frame_ms": 20}}
```

Everything sent here has to fit in 2048 bytes: PubSubClient drops an oversized
message inside the library with no error and no callback.

## Effects

| Category | Effects |
|----------|---------|
| **Standard** | `rainbow`, `breathing`, `chase`, `sparkle` |
| **Party** | `fire`, `confetti`, `cylon`, `strobe` |
| **Ambient** | `ocean`, `aurora`, `candle` |
| **Holiday** | `christmas`, `usa` |

Use `"effect": "none"` to return to solid color mode.

These are the compiled effects, and a named effect clears any loaded recipe —
otherwise the recipe would keep rendering and the buttons would appear dead. A
recipe of the same name takes precedence over the compiled version, so the two
can be compared side by side. Fire stays compiled: it diffuses heat between
neighbouring pixels and cannot be written as a function of position and time.

## Troubleshooting

**Can't connect to WiFi:**
- Check credentials in `secrets.h`
- Make sure ESP32 is within WiFi range

**Can't connect to MQTT:**
- Verify server IP is correct and has a DHCP reservation
- Check that Mosquitto is running: `docker compose ps`
- Make sure firewall allows port 1883

**Device doesn't appear in UI:**
- Check Serial Monitor for connection status
- Verify MQTT broker is receiving messages: `docker compose logs mosquitto`
