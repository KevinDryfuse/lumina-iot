# Lumina IoT

ESP32-based LED strip controller with a web UI. Runs entirely on your local network using Docker.

## Quick Start

```bash
# Clone the repo
git clone <repo-url>
cd lumina-iot

# Copy environment file and edit as needed
cp .env.example .env

# Start all services
docker compose up -d

# Create your first user
docker compose exec api python scripts/create_user.py admin

# Open the UI
# http://localhost:8000
```

## Architecture

```
Browser → FastAPI (HTMX UI) → Mosquitto (MQTT) → ESP32
              ↓
          PostgreSQL
```

- **Mosquitto**: MQTT broker for device communication
- **FastAPI + HTMX**: Web UI and API in one
- **PostgreSQL**: User accounts and device state persistence

## Network Setup

For the ESP32 to reliably connect, your server needs a static IP. The easiest way is to set a **DHCP reservation** in your router.

If you want to access the UI from outside your network, set up **port forwarding** on port 8000 (or 80 if you remap it).

**Windows Firewall:** You may need to allow inbound connections on port 8000:
```powershell
netsh advfirewall firewall add rule name="Lumina API" dir=in action=allow protocol=tcp localport=8000
```

## ESP32 Setup

See [lumina-esp32/README.md](../lumina-esp32/README.md) for wiring and firmware setup.

## Services

| Service | Port | Description |
|---------|------|-------------|
| UI | 8000 | Web interface (Tron-themed!) |
| API | 8001 | REST API + docs |
| Mosquitto | 1883 | MQTT broker |
| PostgreSQL | 5432 | Database |

## Features

- **Power Toggle**: Turn LEDs on/off
- **Color Picker**: Set any RGB color
- **Brightness Control**: 0-100% slider
- **13 Effects**: Organized by category (Standard, Party, Ambient, Holiday)
- **Auto-Discovery**: Devices announce themselves on connect
- **Real-time Updates**: HTMX-powered UI updates without page refresh

## Managing Users

```bash
# Create a user
docker compose exec api python scripts/create_user.py <username>

# View logs
docker compose logs -f api
```

## Development

```bash
# Watch logs for all services
docker compose logs -f

# Restart just the API (after code changes)
docker compose restart api

# Rebuild containers
docker compose up -d --build
```

## Hardware

- ESP32-D (ESP32-WROOM-32)
- WS2815 LED Strip (12V)
- 12V Power Supply

## License

MIT
