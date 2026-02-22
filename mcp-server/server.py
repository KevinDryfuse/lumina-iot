"""
Lumina IoT MCP Server

Exposes LED strip controls as Claude-compatible tools.
Talks to the Lumina internal API (no auth required).
"""

import os

import httpx
from mcp.server.fastmcp import FastMCP

BASE_URL = os.environ.get("LUMINA_API_URL", "http://192.168.1.55:8001")

VALID_EFFECTS = [
    "none", "rainbow", "breathing", "chase", "sparkle",
    "fire", "confetti", "cylon", "strobe",
    "ocean", "aurora", "candle",
    "christmas", "usa",
]

mcp = FastMCP(
    "Lumina IoT",
    description="Control LED strip lights in the house",
)


async def _get_target_devices(client: httpx.AsyncClient, device_id: str | None) -> list[str]:
    """Resolve target device(s). If device_id is None, return all device IDs."""
    if device_id:
        return [device_id]
    resp = await client.get(f"{BASE_URL}/devices")
    resp.raise_for_status()
    return [d["device_id"] for d in resp.json()]


def _format_device(d: dict) -> str:
    """Format a device dict into a readable string."""
    name = d.get("friendly_name") or d["device_id"]
    color = d.get("color", {})
    rgb = f"({color.get('r', 0)}, {color.get('g', 0)}, {color.get('b', 0)})"
    return (
        f"  {name} ({d['device_id']})\n"
        f"    online={d.get('online', False)}, power={'on' if d.get('power') else 'off'}, "
        f"brightness={d.get('brightness', 0)}, color=RGB{rgb}, effect={d.get('effect', 'none')}"
    )


@mcp.tool()
async def list_devices() -> str:
    """List all connected LED strip devices and their current state."""
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.get(f"{BASE_URL}/devices")
            resp.raise_for_status()
        except httpx.ConnectError:
            return f"Could not connect to Lumina API at {BASE_URL}. Is Docker Compose running?"

        device_list = resp.json()
        if not device_list:
            return "No devices found. Make sure your ESP32 is powered on and connected to MQTT."

        lines = [f"Found {len(device_list)} device(s):\n"]
        for d in device_list:
            lines.append(_format_device(d))
        return "\n".join(lines)


@mcp.tool()
async def get_device(device_id: str) -> str:
    """Get the current state of a specific LED strip device.

    Args:
        device_id: The device identifier (e.g. "esp32-abc123")
    """
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.get(f"{BASE_URL}/devices/{device_id}")
        except httpx.ConnectError:
            return f"Could not connect to Lumina API at {BASE_URL}. Is Docker Compose running?"

        if resp.status_code == 404:
            return f"Device '{device_id}' not found. Use list_devices to see available devices."
        resp.raise_for_status()
        return _format_device(resp.json())


@mcp.tool()
async def set_color(r: int, g: int, b: int, device_id: str | None = None) -> str:
    """Set the RGB color of an LED strip.

    Args:
        r: Red value (0-255)
        g: Green value (0-255)
        b: Blue value (0-255)
        device_id: Target device ID. Omit to set ALL devices.
    """
    r = max(0, min(255, r))
    g = max(0, min(255, g))
    b = max(0, min(255, b))

    async with httpx.AsyncClient(timeout=10) as client:
        try:
            targets = await _get_target_devices(client, device_id)
        except httpx.ConnectError:
            return f"Could not connect to Lumina API at {BASE_URL}. Is Docker Compose running?"

        results = []
        for did in targets:
            resp = await client.post(f"{BASE_URL}/devices/{did}/color", params={"r": r, "g": g, "b": b})
            if resp.status_code == 404:
                results.append(f"  {did}: not found")
            else:
                resp.raise_for_status()
                d = resp.json()
                name = d.get("friendly_name") or did
                results.append(f"  {name}: color set to RGB({r}, {g}, {b})")

        return f"Set color to RGB({r}, {g}, {b}):\n" + "\n".join(results)


@mcp.tool()
async def set_brightness(brightness: int, device_id: str | None = None) -> str:
    """Set the brightness of an LED strip.

    Args:
        brightness: Brightness level (0-100)
        device_id: Target device ID. Omit to set ALL devices.
    """
    brightness = max(0, min(100, brightness))

    async with httpx.AsyncClient(timeout=10) as client:
        try:
            targets = await _get_target_devices(client, device_id)
        except httpx.ConnectError:
            return f"Could not connect to Lumina API at {BASE_URL}. Is Docker Compose running?"

        results = []
        for did in targets:
            resp = await client.post(f"{BASE_URL}/devices/{did}/brightness", params={"brightness": brightness})
            if resp.status_code == 404:
                results.append(f"  {did}: not found")
            else:
                resp.raise_for_status()
                d = resp.json()
                name = d.get("friendly_name") or did
                results.append(f"  {name}: brightness set to {brightness}%")

        return f"Set brightness to {brightness}%:\n" + "\n".join(results)


@mcp.tool()
async def set_effect(effect: str, device_id: str | None = None) -> str:
    """Set the lighting effect on an LED strip.

    Available effects: none, rainbow, breathing, chase, sparkle, fire, confetti,
    cylon, strobe, ocean, aurora, candle, christmas, usa

    Args:
        effect: Effect name (see list above)
        device_id: Target device ID. Omit to set ALL devices.
    """
    effect = effect.lower().strip()
    if effect not in VALID_EFFECTS:
        return f"Unknown effect '{effect}'. Valid effects: {', '.join(VALID_EFFECTS)}"

    async with httpx.AsyncClient(timeout=10) as client:
        try:
            targets = await _get_target_devices(client, device_id)
        except httpx.ConnectError:
            return f"Could not connect to Lumina API at {BASE_URL}. Is Docker Compose running?"

        results = []
        for did in targets:
            resp = await client.post(f"{BASE_URL}/devices/{did}/effect", params={"effect": effect})
            if resp.status_code == 404:
                results.append(f"  {did}: not found")
            else:
                resp.raise_for_status()
                d = resp.json()
                name = d.get("friendly_name") or did
                results.append(f"  {name}: effect set to {effect}")

        return f"Set effect to '{effect}':\n" + "\n".join(results)


@mcp.tool()
async def set_power(power: bool, device_id: str | None = None) -> str:
    """Turn an LED strip on or off.

    Args:
        power: True to turn on, False to turn off
        device_id: Target device ID. Omit to set ALL devices.
    """
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            targets = await _get_target_devices(client, device_id)
        except httpx.ConnectError:
            return f"Could not connect to Lumina API at {BASE_URL}. Is Docker Compose running?"

        state = "on" if power else "off"
        results = []
        for did in targets:
            resp = await client.post(f"{BASE_URL}/devices/{did}/power", params={"power": power})
            if resp.status_code == 404:
                results.append(f"  {did}: not found")
            else:
                resp.raise_for_status()
                d = resp.json()
                name = d.get("friendly_name") or did
                results.append(f"  {name}: turned {state}")

        return f"Power {state}:\n" + "\n".join(results)


if __name__ == "__main__":
    mcp.run(transport="stdio")
