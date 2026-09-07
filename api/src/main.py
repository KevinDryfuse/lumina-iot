"""
Lumina IoT - API Service

JSON API for device control. Owns MQTT, DB, and all device state.
No auth — internal only (not exposed to internet).
"""

from contextlib import asynccontextmanager

import os

import base64
import secrets

from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import FileResponse

from .db import init_db, SessionLocal, Device, Effect
from .effects_seed import seed_effects
from .mqtt import mqtt_client, devices as devices_dict, MQTT_BROKER, MQTT_PORT
from . import services as device_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize DB, load devices, connect MQTT."""
    init_db()
    print("Database initialized")

    seed_effects(SessionLocal, Effect)

    mqtt_client.load_devices_from_db()
    mqtt_client.connect()

    yield

    mqtt_client.disconnect()


app = FastAPI(
    title="Lumina IoT API",
    description="Internal API for Lumina IoT - no auth required",
    version="0.1.0",
    lifespan=lifespan,
)


#
# Firmware images, for over-the-air updates.
#
# Served from here rather than from somewhere else on the network because the
# API is the only thing that already knows every device's address and is already
# reachable from all of them. A device is told an absolute URL, so this has to
# be served on an interface the strips can reach - which is why the API's port
# is published on the host rather than kept inside the compose network.
#
# Nothing here is secret. It is signed by nothing either, which is worth being
# honest about: anyone already on this LAN could serve a strip a firmware image
# of their own. That is the same trust boundary the rest of Lumina sits behind -
# the API has no authentication at all - and it is not made worse by this.
FIRMWARE_DIR = os.getenv("FIRMWARE_DIR", "/firmware")
os.makedirs(FIRMWARE_DIR, exist_ok=True)

# Where a DEVICE should fetch firmware from. Not derivable here: the API runs on
# a bridged Docker network, so it only knows its own 172.x address, and the URL
# has to be one the strips can reach on the LAN.
FIRMWARE_BASE_URL = os.getenv("FIRMWARE_BASE_URL", "").rstrip("/")

# Shared with FIRMWARE_TOKEN in the firmware's secrets.h.
FIRMWARE_TOKEN = os.getenv("FIRMWARE_TOKEN", "")


def _firmware_auth(authorization: str | None):
    """Guard the firmware routes.

    These are the one part of this API that is NOT covered by "the trust
    boundary is the LAN". Every other route controls lights; these hand out an
    image with the WiFi SSID and password compiled into it, recoverable with
    `strings`. That is the key to the network the boundary itself rests on, so
    a foothold on a guest device or a compromised bulb should not be able to
    read it.

    Basic auth because that is what HTTPUpdate offers on the device side.
    """
    if not FIRMWARE_TOKEN:
        raise HTTPException(
            status_code=503,
            detail="FIRMWARE_TOKEN is not set, so firmware is not being served",
        )
    expected = "Basic " + base64.b64encode(
        f"ota:{FIRMWARE_TOKEN}".encode()).decode()
    if not authorization or not secrets.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="firmware requires the token",
                            headers={"WWW-Authenticate": 'Basic realm="firmware"'})


@app.get("/firmware")
async def list_firmware(authorization: str = Header(None)):
    """Firmware images staged for OTA, newest first."""
    _firmware_auth(authorization)
    items = []
    for name in os.listdir(FIRMWARE_DIR):
        if not name.endswith(".bin"):
            continue
        path = os.path.join(FIRMWARE_DIR, name)
        st = os.stat(path)
        items.append({
            "name": name,
            "size": st.st_size,
            "modified": st.st_mtime,
            "url": f"{FIRMWARE_BASE_URL}/fw/{name}" if FIRMWARE_BASE_URL else None,
        })
    items.sort(key=lambda i: i["modified"], reverse=True)
    return {"base_url": FIRMWARE_BASE_URL or None, "images": items}


@app.get("/fw/{name}")
async def get_firmware(name: str, authorization: str = Header(None)):
    """Serve one firmware image to a device that knows the token."""
    _firmware_auth(authorization)
    if "/" in name or "\\" in name or not name.endswith(".bin"):
        raise HTTPException(status_code=400, detail="bad firmware filename")
    path = os.path.join(FIRMWARE_DIR, name)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="no such image")
    return FileResponse(path, media_type="application/octet-stream")


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "mqtt_connected": mqtt_client.connected}


@app.get("/debug")
async def debug():
    """Debug endpoint — shows internal state for troubleshooting."""
    db = SessionLocal()
    try:
        db_device_count = db.query(Device).count()
        db_device_ids = [d.device_id for d in db.query(Device).all()]
    finally:
        db.close()
    return {
        "mqtt_connected": mqtt_client.connected,
        "mqtt_broker": MQTT_BROKER,
        "mqtt_port": MQTT_PORT,
        "in_memory_device_count": len(devices_dict),
        "in_memory_device_ids": list(devices_dict.keys()),
        "db_device_count": db_device_count,
        "db_device_ids": db_device_ids,
    }


@app.get("/devices")
async def list_devices():
    """List all devices."""
    return device_service.get_all_devices()


@app.get("/devices/{device_id}")
async def get_device(device_id: str):
    """Get a specific device."""
    return device_service.get_device(device_id)


@app.post("/devices/{device_id}/color")
async def set_color(device_id: str, r: int, g: int, b: int):
    """Set device color."""
    return device_service.set_color(device_id, r, g, b)


@app.post("/devices/{device_id}/brightness")
async def set_brightness(device_id: str, brightness: int):
    """Set device brightness (0-100)."""
    return device_service.set_brightness(device_id, brightness)


@app.get("/devices/{device_id}/config")
async def get_config(device_id: str):
    """Get device hardware configuration (LED count, pin, chipset)."""
    return device_service.get_config(device_id)


@app.post("/devices/{device_id}/config")
async def set_config(device_id: str, led_count: int = None, pin: int = None,
                     led_type: str = None, order: str = None):
    """Set device hardware configuration. The device restarts to apply it."""
    return device_service.set_config(device_id, led_count, pin, led_type, order)


@app.post("/devices/{device_id}/ota")
async def ota(device_id: str, url: str = None, file: str = None):
    """Install firmware from a staged image.

    A full `url` is accepted only if it points at this server's own /fw. The
    parameter used to take anything, which was consistent with "the trust
    boundary is the LAN" right up until the images went behind a token - after
    which it was the way around that token: point a strip at your own web
    server and it fetches and runs whatever is there, no credential needed.

    Restricting it rather than removing it, because the tunnel and any future
    second host still need the full form.
    """
    if url:
        if not FIRMWARE_BASE_URL or not url.startswith(f"{FIRMWARE_BASE_URL}/fw/"):
            raise HTTPException(
                status_code=400,
                detail=f"url must be under {FIRMWARE_BASE_URL}/fw/ - a strip "
                       f"will run whatever it is pointed at, so it is only "
                       f"pointed at images this server is serving",
            )
    if not url:
        if not file:
            raise HTTPException(status_code=400, detail="url or file required")
        if not FIRMWARE_BASE_URL:
            raise HTTPException(
                status_code=400,
                detail="FIRMWARE_BASE_URL is not set, so a filename cannot be "
                       "turned into an address the device can reach",
            )
        # Defend the static mount: a filename is a filename, not a path.
        if "/" in file or "\\" in file or not file.endswith(".bin"):
            raise HTTPException(status_code=400, detail="bad firmware filename")
        url = f"{FIRMWARE_BASE_URL}/fw/{file}"
    return device_service.send_ota(device_id, url)


# ---- effects stored as data (see docs/RECIPES.md) ----
@app.get("/effects")
async def list_effects():
    """Every stored effect."""
    return {"effects": device_service.list_effects()}


@app.put("/effects/{name}")
async def save_effect(name: str, body: dict):
    """Create or replace a stored effect. Body: {recipe, label?, category?}."""
    return device_service.save_effect(
        name, body.get("recipe"), body.get("label"), body.get("category", "custom"))


@app.delete("/effects/{name}")
async def delete_effect(name: str):
    """Remove a stored effect."""
    return device_service.delete_effect(name)


@app.post("/devices/{device_id}/recipe")
async def send_recipe(device_id: str, body: dict = None, name: str = None):
    """Send a recipe to a device, either stored by name or inline in the body."""
    if name:
        return device_service.send_stored_effect(device_id, name)
    if not body or not body.get("recipe"):
        raise HTTPException(status_code=400, detail="name, or a recipe body")
    return device_service.send_recipe(
        device_id, body["recipe"], body.get("effect", "recipe"))


@app.post("/devices/{device_id}/effect")
async def set_effect(device_id: str, effect: str):
    """Set device effect."""
    return device_service.set_effect(device_id, effect)


@app.post("/devices/{device_id}/power")
async def set_power(device_id: str, power: bool):
    """Set device power on/off."""
    return device_service.set_power(device_id, power)


@app.post("/devices/{device_id}/name")
async def set_name(device_id: str, friendly_name: str):
    """Set device friendly name."""
    return device_service.set_name(device_id, friendly_name)
