# Lumina IoT

LED strips on the local network, driven from a browser. Four containers on one
machine — an MQTT broker, Postgres, a JSON API and an HTMX UI — and one firmware
image that runs every strip in the house.

Nothing about a particular strip is compiled into that image any more. Length,
data pin, chipset and colour order arrive from the server over MQTT and are
cached on the device; effects arrive as data rather than as names the firmware
had to know in advance. Both of those used to mean editing a sketch, and in
practice meant commenting out the last strip's length and hoping the right board
was plugged in.

The firmware lives here, in `firmware/led_controller/`, rather than in its own
repository, because the payload format is now a contract between `api/` and the
sketch. A contract split across two repositories lands as two commits that can
be deployed in either order, and the failure mode is a strip that goes dark and
does not say why.

## Running it

```bash
cp .env.example .env      # set SECRET_KEY, and FIRMWARE_BASE_URL if you want OTA
docker compose up -d
docker compose exec ui python scripts/create_user.py admin
```

The UI is on http://localhost:8000. Log in as the user you just created.

| Service | Port | What it is |
|---|---|---|
| `ui` | 8000 | Login, dashboard, effect studio. Talks to the API over HTTP and never touches MQTT |
| `api` | 8001 | Device state, MQTT, Postgres, firmware images. No authentication |
| `mosquitto` | 1883 | Broker. Anonymous, so devices need no credentials |
| `postgres` | 5432 | Users, devices, per-device state, stored effects |

The API's port is published on the host rather than kept inside the compose
network because devices fetch firmware images from it. Everything else about it
is internal.

The server needs a fixed address on the LAN — a DHCP reservation is the easiest
way — because each strip is flashed with the broker's IP in `secrets.h` and has
no way to be told a new one afterwards.

## Adding a strip

Flash `firmware/led_controller/led_controller.ino` once, with WiFi and broker
details in `secrets.h` (copy `secrets.h.example`). Everything after that is done
from the UI: the device announces itself on `devices/announce`, appears on the
dashboard, and the Hardware_Config panel on its card sets LED count, data pin,
chipset and colour order. Applying it restarts the strip, which the form says
out loud — FastLED cannot un-register a controller, so re-running `addLeds()` in
a live sketch would leave the old one driving the old pin.

A strip the server has never seen is believed: whatever it reports becomes the
record. A strip that already has a record is corrected instead, because it may
be a freshly flashed board that has come up on the conservative defaults of 30
LEDs on pin 5. The device caches the result in NVS, so the server is needed to
*change* a configuration, never to restore one — a strip that reboots at 3am
comes back as itself with the server down.

Supported pins are the eighteen in the `STRIP_PINS` macro (2, 4, 5, 12, 13, 14,
16–19, 21–23, 25–27, 32, 33); supported chipsets are WS2815, WS2812B, WS2812,
WS2811 and SK6812; the maximum length is 300 LEDs. That table is brute force,
because FastLED takes pin and chipset as C++ template parameters: every
supported combination is instantiated and one is chosen at boot. Adding a pin
means adding a line to the macro and pushing a build.

## Effects

An effect is a palette plus two slots — which colour each LED reads, and how
bright it is. The format, the modes and the reasoning behind them are in
[docs/RECIPES.md](docs/RECIPES.md), which is the single source of truth for the
payload both sides have to agree on.

Eighteen built-ins are seeded into Postgres on start-up: the twelve that used to
be compiled, translated into recipes, plus six theme palettes riding the same
motions. Seeding is insert-only, so a recipe tuned by hand in the studio
survives every redeploy; deleting the row restores the original on the next
start.

`/studio` in the UI reimplements the device's render maths in JavaScript on a
canvas. It exists because authoring an effect otherwise means change a number,
build, flash, walk over, squint — a loop slow enough that nobody would ever
write the twenty palettes the engine exists to make cheap. Pushing a recipe to a
strip and saving it under a name are separate buttons on purpose: an effect
being tuned is not yet an effect worth keeping.

Two things are worth knowing about where this has got to. The dashboard's effect
buttons still send *names*, which run the compiled effects on the device and
clear any loaded recipe; the seeded recipes are reached from the studio, or from
`POST /devices/{id}/recipe?name=<effect>`. And fire stays compiled, because it
diffuses heat between neighbouring pixels and so cannot be written as a function
of position and time.

## Firmware updates

Images are built with the Arduino IDE or `arduino-cli`, dropped into
`firmware/images/` — a bind mount, so `scp` is enough and no container has to be
rebuilt — served by the API at `/fw`, and pushed from the Firmware_Update
control on a device card or with `POST /devices/{id}/ota?file=<name>`. The
device downloads into the unused app slot, renders its own progress bar in blue
while it does, and reboots into the new image. `FIRMWARE_BASE_URL` has to be
configured rather than detected: the API sits on a bridged Docker network and
knows only its own 172.x address, which no ESP32 on the LAN can reach.

**An image that boots into a crash loop stays there.** The bootloader's rollback
support is compiled in, but the Arduino core marks a pending image valid during
`initArduino()`, before `setup()` ever runs, so nothing that fails after that
point is rolled back. The desk strip (`D4EC67C8`) is the bench: a build proves
itself there before it goes anywhere that needs a ladder.

`.bin` files are deliberately not committed. They are staged and served, not
versioned.

## The trust boundary

There is one, and it is the LAN. The API has no authentication, Mosquitto
accepts anonymous connections so that devices need no credentials, and firmware
images are neither signed nor access-controlled — anyone already on this network
could serve a strip an image of their own. Only the UI has logins, and those
exist to keep a household out of each other's lights rather than to keep anyone
off the network. Do not port-forward the API.

## Known seams

Colour order is stored, reported and offered as a dropdown, but the strip is
always driven as GRB: folding order into `STRIP_PINS` would triple a table that
exists for a setting no strip here has yet needed to change. The MCP server in
`mcp-server/` carries its own hardcoded list of effect names, so anything added
since is invisible to it. And there is no migration tool — columns added to an
existing table are applied by hand in `init_db()` with `ADD COLUMN IF NOT
EXISTS`.

## Hardware

ESP32-D (ESP32-WROOM-32), a WS2815 strip at 12V, and a 12V supply. Data to one
of the supported pins, and the ESP32's ground tied to the supply's ground.
Wiring detail and library versions are in
[firmware/README.md](firmware/README.md).

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — the pieces, and what happens
  between a click and a lit LED
- [docs/RECIPES.md](docs/RECIPES.md) — the effect format
- [CLAUDE.md](CLAUDE.md) — orientation for agents working in this repository

## License

MIT
