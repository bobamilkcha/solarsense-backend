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
from collections.abc import AsyncGenerator, Generator

import paho.mqtt.client as mqtt
import pytest
from app.core.config.app_config import app_config
from app.modules.readings.mqtt import MQTTSubscriber
from app.modules.readings.schemas import ReadingPayload
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

    original = subscriber._dispatch

    def boom(msg: mqtt.MQTTMessage) -> None:
        if "dev-boom" in msg.topic:
            raise RuntimeError("bug in handler")
        original(msg)

    monkeypatch.setattr(subscriber, "_dispatch", boom)
    publisher.publish("solarsense/dev-boom/readings", json.dumps(READING)).wait_for_publish()

    await _wait_for_ingest(subscriber, publisher, "dev-after", timeout=10)
