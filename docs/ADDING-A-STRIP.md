# Adding a strip of lights

Start to finish, assuming you have forgotten everything about this project.

The short version: **wire it, flash it once over USB, then configure it from the
web UI.** The only step that needs a cable is the flash, and only the first one.

---

## What you need

| | |
|---|---|
| An **ESP32 dev board** | Any of them. The desk and wall strips are plain ESP32s with a CP210x USB chip |
| An **addressable LED strip** | WS2815, WS2812B, WS2812, WS2811 or SK6812 |
| A **power supply** for the strip | Sized below. **Not** the ESP32's USB port |
| A **USB cable** | For the first flash only |

**Power is the part people get wrong.** A WS2815 draws roughly 12 mA per LED at
full white. A 173-LED strip is therefore about 2 A at 12 V, and 300 LEDs is
closer to 3.5 A. The ESP32's USB port can supply none of that — it powers the
microcontroller only. Get a supply rated comfortably above your worst case,
because "works until you set it to white" is a miserable fault to chase.

---

## 1. Wire it

```
ESP32                 LED strip
-----                 ---------
GPIO 5      ------>   Data In
GND         ------>   GND

12V PSU               LED strip
-------               ---------
+12V        ------>   +12V
GND         ------>   GND
```

**The two grounds must be connected.** ESP32 ground and power-supply ground tie
together. Without that shared reference the data line has nothing to be measured
against, and the symptom is not a dead strip — it is a strip that flickers,
shows wrong colours, or works until you touch something. It looks like a
software fault and it is not.

GPIO 5 is only the default a fresh board comes up on. Any pin in the
`STRIP_PINS` macro works — 2, 4, 5, 12, 13, 14, 16–19, 21–23, 25–27, 32, 33 —
and you tell the server which one you used *after* flashing. Nothing about the
pin is baked into the image.

---

## 2. Put your WiFi details in `secrets.h`

```bash
cd firmware/led_controller
cp secrets.h.example secrets.h
```

Fill in the SSID, the password, and the broker's address — the Pi. This file is
gitignored and never leaves your machine.

**There is nothing else to configure.** No device ID, no LED count, no name. The
board derives its own identity from the ESP32's chip ID, which is why two boards
flashed from the identical image do not collide.

---

## 3. Set the partition scheme — do not skip this

> **Tools → Partition Scheme → Minimal SPIFFS (1.9MB APP with OTA)**

This is the single easiest step to miss and the most annoying to discover later.
The default scheme leaves the build at about 84% of its app partition, and it
will stop fitting. More importantly the image needs two app slots for
over-the-air updates to work at all — get this wrong and you have signed up for
a cable every time, forever.

Board: **ESP32 Dev Module**.

---

## 4. Flash it, over USB

Plug the board into your computer and upload.

**This first flash has to be by cable and there is no way around it.** Over-the-
air updating arrived in the same firmware you are installing, so a board that
has never had it cannot receive it. Every update after this one is over the
network.

If you would rather not use the Arduino IDE:

```bash
arduino-cli compile --fqbn esp32:esp32:esp32:PartitionScheme=min_spiffs \
  --libraries ~/Documents/Arduino/libraries firmware/led_controller
arduino-cli upload -p COM5 --fqbn esp32:esp32:esp32:PartitionScheme=min_spiffs \
  firmware/led_controller
```

Libraries needed: PubSubClient, ArduinoJson, FastLED. Preferences and HTTPUpdate
come with the ESP32 core.

---

## 5. Watch it introduce itself

Open the serial monitor at 115200 and you should see:

```
================================
Lumina IoT - LED Controller
Device ID: A1B2C3D4              <- note this
================================
Config: 30 LEDs, pin 5, WS2815 GRB
LEDs initialized: 30 on pin 5
Colour order: GRB (native)
Connecting to WiFi
Connected! IP: 192.168.1.66
Connecting to MQTT broker at 192.168.1.55... connected!
Device announced to broker
```

**Thirty LEDs is expected and not a mistake.** A board that has never been told
what it is drives a conservative default, enough to run the boot indicator and
no assumption that anything longer is attached. Only the first few LEDs will
light. The next step fixes it.

Write down the **Device ID**. It is how you will recognise your new board among
the others.

---

## 6. Tell the server what it is

Open the dashboard, and the new device will be there under its chip ID.

Expand **Hardware_Config** on its card and set:

| Field | |
|---|---|
| **LED_Count** | How many LEDs are actually on the strip |
| **Data_Pin** | The GPIO you wired to Data In |
| **Chipset** | WS2815, WS2812B, WS2811 or SK6812 |
| **Colour_Order** | Almost always GRB. See below |

Hit **APPLY**. The strip goes blue for a moment and restarts — that is the form
doing what it said it would. FastLED cannot un-register a controller, so
changing a pin or a length in a live sketch would leave the old one still
driving the old pin. Restarting sidesteps the whole question and costs two
seconds.

It comes back at the right length and stays that way. The setting lives in the
device's own flash as well as in Postgres, so a strip that reboots at 3am comes
back as itself even with the server down. **The server is needed to change a
configuration, never to restore one.**

### If the colours are wrong

Red shows as green, or blue as red: that is colour order, and it varies by
manufacturer. Try RGB, then the others. Nothing is harmed by guessing.

---

## 7. Name it

Click the pencil next to the device ID and give it a name. That is the name that
shows up on the desk display too.

---

## 8. Done — and never a cable again

The strip now has every effect in the database, and so will every effect you
add later, without touching this board again.

To update its firmware from here:

```bash
# stage a build where the strip can fetch it
arduino-cli compile --fqbn esp32:esp32:esp32:PartitionScheme=min_spiffs \
  --libraries ~/Documents/Arduino/libraries \
  --output-dir /tmp/build firmware/led_controller
scp /tmp/build/led_controller.ino.bin \
  kevin@192.168.1.55:~/Documents/lumina-iot/firmware/images/led_controller_v10.bin
```

Then pick it from **Firmware_Update** on the device's card, or:

```bash
curl -X POST "http://192.168.1.55:8001/devices/A1B2C3D4/ota?file=led_controller_v10.bin"
```

It downloads, shows a blue progress bar along the strip, reboots, and
re-announces. About thirty seconds.

---

## The one rule

> **Prove firmware on a strip you can physically reach, before sending it to one
> you cannot.**

There is **no working rollback**. The ESP32 supports it, the Arduino core
compiles it in, and it was implemented here — and then tested with a
deliberately broken image, which crash-looped until a USB cable was attached.
The previous firmware was never restored.

So a bad build means physically reaching that board. The desk strip
(`D4EC67C8`) sits on a desk with a cable next to it and is the bench. Mounted
strips only ever receive a build that has already run there.

A failed *download* is safe — nothing is switched, and the running firmware is
untouched. It is an image that installs and then misbehaves that costs you a
ladder.

---

## When it does not show up

Work down this list; it is roughly in order of likelihood.

**Nothing on serial at all.** Wrong COM port, or the board is not powered. On
Windows, Device Manager will name the port; a Silicon Labs CP210x or a CH340 is
almost certainly your board.

**It prints but never connects to WiFi.** Check `secrets.h` — and check the
band. These are 2.4 GHz only, and a router advertising one name for both bands
will happily hand out a 5 GHz association the ESP32 cannot use.

**WiFi connects, broker does not.** Check the broker address in `secrets.h` and
that Mosquitto is running: `docker compose ps` on the Pi. The board retries
every five seconds in the background and restarts itself after ten minutes of
failure, so it will recover on its own once the broker returns.

**It announces but no card appears.** Reload the dashboard. If it is still
missing, `curl http://192.168.1.55:8001/devices` — if it is in there, the
problem is the UI; if it is not, the API did not process the announce, and
`docker compose logs api` will say why.

**Only the first few LEDs light.** That is step 6, not yet done.

**Everything works but the strip flickers.** Grounds. See step 1.

More symptoms, including ones that look like software faults and are not, in
[TROUBLESHOOTING.md](TROUBLESHOOTING.md).
