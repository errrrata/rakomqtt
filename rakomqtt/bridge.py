import queue
import asyncio
import json
import logging
import socket
import paho.mqtt.client as mqtt
from concurrent.futures import ThreadPoolExecutor
from contextlib import AsyncExitStack

from rakomqtt.RakoBridge import RakoBridge, RakoCommand
from rakomqtt.discovery import RakoDiscovery

_LOGGER = logging.getLogger(__name__)

class AsyncioMQTTClient:
    def __init__(self, host, user, password):
        self.client = mqtt.Client()
        self.client.username_pw_set(user, password)
        self.client.enable_logger()
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_subscribe = self._on_subscribe
        self.client.on_publish = self._on_publish
        self.host = host
        self.connected = asyncio.Event()
        self._thread_queue = queue.Queue()
        self._message_queue = asyncio.Queue()
        self.is_connected = False
        self._thread_pool = ThreadPoolExecutor(max_workers=1)
        self._queue_task = None

    def _on_connect(self, client, userdata, flags, rc):
        _LOGGER.info(f"MQTT Connected with result code {rc}")
        self.is_connected = True
        self.connected.set()

    def _on_message(self, client, userdata, msg):
        _LOGGER.debug(f"Received MQTT message on topic {msg.topic}: {msg.payload}")
        try:
            self._thread_queue.put_nowait(msg)
        except queue.Full:
            _LOGGER.error("Message queue is full, dropping message")

    async def _process_thread_queue(self):
        """Process messages from the thread queue and move them to the async queue"""
        while True:
            try:
                # Use executor to check thread queue in a non-blocking way
                msg = await asyncio.get_event_loop().run_in_executor(
                    self._thread_pool,
                    self._thread_queue.get_nowait
                )
                await self._message_queue.put(msg)
            except queue.Empty:
                await asyncio.sleep(0.1)  # Don't busy-wait
            except Exception as e:
                _LOGGER.error(f"Error processing thread queue: {e}")
                await asyncio.sleep(1)

    async def connect(self):
        """Connect to MQTT broker"""
        if self.is_connected:
            return

        _LOGGER.debug(f"Connecting to MQTT broker at {self.host}")
        self.client.will_set("rako/bridge/status", "offline", retain=True)
        self.client.connect(self.host, 1883, 60)
        self.client.loop_start()
        
        # Start the queue processing task
        if not self._queue_task:
            self._queue_task = asyncio.create_task(self._process_thread_queue())

    async def disconnect(self):
        """Disconnect from MQTT broker"""
        _LOGGER.debug("Disconnecting from MQTT broker")
        if self.is_connected:
            self.is_connected = False
            self.connected.clear()
            
            # Cancel queue processing task
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

    def _on_subscribe(self, client, userdata, mid, granted_qos=None):
        _LOGGER.debug(f"Subscribed successfully: {mid}, QoS: {granted_qos}")

    def _on_publish(self, client, userdata, mid):
        _LOGGER.debug(f"Published message: {mid}")

    async def subscribe(self, topic, qos=0):
        _LOGGER.debug(f"Subscribing to topic: {topic} with QoS {qos}")
        result, mid = self.client.subscribe(topic, qos)
        if result != mqtt.MQTT_ERR_SUCCESS:
            raise Exception(f"Failed to subscribe to {topic}: {result}")
        _LOGGER.debug(f"Subscribe initiated with message ID: {mid}")

    async def publish(self, topic, payload=None, qos=0, retain=False):
        _LOGGER.debug(f"Publishing to topic {topic}: {payload}")
        result, mid = self.client.publish(topic, payload, qos, retain)
        if result != mqtt.MQTT_ERR_SUCCESS:
            raise Exception(f"Failed to publish to {topic}: {result}")
        _LOGGER.debug(f"Publish initiated with message ID: {mid}")

    async def get_message(self):
        return await self._message_queue.get()

    async def wait_for_connection(self, timeout=10):
        """Wait for MQTT connection to be established"""
        try:
            await asyncio.wait_for(self.connected.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            raise TimeoutError(f"Timeout waiting for MQTT connection to {self.host}")

class RakoMQTTBridge:
    def __init__(self, rako_bridge_host, mqtt_host, mqtt_user, mqtt_password):
        if not rako_bridge_host:
            _LOGGER.error("No Rako bridge host provided")
            raise ValueError("Rako bridge host is required")
        
        _LOGGER.info(f"Initializing bridge with Rako host: {rako_bridge_host}")
        self.rako_bridge = RakoBridge(rako_bridge_host)
        self.mqtt_client = AsyncioMQTTClient(mqtt_host, mqtt_user, mqtt_password)
        self.udp_queue = asyncio.Queue()

    async def setup_udp_socket(self):
        """Setup UDP socket for receiving Rako bridge messages"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        _LOGGER.info(f"Binding UDP socket to port {RakoBridge.port}")
        sock.bind(("", RakoBridge.port))
        sock.setblocking(False)
        return sock

    async def watch_rako(self, sock):
        """Listen for Rako bridge UDP broadcasts"""
        _LOGGER.info("Starting Rako UDP watcher")
        
        loop = asyncio.get_event_loop()
        while True:
            try:
                _LOGGER.debug("Waiting for UDP data...")
                # Change the unpacking to handle raw data
                data = await loop.sock_recv(sock, 256)
                if not data:
                    _LOGGER.debug("No data received, continuing...")
                    await asyncio.sleep(0.1)
                    continue
                    
                _LOGGER.debug(f"Received UDP data: {list(data)}")
                byte_list = list(data)
                processed = RakoBridge.process_udp_bytes(byte_list)
                
                if processed:
                    topic, payload = processed
                    _LOGGER.debug(f"Processed UDP data: topic={topic}, payload={payload}")
                    await self.udp_queue.put((topic, payload))
            except Exception as e:
                _LOGGER.error(f"Error in watch_rako: {e}", exc_info=True)
                await asyncio.sleep(1)

    async def process_mqtt_messages(self):
        """Process incoming MQTT messages"""
        _LOGGER.info("Starting MQTT message processor")
        mqtt_topics = [
            ("rako/room/+/set", 1),
            ("rako/room/+/channel/+/set", 1),
        ]
        
        for topic, qos in mqtt_topics:
            _LOGGER.info(f"Subscribing to topic: {topic}")
            await self.mqtt_client.subscribe(topic, qos)
        
        while True:
            _LOGGER.debug("Waiting for MQTT message...")
            message = await self.mqtt_client.get_message()
            _LOGGER.debug(f"Processing MQTT message: {message.topic}")
            try:
                rako_command = RakoCommand.from_mqtt(
                    message.topic,
                    message.payload.decode()
                )
                if rako_command:
                    _LOGGER.info(f"Sending command to Rako bridge: {rako_command}")
                    self.rako_bridge.post_command(rako_command)
            except Exception as e:
                _LOGGER.error(f"Error processing MQTT message: {e}", exc_info=True)

    async def publish_status_updates(self):
        """Publish Rako status updates to MQTT"""
        _LOGGER.info("Starting status update publisher")
        while True:
            try:
                _LOGGER.debug("Waiting for status update...")
                topic, payload = await self.udp_queue.get()
                _LOGGER.debug(f"Publishing status update: topic={topic}, payload={payload}")
                await self.mqtt_client.publish(
                    topic, 
                    json.dumps(payload),
                    qos=1,
                    retain=True
                )
            except Exception as e:
                _LOGGER.error(f"Error publishing status: {e}", exc_info=True)
                await asyncio.sleep(1)

    async def maintain_availability(self):
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

    async def run(self):
        """Run the combined bridge"""
        _LOGGER.info("Starting RakoMQTT Bridge")
        tasks = []
        try:
            # Connect to MQTT with timeout
            _LOGGER.info("Connecting to MQTT broker...")
            await self.mqtt_client.connect()
            await self.mqtt_client.wait_for_connection(timeout=10)
            _LOGGER.info("MQTT connection established")

            # Setup UDP socket
            _LOGGER.info("Setting up UDP socket...")
            sock = await self.setup_udp_socket()
            _LOGGER.info("UDP socket ready")

            # Setup discovery with timeout
            _LOGGER.info(f"Starting device discovery for bridge at {self.rako_bridge.host}")
            try:
                discovery = RakoDiscovery(self.mqtt_client, self.rako_bridge.host)
                await asyncio.wait_for(discovery.async_publish_discovery_configs(), timeout=30)
                _LOGGER.info("Device discovery completed")
            except asyncio.TimeoutError:
                _LOGGER.error("Discovery timed out, continuing without it")
            except Exception as e:
                _LOGGER.error(f"Discovery failed: {e}", exc_info=True)

            # Start Rako watcher
            _LOGGER.info("Starting Rako watcher...")
            watcher = asyncio.create_task(self.watch_rako(sock))
            tasks.append(watcher)

            # Start MQTT message processor
            _LOGGER.info("Starting MQTT message processor...")
            mqtt_processor = asyncio.create_task(self.process_mqtt_messages())
            tasks.append(mqtt_processor)

            # Start status publisher
            _LOGGER.info("Starting status publisher...")
            status_publisher = asyncio.create_task(self.publish_status_updates())
            tasks.append(status_publisher)

            # Start availability maintenance
            _LOGGER.info("Starting availability maintenance...")
            availability = asyncio.create_task(self.maintain_availability())
            tasks.append(availability)

            _LOGGER.info("All tasks started, monitoring for completion")
            
            # Wait for first task to complete or fail
            while True:
                done, pending = await asyncio.wait(
                    tasks,
                    return_when=asyncio.FIRST_COMPLETED
                )

                # Check if any tasks failed
                for task in done:
                    if task.exception():
                        raise task.exception()
                    else:
                        _LOGGER.warning(f"Task completed unexpectedly")
                        return

                # Recreate any completed tasks
                for task in done:
                    tasks = [t for t in tasks if t != task]
                    if task == watcher:
                        new_task = asyncio.create_task(self.watch_rako(sock))
                    elif task == mqtt_processor:
                        new_task = asyncio.create_task(self.process_mqtt_messages())
                    elif task == status_publisher:
                        new_task = asyncio.create_task(self.publish_status_updates())
                    elif task == availability:
                        new_task = asyncio.create_task(self.maintain_availability())
                    tasks.append(new_task)

        except Exception as e:
            _LOGGER.error(f"Bridge crashed: {e}", exc_info=True)
            raise
        finally:
            _LOGGER.info("Shutting down bridge")
            # Cancel all tasks
            for task in tasks:
                if not task.done():
                    task.cancel()
            # Wait for tasks to complete
            if tasks:
                await asyncio.wait(tasks, timeout=5)
            await self.mqtt_client.disconnect()

async def run_bridge(rako_bridge_host, mqtt_host, mqtt_user, mqtt_password):
    """Run the RakoMQTT bridge with the given configuration."""
    bridge = RakoMQTTBridge(
        rako_bridge_host,
        mqtt_host,
        mqtt_user,
        mqtt_password
    )
    await bridge.run()
