# Rako MQTT Bridge Documentation

## Overview
The Rako MQTT Bridge provides integration between Rako lighting systems and MQTT-based home automation systems like Home Assistant. It supports all Rako bridge features including extended room ranges, scene control, and various device types.

## Features

### Core Features
- Auto-discovery of Rako bridge devices
- Support for all Rako device types
- Scene control with named scenes
- Extended room and channel range support
- Configurable fade rates
- Automatic Home Assistant device discovery
- Real-time status monitoring
- Multiple communication methods (UDP + Telnet fallback)

### Device Support Matrix

| Rako Type | Home Assistant Entity | Capabilities | Features |
|-----------|---------------------|--------------|----------|
| Lights    | Light              | Brightness, Scenes | Full dimming control, Scene selection |
| Slider    | Light              | Brightness, Scenes | Smooth dimming, Multiple scenes |
| Switch    | Switch             | On/Off | Binary control |
| Blinds    | Cover              | Position, Commands | Open, Close, Stop, Position control |
| LED Strip | Light              | Brightness | Dimming control |
| Curtains  | Cover              | Position, Commands | Open, Close, Stop, Position control |
| Default   | Light              | Brightness, Scenes | Standard light control |

### Room Range Support
- Standard rooms: 1-255
- Extended range: 256-1019
- Reserved range: 1020-1023
- Whole house control: Room 0

### Channel Support
- Standard range: 1-15
- Extended range: 16-255
- All channels: Channel 0

## Installation

### Prerequisites
- Home Assistant installation
- MQTT broker (like Mosquitto)
- Network access to Rako bridge

### Docker Installation
```bash
docker-compose up -d
```

### Home Assistant Add-on Installation
1. Add repository to Home Assistant
2. Install the add-on
3. Configure required settings
4. Start the add-on

## Configuration

### Configuration Options
```yaml
rako_bridge_host: ""  # Optional, will auto-discover if empty
mqtt_host: "core-mosquitto"
mqtt_user: ""
mqtt_password: ""
debug: false
default_fade_rate: "medium"  # Options below
```

### Fade Rate Options
- `instant`: No fade
- `fast`: ~2 seconds
- `medium`: ~4 seconds
- `slow`: ~8 seconds
- `very_slow`: ~16 seconds
- `extra_slow`: ~32 seconds

## MQTT Protocol

### Topics Structure

#### Command Topics
- Room Control: `rako/room/{room_id}/set`
- Channel Control: `rako/room/{room_id}/channel/{channel_id}/set`
- Cover Commands: `rako/room/{room_id}/channel/{channel_id}/command`

#### State Topics
- Room State: `rako/room/{room_id}/state`
- Channel State: `rako/room/{room_id}/channel/{channel_id}/state`
- Bridge Status: `rako/bridge/status`

### Payload Formats

#### Light/Switch Control
```json
{
  "state": "ON",
  "brightness": 255,
  "transition": 2
}
```

#### Scene Control
```json
{
  "scene": 1,
  "transition": 2
}
```

#### Cover Control
```json
{
  "command": "OPEN"  // OPEN, CLOSE, or STOP
}
```

#### Level Control
```json
{
  "brightness": 128,  // 0-255
  "transition": 2     // seconds
}
```

### Scene Configuration
Scenes are defined in the Rako bridge configuration and automatically discovered. Scene mapping:
- Scene 0: Off
- Scene 1-16: Standard scenes
- Scene 17+: Reserved for future use

## Device Discovery

### Home Assistant Integration
The bridge automatically provides MQTT discovery information to Home Assistant, creating:
- Light entities for dimmable lights
- Switch entities for non-dimming devices
- Cover entities for blinds/curtains
- Scene entities for room scenes

### Device Configuration
Device configuration is read from the bridge's XML configuration file, which includes:
- Room names and types
- Channel configuration
- Scene names
- Level patterns
- Device types

## Technical Details

### Communication Methods

#### Primary: UDP
- Port: 9761
- Bidirectional communication
- Status updates via UDP broadcast
- Command format documented in Rako protocol specification

#### Fallback: Telnet
- Port: 9761
- Used when UDP fails
- Simple text-based protocol
- Automatic fallback handling

### Error Handling
1. Automatic retry mechanism
2. Communication method fallback
3. Reconnection handling
4. Error logging and reporting

### Bridge Status Monitoring
- Regular availability checks
- Automatic offline detection
- Status reporting via MQTT
- Health check endpoints

## Troubleshooting

### Debug Mode
Enable debug logging in configuration:
```yaml
debug: true
```

### Common Issues

#### Bridge Not Found
- Check network connectivity
- Verify bridge IP address
- Ensure bridge is powered and online
- Check network ports (9761) are open

#### MQTT Connection Issues
- Verify MQTT broker address
- Check credentials
- Ensure MQTT broker is running
- Verify network connectivity

#### Device Control Issues
- Check room and channel IDs
- Verify device type configuration
- Review MQTT payload format
- Enable debug logging for detailed information

### Logging
- Location: Container logs
- Format: JSON structured logging
- Levels: DEBUG, INFO, WARNING, ERROR
- Rotation: 10MB files, 3 backups

## Development

### Building from Source
```bash
git clone https://github.com/yourusername/rakomqtt
cd rakomqtt
docker build -t rakomqtt .
```

### Testing
```bash
pip install -r requirements.txt
pytest
```

### Contributing
1. Fork the repository
2. Create a feature branch
3. Make changes
4. Add tests
5. Create pull request

## Support

### Getting Help
- GitHub Issues
- Documentation Wiki
- Community Forums

### Reporting Issues
- Use GitHub issue tracker
- Include debug logs
- Provide configuration
- Describe steps to reproduce

## License
MIT License - See LICENSE file for details
