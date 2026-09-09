"""MQTT subscriber that ingests sensor readings published by ESP32 devices.

paho-mqtt runs its network loop on its own background thread and delivers
`on_message` callbacks synchronously on that thread. The DB/session layer is
async, so each message is handed off to the app's event loop via
`run_coroutine_threadsafe` rather than awaited directly.
"""

import asyncio
import json

import paho.mqtt.client as mqtt
from app.core.config.app_config import app_config
from app.core.database.database import sessionmanager
from app.core.deps import logger
from app.modules.readings.exceptions import UnknownDeviceError
from app.modules.readings.schemas import ReadingPayload
from app.modules.readings.service import ReadingsService
from pydantic import ValidationError


class MQTTSubscriber:
    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)

        if app_config.MQTT_USERNAME:
            self._client.username_pw_set(app_config.MQTT_USERNAME, app_config.MQTT_PASSWORD)

        if app_config.MQTT_USE_TLS:
            self._client.tls_set()

        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message

    def connect(self) -> None:
        try:
            self._client.connect(app_config.MQTT_BROKER_HOST, app_config.MQTT_BROKER_PORT)
        except OSError as exc:
            # Don't take the whole app down if the broker isn't reachable yet
            # (e.g. local dev without real EMQX credentials configured).
            logger.error("mqtt_connect_failed", error=str(exc))
            return

        self._client.loop_start()

    def disconnect(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()

    def _on_connect(self, client: mqtt.Client, userdata, flags, reason_code, properties) -> None:
        client.subscribe(app_config.MQTT_READINGS_TOPIC)

    def _on_message(self, client: mqtt.Client, userdata, msg: mqtt.MQTTMessage) -> None:
        # Topic shape: solarsense/{device_id}/readings
        parts = msg.topic.split("/")
        if len(parts) != 3:
            logger.warning("mqtt_unexpected_topic", topic=msg.topic)
            return

        device_id = parts[1]

        try:
            raw = json.loads(msg.payload)
            payload = ReadingPayload.model_validate(raw)
        except (json.JSONDecodeError, ValidationError) as exc:
            logger.warning("mqtt_invalid_payload", topic=msg.topic, error=str(exc))
            return

        asyncio.run_coroutine_threadsafe(self._handle_reading(device_id, payload), self._loop)

    async def _handle_reading(self, device_id: str, payload: ReadingPayload) -> None:
        async with sessionmanager.session() as db:
            service = ReadingsService(db)
            try:
                await service.record_reading(device_id, payload)
            except UnknownDeviceError:
                await logger.a_warning("mqtt_unknown_device", device_id=device_id)
