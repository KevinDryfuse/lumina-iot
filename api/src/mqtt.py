"""
MQTT client for Lumina IoT.

Handles communication with ESP32 devices via Mosquitto broker.
"""

import json
import os
from datetime import datetime
from typing import Callable, Optional

import paho.mqtt.client as mqtt
from sqlalchemy.orm import Session

from .db import SessionLocal, Device, DeviceState

MQTT_BROKER = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))

# In-memory device state (for quick access, synced with DB)
devices: dict[str, dict] = {}

# Callback for notifying UI of state changes (set by main.py)
on_state_change: Optional[Callable] = None


class MQTTClient:
    """MQTT client for device communication."""

    def __init__(self):
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.connected = False

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        """Handle connection to broker."""
        print(f"Connected to MQTT broker: {reason_code}")
        self.connected = True

        # Subscribe to device topics
        client.subscribe("devices/announce")
        client.subscribe("lights/+/state")
        print("Subscribed to device topics")

    def _on_message(self, client, userdata, msg):
        """Handle incoming MQTT messages."""
        topic = msg.topic
        try:
            payload = json.loads(msg.payload.decode())
        except json.JSONDecodeError:
            print(f"Invalid JSON on topic {topic}")
            return

        if topic == "devices/announce":
            self._handle_device_announce(payload)
        elif topic.startswith("lights/") and topic.endswith("/state"):
            self._handle_state_update(payload)

    def _handle_device_announce(self, payload: dict):
        """Handle device announcement (new device or reconnection)."""
        device_id = payload.get("device_id")
        if not device_id:
            return

        print(f"Device announced: {device_id}")

        # Update in-memory state
        if device_id not in devices:
            devices[device_id] = {
                "device_id": device_id,
                "online": True,
                "power": True,
                "brightness": 100,
                "color": {"r": 255, "g": 255, "b": 255},
                "effect": "none",
            }
        else:
            devices[device_id]["online"] = True

        # Persist to database
        db = SessionLocal()
        try:
            device = db.query(Device).filter(Device.device_id == device_id).first()
            if not device:
                device = Device(
                    device_id=device_id,
                    device_type=payload.get("type", "led_strip"),
                    last_seen=datetime.utcnow(),
                )
                db.add(device)
                db.commit()

                # Create initial state
                state = DeviceState(device_id=device_id)
                db.add(state)
                db.commit()
                print(f"New device registered: {device_id}")
            else:
                device.last_seen = datetime.utcnow()
                db.commit()
                print(f"Device reconnected: {device_id}")
        finally:
            db.close()

    def _handle_state_update(self, payload: dict):
        """Handle device state update."""
        device_id = payload.get("device_id")
        if not device_id or device_id not in devices:
            return

        print(f"State update from {device_id}: {payload}")

        # Mark device as online (it's responding)
        devices[device_id]["online"] = True

        # Update in-memory state
        if "power" in payload:
            devices[device_id]["power"] = payload["power"]
        if "brightness" in payload:
            devices[device_id]["brightness"] = payload["brightness"]
        if "color" in payload:
            devices[device_id]["color"] = payload["color"]
        if "effect" in payload:
            devices[device_id]["effect"] = payload["effect"]

        # Persist to database
        db = SessionLocal()
        try:
            # Update last_seen on the device
            device = db.query(Device).filter(Device.device_id == device_id).first()
            if device:
                device.last_seen = datetime.utcnow()

            state = db.query(DeviceState).filter(DeviceState.device_id == device_id).first()
            if state:
                if "brightness" in payload:
                    state.brightness = payload["brightness"]
                if "color" in payload:
                    state.color_r = payload["color"].get("r", state.color_r)
                    state.color_g = payload["color"].get("g", state.color_g)
                    state.color_b = payload["color"].get("b", state.color_b)
                if "effect" in payload:
                    state.effect = payload["effect"]
            db.commit()
        finally:
            db.close()

        # Notify UI
        if on_state_change:
            on_state_change(device_id, devices[device_id])

    def connect(self):
        """Connect to the MQTT broker."""
        print(f"Connecting to MQTT broker at {MQTT_BROKER}:{MQTT_PORT}")
        self.client.connect(MQTT_BROKER, MQTT_PORT, 60)
        self.client.loop_start()

    def disconnect(self):
        """Disconnect from the MQTT broker."""
        self.client.loop_stop()
        self.client.disconnect()
        print("Disconnected from MQTT broker")

    def send_command(self, device_id: str, payload: dict):
        """Send a command to a device."""
        topic = f"lights/{device_id}/set"
        self.client.publish(topic, json.dumps(payload))
        print(f"Sent to {topic}: {payload}")

    def load_devices_from_db(self):
        """Load persisted device state from database on startup."""
        db = SessionLocal()
        try:
            db_devices = db.query(Device).all()
            now = datetime.utcnow()
            for device in db_devices:
                state = device.state
                # Consider device online if seen within last 5 minutes
                recently_seen = (
                    device.last_seen
                    and (now - device.last_seen).total_seconds() < 300
                )
                devices[device.device_id] = {
                    "device_id": device.device_id,
                    "friendly_name": device.friendly_name,
                    "online": recently_seen,
                    "power": True,  # Assume on at startup
                    "brightness": state.brightness if state else 100,
                    "color": {
                        "r": state.color_r if state else 255,
                        "g": state.color_g if state else 255,
                        "b": state.color_b if state else 255,
                    },
                    "effect": state.effect if state else "none",
                }
            print(f"Loaded {len(devices)} devices from database")
        finally:
            db.close()


# Global MQTT client instance
mqtt_client = MQTTClient()
