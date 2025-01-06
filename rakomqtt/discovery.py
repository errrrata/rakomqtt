import json
import logging
import xml.etree.ElementTree as ET
import requests
from dataclasses import dataclass
from typing import List, Optional

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

    def publish_discovery_configs(self):
        """Query Rako bridge and publish discovery info for all devices."""
        try:
            rooms = self._get_rooms_from_bridge()
            _LOGGER.info(f"Found {len(rooms)} rooms")
            for room in rooms:
                _LOGGER.info(f"Processing room: {room}")
                self._publish_room_config(room)
                # Only publish room controls for Light type rooms
                if room.type.lower() == "lights":
                    self._publish_channel_config(room, RakoChannel(0, "All Channels", "master"))
                # Publish individual channels
                for channel in room.channels:
                    self._publish_channel_config(room, channel)
        except Exception as e:
            _LOGGER.error(f"Failed to publish discovery configurations: {e}")
            raise

    def _get_rooms_from_bridge(self) -> List[RakoRoom]:
        """Fetch and parse rako.xml from bridge."""
        try:
            url = f"http://{self.rako_bridge_host}/rako.xml"
            _LOGGER.debug(f"Fetching Rako config from: {url}")
            response = requests.get(url, timeout=5)
            _LOGGER.debug(f"Got response: {response.status_code}")
            
            root = ET.fromstring(response.content)
            rooms = []
            
            room_elems = root.findall('.//Room')
            _LOGGER.debug(f"Found {len(room_elems)} room elements")
            
            for room_elem in room_elems:
                room_id = int(room_elem.get('id', 0))
                
                # Get room title and type
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
                        
                        # Get channel name and type
                        channel_name_elem = channel_elem.find('Name')
                        channel_type_elem = channel_elem.find('type')
                        
                        channel_name = channel_name_elem.text if channel_name_elem is not None else f'Channel {channel_id}'
                        channel_type = channel_type_elem.text if channel_type_elem is not None else 'unknown'
                        
                        channels.append(RakoChannel(
                            id=channel_id,
                            name=channel_name,
                            type=channel_type.lower()
                        ))
                        _LOGGER.debug(f"Added channel: {channel_id} - {channel_name} ({channel_type})")
                    except ValueError as e:
                        _LOGGER.warning(f"Failed to parse channel in room {room_id}: {e}")
                        continue

                room = RakoRoom(
                    id=room_id,
                    name=room_name,
                    type=room_type,
                    channels=sorted(channels, key=lambda x: x.id)
                )
                _LOGGER.info(f"Created room config: {room}")
                rooms.append(room)

            return sorted(rooms, key=lambda x: x.id)

        except Exception as e:
            _LOGGER.error(f"Failed to get rooms from Rako bridge: {e}")
            raise

    def _publish_room_config(self, room: RakoRoom):
        """Publish discovery configuration for a room."""
        unique_id = f"rako_room_{room.id}"
        
        # Include room type in the name if it's not a standard light
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
        self.mqtt_client.publish(discovery_topic, json.dumps(config), retain=True)
        _LOGGER.debug(f"Published discovery config for room: {room.name} (ID: {room.id})")

    def _publish_channel_config(self, room: RakoRoom, channel: RakoChannel):
        """Publish discovery configuration for a specific channel."""
        unique_id = f"rako_room_{room.id}_channel_{channel.id}"
        
        # Create appropriate name based on whether it's the master channel or individual channel
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
                "via_device": f"rako_room_{room.id}"  # Link to parent room
            },
            "availability_topic": "rako/bridge/status",
            "payload_available": "online",
            "payload_not_available": "offline"
        }
        
        discovery_topic = f"homeassistant/light/{unique_id}/config"
        self.mqtt_client.publish(discovery_topic, json.dumps(config), retain=True)
        _LOGGER.debug(f"Published discovery config for {display_name}")
