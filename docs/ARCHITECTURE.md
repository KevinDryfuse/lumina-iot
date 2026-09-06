# Architecture

Five things: a broker, a database, an API, a UI, and firmware. This page is what
each one is for, why the seams fall where they do, and what actually happens
between clicking a colour and a strip changing colour.

---

## The pieces

**Mosquitto** (`mosquitto/`, port 1883) is the only thing devices talk to. It
accepts anonymous connections, because a strip has nowhere good to keep a
credential and the network is already the trust boundary.

**Postgres** holds four tables — `users`, `devices`, `device_state`, `effects` —
defined in `api/src/db.py`. It is where anything that must outlive a container
restart lives: who can log in, which strips exist and how each is wired, what
each was last set to, and every stored effect. There is no migration tool, so
columns added to a table that already exists in production are applied by hand
in `init_db()` with `ADD COLUMN IF NOT EXISTS`; `create_all()` only ever creates
missing tables and will not alter one.

**The API** (`api/src/`, port 8001) owns everything stateful: the MQTT client,
the database, the in-memory device registry, and the firmware images. It has no
authentication of any kind. That is a deliberate simplification — it is an
internal service — but its port is published on the host anyway, because devices
have to fetch firmware from `/fw` and the API is the one service every strip can
already reach.

**The UI** (`ui/src/`, port 8000) serves HTML and nothing else of substance. It
knows about sessions and templates; it does not know MQTT exists. Every device
operation is an HTTP call to the API through `ui/src/api_client.py`. The only
database it touches is the `users` table, for login. The split is what makes it
possible to drive the lights from something that is not a browser — the MCP
server in `mcp-server/` talks to the same API — without that second client
having to reimplement anything.

**The firmware** (`firmware/led_controller/`) is one sketch that runs every
strip. It is in this repository rather than its own because the recipe payload
in [RECIPES.md](RECIPES.md) is a contract between it and `api/`, and a contract
that lands as two commits in two repositories can be deployed in either order.

---

## A click to a lit LED

Say someone drags the brightness slider and hits apply.

The device card posts the form to the **UI**, at
`/devices/{id}/settings`, targeting its own card. The session cookie is checked
— it is signed with `SECRET_KEY` and lasts a week — and the hex colour is
unpacked into three integers.

The UI calls the **API** over HTTP, `POST /devices/{id}/color` and
`POST /devices/{id}/brightness`, as query parameters. Every such route is a thin
wrapper over `api/src/services.py`, which is where the actual rule lives: look
the device up in the in-memory registry (404 if it is not there), publish, then
record what was asked for.

The API publishes to `lights/{id}/set`:

```json
{"brightness": 60}
```

**The device** receives it in the PubSubClient callback, which parses the JSON
and dispatches on which keys are present. `processCommand()` checks in a fixed
order — OTA first, then config, then power, colour, brightness, recipe, effect —
because the first two do not return: an OTA reboots into a new image and a
config change restarts the board, so anything else in the same payload would be
silently dropped. They are sent on their own for that reason.

Brightness is applied through `FastLED.setBrightness()` and pushed out with
`show()`. Then the device publishes its whole state back on `lights/{id}/state`,
and the API writes that into both the in-memory registry and `device_state`.

Meanwhile the UI has already re-rendered the card from what the API returned,
which is what was *asked for*, not what the strip confirmed. That is the honest
shape of this system: publishing is QoS 0 and unacknowledged, so a strip that is
unplugged silently misses the command while the UI shows the new value. The loop
closes on the device's own state message, which the browser will pick up the
next time the card is fetched. There is no push to the browser — no SSE, no
polling — so the [REFRESH] button is not decoration.

Two consequences of the same design worth knowing. A device is only reachable if
it is in the API's in-memory registry, which is populated at start-up from
Postgres and by announces; and `online` is set true by any announce or state
message but is only ever computed as false at start-up, from whether the device
was seen in the last five minutes. A strip that dies quietly therefore keeps
showing as online until the API restarts. The 60-second heartbeat exists to
refresh `last_seen`, not to detect death.

---

## Registration and hardware configuration

A strip publishes to `devices/announce` when it connects: its ID (derived from
the chip's eFuse MAC, so it is stable and needs no provisioning), its IP, its
firmware version, its capabilities, and the configuration it currently believes
in.

`_handle_device_announce()` in `api/src/mqtt.py` reconciles that against the
record, with a deliberate asymmetry:

- **No record**: the device is believed. What it reports becomes the record.
  A strip already working must not be reconfigured by the mere act of the server
  learning about it.
- **A record exists and differs**: the device is corrected, by publishing
  `{"config": {...}}` back to it. The record is what someone typed into the UI;
  the device may be a freshly flashed board on defaults.

Config is only sent when it actually differs, because applying one costs the
device a restart, and a redeploy of the API that restarted every strip in the
house would be its own kind of bug. The publish happens after the database
session is closed — holding a session open across network I/O is how connection
pools get exhausted.

Going the other way, `set_config()` writes the record *before* telling the
device. That ordering is not cosmetic. The device restarts and re-announces on
the way back up; with the write second, that announce would race it, find the
old record, and be answered with the old config — restarting it again.

On the device, `applyLedConfig()` turns the stored values into a FastLED
controller. Because pin and chipset are template parameters, the `STRIP_PINS`
macro instantiates every supported pin for each chipset and a `switch` picks one
at boot. An unsupported pin falls back to the default rather than leaving a
board with no status indicator and no way to say why.

---

## Effects, both kinds

There are two ways to make a strip do something other than sit at one colour,
and they are different code paths.

**A named effect** — `{"effect": "fire"}` — runs one of the thirteen functions
compiled into the sketch. It clears any loaded recipe, deliberately: without
that the recipe would keep rendering and the buttons would appear dead. Only two
buttons on a device card still take this path, OFF and FIRE, the latter because
fire cannot be expressed as a function of position and time.

**A recipe** — `{"effect": "ocean", "recipe": {...}}` — is data, and runs
through `runRecipe()`. The format is [RECIPES.md](RECIPES.md). It reaches a
device either from the studio (`POST /studio/push/{id}`, which forwards the
recipe being edited to `POST /devices/{id}/recipe`) or by name from the stored
set (`POST /devices/{id}/recipe?name=ocean`), which looks the row up in
`effects` and sends its recipe verbatim. Every other effect button on a device
card is the second of those.

The buttons themselves are rendered from the `effects` table, not from a list in
the template. A template with its own list would be a third place that had to
agree with the firmware and the server about which effects exist, and saving an
effect in the studio would not have made it appear on the dashboard at all.
`card_context()` in `ui/src/main.py` assembles that — and the firmware list, and
the device — in one place, because eleven routes render the same partial and
each assembling its own context is how the firmware list ended up on three of
them and missing from the other eight.

A recipe takes precedence over a compiled effect of the same name, so effects
could be moved into data one at a time and compared side by side against what
they replaced.

A palette stop can also be the string `"device"`, resolved on the strip at
render time to whatever colour it is currently set to. That is what lets the
five effects which used to follow the colour picker — breathing, chase, sparkle,
cylon, strobe — keep doing so as recipes. Because it resolves per frame rather
than at parse time, a colour change reaches a running recipe without anything
being re-sent, which is why `processCommand()` only pushes a solid colour out
when no recipe is loaded.

Both kinds persist. The device writes the effect name — and, for a recipe, the
raw JSON exactly as it arrived rather than unpacked fields — into NVS, so a
strip that reboots comes back as itself without waiting for the server, and so
the format can grow without invalidating what is already stored. The raw JSON
matters on the server side too: `effects.recipe` is a JSON column holding the
same payload, not decomposed into columns.

`api/src/effects_seed.py` inserts the eighteen built-ins on start-up, and only
if missing. Never updating in place is what makes it safe to hand-tune one of
them in the studio and redeploy.

The studio's preview (`ui/src/templates/studio.html`) is a JavaScript mirror of
`runRecipe()`, kept structurally identical to the C rather than written the way
one would write it fresh, because the entire value of the page is that a number
behaves the same there as on the wall. One honest difference is recorded in the
file: `noise` uses a small value-noise function where the device uses FastLED's
`inoise8`, so the character matches but the exact pattern does not.

One limit that bites in practice: PubSubClient's buffer is raised to 2048 bytes
in `setup()`. An oversized message is dropped inside the library with no error
and no callback, so a recipe that grows past that would vanish rather than fail.

---

## Firmware over the air

`POST /devices/{id}/ota?file=<name>` resolves the filename against
`FIRMWARE_BASE_URL` — rejecting anything containing a path separator, since the
static mount is right there — and publishes `{"ota": "<url>"}` on its own.

The device does not act on it in the callback. The first attempt did, and it
failed silently: the callback runs several frames deep on the loop task's 8 KB
stack, and while it blocks for the length of a download nothing services
`mqtt.loop()`, so the 15-second keepalive expires mid-transfer and the broker
drops the connection — taking the failure report with it. So the callback writes
the URL down and returns, and `loop()` picks it up.

`handleOta()` announces the start, disconnects from the broker deliberately (the
connection is lost either way; ending it on purpose gets a clean disconnect in
the log rather than a timeout), and runs `httpUpdate` with a progress callback
that draws a blue progress bar along the strip itself. These controllers are
mounted where reading a serial log is not how anyone finds out whether an update
worked. On success the device reboots inside `update()` and never returns; on
failure it reconnects, publishes the reason, and flashes red.

The default 4 MB partition table already carries two app slots, so a failed
*download* leaves the running firmware untouched. A bad *image* is a different
matter: rollback is compiled into the bootloader, but the Arduino core's
`initArduino()` marks a pending image valid before `setup()` runs, so a build
that crashes after that point is never rolled back. Hence the bench rule —
prove a build on the desk strip first.

---

## What lives where

| State | Home | Survives |
|---|---|---|
| Users, devices, per-device state, effects | Postgres | Everything except a volume wipe |
| Live device registry, `online` | API process memory | Nothing; rebuilt at start-up from Postgres |
| LED count, pin, chipset, order, last effect or recipe | Device NVS | Reboots and power cuts, with the server down |
| Firmware images | `firmware/images/`, bind-mounted | Untracked by git on purpose |

The overlap between the first and third rows is the point. The server is the
authority on how a strip is configured, and the device keeps a cache so that
authority is needed to change the configuration and never to restore it.
