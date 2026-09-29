"""Publish a single mock sensor reading to EMQX Cloud for manual subscriber testing.

Standalone: reads MQTT_* settings straight from .env instead of importing the app
(importing app.core.config would eagerly stand up the DB engine). The target
device_id must already exist as a Site.device_id row, or the subscriber will log
`mqtt_unknown_device` and drop the message.

Usage:
    uv run python scripts/mock_publish_reading.py <device_id>
"""

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import paho.mqtt.client as mqtt
from dotenv import dotenv_values

ENV = dotenv_values(Path(__file__).resolve().parent.parent / ".env")

BROKER_HOST = ENV.get("MQTT_BROKER_HOST", "localhost")
BROKER_PORT = int(ENV.get("MQTT_BROKER_PORT", "8883"))
USERNAME = ENV.get("MQTT_USERNAME", "")
PASSWORD = ENV.get("MQTT_PASSWORD", "")
USE_TLS = ENV.get("MQTT_USE_TLS", "true").lower() == "true"


def build_payload() -> dict:
    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "cell_voltage": 3.42,
        "ambient_temp": 31.5,
        "humidity": 68.2,
        "tilt_x": 12.3,
        "tilt_y": -4.1,
        "tilt_z": 89.7,
        "heading": 215.6,
    }


def main() -> None:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <device_id>", file=sys.stderr)
        sys.exit(1)

    device_id = sys.argv[1]
    topic = f"solarsense/{device_id}/readings"
    payload = build_payload()

    client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    if USERNAME:
        client.username_pw_set(USERNAME, PASSWORD)
    if USE_TLS:
        client.tls_set()

    client.connect(BROKER_HOST, BROKER_PORT)
    client.loop_start()

    info = client.publish(topic, json.dumps(payload), qos=1)
    info.wait_for_publish(timeout=10)

    client.loop_stop()
    client.disconnect()

    print(f"Published to {topic}:")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
