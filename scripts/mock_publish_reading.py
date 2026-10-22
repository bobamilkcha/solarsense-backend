"""Publish a single realistic mock reading to EMQX Cloud for manual subscriber testing.

The reading matches Malaysian (Kuala Lumpur) conditions at the given time —
near-zero sunlight at night, several hundred W/m² around midday, ~24-34 °C,
humid — using the same PVGIS-calibrated weather model as
scripts/mock_publish_series.py. For many readings over a date range, use that
script instead.

Standalone: reads MQTT_* settings straight from .env instead of importing the app
(importing app.core.config would eagerly stand up the DB engine). The target
device_id must already exist as a Site.device_id row, or the subscriber will log
`mqtt_unknown_device` and drop the message.

Usage:
    uv run python -m scripts.mock_publish_reading <device_id>
    uv run python -m scripts.mock_publish_reading <device_id> --at 2026-10-23T13:00
"""

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path

import paho.mqtt.client as mqtt
from dotenv import dotenv_values

from scripts.mock_weather import LOCAL_TZ, MockOptions, MockReading, generate

ENV = dotenv_values(Path(__file__).resolve().parent.parent / ".env")

BROKER_HOST = ENV.get("MQTT_BROKER_HOST") or "localhost"
BROKER_PORT = int(ENV.get("MQTT_BROKER_PORT") or "8883")
USERNAME = ENV.get("MQTT_USERNAME") or ""
PASSWORD = ENV.get("MQTT_PASSWORD") or ""
USE_TLS = (ENV.get("MQTT_USE_TLS") or "true").lower() == "true"
ISC_A = float(ENV.get("REFERENCE_CELL_ISC_A") or 0.22)


def build_reading(at: datetime) -> MockReading:
    opts = MockOptions(isc_a=ISC_A)
    return next(generate(at, at + timedelta(seconds=1), opts))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("device_id")
    parser.add_argument(
        "--at",
        help="Reading time, e.g. 2026-10-23T13:00 (Malaysian time if no offset); default now",
    )
    args = parser.parse_args()

    if args.at:
        at = datetime.fromisoformat(args.at)
        at = at.replace(tzinfo=LOCAL_TZ) if at.tzinfo is None else at
    else:
        at = datetime.now(LOCAL_TZ).replace(microsecond=0)

    reading = build_reading(at)
    topic = f"solarsense/{args.device_id}/readings"
    payload = reading.payload()

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
    print(f"(≈ {reading.irradiance_wm2:.0f} W/m² sunlight at {reading.timestamp:%H:%M} MYT)")


if __name__ == "__main__":
    main()
