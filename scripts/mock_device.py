"""Pretend to be a SolarSense device on EMQX, so remote config works without hardware.

Behaves like the firmware: connects with a Last Will (`online: false`), publishes
a retained status on connect, publishes readings every `publish_interval_s`, and
on every message to `solarsense/<id>/config` applies it (5-3600 s only) and
publishes a fresh status. Ctrl+C disconnects uncleanly so the broker sends the Will.

Standalone like the other mock scripts: MQTT_* settings come straight from .env.

Usage:
    uv run python -m scripts.mock_device solarsense-38BB0B71FE68
    uv run python -m scripts.mock_device solarsense-38BB0B71FE68 --interval 10 --null-ts
"""

import argparse
import json
import threading
import time
from datetime import datetime
from pathlib import Path

import paho.mqtt.client as mqtt
from dotenv import dotenv_values

from scripts.mock_weather import LOCAL_TZ, MockOptions, generate

ENV = dotenv_values(Path(__file__).resolve().parent.parent / ".env")

BROKER_HOST = ENV.get("MQTT_BROKER_HOST") or "localhost"
BROKER_PORT = int(ENV.get("MQTT_BROKER_PORT") or "8883")
USERNAME = ENV.get("MQTT_USERNAME") or ""
PASSWORD = ENV.get("MQTT_PASSWORD") or ""
USE_TLS = (ENV.get("MQTT_USE_TLS") or "true").lower() == "true"
ISC_A = float(ENV.get("ISC_STC_MA") or 220) / 1000

FIRMWARE = "0.3.0-mock"
MIN_INTERVAL_S, MAX_INTERVAL_S = 5, 3600


class MockDevice:
    def __init__(self, device_id: str, interval_s: int, null_ts: bool) -> None:
        self.device_id = device_id
        self.interval_s = interval_s
        self.null_ts = null_ts
        self._wake = threading.Event()
        self._stop = threading.Event()

        # The device ID is the client ID, as on the real firmware.
        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2, client_id=device_id
        )
        if USERNAME:
            self.client.username_pw_set(USERNAME, PASSWORD)
        if USE_TLS:
            self.client.tls_set()
        self.client.will_set(
            self._topic("status"),
            json.dumps({"device": device_id, "online": False}),
            qos=1,
            retain=True,
        )
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

    def _topic(self, leaf: str) -> str:
        return f"solarsense/{self.device_id}/{leaf}"

    def _publish_status(self) -> None:
        body = {
            "device": self.device_id,
            "online": True,
            "fw": FIRMWARE,
            "publish_interval_s": self.interval_s,
            "ts": int(time.time()),
        }
        self.client.publish(self._topic("status"), json.dumps(body), qos=1, retain=True)
        print(f"status -> {body}")

    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        client.subscribe(self._topic("config"), qos=1)
        self._publish_status()

    def _on_message(self, client, userdata, msg) -> None:
        try:
            config = json.loads(msg.payload)
        except json.JSONDecodeError:
            print(f"config ignored (not JSON): {msg.payload!r}")
            return
        print(f"config <- {config}")
        value = config.get("publish_interval_s") if isinstance(config, dict) else None
        if isinstance(value, int) and not isinstance(value, bool):
            if MIN_INTERVAL_S <= value <= MAX_INTERVAL_S:
                self.interval_s = value
                self._wake.set()  # publish the next reading on the new schedule
            else:
                print(f"publish_interval_s={value} out of range, rejected")
        # Status follows every config message, applied or not (as the firmware does).
        self._publish_status()

    def _reading(self) -> dict[str, object]:
        now = datetime.now(LOCAL_TZ).replace(microsecond=0)
        reading = next(generate(now, now.replace(year=now.year + 1), MockOptions(isc_a=ISC_A)))
        body = reading.payload(self.device_id)
        if self.null_ts:
            body["ts"] = None  # device clock not synced yet
        return body

    def run(self) -> None:
        self.client.connect(BROKER_HOST, BROKER_PORT)
        self.client.loop_start()
        try:
            while not self._stop.is_set():
                body = self._reading()
                # QoS 1 like the firmware: the broker queues it while the backend is down.
                self.client.publish(self._topic("readings"), json.dumps(body), qos=1)
                print(f"reading -> v_mv={body['v_mv']} (every {self.interval_s}s)")
                self._wake.wait(self.interval_s)
                self._wake.clear()
        except KeyboardInterrupt:
            pass
        finally:
            self.client.loop_stop()
            # Hard-close without DISCONNECT so the broker publishes the Last Will.
            sock = self.client.socket()
            if sock is not None:
                sock.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("device_id", help="e.g. solarsense-38BB0B71FE68")
    parser.add_argument("--interval", type=int, default=30, help="initial publish interval (s)")
    parser.add_argument(
        "--null-ts", action="store_true", help="send ts=null like an unsynced clock"
    )
    args = parser.parse_args()
    MockDevice(args.device_id, args.interval, args.null_ts).run()


if __name__ == "__main__":
    main()
