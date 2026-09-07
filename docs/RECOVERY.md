# If the Pi dies

One machine runs everything: `moneymakerdashboard`, at `192.168.1.55`, Debian 12,
user `kevin`. It runs two unrelated systems and the tunnel that publishes them.

| Path on the Pi | What it is |
|---|---|
| `~/Documents/lumina-iot` | This repository. `mosquitto` (1883), `postgres` (5432), `api` (8001), `ui` (8000) under Docker Compose |
| `~/desk-display` | A **separate** repository, `github.com/KevinDryfuse/desk-display`. The ADS-B and weather container for the physical desk display, on `:8080` with `network_mode: host` |
| `/etc/cloudflared/config.yml` | One tunnel, publishing `desk.` and `lumina.americanbuttcouncil.org` |

An SD card is a consumable. This page is what to do when that one fails, written
on the assumption that you are reading it with no working Pi in front of you and
no memory of how any of it was set up.

Read the first two sections before touching anything. They are the difference
between a rebuild that takes an evening and one that ends with a ladder and a
USB cable at every mounted strip in the house.

---

## The one thing to get right first

**The replacement Pi must come up on `192.168.1.55`.**

Every ESP32 strip has the broker's IP compiled into `secrets.h`, and there is no
mechanism for telling a flashed board a new address — that is the one setting
which is not data. A strip that cannot find the broker retries every five
seconds forever and restarts itself every ten minutes, so nothing is damaged,
but nothing works either, and the only fix is a USB cable per board.

So the DHCP reservation on the router is part of this system, and it is the
first thing to restore. Everything else in this document is recoverable in some
form; a changed IP address is the item that turns a rebuild into a re-flash.

The desk display is different and does not care: it reaches the container by
hostname over the tunnel, or by whatever LAN address it was given, and both are
settings on the display rather than compiled into it.

---

## What is actually lost

Almost all of it is in git. Both repositories clone back byte for byte, and the
firmware source, the compose files, the Mosquitto config and every document
including this one come with them.

What follows is the short list of things that exist **only on that SD card**.
This is the part that matters, and it is short enough to be worth reading twice.

| Lost | Where it was | Why it hurts |
|---|---|---|
| `~/Documents/lumina-iot/.env` | Gitignored | `POSTGRES_PASSWORD` — and if you restore the old Postgres volume with a new password, nothing connects |
| `~/Documents/lumina-iot/firmware/led_controller/secrets.h` | Gitignored | Wi-Fi SSID, Wi-Fi password, broker IP. Only needed to build firmware, not to run anything |
| The `postgres_data` volume | Docker named volume | Device names, per-device state, users, and **every effect authored in the studio** |
| `~/desk-display/adsb/.env` | Gitignored | `OHGO_API_KEY`, `DESK_TOKEN`, home coordinates, contact email, LIFX serials |
| `~/desk-display/.secrets/` | Gitignored | The Cloudflare API token, and the Access application id |
| `/home/kevin/.cloudflared/<tunnel-uuid>.json` | Never in any repository | The tunnel's actual credential. Without it `cloudflared` cannot run that tunnel |
| `/home/kevin/.cloudflared/cert.pem` | Never in any repository | The account certificate from `cloudflared tunnel login`. Needed to create tunnels or route DNS, not to run an existing one |
| Any SSH deploy keys in `~/.ssh` | Never in any repository | Only matters if either repository was cloned over SSH |
| `firmware/images/*.bin` | Gitignored (`firmware/.gitignore`) | The staged OTA images. Rebuildable from source; nothing unique is in them |

Two entries deserve more than a table row.

**The Postgres volume is the only one with unrecoverable content in it.** Everything
else on that list is a credential, and a credential can be reissued. Consider
what the four tables in `api/src/db.py` actually hold:

- `devices` — device id, friendly name, LED count, pin, chipset, colour order,
  last reported firmware version
- `device_state` — brightness, colour, current effect per strip
- `effects` — name, label, category and the recipe JSON, one row per effect
- `users` — username and a bcrypt hash

Of those, the hardware configuration comes back on its own (see below), and the
built-in effects reseed. What does not come back is the **friendly names**, and
any effect written or hand-tuned in the studio. A studio effect exists in
exactly two places: that row, and the NVS of whichever strips are currently
running it. The firmware never publishes a recipe back — `announceDevice()`
sends the hardware config and firmware version, and `publishState()` sends
brightness, colour and the effect *name* — so a strip happily running your
custom effect cannot tell you what it is. The row is the only readable copy.

**The `.env` password and the Postgres volume are a matched pair.** `POSTGRES_USER`,
`POSTGRES_PASSWORD` and `POSTGRES_DB` in `.env` are only used to *initialise* the
database, on the first start with an empty volume. After that they are baked
into the volume, and the same values also compose the `DATABASE_URL` that `api`
and `ui` are given. Restoring a volume backup while writing a fresh `.env` with a
new password gives you an `api` container that cannot authenticate to a database
that is running perfectly well. If you have the backup and not the password, take
the data out as SQL rather than as a volume; see step 6.

`SECRET_KEY` is less serious than it looks. It signs session cookies, and
nothing else — passwords are bcrypt hashes in Postgres, independent of it. A new
`SECRET_KEY` logs everybody out and costs one login.

---

## What survives on its own

Some of this system was built to tolerate exactly this failure, and it is worth
knowing which parts, because otherwise the rebuild involves work that is not
necessary.

**The strips keep working, and they come back as themselves.** Each controller
caches its LED count, pin, chipset, colour order, current effect name and — for
recipe effects — the raw recipe JSON in NVS, under the `lumina` namespace. That
is what `loadConfig()` reads at boot. A strip does not need the server to know
what it is; it needs the server only to *change* what it is. So while the Pi is
dead the strips carry on running whatever they were last told, and when the new
Pi appears they reconnect on their own.

**And they repopulate the device records.** The reconciliation in
`_handle_device_announce()` believes a strip it has never seen: with an empty
database, whatever each strip reports is adopted as the record. A strip with an
existing record is corrected from the record instead, on the grounds that the
record is what somebody edited in the UI. Against a fresh database every strip
is in the first case, so `led_count`, `led_pin`, `led_type` and `led_order` are
restored from the strips themselves, without anyone opening the Hardware_Config
panel. Only the friendly names are gone — the announce carries a chip ID and no
name, so the dashboard will come back as a wall of hex.

**The built-in effects reseed.** `seed_effects()` inserts every entry of `BUILTIN`
in `api/src/effects_seed.py` that is not already present, on each start. On an
empty database that is all of them. The seeding is insert-only by design — a
built-in that has been tuned in the studio must survive a redeploy — which has
the side effect that a rebuild puts the *original* recipes back and cannot know
that one of them used to be different.

**The tunnel's Cloudflare side is untouched.** The tunnel object, its DNS
records and the Access application in front of Lumina all live in Cloudflare's
account, not on the Pi. The only local part is the credentials JSON that lets
`cloudflared` prove it is that tunnel. Restore the file and the tunnel comes
back with the same id; lose it and you create a new tunnel and repoint two
hostnames, which is a five-minute job and not a disaster.

**The display's own Wi-Fi and token are not on the Pi.** The ESP32-P4 display
keeps up to eight networks and its access token in its own NVS. Rebuilding the
Pi does not touch it. If `DESK_TOKEN` comes back as a different value, though,
the display must be told the new one — the two have to match.

---

## Rebuilding

### 1. OS, and the address

Flash Debian 12 (64-bit) to the new card, enable SSH, boot it. Then recreate the
DHCP reservation for `192.168.1.55` on the router before anything else, and
confirm it:

```bash
hostname -I
```

Set the hostname to `moneymakerdashboard` if anything depends on it by name.

### 2. Docker

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker kevin
```

Log out and back in so the group applies. `docker compose` ships with that
install as a plugin; there is nothing else to add.

### 3. Both repositories

```bash
mkdir -p ~/Documents
git clone https://github.com/KevinDryfuse/lumina-iot ~/Documents/lumina-iot
git clone https://github.com/KevinDryfuse/desk-display ~/desk-display
```

Clone over HTTPS unless you have restored an SSH key, and note the paths: the
Lumina stack lives under `~/Documents`, the display's does not. The path matters
because `firmware/images/` is bind-mounted from it and because the OTA
instructions in [ADDING-A-STRIP.md](ADDING-A-STRIP.md) `scp` into it by name.

### 4. Put the secrets back

Three files, each from backup or reconstructed:

```bash
cd ~/Documents/lumina-iot
cp .env.example .env            # then edit
```

`.env` needs `POSTGRES_PASSWORD` (the old one if you are restoring the old
volume), a fresh `SECRET_KEY` if you do not have the old one, and
`FIRMWARE_BASE_URL=http://192.168.1.55:8001`. That last one cannot be worked out
by the API — it is on a bridged Docker network and knows only its own `172.x`
address, which no ESP32 can reach — so OTA silently has nowhere to point if it
is blank.

```bash
cd ~/desk-display
cp adsb/.env.example adsb/.env  # then edit
```

`adsb/.env` needs `DESK_TOKEN` set to the same value the display has in its
settings, `OHGO_API_KEY` (reissue from the OHGO account if lost), `CONTACT_EMAIL`
(two upstream services enforce it), the home coordinates, `LIFX_LIGHTS` and
`LUMINA_URL=http://192.168.1.55:8001`.

`firmware/led_controller/secrets.h` is only needed to *build* firmware. Skip it
until you next need to flash a board, then copy `secrets.h.example` and fill in
the Wi-Fi details and `MQTT_BROKER_IP 192.168.1.55`.

### 5. Bring the stacks up

```bash
cd ~/Documents/lumina-iot && docker compose up -d --build
cd ~/desk-display/adsb  && docker compose up -d --build
```

The display's compose file is inside `adsb/`, not at the repository root. Give
the first build several minutes on a Pi.

Check both:

```bash
docker compose ps
docker compose logs -f api        # device announces appear here
curl http://192.168.1.55:8001/devices
curl http://localhost:8080/health -H "X-Desk-Token: <token>"
```

The display's health check needs the token header like every other route — a
`/health` that answered without it would tell an unauthenticated caller exactly
what this machine is.

Within a minute or two the strips should reconnect and announce themselves, and
`GET /devices` should list them with their real LED counts, adopted from their
own NVS.

### 6. The database

**If you have a SQL dump**, restore it into the running container:

```bash
docker compose exec -T postgres psql -U lumina lumina < lumina-2026-09-06.sql
```

This is the preferred form. It carries no dependency on the Postgres version, on
the volume's internal state, or on the old `POSTGRES_PASSWORD` — a dump is
restored *as* an authenticated client, so a new password is fine.

**If you have a volume tarball instead**, put it back before the first start,
because Postgres initialises an empty volume on start and you do not want to
restore over that:

```bash
docker compose down
docker run --rm -v lumina-iot_postgres_data:/v -v $PWD:/b alpine \
  tar xzf /b/postgres_data.tar.gz -C /v
docker compose up -d
```

The volume is named for the compose project, which is the directory name — hence
`lumina-iot_postgres_data`. Use the old `POSTGRES_PASSWORD` in `.env` with this
route, or the containers will not be able to log in to their own database.

**If you have neither**, start empty and accept the loss. The built-ins reseed,
the strips repopulate their own hardware configuration, and what you rebuild by
hand is:

```bash
docker compose exec ui python scripts/create_user.py kevin
```

then rename each device from the dashboard — click the pencil beside the chip ID
— and re-author any custom effects in `/studio`. Brightness and colour are not
worth restoring; set a strip once and it is current again.

Do not restore `mosquitto_data` or `mosquitto_log`. The broker is anonymous, has
no credentials to lose, and its persistence file holds retained messages and
session state that are worthless after this long an outage.

### 7. The tunnel

```bash
sudo apt install cloudflared        # or the .deb from Cloudflare
sudo mkdir -p /etc/cloudflared
sudo cp ~/desk-display/deploy/cloudflared-config.yml /etc/cloudflared/config.yml
```

The config is committed in the desk-display repository precisely because it used
to exist only on this Pi. It names the tunnel id and the two ingress rules, and
the header of the file explains what is deliberately absent from it: the Lumina
API on `:8001` has no authentication at all and stays on the LAN.

**If you have the credentials JSON**, put it back where the config expects it and
start the service:

```bash
mkdir -p ~/.cloudflared
cp 238175b8-b158-467a-93ab-087a723051e6.json ~/.cloudflared/
sudo cloudflared service install
sudo systemctl enable --now cloudflared
sudo systemctl status cloudflared
```

Both hostnames should answer immediately. Nothing on Cloudflare's side changed,
so the DNS records and the Access policy in front of Lumina are already correct.

**If you do not have it**, make a new tunnel. The credential cannot be
re-downloaded — Cloudflare issues it once at creation:

```bash
cloudflared tunnel login                       # browser, pick the zone
cloudflared tunnel create desk-display-2
cloudflared tunnel route dns --overwrite-dns desk-display-2 desk.americanbuttcouncil.org
cloudflared tunnel route dns --overwrite-dns desk-display-2 lumina.americanbuttcouncil.org
```

Then edit `/etc/cloudflared/config.yml` with the new tunnel id and credentials
path, keeping both ingress rules and the catch-all `404`, restart the service,
and commit the updated file back to the desk-display repository so the next
rebuild starts from the truth. `--overwrite-dns` is needed because the CNAMEs
still point at the old tunnel. Delete the old tunnel afterwards. The Access
application over `lumina.` is attached to the hostname rather than the tunnel and
survives all of this untouched.

### 8. Firmware images, when you need them

`firmware/images/*.bin` is gitignored, so the staged OTA builds are gone. This
blocks nothing — the strips are already running their firmware — and the images
rebuild from source when you next want to push an update:

```bash
arduino-cli compile --fqbn esp32:esp32:esp32:PartitionScheme=min_spiffs \
  --libraries ~/Documents/Arduino/libraries \
  --output-dir /tmp/build firmware/led_controller
scp /tmp/build/led_controller.ino.bin \
  kevin@192.168.1.55:~/Documents/lumina-iot/firmware/images/led_controller_v9.bin
```

Name it for the `FW_VERSION` it carries. The rules in
[ADDING-A-STRIP.md](ADDING-A-STRIP.md) still apply, and the most important of
them is unchanged by any of this: prove a build on the desk strip before sending
it to one that needs a ladder.

---

## Backing up, so that none of the above is needed

Everything in this document that costs real time comes down to seven files and
one database. None of them is large; the whole set fits in a few megabytes, and
most of it never changes.

**Copy off the Pi once, and again whenever one of them changes:**

```
~/Documents/lumina-iot/.env
~/Documents/lumina-iot/firmware/led_controller/secrets.h
~/desk-display/adsb/.env
~/desk-display/.secrets/cloudflare-api-token
~/desk-display/.secrets/access-app-id
/home/kevin/.cloudflared/*.json
/home/kevin/.cloudflared/cert.pem
```

These are credentials and they are static. A copy in a password manager, or in
an encrypted archive somewhere that is not this house, is enough. Do not put
them in either repository — every one of them is gitignored for a reason, and
the `.gitignore` entries are the only thing standing between the Cloudflare
token and a public commit.

**Dump the database on a schedule.** Weekly is defensible; nightly is better and
costs nothing, because the dump is measured in kilobytes:

```bash
docker compose exec -T postgres pg_dump -U lumina lumina \
  > ~/backups/lumina-$(date +%F).sql
```

A cron entry and a `find ~/backups -mtime +30 -delete` is the whole of it. The
value is not in the device rows, which the strips restore by themselves — it is
in the effects table, which holds work that exists nowhere else and can only be
rewritten by hand.

Keep it **off the SD card**. A backup on the disk you are protecting against is
not a backup. Anywhere else on the network, or a `scp` to a desktop as part of
the same cron line, is enough.

**What is not worth backing up:** the OTA `.bin` files, which rebuild from
source; the Mosquitto volumes, which hold nothing durable; `adsb/shots/`, which
is screenshots, with the curated set already committed under `docs/img`; and the
repositories themselves, which are on GitHub.

**Test the restore path once**, on any spare machine: clone both repositories,
drop the secrets in, `docker compose up -d`, and load the dump. An untested
backup is a hypothesis. This one is cheap to check and the alternative is
discovering the gap on the evening the card fails.
