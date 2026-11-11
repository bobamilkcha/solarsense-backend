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
from collections.abc import Coroutine
from concurrent.futures import Future
from functools import partial
from typing import Any

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
    """Long-lived MQTT connection that must survive network drops unattended.

    Resilience rules (see tests/integration/test_mqtt_reconnect.py):
    - `connect_async` + `loop_start`: the first connection is made by paho's
      thread, which retries forever with backoff, so a broker that is unreachable
      at startup doesn't leave ingestion dead until the next restart.
    - The same thread reconnects automatically after any drop.
    - Subscriptions are (re)made in `on_connect`, because a clean-session
      reconnect starts with no subscriptions on the broker side.
    - No exception may escape a callback: paho re-raises callback exceptions by
      default, which kills its network thread silently and permanently.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._stopping = False
        self._connected_before = False
        # Never a device ID ("solarsense-<12 hex>"): the broker would disconnect the
        # real device. Random suffix so several workers don't kick each other off.
        self._client_id = f"{app_config.MQTT_CLIENT_ID_PREFIX}-{secrets.token_hex(4)}"
        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2, client_id=self._client_id
        )
        # Belt and braces with the try/except in each callback: never let a bug in a
        # callback take down the network thread.
        self._client.suppress_exceptions = True

        if app_config.MQTT_USERNAME:
            self._client.username_pw_set(app_config.MQTT_USERNAME, app_config.MQTT_PASSWORD)

        if app_config.MQTT_USE_TLS:
            self._client.tls_set()

        self._client.on_connect = self._on_connect
        self._client.on_connect_fail = self._on_connect_fail
        self._client.on_disconnect = self._on_disconnect
        self._client.on_subscribe = self._on_subscribe
        self._client.on_message = self._on_message

    def connect(self) -> None:
        """Start the network loop; it connects in the background and keeps retrying."""
        self._client.reconnect_delay_set(
            min_delay=app_config.MQTT_RECONNECT_MIN_DELAY,
            max_delay=app_config.MQTT_RECONNECT_MAX_DELAY,
        )
        try:
            self._client.connect_async(
                app_config.MQTT_BROKER_HOST,
                app_config.MQTT_BROKER_PORT,
                keepalive=app_config.MQTT_KEEPALIVE,
            )
        except (OSError, ValueError) as exc:
            # Only bad arguments get here; connect_async does no network I/O.
            logger.error("mqtt_connect_config_invalid", error=str(exc))
            return

        logger.info(
            "mqtt_connecting",
            host=app_config.MQTT_BROKER_HOST,
            port=app_config.MQTT_BROKER_PORT,
            client_id=self._client_id,
            keepalive=app_config.MQTT_KEEPALIVE,
        )
        self._client.loop_start()

    def disconnect(self) -> None:
        self._stopping = True
        self._client.disconnect()
        self._client.loop_stop()

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
        if reason_code.is_failure:
            # e.g. bad credentials; paho keeps retrying with backoff.
            logger.error("mqtt_connect_refused", reason=str(reason_code))
            return

        event = "mqtt_reconnected" if self._connected_before else "mqtt_connected"
        self._connected_before = True
        logger.info(event, reason=str(reason_code), session_present=flags.session_present)

        # Subscribing here (not once at startup) restores both after a reconnect.
        result, _mid = client.subscribe(
            [(app_config.MQTT_READINGS_TOPIC, 0), (app_config.MQTT_STATUS_TOPIC, 1)]
        )
        if result != mqtt.MQTT_ERR_SUCCESS:
            logger.error("mqtt_subscribe_failed", error=mqtt.error_string(result))

    def _on_subscribe(self, client, userdata, mid, reason_code_list, properties) -> None:
        failed = [str(rc) for rc in reason_code_list if rc.is_failure]
        if failed:
            logger.error("mqtt_subscribe_rejected", reasons=failed)
        else:
            logger.info(
                "mqtt_subscribed",
                topics=[app_config.MQTT_READINGS_TOPIC, app_config.MQTT_STATUS_TOPIC],
            )

    def _on_connect_fail(self, client, userdata) -> None:
        # Network-level failure (DNS, refused, timeout, TLS); paho retries with backoff.
        logger.warning("mqtt_connect_failed", host=app_config.MQTT_BROKER_HOST)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties) -> None:
        if self._stopping:
            logger.info("mqtt_disconnected", reason=str(reason_code))
            return
        logger.warning(
            "mqtt_connection_lost",
            reason=str(reason_code),
            from_broker=flags.is_disconnect_packet_from_server,
            will_reconnect=True,
        )

    def _on_message(self, client: mqtt.Client, userdata, msg: mqtt.MQTTMessage) -> None:
        try:
            self._dispatch(msg)
        except Exception:
            logger.exception("mqtt_message_handler_failed", topic=msg.topic)

    def _dispatch(self, msg: mqtt.MQTTMessage) -> None:
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

        self._submit(self._handle_reading(device_id, payload), msg.topic)

    def _submit(self, coro: Coroutine[Any, Any, None], topic: str) -> None:
        """Run `coro` on the app's event loop and log it if it fails.

        Without the done-callback a DB error during ingestion would vanish inside
        the Future and ingestion would look silently stopped.
        """
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        future.add_done_callback(partial(_log_failure, topic=topic))

    def _on_status(self, device_id: str, msg: mqtt.MQTTMessage) -> None:
        try:
            status = StatusPayload.model_validate(json.loads(msg.payload))
        except (json.JSONDecodeError, ValidationError) as exc:
            logger.warning("mqtt_invalid_status", topic=msg.topic, error=str(exc))
            return

        if status.device is not None and status.device != device_id:
            logger.warning("mqtt_status_device_mismatch", topic=msg.topic, device=status.device)
            return

        self._submit(self._handle_status(device_id, status, bool(msg.retain)), msg.topic)

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


def _log_failure(future: Future[None], *, topic: str) -> None:
    if future.cancelled():
        return
    exc = future.exception()
    if exc is not None:
        logger.error(
            "mqtt_ingest_failed", topic=topic, error=str(exc), error_type=type(exc).__name__
        )
