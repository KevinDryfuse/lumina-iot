"""
Lumina IoT - API Service

JSON API for device control. Owns MQTT, DB, and all device state.
No auth — internal only (not exposed to internet).
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from .db import init_db, SessionLocal, Device
from .mqtt import mqtt_client, devices as devices_dict, MQTT_BROKER, MQTT_PORT
from . import services as device_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize DB, load devices, connect MQTT."""
    init_db()
    print("Database initialized")

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
