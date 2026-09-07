"""
Device control service layer.

All device state mutations go through here. Both the UI routes
and API routes call these functions instead of touching
mqtt_client/devices directly.
"""

import time

from fastapi import HTTPException

from .db import SessionLocal, Device, Effect
from .mqtt import mqtt_client, devices


# A strip publishes a heartbeat every 60 seconds, so three missed ones is a
# reasonable definition of gone.
OFFLINE_AFTER_S = 185

# Must match STRIP_PINS in firmware/led_controller/led_controller.ino. Kept here
# rather than trusted from the form, because the consequence of a wrong pin is a
# strip that reboots every few seconds until someone catches it.
SUPPORTED_PINS = {2, 4, 5, 12, 13, 14, 16, 17, 18, 19, 21, 22, 23, 25, 26, 27, 32, 33}
SUPPORTED_CHIPSETS = {"WS2815", "WS2812B", "WS2812", "WS2811", "SK6812"}
SUPPORTED_ORDERS = {"GRB", "RGB", "BRG", "RBG", "GBR", "BGR"}


def _with_online(d: dict) -> dict:
    """Add a freshly computed `online` to a device record.

    Derived from when the device last spoke rather than stored, because a stored
    flag was only ever set to True. It was set on every announce and every state
    message and computed False only at start-up, so a strip that lost power
    stayed "online" indefinitely - and the desk display, which reads this, would
    have gone on showing it as available.
    """
    age = time.time() - (d.get("last_seen") or 0)
    return {**d, "online": age < OFFLINE_AFTER_S}


def get_all_devices() -> list[dict]:
    """Return all devices."""
    return [_with_online(d) for d in devices.values()]


def get_device(device_id: str) -> dict:
    """Return a single device or raise 404."""
    if device_id not in devices:
        raise HTTPException(status_code=404, detail="Device not found")
    return _with_online(devices[device_id])


def set_color(device_id: str, r: int, g: int, b: int) -> dict:
    """Set device color. Returns updated device dict."""
    get_device(device_id)
    for name, v in (("r", r), ("g", g), ("b", b)):
        if not 0 <= v <= 255:
            raise HTTPException(status_code=400, detail=f"{name} must be 0-255")
    mqtt_client.send_command(device_id, {"color": {"r": r, "g": g, "b": b}})
    devices[device_id]["color"] = {"r": r, "g": g, "b": b}
    return _with_online(devices[device_id])


def set_brightness(device_id: str, brightness: int) -> dict:
    """Set device brightness (0-100). Returns updated device dict."""
    get_device(device_id)
    # Documented as 0-100 and enforced nowhere. 1000 maps to 2550, truncates to
    # 246 in the firmware, and lands the strip DIMMER than 100 with a 200 back.
    if not 0 <= brightness <= 100:
        raise HTTPException(status_code=400, detail="brightness must be 0-100")
    mqtt_client.send_command(device_id, {"brightness": brightness})
    devices[device_id]["brightness"] = brightness
    return _with_online(devices[device_id])


# Still compiled into the strip's firmware. Everything else is a recipe and has
# to be sent as one.
COMPILED_EFFECTS = {"none", "fire"}

# What was compiled in before the recipe engine landed in FW_VERSION 5. A strip
# older than that genuinely can run these by name, and refusing them would break
# a device that works - so they are allowed, but only for a device that reports
# a firmware old enough to have them.
LEGACY_EFFECTS = {
    "rainbow", "breathing", "chase", "sparkle", "confetti", "cylon",
    "strobe", "ocean", "aurora", "candle", "christmas", "usa",
}
RECIPE_ENGINE_FW = 5


def set_effect(device_id: str, effect: str) -> dict:
    """Set one of the compiled effects by name.

    Refuses a name it does not recognise. This endpoint used to accept anything:
    it would publish the name, the strip would accept it, find no effect by that
    name, carry on doing whatever it was doing, and report the name back - so
    every caller saw success and the light never moved. Three separate callers
    hit that before it was noticed, because nothing anywhere said no.

    A stored effect belongs on /recipe, which sends the palette with it.
    """
    get_device(device_id)

    fw = devices[device_id].get("fw_version")
    pre_recipe = fw is None or fw < RECIPE_ENGINE_FW
    if pre_recipe and effect in LEGACY_EFFECTS:
        mqtt_client.send_command(device_id, {"effect": effect})
        devices[device_id]["effect"] = effect
        return _with_online(devices[device_id])

    if effect not in COMPILED_EFFECTS:
        db = SessionLocal()
        try:
            known = db.query(Effect).filter(Effect.name == effect).first()
        finally:
            db.close()
        if known:
            raise HTTPException(
                status_code=400,
                detail=f"'{effect}' is a stored effect - send it to "
                       f"/devices/{device_id}/recipe?name={effect} so the strip "
                       f"gets the palette with it",
            )
        raise HTTPException(status_code=404, detail=f"No effect named '{effect}'")

    mqtt_client.send_command(device_id, {"effect": effect})
    devices[device_id]["effect"] = effect
    return _with_online(devices[device_id])


def set_power(device_id: str, power: bool) -> dict:
    """Set device power on/off. Returns updated device dict."""
    get_device(device_id)
    mqtt_client.send_command(device_id, {"power": power})
    devices[device_id]["power"] = power
    return _with_online(devices[device_id])


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
            # An unsupported pin bricks a strip into a reboot loop, and the form
            # offers 0-39 while only these eighteen are instantiated. The loop:
            # the device stores the bad pin, fails to init, falls back to pin 5
            # in RAM ONLY, announces 5, the server sees 5 != 15 and sends 15
            # back, the device sees a change and restarts. Forever, every few
            # seconds, recoverable only by racing it or with a cable.
            if pin not in SUPPORTED_PINS:
                raise HTTPException(
                    status_code=400,
                    detail=f"pin {pin} is not one of the supported pins "
                           f"{sorted(SUPPORTED_PINS)} - the firmware only "
                           f"instantiates those, and an unsupported one leaves "
                           f"the strip restarting in a loop",
                )
            db_device.led_pin = pin
        if led_type is not None:
            if led_type not in SUPPORTED_CHIPSETS:
                raise HTTPException(status_code=400,
                    detail=f"unknown chipset {led_type}")
            db_device.led_type = led_type
        if order is not None:
            if order not in SUPPORTED_ORDERS:
                raise HTTPException(status_code=400,
                    detail=f"unknown colour order {order}")
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
    get_device(device_id)
    mqtt_client.send_command(device_id, {"effect": effect_name, "recipe": recipe})
    devices[device_id]["effect"] = effect_name
    return _with_online(devices[device_id])


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

    devices[device_id]["friendly_name"] = clean_name
    return _with_online(devices[device_id])
