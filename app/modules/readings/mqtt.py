"""MQTT client: ingests device readings and status, and publishes device config.

Topics (device ID is always taken from the topic path):
  solarsense/<id>/readings  device -> backend, QoS 0
  solarsense/<id>/status    device -> backend, QoS 1, retained (Last Will = offline)
  solarsense/<id>/config    backend -> device, QoS 1, retained

paho-mqtt runs its network loop on its own background thread and delivers
`on_message` callbacks synchronously on that thread. The DB/session layer is
async, so each message is handed off to the app's event loop via
`run_coroutine_threadsafe` rather than awaited directly.
"""

import asyncio
import json
import secrets

import paho.mqtt.client as mqtt
from app.core.config.app_config import app_config
from app.core.database.database import sessionmanager
from app.core.deps import logger
from app.modules.devices.schemas import StatusPayload
from app.modules.devices.service import DevicesService
from app.modules.readings.exceptions import UnknownDeviceError
from app.modules.readings.schemas import ReadingPayload
from app.modules.readings.service import ReadingsService
from pydantic import ValidationError


class MQTTSubscriber:
    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        # Never a device ID ("solarsense-<12 hex>"): the broker would disconnect the
        # real device. Random suffix so several workers don't kick each other off.
        client_id = f"{app_config.MQTT_CLIENT_ID_PREFIX}-{secrets.token_hex(4)}"
        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2, client_id=client_id
        )

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

    def is_connected(self) -> bool:
        return self._client.is_connected()

    def publish_config(self, device_id: str, config: dict[str, int]) -> bool:
        """Publish retained at QoS 1 so an offline device gets it on reconnect.

        Send only the keys being changed; the device ignores unknown keys.
        Returns False if paho could not accept the message.
        """
        info = self._client.publish(
            f"solarsense/{device_id}/config", json.dumps(config), qos=1, retain=True
        )
        return info.rc == mqtt.MQTT_ERR_SUCCESS

    def _on_connect(self, client: mqtt.Client, userdata, flags, reason_code, properties) -> None:
        # Subscribing here (not once at startup) restores both after a reconnect.
        client.subscribe([(app_config.MQTT_READINGS_TOPIC, 0), (app_config.MQTT_STATUS_TOPIC, 1)])

    def _on_message(self, client: mqtt.Client, userdata, msg: mqtt.MQTTMessage) -> None:
        # Topic shape: solarsense/{device_id}/{readings|status}
        parts = msg.topic.split("/")
        if len(parts) != 3 or parts[0] != "solarsense" or not parts[1]:
            logger.warning("mqtt_unexpected_topic", topic=msg.topic)
            return

        device_id = parts[1]

        if parts[2] == "status":
            self._on_status(device_id, msg)
            return
        if parts[2] != "readings":
            logger.warning("mqtt_unexpected_topic", topic=msg.topic)
            return

        try:
            raw = json.loads(msg.payload)
            payload = ReadingPayload.model_validate(raw)
        except (json.JSONDecodeError, ValidationError) as exc:
            logger.warning("mqtt_invalid_payload", topic=msg.topic, error=str(exc))
            return

        asyncio.run_coroutine_threadsafe(self._handle_reading(device_id, payload), self._loop)

    def _on_status(self, device_id: str, msg: mqtt.MQTTMessage) -> None:
        try:
            status = StatusPayload.model_validate(json.loads(msg.payload))
        except (json.JSONDecodeError, ValidationError) as exc:
            logger.warning("mqtt_invalid_status", topic=msg.topic, error=str(exc))
            return

        if status.device is not None and status.device != device_id:
            logger.warning("mqtt_status_device_mismatch", topic=msg.topic, device=status.device)
            return

        asyncio.run_coroutine_threadsafe(
            self._handle_status(device_id, status, bool(msg.retain)), self._loop
        )

    async def _handle_status(self, device_id: str, status: StatusPayload, retained: bool) -> None:
        async with sessionmanager.session() as db:
            await DevicesService(db).apply_status(device_id, status, retained=retained)

    async def _handle_reading(self, device_id: str, payload: ReadingPayload) -> None:
        async with sessionmanager.session() as db:
            # Record every device we hear from, so unpaired ones show up in
            # GET /devices/unpaired for an admin to pick.
            await DevicesService(db).mark_seen(device_id, payload.rssi)
            try:
                await ReadingsService(db).record_reading(device_id, payload)
            except UnknownDeviceError:
                await logger.a_info("mqtt_unpaired_device", device_id=device_id)
