"""
Device control service layer.

All device state mutations go through here. Both the UI routes
and API routes call these functions instead of touching
mqtt_client/devices directly.
"""

from fastapi import HTTPException

from .db import SessionLocal, Device, Effect
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


def get_config(device_id: str) -> dict:
    """Return a device's hardware configuration."""
    get_device(device_id)
    db = SessionLocal()
    try:
        db_device = db.query(Device).filter(Device.device_id == device_id).first()
        return {
            "device_id": device_id,
            "config": db_device.config_dict() if db_device else None,
            "fw_version": db_device.fw_version if db_device else None,
        }
    finally:
        db.close()


def set_config(device_id: str, led_count: int | None = None, pin: int | None = None,
               led_type: str | None = None, order: str | None = None) -> dict:
    """Change a device's hardware configuration.

    Writes the record first, then tells the device. That order matters: the
    device restarts on a config change, and it re-announces on the way back up.
    If the record were written second, that announce would race the write and
    the reconciliation in _handle_device_announce would send the OLD config
    straight back, restarting it again.
    """
    get_device(device_id)

    db = SessionLocal()
    try:
        db_device = db.query(Device).filter(Device.device_id == device_id).first()
        if not db_device:
            raise HTTPException(status_code=404, detail="Device not found")

        if led_count is not None:
            if not 1 <= led_count <= 300:
                raise HTTPException(status_code=400, detail="led_count must be 1-300")
            db_device.led_count = led_count
        if pin is not None:
            db_device.led_pin = pin
        if led_type is not None:
            db_device.led_type = led_type
        if order is not None:
            db_device.led_order = order

        db.commit()
        config = db_device.config_dict()
    finally:
        db.close()

    if config:
        mqtt_client.send_command(device_id, {"config": config})
    return {"device_id": device_id, "config": config}


def send_ota(device_id: str, url: str) -> dict:
    """Start an over-the-air firmware update on one device."""
    get_device(device_id)
    mqtt_client.send_ota(device_id, url)
    return {"device_id": device_id, "ota": "requested", "url": url}


def list_effects() -> list[dict]:
    """Every stored effect, category then name."""
    db = SessionLocal()
    try:
        rows = db.query(Effect).order_by(Effect.category, Effect.name).all()
        return [e.as_dict() for e in rows]
    finally:
        db.close()


def save_effect(name: str, recipe: dict, label: str = None,
                category: str = "custom") -> dict:
    """Create or replace a stored effect."""
    if not name or not recipe:
        raise HTTPException(status_code=400, detail="name and recipe required")
    if not recipe.get("palette"):
        raise HTTPException(status_code=400, detail="recipe needs a palette")

    db = SessionLocal()
    try:
        row = db.query(Effect).filter(Effect.name == name).first()
        if not row:
            row = Effect(name=name)
            db.add(row)
        row.recipe = recipe
        if label is not None:
            row.label = label
        if category:
            row.category = category
        db.commit()
        return row.as_dict()
    finally:
        db.close()


def delete_effect(name: str) -> dict:
    """Remove a stored effect."""
    db = SessionLocal()
    try:
        row = db.query(Effect).filter(Effect.name == name).first()
        if not row:
            raise HTTPException(status_code=404, detail="Effect not found")
        db.delete(row)
        db.commit()
        return {"deleted": name}
    finally:
        db.close()


def send_recipe(device_id: str, recipe: dict, effect_name: str = "recipe") -> dict:
    """Send a recipe straight to a device without storing it.

    This is what the studio's preview pushes: an effect being tuned is not yet
    an effect worth keeping, and making someone name a thing before they can
    see it on the wall is the wrong order.
    """
    device = get_device(device_id)
    mqtt_client.send_command(device_id, {"effect": effect_name, "recipe": recipe})
    device["effect"] = effect_name
    return device


def send_stored_effect(device_id: str, name: str) -> dict:
    """Look a stored effect up by name and send it."""
    db = SessionLocal()
    try:
        row = db.query(Effect).filter(Effect.name == name).first()
        if not row:
            raise HTTPException(status_code=404, detail="Effect not found")
        recipe = row.recipe
    finally:
        db.close()
    return send_recipe(device_id, recipe, name)


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
