"""
Start both the UI server (port 8000) and API server (port 8001).

Both run in a single process so they share the same MQTT connection
and in-memory device state. The UI app's lifespan handles all
initialization (DB, MQTT, device loading).

We import the app objects directly (not via string) to guarantee
both servers reference the same module-level state.
"""

import asyncio
import uvicorn

from src.main import app, api_app


async def main():
    ui_config = uvicorn.Config(app, host="0.0.0.0", port=8000, log_level="info")
    api_config = uvicorn.Config(api_app, host="0.0.0.0", port=8001, log_level="info")

    ui_server = uvicorn.Server(ui_config)
    api_server = uvicorn.Server(api_config)

    await asyncio.gather(ui_server.serve(), api_server.serve())


if __name__ == "__main__":
    asyncio.run(main())
