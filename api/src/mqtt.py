"""
MQTT client for Lumina IoT.

Handles communication with ESP32 devices via Mosquitto broker.
"""

import json
import os
import threading
import time
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
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self.connected = False
        self._broker = MQTT_BROKER
        self._port = MQTT_PORT

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        """Handle connection to broker."""
        if reason_code == 0:
            print(f"Connected to MQTT broker successfully")
            self.connected = True
            client.subscribe("devices/announce")
            client.subscribe("lights/+/state")
            print("Subscribed to device topics")
        else:
            print(f"MQTT connection failed with reason code: {reason_code}")
            self.connected = False

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        """Handle disconnection from broker."""
        print(f"Disconnected from MQTT broker: {reason_code}")
        self.connected = False

    def _on_message(self, client, userdata, msg):
        """Handle incoming MQTT messages."""
        topic = msg.topic
        try:
            payload = json.loads(msg.payload.decode())
        except json.JSONDecodeError:
            print(f"Invalid JSON on topic {topic}")
            return

        #
        # Never let a handler escape.
        #
        # paho re-raises out of on_message and its loop thread is try/finally
        # only, so one bad payload killed the thread outright - and because
        # on_disconnect never fired, `connected` stayed True and /health went on
        # saying so. Publishes then went out on a dead socket until the broker
        # dropped it, after which nothing reconnected and no announce or state
        # message was ever processed again.
        #
        # Any device on this LAN can publish to the broker, so this needs no
        # firmware bug to trigger: a single `{"color":"red"}` was enough.
        #
        try:
            if topic == "devices/announce":
                self._handle_device_announce(payload)
            elif topic.startswith("lights/") and topic.endswith("/state"):
                self._handle_state_update(payload)
        except Exception as e:
            print(f"handler failed for {topic}: {type(e).__name__}: {e}")

    def _handle_device_announce(self, payload: dict):
        """Handle device announcement (new device or reconnection)."""
        device_id = payload.get("device_id")
        if not device_id:
            return

        print(f"Device announced: {device_id}")

        reported = payload.get("config") or {}

        # Update in-memory state
        if device_id not in devices:
            devices[device_id] = {
                "device_id": device_id,
                "last_seen": time.time(),
                "power": True,
                "brightness": 100,
                "color": {"r": 255, "g": 255, "b": 255},
                "effect": "none",
            }
        else:
            devices[device_id]["last_seen"] = time.time()

        # Persist to database
        send_config = None
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

            fw = payload.get("fw")
            device.fw_version = fw if isinstance(fw, int) else None

            #
            # Reconcile hardware configuration.
            #
            # A strip we have never seen is believed: whatever it reports gets
            # adopted as the record. A strip we DO have a record for is
            # corrected, because the record is what someone edited in the UI and
            # the device may be a freshly flashed board that has come up on
            # conservative defaults.
            #
            # Only send when they actually differ. A config message costs the
            # device a restart, and restarting every strip in the house whenever
            # the API happens to redeploy would be its own kind of bug.
            #
            stored = device.config_dict()
            if stored is None and reported:
                device.led_count = reported.get("led_count")
                device.led_pin = reported.get("pin")
                device.led_type = reported.get("type")
                device.led_order = reported.get("order")
                print(f"Adopted reported config from {device_id}: {reported}")
            elif stored is not None and reported != stored:
                send_config = stored
                print(f"Config mismatch on {device_id}: "
                      f"device has {reported}, sending {stored}")

            db.commit()
            stored_after = device.config_dict()
        finally:
            db.close()

        # Mirror into the in-memory record so /devices carries it and the UI can
        # render a card without a second round trip per device.
        devices[device_id]["config"] = stored_after
        devices[device_id]["fw_version"] = payload.get("fw")

        # Outside the session: publishing can block, and a DB session held open
        # across network I/O is how connection pools get exhausted.
        if send_config:
            self.send_command(device_id, {"config": send_config})

    def _handle_state_update(self, payload: dict):
        """Handle device state update."""
        device_id = payload.get("device_id")
        if not device_id or device_id not in devices:
            return

        print(f"State update from {device_id}: {payload}")

        devices[device_id]["last_seen"] = time.time()

        # Update in-memory state
        if "power" in payload:
            devices[device_id]["power"] = payload["power"]
        if "brightness" in payload:
            devices[device_id]["brightness"] = payload["brightness"]
        if isinstance(payload.get("color"), dict):
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
        """Connect to the MQTT broker with retry logic."""
        def _connect_with_retry():
            max_retries = 10
            for attempt in range(1, max_retries + 1):
                try:
                    print(f"Connecting to MQTT broker at {self._broker}:{self._port} (attempt {attempt}/{max_retries})")
                    self.client.connect(self._broker, self._port, 60)
                    self.client.loop_start()
                    print("MQTT loop started, waiting for CONNACK...")
                    return
                except Exception as e:
                    print(f"MQTT connection attempt {attempt} failed: {e}")
                    if attempt < max_retries:
                        time.sleep(2)
                    else:
                        print(f"MQTT failed after {max_retries} attempts. Will rely on paho auto-reconnect.")
                        self.client.loop_start()

        _connect_with_retry()

    def disconnect(self):
        """Disconnect from the MQTT broker."""
        self.client.loop_stop()
        self.client.disconnect()
        print("Disconnected from MQTT broker")

    def send_ota(self, device_id: str, url: str):
        """Tell a device to fetch and install new firmware.

        Sent on its own, never alongside other keys: the device acts on it
        immediately and reboots, so anything else in the same payload would be
        silently dropped.
        """
        self.send_command(device_id, {"ota": url})

    def send_command(self, device_id: str, payload: dict):
        """Send a command to a device.

        Refuses rather than publishing into a void. paho accepts a publish on a
        disconnected client and returns a result nobody was checking, so a
        command issued while the broker was unreachable vanished with no error,
        no log line and a 200 back to the caller.

        That is not hypothetical: firing an OTA seconds after restarting this
        service - before its own MQTT client had reconnected - silently did
        nothing, and the only symptom was a firmware version that never changed.
        """
        topic = f"lights/{device_id}/set"

        if not self.connected:
            print(f"REFUSED {topic}: not connected to the broker")
            raise RuntimeError("not connected to the MQTT broker")

        info = self.client.publish(topic, json.dumps(payload))
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            print(f"FAILED {topic}: publish returned rc={info.rc}")
            raise RuntimeError(f"MQTT publish failed (rc={info.rc})")

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
                devices[device.device_id] = {
                    "device_id": device.device_id,
                    "friendly_name": device.friendly_name,
                    "last_seen": device.last_seen.timestamp() if device.last_seen else 0,
                    "power": True,  # Assume on at startup
                    "brightness": state.brightness if state else 100,
                    "color": {
                        "r": state.color_r if state else 255,
                        "g": state.color_g if state else 255,
                        "b": state.color_b if state else 255,
                    },
                    "effect": state.effect if state else "none",
                    "config": device.config_dict(),
                    "fw_version": device.fw_version,
                }
            print(f"Loaded {len(devices)} devices from database")
        finally:
            db.close()


# Global MQTT client instance
mqtt_client = MQTTClient()
