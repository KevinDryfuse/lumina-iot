"""
HTTP client for the Lumina API service.

The UI calls the API over HTTP for all device operations.
"""

import os

import httpx

API_URL = os.getenv("API_URL", "http://api:8001")


async def get_all_devices() -> list[dict]:
    """Fetch all devices from the API."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{API_URL}/devices")
        resp.raise_for_status()
        return resp.json()


async def get_device(device_id: str) -> dict:
    """Fetch a single device from the API."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{API_URL}/devices/{device_id}")
        resp.raise_for_status()
        return resp.json()


async def set_color(device_id: str, r: int, g: int, b: int) -> dict:
    """Set device color via the API."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{API_URL}/devices/{device_id}/color",
            params={"r": r, "g": g, "b": b},
        )
        resp.raise_for_status()
        return resp.json()


async def set_brightness(device_id: str, brightness: int) -> dict:
    """Set device brightness via the API."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{API_URL}/devices/{device_id}/brightness",
            params={"brightness": brightness},
        )
        resp.raise_for_status()
        return resp.json()


async def set_effect(device_id: str, effect: str) -> dict:
    """Set device effect via the API."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{API_URL}/devices/{device_id}/effect",
            params={"effect": effect},
        )
        resp.raise_for_status()
        return resp.json()


async def set_power(device_id: str, power: bool) -> dict:
    """Set device power via the API."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{API_URL}/devices/{device_id}/power",
            params={"power": power},
        )
        resp.raise_for_status()
        return resp.json()


async def set_name(device_id: str, friendly_name: str) -> dict:
    """Set device friendly name via the API."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{API_URL}/devices/{device_id}/name",
            params={"friendly_name": friendly_name},
        )
        resp.raise_for_status()
        return resp.json()


async def set_config(device_id: str, led_count: int, pin: int,
                     led_type: str, order: str) -> dict:
    """Set device hardware configuration. The device restarts to apply it."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{API_URL}/devices/{device_id}/config",
            params={"led_count": led_count, "pin": pin,
                    "led_type": led_type, "order": order},
        )
        resp.raise_for_status()
        return resp.json()


async def send_ota(device_id: str, file: str) -> dict:
    """Start an over-the-air firmware update from a staged image."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{API_URL}/devices/{device_id}/ota", params={"file": file},
        )
        resp.raise_for_status()
        return resp.json()


async def list_firmware() -> dict:
    """Firmware images staged for OTA."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{API_URL}/firmware")
        resp.raise_for_status()
        return resp.json()


async def set_settings(device_id: str, r: int, g: int, b: int, brightness: int) -> dict:
    """Set device color and brightness via the API (two calls)."""
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(
            f"{API_URL}/devices/{device_id}/color",
            params={"r": r, "g": g, "b": b},
        )
        resp = await client.post(
            f"{API_URL}/devices/{device_id}/brightness",
            params={"brightness": brightness},
        )
        resp.raise_for_status()
        return resp.json()
