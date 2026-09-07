# Troubleshooting

Organised by what you can see. Find the symptom, and the entry explains what is
actually happening underneath it — which matters, because several of these look
identical from the outside and have nothing to do with each other.

Everything here either happened or is a failure the code now explicitly guards
against. Where a fix exists, it says which firmware version carries it.

If the strip is **new and has never worked**, this is the wrong page: start with
[ADDING-A-STRIP.md](ADDING-A-STRIP.md), which walks the first flash and the
bring-up. This page is about a system that worked, and has stopped, or is
telling you something that is not true.

---

## Which firmware version matters

A strip reports its version in its announce payload; the dashboard shows it next
to the device ID, and `GET /devices` carries it as `fw_version`. Almost every
entry below turns on it.

| Version | What changed |
|---|---|
| *(reports nothing)* | The original firmware. No OTA and no recipe engine — needs a USB cable to get anywhere |
| **v2** | Hardware configuration became data, and OTA arrived. Every update after this one can be over the air |
| **v5** | The recipe engine. Effects became rows in a database |
| **v6** | The `"device"` palette stop, so recipe effects follow the colour picker again |
| **v8** | Colour order is actually applied to the wire, having been stored and ignored until then |
| **v9** | Survives a network outage: non-blocking reconnect, and the compiled effects other than fire are gone |

A strip reporting no version at all is not a bug in the announce handling. That
firmware predates `FW_VERSION` entirely.

---

## The strip flashes green over and over and never stops

Three separate faults compounding, all of them in firmware older than v9.

`connectWiFi()` ran only in `setup()`, so a radio that dropped was never brought
back and the MQTT retry spun against a dead network for as long as the strip had
power. `flashGreen()` sat inside that retry loop. And after an outage a socket
can be stale enough that `connect()` returns true while `connected()` is false
immediately afterwards — so it connected, flashed green, found itself
disconnected, connected again, flashed green again. Nothing anywhere gave up.

A green flash is normally the good sign: it means the broker answered. It is
only pathological when it repeats, and on v9 it cannot, because green is flashed
only while booting. A reconnect at three in the morning does not light the room.

**The fix is v9 or later.** On v9 the retry is non-blocking with a five-second
backoff, WiFi is repaired before MQTT is attempted, and ten minutes without the
broker restarts the strip outright. That last part is crude, but a strip in a
ceiling has no better move, and it means a v9 strip in this state recovers by
itself within ten minutes. An older one needs its power cycled, and then
updating — see [ADDING-A-STRIP.md](ADDING-A-STRIP.md) for how, and read the
crash-loop entry below before you send anything to a strip you cannot reach.

## The lights went out when the network went down

Same cause, same fix, and it is the more important half of it. The old
`connectMqtt()` **blocked**. While it was retrying, nothing rendered, so a
router reboot turned the lights off.

These are lights. From v9 they keep doing whatever they were last told — read
back out of NVS, where the recipe is stored as the raw JSON it arrived as — while
the network is repaired quietly underneath them. A strip that reboots at 3am with
the server down comes back as itself. The server is needed to *change* what a
strip is doing, never to restore it.

## An effect button does nothing — the light does not change

Almost always the routing, not the strip.

**A stored effect has to be sent to `/devices/{id}/recipe`, not
`/devices/{id}/effect`.** Only two effects still exist as names: `none` and
`fire`. Everything else is a row in the `effects` table, and the palette has to
travel with the name or the strip has nothing to render.

This was hard to spot for a long time because nothing said no. `/effect` used to
accept any string: it published the name, the strip accepted it, found no effect
by that name, and reported the name back — so the caller got a 200, the button
highlighted, and the light did not move. Three separate callers hit it before it
was noticed, and each time it presented as something else. The desk display's
effect buttons appeared dead while every tap was arriving and being answered
successfully.

On the strip, a name it does not recognise is worse than inert: it *clears* any
loaded recipe first, because a named effect is supposed to supersede one. So the
running effect stops and nothing replaces it, and the strip holds the last frame
it drew. It looks frozen rather than wrong.

`/effect` now refuses. A name that matches a stored effect returns 400 naming
`/recipe` as the endpoint that would have worked; anything else is a 404. If you
are calling the API directly:

```bash
# stored effect - sends the palette with it
curl -X POST "http://192.168.1.55:8001/devices/D4EC67C8/recipe?name=aurora"

# only these two go to /effect
curl -X POST "http://192.168.1.55:8001/devices/D4EC67C8/effect?effect=fire"
curl -X POST "http://192.168.1.55:8001/devices/D4EC67C8/effect?effect=none"
```

**A strip older than v5** has no recipe engine, so its card falls back to
offering the effects that used to be compiled in. Those genuinely work on such a
strip, and `/effect` accepts them for a device reporting a firmware old enough to
have them — the refusal above applies to names a device cannot actually run, not
to names that are merely old.

Briefly it did refuse them, which broke a working device: the card offered the
buttons, the API rejected them, and the request failed without swapping the
card — a third distinct cause with the same symptom. Fixed; recorded because the
shape of that mistake is worth recognising.

## Setting a colour does nothing

The effect is running, and it carries its own palette.

A recipe brings its colours with it; that is what makes an effect data rather
than code. Unless it uses the `"device"` palette stop, the colour picker has
nothing to change. The firmware knows this and does not even redraw — a colour
command only pushes pixels when no recipe is loaded.

**Press OFF and the colour will appear.** That sets `effect=none`, which drops
back to solid colour.

This presented as a broken colour picker twice, which is why the `"device"` stop
exists (v6 and later). Chase, cylon, sparkle, breathing and strobe all used to
render in whatever colour you had picked; the first translation of them into
recipes silently lost that. Those five built-ins now use `"device"`, resolved at
render time, so changing the colour takes effect immediately without re-sending
anything. Any effect that does not use it is simply not a colour-following
effect — see the `"device"` section of [RECIPES.md](RECIPES.md).

## A newly flashed strip lights only the first 30 LEDs

Expected. Thirty is what a board that has never been told anything comes up as —
enough to drive the boot indicator, and no assumption that anything longer is
attached.

What happens next depends on whether the server already knows the board. On
announce, a strip the server **has** a configuration for is corrected: the record
is what someone typed into the UI, and the device may be a freshly flashed board
on conservative defaults, so the record wins and the strip restarts at the right
length. A strip the server has **never seen** is believed instead, and the
reported 30 is adopted as the record.

That second case is the one that surprises people. Reflashing a board whose
database row was deleted — or a board whose row never had a configuration
written — leaves the server holding 30 as the truth, and it will keep sending it
back. Set the length in Hardware_Config on the card, or:

```bash
curl -X POST "http://192.168.1.55:8001/devices/D4EC67C8/config?led_count=91"
```

Configuration is only published when it actually differs from what the strip
reported, because applying one costs a restart and redeploying the API must not
restart every strip in the house.

## A command silently does nothing — no error anywhere

Two causes, both of which lose a message with no log line and a success returned
to the caller.

**The broker was unreachable.** paho accepts a publish on a disconnected client
and returns a result nobody was checking, so the command evaporated and the API
answered 200. This was hit for real: an OTA fired seconds after restarting the
API — before its own MQTT client had reconnected — did nothing at all, and the
only symptom was a firmware version that never changed. `send_command` now
refuses outright when disconnected and checks the publish result, so this
surfaces as an error rather than as nothing. `GET /health` reports
`mqtt_connected`; if it is false, that is your answer.

**The message was over 2048 bytes.** PubSubClient drops an oversized message
inside the library, with no error and no callback, on the receiving end. The
buffer is raised from its 256-byte default in `setup()` before anything depends
on it, but a recipe with eight palette stops and a long name can still approach
the limit. If a recipe pushed from the studio does nothing at all while smaller
ones work, this is the first thing to suspect, and the strip's serial output will
be silent about it because the callback never runs.

## A strip that is unplugged still shows as online

Fixed, and worth knowing how. `online` used to be a stored flag, set True on
every announce and every state message and computed False only at start-up.
Nothing ever set it False while running, so a strip that lost power stayed
"online" until the API was restarted — and the desk display reads this, so it
went on offering controls for a light that was not there.

It is now derived at read time from `last_seen`: a strip is online if it has
spoken within **185 seconds**. A strip publishes a heartbeat every 60 seconds, so
that is three missed ones, which is a reasonable definition of gone without
flickering offline over a single dropped packet.

The practical consequence is that a strip can take up to about three minutes to
be reported offline after it dies, and shows as offline for up to three minutes
after a restart if nothing has prompted it to speak. Neither is a fault.

## Firmware_Update appears to do nothing on an old strip

If the strip reports no firmware version at all, it cannot be updated over the
air. **OTA arrived in v2; anything older has no code to receive an update with.**
The first flash of such a board has to be by USB, once, and every update after
that is over the network. [ADDING-A-STRIP.md](ADDING-A-STRIP.md) covers the
cable.

If the strip does report a version and the update still does nothing, the causes
are ordinary and the logs will say which. The API refuses to publish when it is
not connected to the broker (above). `FIRMWARE_BASE_URL` has to be set, because
the API runs on a bridged Docker network and knows only its own 172.x address,
which no ESP32 on the LAN can reach — without it, `POST /ota?file=...` returns a
400 saying exactly that. And the strip reports its own progress: it renders a
blue bar along itself while downloading, flashes red three times if the update
fails, and publishes `{"ota": "failed", "error": ...}` on its state topic.

An early OTA attempt failed silently for a different reason worth recording, in
case something like it returns: the update ran inside the PubSubClient callback,
so `mqtt.loop()` was never called during the transfer, the 15-second keepalive
expired, the broker dropped the connection, and the failure report went nowhere.
The device published "started" and then went quiet. It now runs from `loop()`,
and disconnects deliberately before the transfer so the broker logs a clean
disconnect rather than a timeout.

**A failed download is safe.** Nothing is switched and the running firmware is
untouched. It is an image that installs and then misbehaves that costs you a
ladder — which is the next entry.

## A strip crash-loops after an update

It will not recover on its own. **There is no working rollback.**

This is not an assumption. The mechanism is implemented in the firmware and it
was tested: a deliberately broken image — a null dereference in `setup()` — was
built, staged, and installed over the air on the desk strip. It panicked, reset,
panicked again, and went on doing so. The previous image was never restored. The
strip came back only because a USB cable was already attached to it.

Every documented precondition was satisfied. The bootloader is built from this
core with `CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE=y`, the prebuilt libs set
`CONFIG_APP_ROLLBACK_ENABLE=y`, `Update` calls `esp_ota_set_boot_partition()`,
`min_spiffs` provides two app slots, and the inactive slot held a valid image.
Something in that chain does not behave as documented. The code stays, commented
with exactly what was observed, because it is the documented approach and a
future attempt should start from there — but nothing should be relied on.

The recovery is a USB cable and a reflash.

This is the whole reason for the bench rule: **prove firmware on a strip you can
physically reach before sending it to one you cannot.** The desk strip
(`D4EC67C8`) sits on a desk with a cable next to it and is that bench. Strips
that need a ladder only ever receive a build that has already run there. Note
that rollback would only ever have caught a *crash* anyway, not an effect that
merely renders wrong, so the bench is load-bearing regardless.

## Colour_Order is set but the colours are still wrong

If the strip is on firmware older than v8, colour order was dead configuration.
It was stored in NVS, reconciled with the server on every announce, reported in
the announce payload and offered as a six-value dropdown — and never used,
because the strip was always instantiated as GRB. Choosing RGB changed a database
row and a value in the device's flash and had no effect whatsoever on the light.

From v8 the buffer is permuted immediately before `show()` and restored
afterwards, so the dropdown does what it says. Update the strip, then set the
order.

## Every page returns 500

Twice, from two unrelated causes, both worth recognising.

**A dependency bump.** Every dependency was once an unbounded `>=`, and an image
rebuild done for other reasons pulled Starlette 1.x, whose `TemplateResponse`
takes the request first. Every page returned 500, and the error surfaced inside
Jinja's template cache as "unhashable type: dict", naming neither the argument
nor the file. `api/pyproject.toml` and `ui/pyproject.toml` carry upper bounds on
purpose; do not loosen them.

**A missing template variable.** `dashboard.html` includes the device card, and a
Jinja include inherits the *including* template's context rather than the context
of the routes that render a card on its own. A variable added to `card_context()`
and nowhere else meant every individual card route worked while the dashboard
raised `UndefinedError`. The card now defaults that variable, so a missing
context degrades to a card with no effect buttons instead of a blank site — if
you see a card with no effects at all, that is what you are looking at.

The smoke test that missed the second one checked `GET /` while logged out, which
returns a 302 and never renders the dashboard. It verified the only path that
could not fail.

---

## Useful commands

The API is on port 8001 and the UI on 8000, both published on the host. The
examples use `192.168.1.55`; substitute the machine running Compose.

**Container logs.** Almost everything interesting is in the API's: MQTT traffic,
device announces, config reconciliation, and every refused publish.

```bash
docker compose logs -f api
docker compose logs -f ui
docker compose ps
```

**Is the API talking to the broker at all.**

```bash
curl http://192.168.1.55:8001/health
curl http://192.168.1.55:8001/debug     # in-memory vs database device lists
```

`/debug` is the one to reach for when a device exists in one place and not the
other — it prints both sets of device IDs side by side.

**What a device is reporting.**

```bash
curl http://192.168.1.55:8001/devices | jq
curl http://192.168.1.55:8001/devices/D4EC67C8 | jq
curl http://192.168.1.55:8001/devices/D4EC67C8/config | jq
```

`/devices` carries `online`, `fw_version`, `last_seen`, the current effect and
the configuration the server holds. `/config` is the authoritative record — the
one the server will push back at the strip on its next announce.

**The mosquitto log.** Clean disconnects during OTA, keepalive timeouts, and
which clients are actually connected.

```bash
docker compose logs -f mosquitto
docker compose exec mosquitto tail -f /mosquitto/log/mosquitto.log
```

**Watch the MQTT traffic directly**, which is the fastest way to tell whether a
command left the server or the strip never answered:

```bash
docker compose exec mosquitto mosquitto_sub -t 'lights/#' -t 'devices/#' -v
```

**What a strip prints on serial.** 115200 baud. It logs every command it
receives, what it did with it, and the state it published back.

```bash
arduino-cli monitor -p COM5 -c baudrate=115200
```

On Linux the port is usually `/dev/ttyUSB0`; the Arduino IDE's Serial Monitor
does the same job. Note that a message dropped for being oversized never reaches
the callback, so serial will show nothing at all rather than an error.

**Stored effects**, which is what the dashboard renders its buttons from:

```bash
curl http://192.168.1.55:8001/effects | jq '.effects[] | {name, category}'
```
