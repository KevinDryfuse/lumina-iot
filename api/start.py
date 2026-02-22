"""
Start both the UI server (port 8000) and API server (port 8001).

Initialization (DB, MQTT, device loading) happens here before
either server starts. Both apps share the same process and state.
"""

import asyncio
import uvicorn

from src.db import init_db
from src.mqtt import mqtt_client
from src.main import app, api_app


async def main():
    # Initialize everything before either server starts
    init_db()
    print("Database initialized")

    mqtt_client.load_devices_from_db()
    mqtt_client.connect()

    ui_config = uvicorn.Config(app, host="0.0.0.0", port=8000, log_level="info")
    api_config = uvicorn.Config(api_app, host="0.0.0.0", port=8001, log_level="info")

    ui_server = uvicorn.Server(ui_config)
    api_server = uvicorn.Server(api_config)

    try:
        await asyncio.gather(ui_server.serve(), api_server.serve())
    finally:
        mqtt_client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
