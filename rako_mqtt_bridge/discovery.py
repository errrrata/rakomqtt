"""Device discovery and configuration for Rako integration."""
import json
import logging
from typing import List, Dict, Any, Optional, Final, Tuple
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
import aiohttp
from aiohttp.client_exceptions import ClientError

_LOGGER = logging.getLogger(__name__)

@dataclass
class RakoBridgeInfo:
    """Rako bridge information from XML."""
    version: str
    build_date: str
    host_name: str
    host_ip: str
    host_mac: str
    hw_status: str
    db_version: str

@dataclass(frozen=True)
class RakoChannel:
    id: int
    name: str
    type: str
    levels: Optional[str] = None  # Hex string of levels for scenes

@dataclass(frozen=True)
class RakoScene:
    id: int
    name: str

@dataclass(frozen=True)
class RakoRoom:
    id: int
    name: str
    type: str
    mode: Optional[str] = None
    scenes: Dict[int, str] = field(default_factory=dict)  # scene_id -> scene_name
    channels: List[RakoChannel] = field(default_factory=list)


class RakoDeviceType:
    """Mapping between Rako and Home Assistant device types."""
    
    MAPPINGS: Final[Dict[str, Tuple[str, Dict[str, Any]]]] = {
        "lights": ("light", {
            "schema": "json",
            "brightness": True,
            "state_value_template": "{{ value_json.state }}",
            "brightness_value_template": "{{ value_json.brightness }}",
            "brightness_scale": 255,
            "state_topic": "~/state",
            "command_topic": "~/set",
            "brightness_command_topic": "~/set",
            "command_template": '{"state": "{{ value }}"}',
            "brightness_command_template": '{"state": "ON", "brightness": {{ value }}}'
        }),
        "switch": ("switch", {
            "schema": "json",
            "state_value_template": "{{ value_json.state }}",
            "command_topic": "~/set",
            "state_topic": "~/state",
            "payload_on": '{"state": "ON"}',
            "payload_off": '{"state": "OFF"}',
            # Add these values for better state handling
            "value_template": "{{ value_json.state }}",  # Add this
            "state_on": "ON",                           # Add this
            "state_off": "OFF",                         # Add this
            "optimistic": False
        }),
        "blinds": ("cover", {
            "schema": "json",
            "device_class": "blind",
            "position_template": "{{ value_json.brightness }}",
            "set_position_template": "{{ position }}",
            "command_topic": "~/command",
            "position_topic": "~",
            "set_position_topic": "~/set",
            "payload_open": "OPEN",
            "payload_close": "CLOSE",
            "payload_stop": "STOP",
            "position_open": 255,
            "position_closed": 0,
            "state_open": "ON",
            "state_closed": "OFF",
            "optimistic": False
        }),
        "slider": ("light", {
            "schema": "json",
            "brightness": True,
            "state_value_template": "{{ value_json.state }}",
            "brightness_value_template": "{{ value_json.brightness }}",
            "brightness_scale": 255,
            "state_topic": "~/state",
            "command_topic": "~/set",
            "brightness_command_topic": "~/set",
            "command_template": '{"state": "{{ value }}"}',
            "brightness_command_template": '{"state": "ON", "brightness": {{ value }}}'
        }),
        "default": ("switch", {
            "schema": "json",
            "state_value_template": "{{ value_json.state }}",
            "command_topic": "~/set",
            "state_topic": "~/state",
            "payload_on": '{"state": "ON"}',
            "payload_off": '{"state": "OFF"}',
            # Add these values for better state handling
            "value_template": "{{ value_json.state }}",  # Add this
            "state_on": "ON",                           # Add this
            "state_off": "OFF",                         # Add this
            "optimistic": False
        })
    }

    @classmethod
    def get_mapping(cls, rako_type: str) -> Tuple[str, Dict[str, Any]]:
        """Get Home Assistant device type and config for Rako type."""
        rako_type = rako_type.lower()
        if rako_type in cls.MAPPINGS:
            return cls.MAPPINGS[rako_type]
        # Default to switch if type is unknown
        _LOGGER.warning(f"Unknown Rako device type: {rako_type}, defaulting to switch")
        return cls.MAPPINGS["default"]

class RakoDiscovery:
    """Handle device discovery for Rako integration."""

    TIMEOUT: Final[int] = 5
    BASE_SCHEMA: Final[Dict[str, Any]] = {
        "availability_topic": "rako/bridge/status",
        "payload_available": "online",
        "payload_not_available": "offline",
        "optimistic": False,
        "qos": 1
    }

    def __init__(self, mqtt_client: Any, rako_bridge_host: str):
        self.mqtt_client = mqtt_client
        self.rako_bridge_host = rako_bridge_host
        self.device_base_info = {
            "identifiers": [f"rako_bridge_{self.rako_bridge_host}"],
            "name": "Rako Bridge",
            "model": "RA-BRIDGE",
            "manufacturer": "Rako",
            "sw_version": "rakomqtt"
        }

    async def publish_config(self, discovery_topic: str, config: Dict[str, Any]) -> None:
        """Helper method to publish discovery config."""
        await self.mqtt_client.publish(
            discovery_topic,
            json.dumps(config),
            qos=1,
            retain=True
        )

    async def _test_bridge_connectivity(self) -> None:
        """Test connectivity to the Rako bridge."""
        _LOGGER.debug("Testing connection to Rako bridge...")
        async with aiohttp.ClientSession() as session:
            url = f"http://{self.rako_bridge_host}/rako.xml"
            async with session.get(url, timeout=self.TIMEOUT) as response:
                response.raise_for_status()
                _LOGGER.debug("Successfully connected to Rako bridge")

    async def _async_get_bridge_info(self) -> RakoBridgeInfo:
        """Get bridge version and info from XML."""
        async with aiohttp.ClientSession() as session:
            url = f"http://{self.rako_bridge_host}/rako.xml"
            async with session.get(url) as response:
                content = await response.text()
                root = ET.fromstring(content)
                info = root.find('info')

                return RakoBridgeInfo(
                    version=info.findtext('version', ''),
                    build_date=info.findtext('buildDate', ''),
                    host_name=info.findtext('hostName', '').strip(),
                    host_ip=info.findtext('hostIP', ''),
                    host_mac=info.findtext('hostMAC', ''),
                    hw_status=info.findtext('hwStatus', ''),
                    db_version=info.findtext('dbVersion', '')
                )

    async def _async_get_rooms_from_bridge(self) -> List[RakoRoom]:
        """Fetch and parse room configuration from the bridge."""
        _LOGGER.debug("Fetching room configuration from bridge...")
        async with aiohttp.ClientSession() as session:
            url = f"http://{self.rako_bridge_host}/rako.xml"
            async with session.get(url, timeout=self.TIMEOUT) as response:
                content = await response.text()
                _LOGGER.debug(f"Received XML content (length: {len(content)})")

        root = ET.fromstring(content)
        _LOGGER.debug("Successfully parsed XML")
        rooms: List[RakoRoom] = []
        
        for room_elem in root.findall('.//Room'):
            try:
                room = self._parse_room_element(room_elem)
                if room:
                    rooms.append(room)
            except Exception as e:
                _LOGGER.error(f"Failed to process room element: {e}")
                continue

        return sorted(rooms, key=lambda x: x.id)

    def _parse_scene_element(self, scene_elem: ET.Element) -> Optional[RakoScene]:
        """Parse a scene element from the XML."""
        try:
            scene_id = int(scene_elem.get('id', '0'))
            scene_name = scene_elem.findtext('Name', f'Scene {scene_id}')
            return RakoScene(id=scene_id, name=scene_name)
        except Exception as e:
            _LOGGER.error(f"Failed to parse scene element: {e}")
            return None

    def _parse_channel_element(self, channel_elem: ET.Element) -> Optional[RakoChannel]:
        """Parse a channel element from the XML."""
        try:
            channel_id = int(channel_elem.get('id', '0'))
            channel_name = channel_elem.findtext('Name', f'Channel {channel_id}')
            channel_type = channel_elem.findtext('type', 'unknown').lower()
            levels = channel_elem.findtext('Levels')
            
            return RakoChannel(
                id=channel_id,
                name=channel_name,
                type=channel_type,
                levels=levels
            )
        except Exception as e:
            _LOGGER.error(f"Failed to parse channel element: {e}")
            return None

    def _parse_room_element(self, room_elem: ET.Element) -> Optional[RakoRoom]:
        """Parse a room element from the XML."""
        try:
            room_id = int(room_elem.get('id', '0'))
            room_type = room_elem.findtext('Type', 'Unknown')
            room_name = room_elem.findtext('Title', f'Room {room_id}')
            room_mode = room_elem.findtext('mode')
            
            # Parse scenes
            scenes = {}
            for scene_elem in room_elem.findall('Scene'):
                scene = self._parse_scene_element(scene_elem)
                if scene:
                    scenes[scene.id] = scene.name
            
            # Parse channels
            channels = []
            for channel_elem in room_elem.findall('Channel'):
                channel = self._parse_channel_element(channel_elem)
                if channel:
                    channels.append(channel)

            return RakoRoom(
                id=room_id,
                name=room_name,
                type=room_type,
                mode=room_mode,
                scenes=scenes,
                channels=sorted(channels, key=lambda x: x.id)
            )
        except Exception as e:
            _LOGGER.error(f"Failed to parse room element: {e}")
            return None

    async def _async_publish_room_config(self, room: RakoRoom) -> None:
        """Publish discovery configuration for a room."""
        _LOGGER.debug(f"Publishing room config for room {room.id} ({room.type})")
        # We really do skip room-level config now
        return

    async def _async_publish_channel_config(self, room: RakoRoom, channel: RakoChannel) -> None:
        """Publish discovery configuration for a specific channel."""
        try:
            # Determine device type based on channel and room
            if channel.id == 0:
                # For channel 0, use room type
                device_type = room.type
                display_name = f"{room.name} (All)"
            else:
                # For specific channels, use channel type if not Default, otherwise use room type
                device_type = channel.type if channel.type.lower() != "default" else room.type
                display_name = f"{channel.name}"

            ha_type, type_config = RakoDeviceType.get_mapping(device_type)
            unique_id = f"rako_room_{room.id}_channel_{channel.id}"

            base_topic = f"rako/room/{room.id}/channel/{channel.id}"

            room_device_info = {
                "identifiers": [f"rako_room_{room.id}"],
                "name": room.name,
                "model": f"Rako {room.type}",
                "manufacturer": "Rako",
                "sw_version": "rakomqtt",
                "via_device": f"rako_bridge_{self.rako_bridge_host}",  # Link to bridge as parent device
            }

            # Replace ~ with actual base topic in type_config
            processed_config = {}
            for key, value in type_config.items():
                if isinstance(value, str) and "~" in value:
                    processed_config[key] = value.replace("~", base_topic)
                else:
                    processed_config[key] = value

            config = {
                "name": display_name,
                "unique_id": unique_id,
                "state_topic": f"{base_topic}/state",
                "command_topic": f"{base_topic}/set",
                "device": room_device_info,
                **self.BASE_SCHEMA,
                **processed_config
            }

            _LOGGER.debug(f"Publishing discovery config for {display_name}:")
            _LOGGER.debug(json.dumps(config, indent=2))

            discovery_topic = f"homeassistant/{ha_type}/{unique_id}/config"
            await self.publish_config(discovery_topic, config)
            _LOGGER.debug(f"Published {ha_type} device config for {display_name}")

        except Exception as e:
            _LOGGER.error(f"Failed to publish channel config: {e}")
            raise

    async def async_publish_discovery_configs(self) -> None:
        """Query Rako bridge and publish discovery info for all devices."""
        _LOGGER.info(f"Starting discovery for Rako bridge at {self.rako_bridge_host}")

        try:
            # Get bridge info first
            bridge_info = await self._async_get_bridge_info()

            # Update device info with actual bridge version
            self.device_base_info.update({
                "sw_version": bridge_info.version,
                "hw_version": bridge_info.hw_status,
                "configuration_url": f"http://{self.rako_bridge_host}"
            })

            # Publish bridge device info
            await self.publish_config(
                "homeassistant/device/rako_bridge/config",
                {
                    "name": bridge_info.host_name,
                    "identifiers": [f"rako_bridge_{bridge_info.host_mac}"],
                    "manufacturer": "Rako",
                    "model": "Bridge",
                    "sw_version": bridge_info.version,
                    "hw_version": bridge_info.hw_status,
                    "configuration_url": f"http://{self.rako_bridge_host}"
                }
            )

            await self._test_bridge_connectivity()
            rooms = await self._async_get_rooms_from_bridge()
            _LOGGER.info(f"Found {len(rooms)} rooms in bridge configuration")

            for room in rooms:
                _LOGGER.debug(f"Processing room: {room}")
                try:
                    # Skip room config as we're only using channel interface

                    # Process all channels including channel 0
                    await self._async_publish_channel_config(
                        room,
                        RakoChannel(0, "All Channels", "master")
                    )
                    for channel in room.channels:
                        await self._async_publish_channel_config(room, channel)
                except Exception as e:
                    _LOGGER.error(f"Failed to process room {room.id}: {e}")
                    continue

            _LOGGER.info("Discovery configuration completed successfully")

        except ClientError as e:
            _LOGGER.error(f"HTTP connection error during discovery: {e}")
            raise
        except Exception as e:
            _LOGGER.error(f"Failed to complete discovery: {e}", exc_info=True)
            raise
