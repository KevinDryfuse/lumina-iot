"""
Lumina IoT - FastAPI Application

LED strip controller with HTMX-based UI.

Two apps are exposed:
- app (port 8000): UI only, with auth, no docs - exposed to internet
- api_app (port 8001): JSON API with docs, no auth - internal only
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Form, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .db import get_db, init_db, Device, DeviceState
from .auth import (
    authenticate_user,
    create_session_token,
    get_current_user,
    require_auth,
    SESSION_COOKIE_NAME,
    User,
)
from .mqtt import mqtt_client, devices

# Template directory
TEMPLATE_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    # Initialize database
    init_db()
    print("Database initialized")

    # Load devices from database
    mqtt_client.load_devices_from_db()

    # Connect to MQTT
    mqtt_client.connect()

    yield

    # Cleanup
    mqtt_client.disconnect()


# ===================
# Main UI App (port 8000) - no docs, requires auth
# ===================
app = FastAPI(
    title="Lumina IoT",
    description="LED strip controller with HTMX UI",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

# ===================
# Internal API App (port 8001) - has docs, no auth
# ===================
api_app = FastAPI(
    title="Lumina IoT API",
    description="Internal API for Lumina IoT - no auth required",
    version="0.1.0",
)


# ===================
# Health Check
# ===================
@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "mqtt_connected": mqtt_client.connected}


# ===================
# Authentication Routes
# ===================
@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Show login page."""
    user = get_current_user(request, next(get_db()))
    if user:
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    """Handle login form submission."""
    user = authenticate_user(db, username, password)
    if not user:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Invalid username or password"},
            status_code=401,
        )

    # Create session and redirect
    token = create_session_token(user.id)
    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        max_age=60 * 60 * 24 * 7,  # 7 days
        samesite="lax",
    )
    return response


@app.get("/logout")
async def logout():
    """Log out the current user."""
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie(SESSION_COOKIE_NAME)
    return response


# ===================
# Dashboard (Main UI)
# ===================
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    """Main dashboard showing all devices."""
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "devices": list(devices.values()),
        },
    )


# ===================
# Device Control (HTMX endpoints)
# ===================
@app.get("/devices/{device_id}/card", response_class=HTMLResponse)
async def get_device_card(
    request: Request,
    device_id: str,
    user: User = Depends(require_auth),
):
    """Get a single device card (for HTMX refresh)."""
    if device_id not in devices:
        raise HTTPException(status_code=404, detail="Device not found")

    return templates.TemplateResponse(
        "partials/device_card.html",
        {
            "request": request,
            "device": devices[device_id],
        },
    )


@app.post("/devices/{device_id}/color", response_class=HTMLResponse)
async def set_color(
    request: Request,
    device_id: str,
    color: str = Form(...),
    user: User = Depends(require_auth),
):
    """Set device color."""
    if device_id not in devices:
        raise HTTPException(status_code=404, detail="Device not found")

    # Parse hex color (#rrggbb)
    hex_color = color.lstrip("#")
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)

    # Send command to device
    mqtt_client.send_command(device_id, {"color": {"r": r, "g": g, "b": b}})

    # Update local state optimistically
    devices[device_id]["color"] = {"r": r, "g": g, "b": b}

    # Return updated device card
    return templates.TemplateResponse(
        "partials/device_card.html",
        {
            "request": request,
            "device": devices[device_id],
            "message": f"Color set to RGB({r}, {g}, {b})",
        },
    )


@app.post("/devices/{device_id}/settings", response_class=HTMLResponse)
async def set_settings(
    request: Request,
    device_id: str,
    color: str = Form(...),
    brightness: int = Form(...),
    user: User = Depends(require_auth),
):
    """Set device color and brightness together."""
    if device_id not in devices:
        raise HTTPException(status_code=404, detail="Device not found")

    # Parse hex color (#rrggbb)
    hex_color = color.lstrip("#")
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)

    # Send commands to device
    mqtt_client.send_command(device_id, {"color": {"r": r, "g": g, "b": b}})
    mqtt_client.send_command(device_id, {"brightness": brightness})

    # Update local state optimistically
    devices[device_id]["color"] = {"r": r, "g": g, "b": b}
    devices[device_id]["brightness"] = brightness

    # Return updated device card
    return templates.TemplateResponse(
        "partials/device_card.html",
        {
            "request": request,
            "device": devices[device_id],
            "message": f"Settings applied",
        },
    )


@app.post("/devices/{device_id}/effect", response_class=HTMLResponse)
async def set_effect(
    request: Request,
    device_id: str,
    effect: str = Form(...),
    user: User = Depends(require_auth),
):
    """Set device effect."""
    if device_id not in devices:
        raise HTTPException(status_code=404, detail="Device not found")

    # Send command to device
    mqtt_client.send_command(device_id, {"effect": effect})

    # Update local state optimistically
    devices[device_id]["effect"] = effect

    # Return updated device card
    return templates.TemplateResponse(
        "partials/device_card.html",
        {
            "request": request,
            "device": devices[device_id],
            "message": f"Effect set to {effect}",
        },
    )


@app.post("/devices/{device_id}/power", response_class=HTMLResponse)
async def set_power(
    request: Request,
    device_id: str,
    power: str = Form(...),
    user: User = Depends(require_auth),
):
    """Toggle device power."""
    if device_id not in devices:
        raise HTTPException(status_code=404, detail="Device not found")

    power_on = power == "on"

    # Send command to device
    mqtt_client.send_command(device_id, {"power": power_on})

    # Update local state optimistically
    devices[device_id]["power"] = power_on

    # Return updated device card
    return templates.TemplateResponse(
        "partials/device_card.html",
        {
            "request": request,
            "device": devices[device_id],
            "message": f"Power {'ON' if power_on else 'OFF'}",
        },
    )


@app.post("/devices/{device_id}/name", response_class=HTMLResponse)
async def set_device_name(
    request: Request,
    device_id: str,
    friendly_name: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_auth),
):
    """Set device friendly name."""
    if device_id not in devices:
        raise HTTPException(status_code=404, detail="Device not found")

    # Update in database
    device = db.query(Device).filter(Device.device_id == device_id).first()
    if device:
        device.friendly_name = friendly_name.strip() or None
        db.commit()

    # Update in-memory state
    devices[device_id]["friendly_name"] = friendly_name.strip() or None

    # Return updated device card
    return templates.TemplateResponse(
        "partials/device_card.html",
        {
            "request": request,
            "device": devices[device_id],
            "message": f"Name updated to '{friendly_name}'" if friendly_name.strip() else "Name cleared",
        },
    )


# ===================
# Internal API Endpoints (on api_app, port 8001, no auth)
# ===================
@api_app.get("/health")
async def api_health():
    """Health check endpoint."""
    return {"status": "ok", "mqtt_connected": mqtt_client.connected}


@api_app.get("/devices")
async def api_list_devices():
    """List all devices."""
    return list(devices.values())


@api_app.get("/devices/{device_id}")
async def api_get_device(device_id: str):
    """Get a specific device."""
    if device_id not in devices:
        raise HTTPException(status_code=404, detail="Device not found")
    return devices[device_id]


@api_app.post("/devices/{device_id}/color")
async def api_set_color(device_id: str, r: int, g: int, b: int):
    """Set device color."""
    if device_id not in devices:
        raise HTTPException(status_code=404, detail="Device not found")
    mqtt_client.send_command(device_id, {"color": {"r": r, "g": g, "b": b}})
    devices[device_id]["color"] = {"r": r, "g": g, "b": b}
    return devices[device_id]


@api_app.post("/devices/{device_id}/brightness")
async def api_set_brightness(device_id: str, brightness: int):
    """Set device brightness (0-100)."""
    if device_id not in devices:
        raise HTTPException(status_code=404, detail="Device not found")
    mqtt_client.send_command(device_id, {"brightness": brightness})
    devices[device_id]["brightness"] = brightness
    return devices[device_id]


@api_app.post("/devices/{device_id}/effect")
async def api_set_effect(device_id: str, effect: str):
    """Set device effect."""
    if device_id not in devices:
        raise HTTPException(status_code=404, detail="Device not found")
    mqtt_client.send_command(device_id, {"effect": effect})
    devices[device_id]["effect"] = effect
    return devices[device_id]


@api_app.post("/devices/{device_id}/power")
async def api_set_power(device_id: str, power: bool):
    """Set device power on/off."""
    if device_id not in devices:
        raise HTTPException(status_code=404, detail="Device not found")
    mqtt_client.send_command(device_id, {"power": power})
    devices[device_id]["power"] = power
    return devices[device_id]
