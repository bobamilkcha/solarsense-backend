"""MQTT ingestion must resume on its own after the network drops.

A real Mosquitto broker runs in Docker; the subscriber reaches it through a
small in-process TCP proxy that can simulate the two ways a link dies:

- `reset()`: every connection is closed at once (broker restart, NAT reset).
  paho sees EOF immediately.
- `blackhole()`: traffic silently stops and new connections are refused, like a
  laptop losing Wi-Fi. No TCP reset is sent, so paho only notices when its
  keepalive ping goes unanswered (~1.5x MQTT_KEEPALIVE).

Readings are published straight to the broker (not via the proxy), so the device
side is unaffected, exactly as in the field. No Postgres: `_handle_reading` is
replaced with a queue.
"""

import asyncio
import contextlib
import json
import socket
import threading
import time
import uuid
from collections.abc import AsyncGenerator, Generator

import paho.mqtt.client as mqtt
import pytest
from app.core.config.app_config import app_config
from app.modules.readings.mqtt import MQTTSubscriber
from app.modules.readings.schemas import ReadingPayload
from sqlalchemy.exc import OperationalError
from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import LogMessageWaitStrategy

KEEPALIVE = 5  # seconds; keeps the blackhole case fast
READING = {"ts": None, "v_mv": 1850, "temp": 24.2, "rh": 61.8, "rssi": -71}


class FlakyProxy:
    """TCP proxy on 127.0.0.1 that can reset or blackhole its connections."""

    def __init__(self, upstream: tuple[str, int]) -> None:
        self._upstream = upstream
        self._lock = threading.Lock()
        self._sockets: list[socket.socket] = []
        self._down = False
        self.accepted = 0
        self._listener = socket.create_server(("127.0.0.1", 0))
        self.port = self._listener.getsockname()[1]
        threading.Thread(target=self._accept_loop, daemon=True).start()

    def _accept_loop(self) -> None:
        while True:
            try:
                client, _ = self._listener.accept()
            except OSError:
                return  # listener closed
            if self._down:
                client.close()  # unreachable: refuse new connections
                continue
            try:
                upstream = socket.create_connection(self._upstream, timeout=5)
            except OSError:
                client.close()
                continue
            upstream.settimeout(None)
            with self._lock:
                self.accepted += 1
                self._sockets += [client, upstream]
            threading.Thread(target=self._pump, args=(client, upstream), daemon=True).start()
            threading.Thread(target=self._pump, args=(upstream, client), daemon=True).start()

    def _pump(self, src: socket.socket, dst: socket.socket) -> None:
        while True:
            try:
                data = src.recv(65536)
            except OSError:
                break
            if not data:
                break
            if self._down:
                continue  # blackhole: swallow everything, send no reset
            try:
                dst.sendall(data)
            except OSError:
                break
        if not self._down:
            for s in (src, dst):
                _close(s)

    def reset(self) -> None:
        with self._lock:
            sockets, self._sockets = self._sockets, []
        for s in sockets:
            _close(s)

    def blackhole(self) -> None:
        self._down = True

    def restore(self) -> None:
        # Drop the dead blackholed sockets for real now, then accept again.
        self.reset()
        self._down = False

    def close(self) -> None:
        self._listener.close()
        self.reset()


def _close(s: socket.socket) -> None:
    with contextlib.suppress(OSError):
        s.shutdown(socket.SHUT_RDWR)
    s.close()


@pytest.fixture(scope="module")
def broker() -> Generator[tuple[str, int]]:
    container = (
        DockerContainer("eclipse-mosquitto:2")
        .with_command("mosquitto -c /mosquitto-no-auth.conf")
        .with_exposed_ports(1883)
        .waiting_for(LogMessageWaitStrategy("running"))
    )
    with container:
        yield container.get_container_host_ip(), int(container.get_exposed_port(1883))


@pytest.fixture
def proxy(broker: tuple[str, int]) -> Generator[FlakyProxy]:
    p = FlakyProxy(broker)
    yield p
    p.close()


@pytest.fixture
def mqtt_config(monkeypatch: pytest.MonkeyPatch, proxy: FlakyProxy) -> None:
    for name, value in {
        "MQTT_BROKER_HOST": "127.0.0.1",
        "MQTT_BROKER_PORT": proxy.port,
        "MQTT_USE_TLS": False,
        "MQTT_USERNAME": "",
        "MQTT_KEEPALIVE": KEEPALIVE,
        "MQTT_RECONNECT_MIN_DELAY": 1,
        "MQTT_RECONNECT_MAX_DELAY": 2,
    }.items():
        monkeypatch.setattr(app_config, name, value)


class RecordingSubscriber(MQTTSubscriber):
    """The real subscriber, with the DB write swapped for a queue."""

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        super().__init__(loop)
        self.received: asyncio.Queue[str] = asyncio.Queue()

    async def _handle_reading(self, device_id: str, payload: ReadingPayload) -> None:
        await self.received.put(device_id)


@pytest.fixture
def publisher(broker: tuple[str, int]) -> Generator[mqtt.Client]:
    client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    client.connect(*broker)
    client.loop_start()
    yield client
    client.loop_stop()
    client.disconnect()


@pytest.fixture
async def subscriber(mqtt_config: None) -> AsyncGenerator[RecordingSubscriber]:
    sub = RecordingSubscriber(asyncio.get_running_loop())
    yield sub
    sub.disconnect()


async def _wait_for_ingest(
    sub: RecordingSubscriber, publisher: mqtt.Client, device_id: str, timeout: float
) -> float:
    """Publish a reading for `device_id` every 0.5 s until it's ingested.

    Returns seconds taken. Retrying covers the gap between the subscriber
    reconnecting and its re-subscription being active on the broker.
    """
    start = time.monotonic()
    deadline = start + timeout
    while time.monotonic() < deadline:
        publisher.publish(f"solarsense/{device_id}/readings", json.dumps(READING))
        try:
            while True:
                if await asyncio.wait_for(sub.received.get(), timeout=0.5) == device_id:
                    return time.monotonic() - start
        except TimeoutError:
            continue
    pytest.fail(f"reading from {device_id} not ingested within {timeout}s")


async def test_ingestion_resumes_after_connection_reset(
    subscriber: RecordingSubscriber, publisher: mqtt.Client, proxy: FlakyProxy
) -> None:
    subscriber.connect()
    await _wait_for_ingest(subscriber, publisher, "dev-before", timeout=15)

    proxy.reset()

    await _wait_for_ingest(subscriber, publisher, "dev-after", timeout=15)
    assert proxy.accepted >= 2, "subscriber should have opened a new connection"


async def test_ingestion_resumes_after_silent_network_drop(
    subscriber: RecordingSubscriber, publisher: mqtt.Client, proxy: FlakyProxy
) -> None:
    subscriber.connect()
    await _wait_for_ingest(subscriber, publisher, "dev-before", timeout=15)

    proxy.blackhole()
    # Long enough for the keepalive to expire, so paho declares the link dead
    # and starts reconnect attempts that fail while the "network" is down.
    deadline = time.monotonic() + KEEPALIVE * 3
    while subscriber.is_connected() and time.monotonic() < deadline:
        await asyncio.sleep(0.5)
    assert not subscriber.is_connected(), "keepalive should detect the dead link"
    await asyncio.sleep(3)  # a few failed reconnect attempts

    proxy.restore()

    await _wait_for_ingest(subscriber, publisher, "dev-after", timeout=20)
    assert subscriber.is_connected()


async def test_initial_connect_retries_until_broker_reachable(
    subscriber: RecordingSubscriber, publisher: mqtt.Client, proxy: FlakyProxy
) -> None:
    proxy.blackhole()  # broker unreachable when the backend starts
    subscriber.connect()
    await asyncio.sleep(3)
    assert not subscriber.is_connected()

    proxy.restore()

    await _wait_for_ingest(subscriber, publisher, "dev-late", timeout=15)


async def test_handler_exception_does_not_kill_network_thread(
    subscriber: RecordingSubscriber, publisher: mqtt.Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    subscriber.connect()
    await _wait_for_ingest(subscriber, publisher, "dev-before", timeout=15)

    original = subscriber._parse

    def boom(msg: mqtt.MQTTMessage):
        if "dev-boom" in msg.topic:
            raise RuntimeError("bug in handler")
        return original(msg)

    monkeypatch.setattr(subscriber, "_parse", boom)
    publisher.publish("solarsense/dev-boom/readings", json.dumps(READING)).wait_for_publish()

    await _wait_for_ingest(subscriber, publisher, "dev-after", timeout=10)


# --- Backend offline: the broker must keep readings for it (persistent session) ---


@pytest.fixture
def persistent_session(mqtt_config: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_config, "MQTT_SESSION_EXPIRY_S", 300)
    # Fixed client ID per test (that's what lets the broker find the session),
    # unique across tests so they don't inherit each other's queues.
    monkeypatch.setattr(app_config, "MQTT_CLIENT_ID_PREFIX", f"test-{uuid.uuid4().hex[:8]}")


async def _collect(sub: RecordingSubscriber, expected: set[str], timeout: float) -> set[str]:
    got: set[str] = set()
    deadline = time.monotonic() + timeout
    while not expected <= got and time.monotonic() < deadline:
        try:
            got.add(await asyncio.wait_for(sub.received.get(), timeout=0.5))
        except TimeoutError:
            continue
    return got


async def test_readings_published_while_backend_down_are_delivered_on_restart(
    persistent_session: None, publisher: mqtt.Client
) -> None:
    loop = asyncio.get_running_loop()
    first = RecordingSubscriber(loop)
    first.connect()
    await _wait_for_ingest(first, publisher, "dev-warmup", timeout=15)
    first.disconnect()  # backend stopped (crash, redeploy, PC asleep)

    offline = {f"dev-offline-{i}" for i in range(20)}
    for device_id in sorted(offline):
        msg = {**READING, "ts": 1794226000 + int(device_id.rsplit("-", 1)[1])}
        publisher.publish(f"solarsense/{device_id}/readings", json.dumps(msg), qos=1)
    publisher.publish("solarsense/dev-last/readings", json.dumps(READING), qos=1).wait_for_publish()

    second = RecordingSubscriber(loop)  # backend back up, same client ID
    second.connect()
    try:
        got = await _collect(second, offline, timeout=15)
    finally:
        second.disconnect()

    assert offline <= got, f"lost while backend was down: {sorted(offline - got)}"


async def test_message_not_yet_saved_is_redelivered_after_restart(
    persistent_session: None, publisher: mqtt.Client
) -> None:
    """Acks are sent only after the save, so a crash mid-save loses nothing."""
    loop = asyncio.get_running_loop()
    started = asyncio.Event()

    class StuckSubscriber(RecordingSubscriber):
        async def _handle_reading(self, device_id: str, payload: ReadingPayload) -> None:
            started.set()
            await asyncio.Event().wait()  # the save never finishes

    stuck = StuckSubscriber(loop)
    stuck.connect()
    deadline = time.monotonic() + 15
    while not stuck.is_connected() and time.monotonic() < deadline:
        await asyncio.sleep(0.2)
    await asyncio.sleep(0.5)  # let the subscription land
    publisher.publish("solarsense/dev-stuck/readings", json.dumps(READING), qos=1)
    await asyncio.wait_for(started.wait(), timeout=10)
    stuck.disconnect()  # dies mid-save, before acking

    second = RecordingSubscriber(loop)
    second.connect()
    try:
        got = await _collect(second, {"dev-stuck"}, timeout=15)
    finally:
        second.disconnect()

    assert "dev-stuck" in got


async def test_transient_db_error_is_retried(
    subscriber: RecordingSubscriber, publisher: mqtt.Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    failures = 2
    original = subscriber._handle_reading

    async def flaky(device_id: str, payload: ReadingPayload) -> None:
        nonlocal failures
        if device_id == "dev-flaky" and failures:
            failures -= 1
            raise OperationalError("SELECT 1", {}, ConnectionRefusedError("db down"))
        await original(device_id, payload)

    monkeypatch.setattr(subscriber, "_handle_reading", flaky)
    subscriber.connect()
    await _wait_for_ingest(subscriber, publisher, "dev-before", timeout=15)

    publisher.publish("solarsense/dev-flaky/readings", json.dumps(READING), qos=1)

    assert "dev-flaky" in await _collect(subscriber, {"dev-flaky"}, timeout=10)
    assert failures == 0
