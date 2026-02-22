"""
Lumina IoT - FastAPI Application

LED strip controller with HTMX-based UI.

Two apps are exposed:
- app (port 8000): UI only, with auth, no docs - exposed to internet
- api_app (port 8001): JSON API with docs, no auth - internal only

All device control logic lives in services.py. Both apps call
the service layer instead of touching MQTT/devices directly.
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .db import get_db, init_db
from .auth import (
    authenticate_user,
    create_session_token,
    get_current_user,
    require_auth,
    SESSION_COOKIE_NAME,
    User,
)
from .mqtt import mqtt_client
from . import services as device_service

# Template directory
TEMPLATE_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    init_db()
    print("Database initialized")

    mqtt_client.load_devices_from_db()
    mqtt_client.connect()

    yield

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

    token = create_session_token(user.id)
    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        max_age=60 * 60 * 24 * 7,
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
            "devices": device_service.get_all_devices(),
        },
    )


# ===================
# Device Control (HTMX endpoints — thin wrappers around service layer)
# ===================
@app.get("/devices/{device_id}/card", response_class=HTMLResponse)
async def get_device_card(
    request: Request,
    device_id: str,
    user: User = Depends(require_auth),
):
    """Get a single device card (for HTMX refresh)."""
    device = device_service.get_device(device_id)
    return templates.TemplateResponse(
        "partials/device_card.html",
        {"request": request, "device": device},
    )


@app.post("/devices/{device_id}/color", response_class=HTMLResponse)
async def set_color(
    request: Request,
    device_id: str,
    color: str = Form(...),
    user: User = Depends(require_auth),
):
    """Set device color."""
    hex_color = color.lstrip("#")
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)

    device = device_service.set_color(device_id, r, g, b)

    return templates.TemplateResponse(
        "partials/device_card.html",
        {
            "request": request,
            "device": device,
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
    hex_color = color.lstrip("#")
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)

    device_service.set_color(device_id, r, g, b)
    device = device_service.set_brightness(device_id, brightness)

    return templates.TemplateResponse(
        "partials/device_card.html",
        {
            "request": request,
            "device": device,
            "message": "Settings applied",
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
    device = device_service.set_effect(device_id, effect)

    return templates.TemplateResponse(
        "partials/device_card.html",
        {
            "request": request,
            "device": device,
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
    power_on = power == "on"
    device = device_service.set_power(device_id, power_on)

    return templates.TemplateResponse(
        "partials/device_card.html",
        {
            "request": request,
            "device": device,
            "message": f"Power {'ON' if power_on else 'OFF'}",
        },
    )


@app.post("/devices/{device_id}/name", response_class=HTMLResponse)
async def set_device_name(
    request: Request,
    device_id: str,
    friendly_name: str = Form(...),
    user: User = Depends(require_auth),
):
    """Set device friendly name."""
    device = device_service.set_name(device_id, friendly_name)

    return templates.TemplateResponse(
        "partials/device_card.html",
        {
            "request": request,
            "device": device,
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
    return device_service.get_all_devices()


@api_app.get("/devices/{device_id}")
async def api_get_device(device_id: str):
    """Get a specific device."""
    return device_service.get_device(device_id)


@api_app.post("/devices/{device_id}/color")
async def api_set_color(device_id: str, r: int, g: int, b: int):
    """Set device color."""
    return device_service.set_color(device_id, r, g, b)


@api_app.post("/devices/{device_id}/brightness")
async def api_set_brightness(device_id: str, brightness: int):
    """Set device brightness (0-100)."""
    return device_service.set_brightness(device_id, brightness)


@api_app.post("/devices/{device_id}/effect")
async def api_set_effect(device_id: str, effect: str):
    """Set device effect."""
    return device_service.set_effect(device_id, effect)


@api_app.post("/devices/{device_id}/power")
async def api_set_power(device_id: str, power: bool):
    """Set device power on/off."""
    return device_service.set_power(device_id, power)


@api_app.post("/devices/{device_id}/name")
async def api_set_name(device_id: str, friendly_name: str):
    """Set device friendly name."""
    return device_service.set_name(device_id, friendly_name)
