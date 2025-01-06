import json
import logging
import xml.etree.ElementTree as ET
import aiohttp
from dataclasses import dataclass
from typing import List

_LOGGER = logging.getLogger(__name__)

@dataclass
class RakoChannel:
    id: int
    name: str
    type: str

@dataclass
class RakoRoom:
    id: int
    name: str
    type: str
    channels: List[RakoChannel]

class RakoDiscovery:
    def __init__(self, mqtt_client, rako_bridge_host):
        self.mqtt_client = mqtt_client
        self.rako_bridge_host = rako_bridge_host

    async def async_publish_discovery_configs(self):
        """Query Rako bridge and publish discovery info for all devices."""
        _LOGGER.info(f"Starting discovery for Rako bridge at {self.rako_bridge_host}")
        try:
            # Test connectivity to bridge first
            _LOGGER.debug("Testing connection to Rako bridge...")
            async with aiohttp.ClientSession() as session:
                url = f"http://{self.rako_bridge_host}/rako.xml"
                async with session.get(url, timeout=5) as response:
                    if response.status != 200:
                        _LOGGER.error(f"Failed to connect to Rako bridge. Status: {response.status}")
                        return
                    _LOGGER.debug("Successfully connected to Rako bridge")

            rooms = await self._async_get_rooms_from_bridge()
            _LOGGER.info(f"Found {len(rooms)} rooms in bridge configuration")

            for room in rooms:
                _LOGGER.debug(f"Processing room: {room}")
                try:
                    await self._async_publish_room_config(room)
                    if room.type.lower() == "lights":
                        await self._async_publish_channel_config(room, RakoChannel(0, "All Channels", "master"))
                    for channel in room.channels:
                        await self._async_publish_channel_config(room, channel)
                except Exception as e:
                    _LOGGER.error(f"Failed to process room {room.id}: {e}")
                    continue

            _LOGGER.info("Discovery configuration completed successfully")

        except aiohttp.ClientError as e:
            _LOGGER.error(f"HTTP connection error during discovery: {e}")
            raise
        except asyncio.TimeoutError:
            _LOGGER.error("Timeout while connecting to Rako bridge")
            raise
        except Exception as e:
            _LOGGER.error(f"Failed to complete discovery: {e}", exc_info=True)
            raise

    async def _async_get_rooms_from_bridge(self) -> List[RakoRoom]:
        """Fetch and parse rako.xml from bridge."""
        _LOGGER.debug("Fetching room configuration from bridge...")
        try:
            url = f"http://{self.rako_bridge_host}/rako.xml"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=5) as response:
                    content = await response.text()
                    _LOGGER.debug(f"Received XML content (length: {len(content)})")

            root = ET.fromstring(content)
            _LOGGER.debug("Successfully parsed XML")
            rooms = []
            
            room_elems = root.findall('.//Room')
            _LOGGER.debug(f"Found {len(room_elems)} room elements")
            
            for room_elem in room_elems:
                try:
                    room_id = int(room_elem.get('id', 0))
                    room_type_elem = room_elem.find('Type')
                    room_title_elem = room_elem.find('Title')
                    
                    room_type = room_type_elem.text if room_type_elem is not None else 'Unknown'
                    room_name = room_title_elem.text if room_title_elem is not None else f'Room {room_id}'
                    
                    channels = []
                    channel_elems = room_elem.findall('Channel')
                    _LOGGER.debug(f"Found {len(channel_elems)} channels in room {room_id}")
                    
                    for channel_elem in channel_elems:
                        try:
                            channel_id = int(channel_elem.get('id', 0))
                            channel_name_elem = channel_elem.find('Name')
                            channel_type_elem = channel_elem.find('type')
                            
                            channel_name = channel_name_elem.text if channel_name_elem is not None else f'Channel {channel_id}'
                            channel_type = channel_type_elem.text if channel_type_elem is not None else 'unknown'
                            
                            channels.append(RakoChannel(
                                id=channel_id,
                                name=channel_name,
                                type=channel_type.lower()
                            ))
                        except ValueError as e:
                            _LOGGER.warning(f"Failed to parse channel in room {room_id}: {e}")
                            continue

                    room = RakoRoom(
                        id=room_id,
                        name=room_name,
                        type=room_type,
                        channels=sorted(channels, key=lambda x: x.id)
                    )
                    _LOGGER.debug(f"Successfully processed room: {room}")
                    rooms.append(room)
                except Exception as e:
                    _LOGGER.error(f"Failed to process room element: {e}")
                    continue

            sorted_rooms = sorted(rooms, key=lambda x: x.id)
            _LOGGER.info(f"Successfully processed {len(sorted_rooms)} rooms")
            return sorted_rooms

        except ET.ParseError as e:
            _LOGGER.error(f"Failed to parse XML from bridge: {e}")
            raise
        except Exception as e:
            _LOGGER.error(f"Failed to get rooms from Rako bridge: {e}", exc_info=True)
            raise

    async def _async_publish_room_config(self, room: RakoRoom):
        """Publish discovery configuration for a room."""
        _LOGGER.debug(f"Publishing room config for room {room.id}")
        try:
            unique_id = f"rako_room_{room.id}"
            
            display_name = room.name
            if room.type.lower() not in ['lights', 'switch']:
                display_name = f"{room.name} ({room.type})"

            config = {
                "name": display_name,
                "unique_id": unique_id,
                "state_topic": f"rako/room/{room.id}",
                "command_topic": f"rako/room/{room.id}/set",
                "schema": "json",
                "brightness": True,
                "device": {
                    "identifiers": [f"rako_bridge_{self.rako_bridge_host}"],
                    "name": "Rako Bridge",
                    "model": "RA-BRIDGE",
                    "manufacturer": "Rako",
                    "sw_version": "rakomqtt"
                },
                "availability_topic": "rako/bridge/status",
                "payload_available": "online",
                "payload_not_available": "offline"
            }
            
            discovery_topic = f"homeassistant/light/{unique_id}/config"
            await self.mqtt_client.publish(
                discovery_topic,
                json.dumps(config),
                qos=1,
                retain=True
            )
            _LOGGER.debug(f"Published room config for {room.name} (ID: {room.id})")
        except Exception as e:
            _LOGGER.error(f"Failed to publish room config for room {room.id}: {e}")
            raise

    async def _async_publish_channel_config(self, room: RakoRoom, channel: RakoChannel):
        """Publish discovery configuration for a specific channel."""
        _LOGGER.debug(f"Publishing channel config for room {room.id}, channel {channel.id}")
        try:
            unique_id = f"rako_room_{room.id}_channel_{channel.id}"
            
            if channel.id == 0:
                display_name = f"{room.name} (All)"
            else:
                display_name = f"{room.name} - {channel.name}"
                if channel.type not in ["unknown", "default"]:
                    display_name += f" ({channel.type})"

            config = {
                "name": display_name,
                "unique_id": unique_id,
                "state_topic": f"rako/room/{room.id}/channel/{channel.id}",
                "command_topic": f"rako/room/{room.id}/channel/{channel.id}/set",
                "schema": "json",
                "brightness": True,
                "device": {
                    "identifiers": [f"rako_bridge_{self.rako_bridge_host}"],
                    "name": "Rako Bridge",
                    "model": "RA-BRIDGE",
                    "manufacturer": "Rako",
                    "sw_version": "rakomqtt",
                    "via_device": f"rako_room_{room.id}"
                },
                "availability_topic": "rako/bridge/status",
                "payload_available": "online",
                "payload_not_available": "offline"
            }
            
            discovery_topic = f"homeassistant/light/{unique_id}/config"
            await self.mqtt_client.publish(
                discovery_topic,
                json.dumps(config),
                qos=1,
                retain=True
            )
            _LOGGER.debug(f"Published channel config for {display_name}")
        except Exception as e:
            _LOGGER.error(f"Failed to publish channel config: {e}")
            raise
