"""MQTT client: ingests device readings and status, and publishes device config.

Topics (device ID is always taken from the topic path):
  solarsense/<id>/readings  device -> backend, QoS 1 (firmware must publish at QoS 1)
  solarsense/<id>/status    device -> backend, QoS 1, retained (Last Will = offline)
  solarsense/<id>/config    backend -> device, QoS 1, retained

No reading is lost while the backend is down (up to the broker's queue limit):
- Persistent session (MQTT 5, `clean_start=False`, session expiry, stable client
  ID): the broker queues QoS 1 messages for the backend while it is offline and
  delivers them when it reconnects.
- Manual acks: a message is acknowledged only after it is saved. If the backend
  dies first, the broker redelivers it on the next connection.
- Redelivery means duplicates, so the reading insert is idempotent (unique
  site + device timestamp).

paho runs its network loop on its own thread and calls `on_message` there. The
DB layer is async, so messages are queued onto the app's event loop and one
worker saves them in order. One worker, not a task per message: a backlog of
hundreds of queued messages arriving at once would otherwise exhaust the DB pool.
"""

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import paho.mqtt.client as mqtt
from app.core.config.app_config import app_config
from app.core.database.database import sessionmanager
from app.core.deps import logger
from app.modules.devices.schemas import StatusPayload
from app.modules.devices.service import DevicesService
from app.modules.readings.exceptions import UnknownDeviceError
from app.modules.readings.schemas import ReadingPayload
from app.modules.readings.service import ReadingsService
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties
from pydantic import ValidationError
from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

# Errors that mean "the database is unreachable right now", worth retrying. While
# retrying, the message stays unacked so the broker keeps it.
_TRANSIENT_ERRORS = (OSError, TimeoutError, OperationalError, InterfaceError, PoolTimeoutError)
_RETRY_MAX_DELAY_S = 30


@dataclass(frozen=True)
class _Inbound:
    topic: str
    mid: int
    qos: int
    handle: Callable[[], Awaitable[None]]


class MQTTSubscriber:
    """Long-lived MQTT connection that must survive network drops unattended.

    Resilience rules (see tests/integration/test_mqtt_reconnect.py):
    - `connect_async` + `loop_start`: the first connection is made by paho's
      thread, which retries forever with backoff, so a broker that is unreachable
      at startup doesn't leave ingestion dead until the next restart.
    - The same thread reconnects automatically after any drop.
    - Subscriptions are (re)made in `on_connect`, in case the session was lost.
    - No exception may escape a callback: paho re-raises callback exceptions by
      default, which kills its network thread silently and permanently.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._stopping = False
        self._connected_before = False
        self._queue: asyncio.Queue[_Inbound] = asyncio.Queue()
        self._worker: asyncio.Task[None] | None = None
        self._session_expiry_s = app_config.mqtt_session_expiry_s
        self._client_id = app_config.mqtt_client_id
        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=self._client_id,
            protocol=mqtt.MQTTv5,
            manual_ack=True,
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
        """Start the save worker and the network loop, which connects in the
        background and keeps retrying. Call from the app's event loop."""
        self._worker = self._loop.create_task(self._consume())
        self._client.reconnect_delay_set(
            min_delay=app_config.MQTT_RECONNECT_MIN_DELAY,
            max_delay=app_config.MQTT_RECONNECT_MAX_DELAY,
        )
        props = Properties(PacketTypes.CONNECT)
        props.SessionExpiryInterval = self._session_expiry_s
        try:
            self._client.connect_async(
                app_config.MQTT_BROKER_HOST,
                app_config.MQTT_BROKER_PORT,
                keepalive=app_config.MQTT_KEEPALIVE,
                clean_start=self._session_expiry_s == 0,
                properties=props,
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
            session_expiry_s=self._session_expiry_s,
        )
        self._client.loop_start()

    def disconnect(self) -> None:
        """Stop without acking anything still queued: the broker keeps those
        messages (persistent session) and redelivers them on the next start."""
        self._stopping = True
        if self._worker is not None:
            self._worker.cancel()
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

    # --- paho callbacks (network thread) ---

    def _on_connect(self, client: mqtt.Client, userdata, flags, reason_code, properties) -> None:
        if reason_code.is_failure:
            # e.g. bad credentials; paho keeps retrying with backoff.
            logger.error("mqtt_connect_refused", reason=str(reason_code))
            return

        event = "mqtt_reconnected" if self._connected_before else "mqtt_connected"
        self._connected_before = True
        # session_present=True after downtime means the broker kept our queue and
        # is about to deliver what was published meanwhile.
        logger.info(event, reason=str(reason_code), session_present=flags.session_present)

        # Re-subscribing is harmless when the session survived, and essential when
        # it didn't (first start, expired session, or a clean session in dev).
        result, _mid = client.subscribe(
            [(app_config.MQTT_READINGS_TOPIC, 1), (app_config.MQTT_STATUS_TOPIC, 1)]
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
                granted=[str(rc) for rc in reason_code_list],
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
            item = self._parse(msg)
        except Exception:
            logger.exception("mqtt_message_handler_failed", topic=msg.topic)
            item = None

        if item is None:
            # Malformed or unexpected: retrying would never help, so ack and drop.
            client.ack(msg.mid, msg.qos)
            return

        try:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, item)
        except RuntimeError:
            # Event loop closed (shutting down): leave it unacked for redelivery.
            logger.warning("mqtt_message_not_queued", topic=msg.topic)

    def _parse(self, msg: mqtt.MQTTMessage) -> _Inbound | None:
        # Topic shape: solarsense/{device_id}/{readings|status}
        parts = msg.topic.split("/")
        if len(parts) != 3 or parts[0] != "solarsense" or not parts[1]:
            logger.warning("mqtt_unexpected_topic", topic=msg.topic)
            return None

        device_id = parts[1]

        if parts[2] == "status":
            return self._parse_status(device_id, msg)
        if parts[2] != "readings":
            logger.warning("mqtt_unexpected_topic", topic=msg.topic)
            return None

        try:
            payload = ReadingPayload.model_validate(json.loads(msg.payload))
        except (json.JSONDecodeError, ValidationError) as exc:
            logger.warning("mqtt_invalid_payload", topic=msg.topic, error=str(exc))
            return None

        if payload.timestamp is None:
            # Stored with the receive time. Wrong if the broker held it while the
            # backend was down, so firmware should only publish once NTP synced.
            logger.warning("mqtt_reading_without_ts", device_id=device_id)

        return _Inbound(
            msg.topic, msg.mid, msg.qos, lambda: self._handle_reading(device_id, payload)
        )

    def _parse_status(self, device_id: str, msg: mqtt.MQTTMessage) -> _Inbound | None:
        try:
            status = StatusPayload.model_validate(json.loads(msg.payload))
        except (json.JSONDecodeError, ValidationError) as exc:
            logger.warning("mqtt_invalid_status", topic=msg.topic, error=str(exc))
            return None

        if status.device is not None and status.device != device_id:
            logger.warning("mqtt_status_device_mismatch", topic=msg.topic, device=status.device)
            return None

        retained = bool(msg.retain)
        return _Inbound(
            msg.topic, msg.mid, msg.qos, lambda: self._handle_status(device_id, status, retained)
        )

    # --- save worker (event loop) ---

    async def _consume(self) -> None:
        while True:
            item = await self._queue.get()
            if await self._process(item):
                # Ack only once saved. If the connection dropped meanwhile the ack
                # fails, the broker redelivers, and the duplicate insert is a no-op.
                self._client.ack(item.mid, item.qos)

    async def _process(self, item: _Inbound) -> bool:
        """Save one message. Returns False only when shutting down mid-retry."""
        delay = 1
        while True:
            try:
                await item.handle()
                return True
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if not _is_transient(exc):
                    # A bug or bad data: retrying won't help, and holding it would
                    # block every message behind it. Log, ack and move on.
                    logger.exception(
                        "mqtt_ingest_failed", topic=item.topic, error_type=type(exc).__name__
                    )
                    return True
                await logger.a_warning(
                    "mqtt_ingest_retry",
                    topic=item.topic,
                    error=str(exc),
                    error_type=type(exc).__name__,
                    retry_in_s=delay,
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, _RETRY_MAX_DELAY_S)

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


def _is_transient(exc: BaseException) -> bool:
    if isinstance(exc, _TRANSIENT_ERRORS):
        return True
    return isinstance(exc, DBAPIError) and exc.connection_invalidated
