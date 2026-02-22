"""
Device control service layer.

All device state mutations go through here. Both the UI routes
and API routes call these functions instead of touching
mqtt_client/devices directly.
"""

from fastapi import HTTPException

from .db import SessionLocal, Device
from .mqtt import mqtt_client, devices


def get_all_devices() -> list[dict]:
    """Return all devices."""
    return list(devices.values())


def get_device(device_id: str) -> dict:
    """Return a single device or raise 404."""
    if device_id not in devices:
        raise HTTPException(status_code=404, detail="Device not found")
    return devices[device_id]


def set_color(device_id: str, r: int, g: int, b: int) -> dict:
    """Set device color. Returns updated device dict."""
    device = get_device(device_id)
    mqtt_client.send_command(device_id, {"color": {"r": r, "g": g, "b": b}})
    device["color"] = {"r": r, "g": g, "b": b}
    return device


def set_brightness(device_id: str, brightness: int) -> dict:
    """Set device brightness (0-100). Returns updated device dict."""
    device = get_device(device_id)
    mqtt_client.send_command(device_id, {"brightness": brightness})
    device["brightness"] = brightness
    return device


def set_effect(device_id: str, effect: str) -> dict:
    """Set device effect. Returns updated device dict."""
    device = get_device(device_id)
    mqtt_client.send_command(device_id, {"effect": effect})
    device["effect"] = effect
    return device


def set_power(device_id: str, power: bool) -> dict:
    """Set device power on/off. Returns updated device dict."""
    device = get_device(device_id)
    mqtt_client.send_command(device_id, {"power": power})
    device["power"] = power
    return device


def set_name(device_id: str, friendly_name: str) -> dict:
    """Set device friendly name. Persists to DB. Returns updated device dict."""
    device = get_device(device_id)
    clean_name = friendly_name.strip() or None

    db = SessionLocal()
    try:
        db_device = db.query(Device).filter(Device.device_id == device_id).first()
        if db_device:
            db_device.friendly_name = clean_name
            db.commit()
    finally:
        db.close()

    device["friendly_name"] = clean_name
    return device
