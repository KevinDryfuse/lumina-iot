# Lumina ESP32 - LED Controller Firmware

ESP32 firmware for controlling WS2815 LED strips via MQTT. Pairs with the [lumina-iot](../lumina-iot) server.

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

## Effects

| Category | Effects |
|----------|---------|
| **Standard** | `rainbow`, `breathing`, `chase`, `sparkle` |
| **Party** | `fire`, `confetti`, `cylon`, `strobe` |
| **Ambient** | `ocean`, `aurora`, `candle` |
| **Holiday** | `christmas`, `usa` |

Use `"effect": "none"` to return to solid color mode.

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
