# ./rakomqtt/telnet_interface.py
import asyncio
import logging
from typing import Optional, AsyncGenerator, List

_LOGGER = logging.getLogger(__name__)

class RakoTelnetInterface:
    """Telnet interface to Rako bridge (port 9761)."""
    
    def __init__(self, host: str, port: int = 9761):
        self.host = host
        self.port = port
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self._connected = False
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        """Establish telnet connection."""
        try:
            self.reader, self.writer = await asyncio.open_connection(
                self.host, self.port
            )
            self._connected = True
            _LOGGER.info(f"Connected to Rako bridge telnet interface at {self.host}:{self.port}")
        except Exception as e:
            _LOGGER.error(f"Failed to connect to telnet interface: {e}")
            self._connected = False
            raise

    async def disconnect(self) -> None:
        """Close telnet connection."""
        if self.writer:
            try:
                self.writer.close()
                await self.writer.wait_closed()
            except Exception as e:
                _LOGGER.error(f"Error closing telnet connection: {e}")
            finally:
                self._connected = False
                self.writer = None
                self.reader = None

    async def send_command(self, command: bytes) -> Optional[bytes]:
        """Send raw command bytes and return response."""
        async with self._lock:  # Ensure commands are sent sequentially
            if not self._connected or not self.writer or not self.reader:
                await self.connect()
            
            try:
                self.writer.write(command + b'\r\n')
                await self.writer.drain()
                
                # Read response
                response = await self.reader.read(256)
                _LOGGER.debug(f"Telnet command response: {response}")
                return response
            except Exception as e:
                _LOGGER.error(f"Error sending telnet command: {e}")
                self._connected = False
                raise

    async def send_scene_command(self, room: int, channel: int, scene: int) -> None:
        """Send scene command over telnet."""
        # Format according to Rako RS232 protocol: ROOMxx,CHANNELxx,SCENExx
        command = f"ROOM{room:02d},CHANNEL{channel:02d},SCENE{scene:02d}".encode()
        try:
            response = await self.send_command(command)
            if response and b'OK' not in response:
                _LOGGER.warning(f"Unexpected response for scene command: {response}")
        except Exception as e:
            _LOGGER.error(f"Failed to send scene command: {e}")
            raise

    async def send_level_command(self, room: int, channel: int, level: int) -> None:
        """Send level command over telnet."""
        # Format: ROOMxx,CHANNELxx,LEVELxxx
        command = f"ROOM{room:02d},CHANNEL{channel:02d},LEVEL{level:03d}".encode()
        try:
            response = await self.send_command(command)
            if response and b'OK' not in response:
                _LOGGER.warning(f"Unexpected response for level command: {response}")
        except Exception as e:
            _LOGGER.error(f"Failed to send level command: {e}")
            raise

    async def send_identify_command(self, room: int, channel: int) -> None:
        """Send identify command over telnet."""
        command = f"ROOM{room:02d},CHANNEL{channel:02d},IDENT".encode()
        try:
            response = await self.send_command(command)
            if response and b'OK' not in response:
                _LOGGER.warning(f"Unexpected response for identify command: {response}")
        except Exception as e:
            _LOGGER.error(f"Failed to send identify command: {e}")
            raise

    async def monitor_responses(self) -> AsyncGenerator[bytes, None]:
        """Monitor telnet interface for responses."""
        if not self._connected:
            await self.connect()
            
        while self._connected and self.reader:
            try:
                response = await self.reader.read(256)
                if not response:  # Connection closed
                    self._connected = False
                    break
                    
                _LOGGER.debug(f"Received telnet response: {response}")
                yield response
            except Exception as e:
                _LOGGER.error(f"Error monitoring telnet responses: {e}")
                self._connected = False
                break

    @staticmethod
    def _parse_response(response: bytes) -> List[str]:
        """Parse telnet response into components."""
        try:
            decoded = response.decode().strip()
            return [part.strip() for part in decoded.split(',')]
        except Exception as e:
            _LOGGER.error(f"Error parsing telnet response: {e}")
            return []

    async def __aenter__(self) -> 'RakoTelnetInterface':
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.disconnect()
