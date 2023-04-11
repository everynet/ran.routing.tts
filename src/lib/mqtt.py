import asyncio
import ssl
from contextlib import AsyncExitStack, asynccontextmanager, suppress
from typing import Any, AsyncGenerator, Literal, Optional, Tuple, Union

import structlog
from asyncio_mqtt import Client as AsyncioClient
from asyncio_mqtt import MqttError
from paho.mqtt.matcher import MQTTMatcher
from paho.mqtt.properties import Properties
from paho.mqtt.subscribeoptions import SubscribeOptions

logger = structlog.getLogger(__name__)


class MQTTClient:
    """Represent an MQTT client."""

    # TODO: better way to configure client!
    def __init__(self, topics_prefix: str | None = None, **client_options: Any) -> None:
        """Set up client."""
        self._topics_prefix = topics_prefix if topics_prefix else None  # replacing empty string with None
        self._client_options = client_options
        self._reconnect_interval = 1
        self._connected = asyncio.Event()
        self._connection_failed = asyncio.Event()
        self._exception: Exception | None = None
        self._listeners = MQTTMatcher()
        self._client: AsyncioClient = None  # type: ignore
        self._create_client()

    @classmethod
    def from_conn_params(
        cls,
        host: str,
        port: int,
        username: str = "",
        password: str = "",
        secure: bool = False,
        cert_path: str | None = None,
        transport: Literal["websockets", "tcp"] = "tcp",
        ws_params: dict[str, Any] | None = None,
        topics_prefix: str | None = None,  # can contain "path" or "headers" keys
        **client_options: Any,
    ):
        # Basic AsyncioClient options
        client_options["hostname"] = host
        client_options["port"] = port
        if secure:
            tls_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            tls_context.verify_mode = ssl.CERT_REQUIRED
            tls_context.check_hostname = True
            if cert_path is not None:
                tls_context.load_cert_chain(cert_path)
            else:
                tls_context.load_default_certs(ssl.Purpose.SERVER_AUTH)
            client_options["tls_context"] = tls_context
        else:
            if cert_path:
                logger.warning("'cert_path' option ignored, because 'secure' flag is not set")

        client_options["username"] = username
        client_options["password"] = password

        # Custom options
        client_options["transport"] = transport
        client_options["ws_params"] = ws_params

        return MQTTClient(topics_prefix=topics_prefix, **client_options)

    def _create_client(self) -> None:
        """Create the asyncio client."""
        client_options = self._client_options.copy()
        logger.debug(
            "Creating MQTT client",
            client_options={
                k: (v if k not in ("password", "tls_context") else "<sanitized>") for k, v in client_options.items()
            },
        )

        transport = client_options.pop("transport")
        ws_params = client_options.pop("ws_params")

        client = AsyncioClient(**client_options)
        if transport == "websockets":
            client._client._transport = "websockets"
            if ws_params:
                client._client.ws_set_options(**ws_params)

        self._connected.clear()
        self._connection_failed.clear()
        self._exception = None
        self._client = client

    def _topic_with_prefix(self, topic: str) -> str:
        if self._topics_prefix is not None:
            if topic.startswith("/"):
                return self._topics_prefix + topic
            else:
                return self._topics_prefix + "/" + topic
        return topic

    async def wait_for_connection(self, timeout=None) -> bool:
        try:
            _, pending = await asyncio.wait_for(
                asyncio.wait(
                    {asyncio.create_task(self._connected.wait()), asyncio.create_task(self._connection_failed.wait())},
                    return_when=asyncio.FIRST_COMPLETED,
                ),
                timeout,
            )

            # If listener stopped then cancel waiter and raise exception
            pending_task = pending.pop()
            pending_task.cancel()

            # Waiting until task cancelled
            try:
                await pending_task
            except asyncio.CancelledError:
                pass

        except asyncio.TimeoutError:
            return False

        if self._exception:
            raise Exception("MQTT connection not established") from self._exception

        return True

    async def publish(
        self,
        topic: str,
        payload: Optional[Union[bytes, str]] = None,
        retain: bool = False,
        qos: int = 0,
        properties: Optional[Properties] = None,
        timeout: int = 10,
    ) -> None:
        """Publish to topic.
        Can raise asyncio_mqtt.MqttError.
        """
        logger.debug("Sending message", topic=self._topic_with_prefix(topic), payload=payload)
        await self._client.publish(
            self._topic_with_prefix(topic),
            qos=qos,
            payload=payload,
            retain=retain,
            properties=properties,
            timeout=timeout,
        )

    async def subscribe(
        self,
        topic: str,
        qos: int = 0,
        options: Optional[SubscribeOptions] = None,
        properties: Optional[Properties] = None,
        timeout: int = 10,
    ) -> None:
        """Subscribe to topic.
        Can raise asyncio_mqtt.MqttError.
        """
        await self._client.subscribe(
            topic=self._topic_with_prefix(topic), qos=qos, options=options, properties=properties, timeout=timeout
        )

    async def unsubscribe(self, topic: str, properties: Optional[Properties] = None, timeout: int = 10) -> None:
        """Unsubscribe from topic.
        Can raise asyncio_mqtt.MqttError.
        """
        await self._client.unsubscribe(topic=self._topic_with_prefix(topic), properties=properties, timeout=timeout)

    async def on_connect(self):
        pass

    async def on_disconnect(self):
        pass

    async def run(self, stop_event: asyncio.Event) -> None:
        """Run the MQTT client worker."""
        # Reconnect automatically until the client is stopped.
        logger.info("Starting MQTT client")

        async def disconnect_on_stop():
            await stop_event.wait()
            if not self._connected.is_set():
                return
            logger.debug("Stop signal received, closing MQTT client")
            try:
                await self._client.disconnect()
                logger.debug("MQTT client disconnected normally")
            except MqttError as err:
                logger.debug("MQTT client abnormal disconnect", error=err)
            finally:
                return

        disconnect_task = asyncio.create_task(disconnect_on_stop())

        while not stop_event.is_set():
            try:
                await self._subscribe_worker()
            except MqttError as err:
                self._connected.clear()
                self._connection_failed.set()
                self._exception = err

                # Also breaking here, because "_subscribe_worker" may block execution forever until error.
                if stop_event.is_set():
                    break

                self._reconnect_interval = min(self._reconnect_interval * 2, 900)
                logger.error("MQTT error", error=err)
                await self.on_disconnect()

                logger.warning("Next MQTT client reconnect attempt scheduled", after=self._reconnect_interval)
                with suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(stop_event.wait(), timeout=self._reconnect_interval)

                logger.warning("Reconnecting to MQTT...")
                self._create_client()  # reset connect/reconnect futures

        await disconnect_task
        logger.debug("MQTT main loop exited")

    async def _subscribe_worker(self) -> None:
        """Connect and manage receive tasks."""
        async with AsyncExitStack() as stack:
            # Connect to the MQTT broker.
            await stack.enter_async_context(self._client)
            # Reset the reconnect interval after successful connection.
            self._reconnect_interval = 1

            # Messages that doesn't match a filter will get logged and handled here.
            messages = await stack.enter_async_context(self._client.unfiltered_messages())

            if not self._connected.is_set():
                await self.on_connect()
                self._connected.set()
                logger.info("MQTT connection established")

            async for message in messages:
                logger.debug("Received message", topic=message.topic, payload=message.payload)

                for listeners in self._listeners.iter_match(message.topic):
                    for listener in listeners:
                        await listener.put([message.topic, message.payload])

    @asynccontextmanager
    async def listen(self, topic_filter=None) -> AsyncGenerator[asyncio.Queue[Tuple[str, bytes]], None]:
        if topic_filter is None:
            topic_filter = "#"
        topic_filter = self._topic_with_prefix(topic_filter)

        listeners = set()
        queue: asyncio.Queue[Tuple[str, bytes]] = asyncio.Queue()

        try:
            listeners = self._listeners[topic_filter]
        except KeyError:
            self._listeners[topic_filter] = listeners

        listeners.add(queue)

        try:
            yield queue
        finally:
            listeners.remove(queue)

            # Clean up empty set
            if len(listeners) == 0:
                del self._listeners[topic_filter]
