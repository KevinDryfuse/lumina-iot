# Lumina IoT

LED strips on a home network: an MQTT broker, Postgres, a JSON API, an HTMX UI,
and the ESP32 firmware that drives the strips — all in this repository, all
running on one machine under Docker Compose.

Read [README.md](README.md) for what the system is and how to run it,
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for how the pieces fit and what
happens between a click and a lit LED, and [docs/RECIPES.md](docs/RECIPES.md)
before touching anything to do with effects. This file is the orientation for
working *in* the repository: where things live, and which invariants are load
bearing.

## Layout

```
api/src/            The only service that touches MQTT, Postgres or firmware images
  main.py           FastAPI routes; thin wrappers over services.py
  services.py       Every device state mutation goes through here
  mqtt.py           Broker client, announce handling, in-memory device registry
  db.py             SQLAlchemy models and init_db()
  effects_seed.py   The eighteen built-in recipes
ui/src/             HTML only; calls the API over HTTP, knows nothing of MQTT
  main.py           Session auth, HTMX routes, /studio
  api_client.py     The one place the UI talks to the API
  templates/        Jinja2; device_card.html and studio.html carry the interesting bits
ui/scripts/         create_user.py
firmware/
  led_controller/   The sketch. One image, every strip
  images/           .bin files staged for OTA; bind-mounted into the API, never committed
mcp-server/         MCP tools over the same API, for driving lights from Claude
mosquitto/          Broker config
docs/               RECIPES.md, ARCHITECTURE.md
```

Four compose services — `mosquitto` (1883), `postgres` (5432), `api` (8001),
`ui` (8000) — on the `lumina-net` bridge network.

## Things that will bite

**The recipe format is a contract.** `api/src/effects_seed.py`, the parser in
`led_controller.ino`, and the JavaScript preview in `studio.html` all implement
the same maths. A change to any one of them has to land in the same commit as
the others, and in `docs/RECIPES.md`. The studio's JS is deliberately a
structural mirror of `runRecipe()` rather than idiomatic JavaScript, because its
whole value is that a number behaves the same in the browser as on the wall.

**Effect seeding is insert-only.** Built-ins are inserted if missing and never
updated, so that a recipe hand-tuned in the studio survives a redeploy. If you
change a seeded recipe, existing installs keep the old one until someone deletes
the row.

**Write the record before telling the device.** A config change restarts the
strip and it re-announces on the way up; if the database write came second, that
announce would race it and be answered with the old config, restarting the strip
again. `services.set_config()` has the ordering, and a comment saying why.

**Config is only published when it differs.** Applying one costs a restart.
Redeploying the API must not restart every strip in the house.

**There is no migration tool.** `create_all()` creates missing tables and will
not alter an existing one, so a new column on an existing table goes in the
`_ADDED_COLUMNS` list in `api/src/db.py`, applied with `ADD COLUMN IF NOT
EXISTS` on every start.

**The API has no auth, and it is published on the host.** That is intentional —
devices fetch firmware from `/fw` — but it means any new API route is reachable
by anything on the LAN. Do not put anything behind it that would not survive
that.

**Anything sent over MQTT must fit in 2048 bytes.** PubSubClient drops an
oversized message inside the library with no error and no callback.

## Firmware

Built with the Arduino toolchain, FQBN
`esp32:esp32:esp32:PartitionScheme=min_spiffs`; verified against esp32 core
3.3.8, ArduinoJson 7.4.3, FastLED 3.10.3 and PubSubClient 2.8. `secrets.h` is
not committed — copy `secrets.h.example`.

Bump `FW_VERSION` on any build that gets published for OTA; it is reported in
the announce payload and is how the server knows which strips are behind. Stage
the `.bin` in `firmware/images/` under a name that says which version it is.
`.bin` files are gitignored on purpose.

**Test on the desk strip first.** An image that boots into a crash loop stays
there: rollback is compiled into the bootloader, but the Arduino core marks a
pending image valid during `initArduino()`, before `setup()` runs. Nothing that
fails after that point is recoverable over the air. Strips that need a ladder
only get builds that have already run on the bench.

Adding support for a new data pin means adding a line to the `STRIP_PINS` macro.
It is brute force because FastLED takes pin and chipset as template parameters;
the alternative, a sketch per strip, puts every future fix in more than one
place.

## Commands

```bash
docker compose up -d                 # start everything
docker compose up -d --build         # after changing api/ or ui/
docker compose logs -f api           # MQTT traffic and device announces show up here
docker compose exec ui python scripts/create_user.py <username>
```

`create_user.py` runs in the `ui` container, not `api` — the UI owns
authentication and the scripts directory is only copied into that image.

## Style

Comments in this codebase explain why a thing is the way it is, especially where
the obvious approach was tried and failed — the OTA deferral in `loop()`, the
announce reconciliation asymmetry, the `detune` parameter. Keep that. The commit
messages carry the same weight and are worth reading before changing anything
load bearing.
