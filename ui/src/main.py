"""
Lumina IoT - UI Service

HTMX-based frontend. Calls the API service over HTTP for all
device operations. Handles its own auth against the shared DB.
"""

from pathlib import Path

from fastapi import FastAPI, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .db import get_db
from .auth import (
    authenticate_user,
    create_session_token,
    get_current_user,
    require_auth,
    SESSION_COOKIE_NAME,
    User,
)
from . import api_client

TEMPLATE_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

app = FastAPI(
    title="Lumina IoT",
    description="LED strip controller with HTMX UI",
    version="0.1.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


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
# Dashboard
# ===================
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    """Main dashboard showing all devices."""
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    devices = await api_client.get_all_devices()

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "devices": devices,
        },
    )


# ===================
# Device Control (HTMX endpoints — calls API over HTTP)
# ===================
@app.get("/devices/{device_id}/card", response_class=HTMLResponse)
async def get_device_card(
    request: Request,
    device_id: str,
    user: User = Depends(require_auth),
):
    """Get a single device card (for HTMX refresh)."""
    device = await api_client.get_device(device_id)
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

    device = await api_client.set_color(device_id, r, g, b)

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

    device = await api_client.set_settings(device_id, r, g, b, brightness)

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
    device = await api_client.set_effect(device_id, effect)

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
    device = await api_client.set_power(device_id, power_on)

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
    device = await api_client.set_name(device_id, friendly_name)

    return templates.TemplateResponse(
        "partials/device_card.html",
        {
            "request": request,
            "device": device,
            "message": f"Name updated to '{friendly_name}'" if friendly_name.strip() else "Name cleared",
        },
    )
