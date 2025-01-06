import logging
from enum import IntEnum, Enum, auto
from typing import Optional, Tuple, Dict, Any, List, Union, Final
from .telnet_interface import RakoTelnetInterface
from dataclasses import dataclass
import socket
from functools import lru_cache

from rakomqtt.model import mqtt_payload_schema

_LOGGER = logging.getLogger(__name__)
DEFAULT_TIMEOUT: Final[int] = 5

class RakoCommandType(Enum):
    """Rako bridge command types.
    
    As documented in the Rako RS232 Command Summary:
    0x00-0x0F: Basic commands
    0x2D-0x34: Extended commands
    """
    OFF = 0x00
    FADE_UP = 0x01
    FADE_DOWN = 0x02
    SC1_LEGACY = 0x03
    SC2_LEGACY = 0x04
    SC3_LEGACY = 0x05
    SC4_LEGACY = 0x06
    IDENT = 0x08
    LEVEL_SET_LEGACY = 0x0C
    STORE = 0x0D
    STOP = 0x0F

    # Extended commands
    CUSTOM_232 = 0x2D  # Trigger custom string
    HOLIDAY = 0x2F     # Holiday mode control
    SET_SCENE = 0x31   # Set specific scene
    FADE = 0x32        # Fade control
    BUTTON_PRESS = 0x33  # Button press event
    SET_LEVEL = 0x34   # Set specific level

    @classmethod
    def from_byte(cls, byte_value: int) -> 'RakoCommandType':
        """Convert a byte value to RakoCommandType."""
        try:
            return cls(byte_value)
        except ValueError:
            _LOGGER.warning(f"Unknown command type: 0x{byte_value:02x}, treating as BUTTON_PRESS")
            return cls.BUTTON_PRESS

HOLIDAY_MODE_FLAGS: Final[Dict[str, int]] = {
    'STOP_PLAYBACK': 0x00,
    'START_PLAYBACK': 0x01,
    'START_RECORD': 0x02,
    'STOP_RECORD': 0x03
}

SCENE_COMMAND_FLAGS: Final[Dict[str, int]] = {
    'USE_DEFAULT_RATE': 0x01
}

SCENE_NUMBER_TO_COMMAND: Final[Dict[int, RakoCommandType]] = {
    1: RakoCommandType.SC1_LEGACY,
    2: RakoCommandType.SC2_LEGACY,
    3: RakoCommandType.SC3_LEGACY,
    4: RakoCommandType.SC4_LEGACY,
    0: RakoCommandType.OFF
}

SCENE_COMMAND_TO_NUMBER: Final[Dict[RakoCommandType, int]] = {
    v: k for k, v in SCENE_NUMBER_TO_COMMAND.items()
}

class RakoFadeRate(IntEnum):
    """Rako fade rates in seconds."""
    INSTANT = 0    # No fade
    FAST = 1      # ~2 seconds
    MEDIUM = 2    # ~4 seconds
    SLOW = 3      # ~8 seconds
    VERY_SLOW = 4 # ~16 seconds
    EXTRA_SLOW = 5 # ~32 seconds

    @classmethod
    def from_string(cls, name: str) -> 'RakoFadeRate':
        """Convert string name to RakoFadeRate."""
        try:
            return cls[name.upper()]
        except KeyError:
            _LOGGER.warning(f"Invalid fade rate '{name}', using MEDIUM")
            return cls.MEDIUM

class RakoDeserialisationException(Exception):
    """Exception raised when deserializing Rako messages fails."""

@dataclass(frozen=True)
class RakoStatusMessage:
    room_id: int          # Changed from 'room' to 'room_id'
    channel_id: int       # Changed from 'channel' to 'channel_id'
    command: RakoCommandType
    scene: Optional[int] = None
    brightness: Optional[int] = None

    @classmethod
    def from_byte_list(cls, byte_list: List[int]) -> 'RakoStatusMessage':
        if chr(byte_list[0]) != 'S':
            raise RakoDeserialisationException(
                f'Unsupported UDP message type: {chr(byte_list[0])}'
            )

        data_length = byte_list[1] - 5
        room_id = byte_list[3]
        channel_id = byte_list[4]
        command_byte = byte_list[5]
        data = byte_list[6:6 + data_length] if data_length > 0 else []

        _LOGGER.debug(f"Command byte: 0x{command_byte:02x}")

        # Handle button press command (0x33)
        if command_byte == 0x33:
            scene = data[-1] if data else 0
            _LOGGER.debug(f"Button press detected - Scene: {scene}")
            return cls(
                room_id=room_id,
                channel_id=channel_id,
                command=RakoCommandType.BUTTON_PRESS,
                scene=scene,
                brightness=cls._scene_brightness(scene)
            )

        try:
            command = RakoCommandType(command_byte)
        except ValueError as e:
            _LOGGER.error(f"Failed to create RakoCommandType from value 0x{command_byte:02x}")
            raise RakoDeserialisationException(str(e))

        _LOGGER.debug(f"Processing status message - Room: {room_id}, Channel: {channel_id}, Command: {command}, Data: {data}")

        match command:
            case RakoCommandType.LEVEL_SET_LEGACY | RakoCommandType.SET_LEVEL:
                if len(data) >= 2:
                    brightness = data[1]
                    return cls(
                        room_id=room_id,
                        channel_id=channel_id,
                        command=command,
                        brightness=brightness,
                    )
            case RakoCommandType.SET_SCENE:
                scene = data[1]
                return cls(
                    room_id=room_id,
                    channel_id=channel_id,
                    command=command,
                    scene=scene,
                    brightness=cls._scene_brightness(scene),
                )
            case RakoCommandType.FADE_UP:
                return cls(
                    room_id=room_id,
                    channel_id=channel_id,
                    command=command,
                    brightness=255
                )
            case RakoCommandType.FADE_DOWN:
                return cls(
                    room_id=room_id,
                    channel_id=channel_id,
                    command=command,
                    brightness=0
                )
            case RakoCommandType.STOP:
                return cls(
                    room_id=room_id,
                    channel_id=channel_id,
                    command=command,
                )

        raise RakoDeserialisationException(f"Unhandled command type: {command}")

    @staticmethod
    @lru_cache(maxsize=None)
    def _scene_brightness(rako_scene_number: int) -> int:
        scene_brightness: Final[Dict[int, int]] = {
            1: 255,  # Scene 1 (brightest)
            2: 192,  # Scene 2
            3: 128,  # Scene 3
            4: 64,   # Scene 4
            0: 0,    # Off
        }
        return scene_brightness[rako_scene_number]


@dataclass(frozen=True)
class RakoCommand:
    room_id: int  # Changed from 'room' to 'room_id' to match constructor
    channel_id: int  # Changed from 'channel' to 'channel_id'
    scene: Optional[int] = None
    brightness: Optional[int] = None
    command: Optional[RakoCommandType] = None
    fade_rate: Optional[RakoFadeRate] = None

    @staticmethod
    def _rako_command(brightness: int) -> int:
        """Convert brightness to Rako scene number"""
        if brightness == 0:
            return 0  # OFF
        elif brightness >= 255:
            return 1  # Scene 1 (100%)
        elif brightness >= 192:
            return 2  # Scene 2 (75%)
        elif brightness >= 128:
            return 3  # Scene 3 (50%)
        elif brightness >= 64:
            return 4  # Scene 4 (25%)
        return 0  # Default to OFF

    @classmethod
    def from_mqtt(cls, topic: str, payload_str: str) -> Optional['RakoCommand']:
        """Create RakoCommand from MQTT message"""
        import re
        topic_patterns = {
            'room': r'^rako/room/([0-9]+)/set$',
            'channel': r'^rako/room/([0-9]+)/channel/([0-9]+)/set$',
            'command': r'^rako/room/([0-9]+)/channel/([0-9]+)/command$'
        }
        
        matches = {
            name: re.match(pattern, topic) 
            for name, pattern in topic_patterns.items()
        }
        
        try:
            payload = mqtt_payload_schema.loads(payload_str)
            # Extract transition time if provided (in seconds)
            transition = payload.get('transition')
            fade_rate = None
            if transition is not None:
                # Map transition time to closest Rako fade rate
                if transition == 0:
                    fade_rate = RakoFadeRate.INSTANT
                elif transition <= 2:
                    fade_rate = RakoFadeRate.FAST
                elif transition <= 4:
                    fade_rate = RakoFadeRate.MEDIUM
                elif transition <= 8:
                    fade_rate = RakoFadeRate.SLOW
                elif transition <= 16:
                    fade_rate = RakoFadeRate.VERY_SLOW
                else:
                    fade_rate = RakoFadeRate.EXTRA_SLOW

            if matches['command']:  # Move command matching to first position
                room_id = int(matches['command'].group(1))
                channel_id = int(matches['command'].group(2))
                command_str = payload_str.strip().strip('"\'').upper()
                
                command_map = {
                    'OPEN': RakoCommandType.FADE_UP,
                    'CLOSE': RakoCommandType.FADE_DOWN,
                    'STOP': RakoCommandType.STOP
                }
                
                if command_str in command_map:
                    return cls(
                        room_id=room_id,
                        channel_id=channel_id,
                        command=command_map[command_str],
                        fade_rate=fade_rate
                    )
                else:
                    _LOGGER.warning(f"Unsupported cover command: {command_str}")
                    return None

            elif matches['room']:  # Changed from 'scene'
                room_id = int(matches['room'].group(1))
                payload = mqtt_payload_schema.loads(payload_str)
                _LOGGER.debug(f"Processing room command for room {room_id}")
                
                if 'state' in payload:
                    scene = 1 if payload['state'] == 'ON' else 0
                else:
                    scene = cls._rako_command(payload['brightness'])
                    
                return cls(
                    room_id=room_id,
                    channel_id=0,
                    scene=scene,
                )
                    
            elif matches['channel']:
                room_id = int(matches['channel'].group(1))
                channel_id = int(matches['channel'].group(2))
                payload = mqtt_payload_schema.loads(payload_str)
                _LOGGER.debug(f"Processing channel command for room {room_id} channel {channel_id}")
                
                if 'state' in payload:
                    if payload['state'] == 'ON':
                        brightness = payload.get('brightness', 255)
                    else:
                        brightness = 0
                elif 'brightness' in payload:
                    brightness = payload['brightness']
                else:
                    return None
                    
                return cls(
                    room_id=room_id,
                    channel_id=channel_id,
                    brightness=brightness
                )
                        
            else:
                _LOGGER.warning(f"No matching topic pattern for: {topic}")
                return None
                    
        except Exception as e:
            _LOGGER.error(f"Error processing MQTT message: {e}", exc_info=True)
            return None

    def to_udp_command(self) -> List[int]:
        """Convert RakoCommand to UDP command bytes"""
        if self.command:
            command_type = self.command
            data = [0x00]  # Add a data byte with value 0
        elif self.scene is not None:
            command_type = RakoCommandType.SET_SCENE
            # Set fade rate flags in first data byte
            flags = self.fade_rate.value if self.fade_rate else RakoFadeRate.MEDIUM.value
            data = [flags, self.scene]
        else:
            command_type = RakoCommandType.SET_LEVEL
            # Set fade rate flags in first data byte
            flags = self.fade_rate.value if self.fade_rate else RakoFadeRate.MEDIUM.value
            data = [flags, self.brightness]

        room_high = (self.room_id >> 8) & 0xFF
        room_low = self.room_id & 0xFF

        command = [
            0x52,  # 'R' for request
            5 + len(data),  # Number of bytes to follow
            room_high,
            room_low,
            self.channel_id,
            command_type.value,
            *data
        ]

        # Calculate checksum
        checksum = (256 - sum(command[1:]) % 256) % 256
        command.append(checksum)

        return command

@dataclass
class SceneCacheEntry:
    """Represents a single scene cache entry."""
    room_id: int
    scene_id: int

@dataclass
class LevelCacheEntry:
    """Represents a single level cache entry."""
    room_id: int
    channel_id: int
    levels: List[int]  # List of 16 level values
    active: bool
    deleted: bool

class RakoBridge:
    port: Final[int] = 9761

    def __init__(self, host: Optional[str] = None, default_fade_rate: str = "medium"):
        self.host = host if host else self.find_bridge()
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.settimeout(DEFAULT_TIMEOUT)
        self._telnet: Optional[RakoTelnetInterface] = None
        self._use_telnet = False
        self._command_retries = 3
        self.default_fade_rate = RakoFadeRate.from_string(default_fade_rate)

    def create_command(self, room_id: int, channel_id: int,
                      scene: Optional[int] = None,
                      brightness: Optional[int] = None,
                      command: Optional[RakoCommandType] = None,
                      fade_rate: Optional[RakoFadeRate] = None) -> RakoCommand:
        """Create a RakoCommand with default fade rate if none specified."""
        return RakoCommand(
            room_id=room_id,
            channel_id=channel_id,
            scene=scene,
            brightness=brightness,
            command=command,
            fade_rate=fade_rate if fade_rate is not None else self.default_fade_rate
        )

    async def _init_telnet(self) -> None:
        """Initialize telnet interface if needed."""
        if not self._telnet and self.host:
            self._telnet = RakoTelnetInterface(self.host)
            try:
                await self._telnet.connect()
            except Exception as e:
                _LOGGER.error(f"Failed to initialize telnet interface: {e}")
                self._telnet = None

    async def get_level_cache(self) -> List[LevelCacheEntry]:
        """Get current level cache from bridge."""
        try:
            async with aiohttp.ClientSession() as session:
                url = f"http://{self.host}/levels.htm"
                async with session.get(url) as response:
                    content = await response.text()
                    return self._parse_level_cache(content)
        except Exception as e:
            _LOGGER.error(f"Failed to get level cache: {e}")
            return []

    def _parse_level_cache(self, cache_content: str) -> List[LevelCacheEntry]:
        """Parse level cache response.

        Format per documentation:
        Byte 0: 0x58 ('X' for data record)
        Byte 1: Record type (0x04 for level cache)
        Byte 2: Flags (bit 7: Active, bit 6: Deleted)
        Bytes 2-3: Room ID (10 bits)
        Byte 4: Channel
        Bytes 5-20: Level values for scenes 1-16
        """
        entries = []
        try:
            # Remove any whitespace and process in chunks
            data = bytes.fromhex(cache_content.replace(' ', ''))

            pos = 0
            while pos < len(data):
                if data[pos] != 0x58:  # 'X'
                    pos += 1
                    continue

                if data[pos + 1] != 0x04:  # Level cache record type
                    pos += 1
                    continue

                flags = data[pos + 2]
                active = bool(flags & 0x80)
                deleted = bool(flags & 0x40)

                room_id = ((data[pos + 2] & 0x03) << 8) | data[pos + 3]
                channel_id = data[pos + 4]

                # Get 16 level values
                levels = list(data[pos + 5:pos + 21])

                entries.append(LevelCacheEntry(
                    room_id=room_id,
                    channel_id=channel_id,
                    levels=levels,
                    active=active,
                    deleted=deleted
                ))

                pos += 21  # Move to next record

        except Exception as e:
            _LOGGER.error(f"Error parsing level cache: {e}")

        return entries

    async def get_scene_cache(self) -> List[SceneCacheEntry]:
        """Get current scene cache from bridge.

        Format example: 0x04041006 represents:
        - Room 4 Scene 1
        - Room 6 Scene 4
        """
        try:
            async with aiohttp.ClientSession() as session:
                url = f"http://{self.host}/scenes.htm"
                async with session.get(url) as response:
                    content = await response.text()
                    return self._parse_scene_cache(content)
        except Exception as e:
            _LOGGER.error(f"Failed to get scene cache: {e}")
            return []

    def _parse_scene_cache(self, cache_content: str) -> List[SceneCacheEntry]:
        """Parse scene cache hex string into entries."""
        entries = []
        # Remove 0x prefix if present and process in 4-character chunks
        cache_content = cache_content.replace('0x', '')
        for i in range(0, len(cache_content), 4):
            chunk = cache_content[i:i+4]
            if len(chunk) == 4:
                try:
                    value = int(chunk, 16)
                    scene_id = (value >> 12) & 0x0F  # First 4 bits
                    room_id = value & 0x3FF         # Last 10 bits
                    entries.append(SceneCacheEntry(room_id=room_id, scene_id=scene_id))
                except ValueError:
                    _LOGGER.warning(f"Invalid scene cache entry: {chunk}")
                    continue
        return entries

    @classmethod
    def find_bridge(cls) -> Optional[str]:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(DEFAULT_TIMEOUT)

        resp = cls.poll_for_bridge_response(sock)
        if resp:
            _, (host, _) = resp
            _LOGGER.debug(f'Found Rako bridge at {host}')
            return host
        else:
            _LOGGER.error('Cannot find a Rako bridge after 3 attempts')
            return None

    @classmethod
    def poll_for_bridge_response(cls, sock: socket.socket) -> Optional[Tuple[bytes, Any]]:
        sock.bind(('', 0))
        for i in range(1, 4):
            _LOGGER.debug(f"Broadcasting attempt #{i} to find Rako bridge...")
            sock.sendto(b'D', ('255.255.255.255', cls.port))
            try:
                resp = sock.recvfrom(256)
                _LOGGER.debug(f"Received response: {resp}")
                return resp
            except socket.timeout:
                _LOGGER.debug(f"No Rako bridge found on try #{i}")
        return None

    @staticmethod
    def calculate_checksum(data: List[int]) -> int:
        """Calculate checksum for UDP command"""
        total = sum(data) % 256
        return (256 - total) % 256

    def send_udp_command(self, command_bytes: List[int]) -> None:
        """Send UDP command to Rako bridge"""
        try:
            # Convert list of ints to bytes
            data = bytes(command_bytes)
            
            _LOGGER.debug(f"Sending raw bytes: {' '.join(f'0x{b:02x}' for b in data)}")
            
            self._socket.sendto(data, (self.host, self.port))
            response = self._socket.recv(256)
            
            if response == b'AOK\r\n':
                _LOGGER.debug("Command acknowledged")
            else:
                _LOGGER.warning(f"Unexpected response: {response}")
                # Log the command that caused the error
                _LOGGER.warning(f"Command that caused error: {' '.join(f'0x{b:02x}' for b in command_bytes)}")
        except Exception as e:
            _LOGGER.error(f"Failed to send UDP command: {e}")

    async def post_command(self, rako_command: RakoCommand) -> None:
        """Send command to Rako bridge using UDP with telnet fallback."""
        for attempt in range(self._command_retries):
            try:
                if not self._use_telnet:
                    # Try UDP first
                    command_bytes = rako_command.to_udp_command()
                    _LOGGER.debug(f"Sending UDP command: {[hex(b) for b in command_bytes]}")
                    self.send_udp_command(command_bytes)
                    return
                    
            except Exception as e:
                _LOGGER.warning(f"UDP command failed (attempt {attempt + 1}): {e}")
                self._use_telnet = True

            if self._use_telnet:
                try:
                    # Fallback to telnet
                    if not self._telnet:
                        await self._init_telnet()
                    
                    if self._telnet:
                        if rako_command.scene is not None:
                            await self._telnet.send_scene_command(
                                rako_command.room_id,
                                rako_command.channel_id,
                                rako_command.scene
                            )
                        elif rako_command.brightness is not None:
                            await self._telnet.send_level_command(
                                rako_command.room_id,
                                rako_command.channel_id,
                                rako_command.brightness
                            )
                        return
                        
                except Exception as e:
                    _LOGGER.error(f"Telnet command failed: {e}")
                    self._telnet = None
                    self._use_telnet = False
                    
            # Add delay between retries
            if attempt < self._command_retries - 1:
                await asyncio.sleep(1)
                
        raise Exception("Failed to send command via both UDP and telnet")

    async def start_monitoring(self) -> None:
        """Start monitoring both UDP and telnet interfaces."""
        if self._telnet:
            asyncio.create_task(self._monitor_telnet())

    async def _monitor_telnet(self) -> None:
        """Monitor telnet interface for responses."""
        if not self._telnet:
            return

        async for response in self._telnet.monitor_responses():
            try:
                # Parse telnet response and convert to status message
                status = self._parse_telnet_response(response)
                if status:
                    # Process status message
                    self._process_status_message(status)
            except Exception as e:
                _LOGGER.error(f"Error processing telnet response: {e}")

    def _parse_telnet_response(self, response: bytes) -> Optional[RakoStatusMessage]:
        """Parse telnet response into status message."""
        try:
            # Implement parsing based on protocol documentation
            # Convert telnet format to RakoStatusMessage
            pass
        except Exception as e:
            _LOGGER.error(f"Error parsing telnet response: {e}")
            return None

    @property
    def found_bridge(self) -> bool:
        return bool(self.host)

    @classmethod
    def process_udp_bytes(cls, byte_list: List[int]) -> Optional[Tuple[str, Dict[str, Any]]]:
        """Process incoming UDP status messages"""
        _LOGGER.debug(f'received byte_list: {byte_list}')

        try:
            rako_status_message = RakoStatusMessage.from_byte_list(byte_list)
        except (RakoDeserialisationException, ValueError, IndexError) as ex:
            _LOGGER.debug(f'unhandled bytestring: {ex}')
            return None

        topic = cls.create_topic(rako_status_message)
        payload = cls.create_payload(rako_status_message)

        return topic, payload

    @staticmethod
    def create_topic(rako_status_message: RakoStatusMessage) -> str:
        # Change this method to handle both room and channel level topics consistently
        if rako_status_message.channel_id == 0:
            return f"rako/room/{rako_status_message.room_id}/state"
        else:
            return f"rako/room/{rako_status_message.room_id}/channel/{rako_status_message.channel_id}/state"

    @staticmethod
    def create_payload(rako_status_message: RakoStatusMessage) -> Dict[str, Any]:
        """Create MQTT payload from status message"""
        match rako_status_message.command:
            case RakoCommandType.SET_LEVEL | RakoCommandType.LEVEL_SET_LEGACY:
                return {
                    "state": 'ON' if rako_status_message.brightness else 'OFF',
                    "brightness": rako_status_message.brightness
                }
            case RakoCommandType.SET_SCENE:
                state = 'ON' if rako_status_message.scene > 0 else 'OFF'
                brightness = 255 if rako_status_message.scene > 0 else 0
                return {
                    "state": state,
                    "brightness": brightness
                }
            case RakoCommandType.BUTTON_PRESS:  # Add this case
                return {
                    "state": 'ON' if rako_status_message.scene > 0 else 'OFF',
                    "brightness": rako_status_message.brightness or 0,
                    "scene": rako_status_message.scene,
                    "event": "button_press",
                    "event_type": "scene",
                    "event_data": {
                        "scene": rako_status_message.scene
                    }
                }
            case RakoCommandType.FADE_UP:
                return {
                    "state": "ON",
                    "brightness": 255,
                    "action": "opening"
                }
            case RakoCommandType.FADE_DOWN:
                return {
                    "state": "ON",
                    "brightness": 0,
                    "action": "closing"
                }
            case RakoCommandType.STOP:
                return {
                    "action": "stopped"
                }
            case _:
                _LOGGER.warning(f"Unsupported command type for payload: {rako_status_message.command}")
                return {
                    "state": "OFF",
                    "brightness": 0
                }


if __name__ == '__main__':
    import sys
    bridge = RakoBridge()
    print(bridge.host)
    sys.exit(0 if bridge.host else 1)
