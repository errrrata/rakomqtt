import asyncio
import json
import logging
from typing import Optional, List, Tuple, Dict, Any, Final
from collections.abc import AsyncIterator
import socket
from contextlib import AsyncExitStack, asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
import paho.mqtt.client as mqtt

from rakomqtt.RakoBridge import RakoBridge, RakoCommand
from rakomqtt.discovery import RakoDiscovery

_LOGGER = logging.getLogger(__name__)

class AsyncioMQTTClient:
    def __init__(self, host: str, user: str, password: str):
        self.client = mqtt.Client(protocol=mqtt.MQTTv5)
        self.client.username_pw_set(user, password)
        self.client.enable_logger()
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_subscribe = self._on_subscribe
        self.client.on_publish = self._on_publish
        self.host = host
        self.connected = asyncio.Event()
        self._message_queue: asyncio.Queue[mqtt.MQTTMessage] = asyncio.Queue()
        self.is_connected = False
        self._thread_pool = ThreadPoolExecutor(max_workers=1)
        self._queue_task: Optional[asyncio.Task] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def _on_connect(self, client: mqtt.Client, userdata: Any, flags: Dict, 
                   rc: int, properties: Optional[Any] = None) -> None:
        """Handle connection established callback."""
        _LOGGER.info(f"MQTT Connected with result code {rc}")
        if properties:
            _LOGGER.debug(f"Connection properties: {properties}")
        self.is_connected = True
        asyncio.run_coroutine_threadsafe(self._set_connected(), self._loop)

    async def _set_connected(self) -> None:
        """Set the connected event."""
        self.connected.set()

    def _on_message(self, client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage) -> None:
        """Handle incoming message callback."""
        _LOGGER.debug(f"Received MQTT message on topic {msg.topic}: {msg.payload}")
        try:
            asyncio.run_coroutine_threadsafe(self._message_queue.put(msg), self._loop)
        except Exception as e:
            _LOGGER.error(f"Error putting message in queue: {e}")

    def _on_subscribe(self, client: mqtt.Client, userdata: Any, mid: int, 
                     granted_qos: Optional[List[int]] = None, 
                     properties: Optional[Any] = None) -> None:
        """Handle subscription acknowledgment callback."""
        _LOGGER.debug(f"Subscribed successfully: {mid}, QoS: {granted_qos}")
        if properties:
            _LOGGER.debug(f"Subscription properties: {properties}")

    def _on_publish(self, client: mqtt.Client, userdata: Any, mid: int) -> None:
        """Handle message published callback."""
        _LOGGER.debug(f"Published message: {mid}")

    async def connect(self) -> None:
        """Connect to MQTT broker."""
        if self.is_connected:
            return

        self._loop = asyncio.get_running_loop()
        _LOGGER.debug(f"Connecting to MQTT broker at {self.host}")
        
        self.client.will_set(
            "rako/bridge/status",
            "offline",
            qos=1,
            retain=True
        )
        
        self.client.connect(self.host, 1883, 60)
        self.client.loop_start()

    async def disconnect(self) -> None:
        """Disconnect from MQTT broker."""
        _LOGGER.debug("Disconnecting from MQTT broker")
        if self.is_connected:
            self.is_connected = False
            self.connected.clear()
            
            if self._queue_task:
                self._queue_task.cancel()
                try:
                    await self._queue_task
                except asyncio.CancelledError:
                    pass
                self._queue_task = None
            
            self.client.loop_stop()
            self.client.disconnect()
            self._thread_pool.shutdown(wait=False)

    async def subscribe(self, topic: str, qos: int = 0) -> None:
        """Subscribe to an MQTT topic."""
        _LOGGER.debug(f"Subscribing to topic: {topic} with QoS {qos}")
        result, mid = self.client.subscribe(topic, qos)
        if result != mqtt.MQTT_ERR_SUCCESS:
            raise Exception(f"Failed to subscribe to {topic}: {result}")
        _LOGGER.debug(f"Subscribe initiated with message ID: {mid}")

    async def publish(self, topic: str, payload: Optional[str] = None, 
                     qos: int = 0, retain: bool = False) -> None:
        """Publish an MQTT message."""
        _LOGGER.debug(f"Publishing to topic {topic}: {payload}")
        result, mid = self.client.publish(topic, payload, qos, retain)
        if result != mqtt.MQTT_ERR_SUCCESS:
            raise Exception(f"Failed to publish to {topic}: {result}")
        _LOGGER.debug(f"Publish initiated with message ID: {mid}")

    async def get_message(self) -> mqtt.MQTTMessage:
        """Get the next message from the message queue."""
        return await self._message_queue.get()

    async def wait_for_connection(self, timeout: float = 10) -> None:
        """Wait for MQTT connection to be established."""
        try:
            await asyncio.wait_for(self.connected.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            raise TimeoutError(f"Timeout waiting for MQTT connection to {self.host}")

class RakoMQTTBridge:
    MQTT_TOPICS: Final[List[Tuple[str, int]]] = [
        ("rako/room/+/set", 1),
        ("rako/room/+/channel/+/set", 1),
        ("rako/room/+/channel/+/command", 1),  # Add subscription for cover commands
    ]

    def __init__(
        self,
        rako_bridge_host: str,
        mqtt_host: str,
        mqtt_user: str,
        mqtt_password: str,
        default_fade_rate: str = "medium"
    ):
        if not rako_bridge_host:
            raise ValueError("Rako bridge host is required")
        
        _LOGGER.info(f"Initializing bridge with Rako host: {rako_bridge_host}")
        self.rako_bridge = RakoBridge(
            host=rako_bridge_host,
            default_fade_rate=default_fade_rate
        )
        self.mqtt_client = AsyncioMQTTClient(mqtt_host, mqtt_user, mqtt_password)
        self.udp_queue: asyncio.Queue[Tuple[str, Dict[str, Any]]] = asyncio.Queue()

    async def monitor_scene_cache(self) -> None:
        """Monitor scene cache updates from bridge."""
        while True:
            try:
                cache_entries = await self.rako_bridge.get_scene_cache()
                for entry in cache_entries:
                    # Publish scene status to MQTT
                    topic = f"rako/room/{entry.room_id}/state"
                    payload = {
                        "state": "ON" if entry.scene_id > 0 else "OFF",
                        "scene": entry.scene_id,
                        "source": "scene_cache"
                    }
                    await self.mqtt_client.publish(
                        topic,
                        json.dumps(payload),
                        qos=1,
                        retain=True
                    )
            except Exception as e:
                _LOGGER.error(f"Scene cache monitoring error: {e}")
            await asyncio.sleep(5)  # Poll every 5 seconds

    @asynccontextmanager
    async def setup_udp_socket(self) -> AsyncIterator[socket.socket]:
        """Setup UDP socket for receiving Rako bridge messages"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        _LOGGER.info(f"Binding UDP socket to port {RakoBridge.port}")
        sock.bind(("", RakoBridge.port))
        sock.setblocking(False)
        try:
            yield sock
        finally:
            sock.close()

    async def watch_rako(self, sock: socket.socket) -> None:
        """Listen for Rako bridge UDP broadcasts"""
        _LOGGER.info("Starting Rako UDP watcher")
        loop = asyncio.get_running_loop()
        
        while True:
            try:
                data = await loop.sock_recv(sock, 256)
                if not data:
                    await asyncio.sleep(0.1)
                    continue
                    
                _LOGGER.debug(f"Received UDP data: {list(data)}")
                processed = RakoBridge.process_udp_bytes(list(data))
                
                if processed:
                    topic, payload = processed
                    _LOGGER.debug(f"Processed UDP data: topic={topic}, payload={payload}")
                    await self.udp_queue.put((topic, payload))
            except Exception as e:
                _LOGGER.error(f"Error in watch_rako: {e}", exc_info=True)
                await asyncio.sleep(1)

    async def process_mqtt_messages(self) -> None:
        """Process incoming MQTT messages"""
        _LOGGER.info("Starting MQTT message processor")


        # Modify MQTT_TOPICS to remove room-level topic
        MQTT_TOPICS: Final[List[Tuple[str, int]]] = [
            ("rako/room/+/channel/+/set", 1),
            ("rako/room/+/channel/+/command", 1),
        ]

        # Log all subscriptions
        for topic, qos in self.MQTT_TOPICS:
            _LOGGER.info(f"Subscribing to topic: {topic}")
            await self.mqtt_client.subscribe(topic, qos)

        while True:
            _LOGGER.debug("Waiting for MQTT message...")
            message = await self.mqtt_client.get_message()

            # Add detailed logging of incoming messages
            _LOGGER.debug(f"""MQTT Message received:
                Topic: {message.topic}
                Payload: {message.payload}
                QOS: {message.qos}
                Retain: {message.retain}
                """)

            try:
                if isinstance(message.payload, bytes):
                    payload_str = message.payload.decode('utf-8')
                else:
                    payload_str = str(message.payload)

                _LOGGER.debug(f"Decoded payload: {payload_str}")

                rako_command = RakoCommand.from_mqtt(
                    message.topic,
                    payload_str
                )

                if rako_command:
                    _LOGGER.info(f"Sending command to Rako bridge: {rako_command}")
                    # Fix: Await the post_command coroutine
                    await self.rako_bridge.post_command(rako_command)
                else:
                    _LOGGER.warning(f"Could not create RakoCommand from message: {message.topic} {payload_str}")
            except Exception as e:
                _LOGGER.error(f"Error processing MQTT message: {e}", exc_info=True)


    async def publish_status_updates(self) -> None:
        """Publish Rako status updates to MQTT"""
        _LOGGER.info("Starting status update publisher")
        while True:
            try:
                topic, payload = await self.udp_queue.get()
                _LOGGER.debug(f"Publishing status update: topic={topic}, payload={payload}")
                
                # Remove this block that adds an additional /state suffix since the topic
                # already includes it from RakoBridge.create_topic()
                """
                # Add state topic suffix for status updates
                if '/channel/' in topic:
                    status_topic = f"{topic}/state"
                else:
                    status_topic = f"{topic}/state"
                """
                # Use the topic directly as it already has /state
                status_topic = topic
                        
                await self.mqtt_client.publish(
                    status_topic,
                    json.dumps(payload),
                    qos=1,
                    retain=True
                )
            except Exception as e:
                _LOGGER.error(f"Error publishing status: {e}", exc_info=True)
                await asyncio.sleep(1)

    async def maintain_availability(self) -> None:
        """Maintain bridge availability status"""
        _LOGGER.info("Starting availability maintenance")
        availability_topic = "rako/bridge/status"
        while True:
            try:
                await self.mqtt_client.publish(
                    availability_topic,
                    "online",
                    qos=1,
                    retain=True
                )
                await asyncio.sleep(60)
            except Exception as e:
                _LOGGER.error(f"Error in availability maintenance: {e}", exc_info=True)
                try:
                    await self.mqtt_client.publish(
                        availability_topic,
                        "offline",
                        qos=1,
                        retain=True
                    )
                except:
                    pass
                raise

    async def shutdown(self) -> None:
        """Perform graceful shutdown of the bridge."""
        _LOGGER.info("Starting graceful shutdown")

        # Set bridge status to offline
        try:
            await self.mqtt_client.publish(
                "rako/bridge/status",
                "offline",
                qos=1,
                retain=True
            )
        except Exception as e:
            _LOGGER.error(f"Error publishing offline status: {e}")

        # Close UDP socket
        if hasattr(self, '_socket'):
            try:
                self._socket.close()
            except Exception as e:
                _LOGGER.error(f"Error closing UDP socket: {e}")

        # Disconnect MQTT
        try:
            await self.mqtt_client.disconnect()
        except Exception as e:
            _LOGGER.error(f"Error disconnecting MQTT: {e}")

        # Close telnet connection if exists
        if hasattr(self.rako_bridge, '_telnet') and self.rako_bridge._telnet:
            try:
                await self.rako_bridge._telnet.disconnect()
            except Exception as e:
                _LOGGER.error(f"Error closing telnet connection: {e}")

        _LOGGER.info("Shutdown completed")

    async def run(self) -> None:
        """Run the combined bridge"""
        _LOGGER.info("Starting RakoMQTT Bridge")
        tasks: List[asyncio.Task] = []

        try:
            async with AsyncExitStack() as stack:
                # Connect to MQTT
                _LOGGER.info("Connecting to MQTT broker...")
                await self.mqtt_client.connect()
                await self.mqtt_client.wait_for_connection(timeout=10)
                sock = await stack.enter_async_context(self.setup_udp_socket())
                _LOGGER.info("MQTT connection established")

                discovery = RakoDiscovery(self.mqtt_client, self.rako_bridge.host)
                await discovery.async_publish_discovery_configs()

                # Create tasks
                tasks = [
                    asyncio.create_task(self.watch_rako(sock), name="watch_rako"),
                    asyncio.create_task(self.process_mqtt_messages(), name="process_mqtt"),
                    asyncio.create_task(self.publish_status_updates(), name="publish_status"),
                    asyncio.create_task(self.maintain_availability(), name="maintain_availability"),
                ]

                # Wait for first task to complete or fail
                done, pending = await asyncio.wait(
                    tasks,
                    return_when=asyncio.FIRST_COMPLETED
                )

                # Check if any task failed
                for task in done:
                    if task.exception():
                        raise task.exception()

        except Exception as e:
            _LOGGER.error(f"Bridge crashed: {e}", exc_info=True)
            raise
        finally:
            _LOGGER.info("Starting cleanup")
            # Cancel all running tasks
            for task in tasks:
                if not task.done():
                    _LOGGER.debug(f"Cancelling task: {task.get_name()}")
                    task.cancel()

            if tasks:
                # Wait for tasks to complete with timeout
                try:
                    await asyncio.wait(tasks, timeout=5)
                except asyncio.TimeoutError:
                    _LOGGER.warning("Some tasks did not shut down cleanly")

            # Perform graceful shutdown
            await self.shutdown()

async def run_bridge(
    rako_bridge_host: str,
    mqtt_host: str,
    mqtt_user: str,
    mqtt_password: str,
    default_fade_rate: str = "medium"
) -> None:
    """Run the RakoMQTT bridge with the given configuration."""
    bridge = RakoMQTTBridge(
        rako_bridge_host=rako_bridge_host,
        mqtt_host=mqtt_host,
        mqtt_user=mqtt_user,
        mqtt_password=mqtt_password,
        default_fade_rate=default_fade_rate
    )
    try:
        await bridge.run()
    finally:
        try:
            await bridge.mqtt_client.publish(
                "rako/bridge/status",
                "offline",
                qos=1,
                retain=True
            )
            await bridge.mqtt_client.disconnect()
        except Exception as e:
            _LOGGER.error(f"Error during bridge cleanup: {e}")
