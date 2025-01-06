# Home Assistant Add-on: Rako MQTT Bridge

Control your Rako lighting system through Home Assistant with MQTT integration.

## About

This add-on creates a bridge between your Rako lighting system and Home Assistant via MQTT. It provides:

- Auto-discovery of Rako devices
- Real-time status updates
- Support for lights, scenes, and blinds
- Compatible with all Rako bridge models
- Automatic MQTT device configuration

## Installation

Follow these steps to install the add-on:

1. Click the Home Assistant My button below to add this repository:

   [![Open your Home Assistant instance and show the dashboard of a Supervisor add-on.](https://my.home-assistant.io/badges/supervisor_addon.svg)](https://my.home-assistant.io/redirect/supervisor_addon/?repository_url=https%3A%2F%2Fgithub.com%2Fyourusername%2Frakomqtt)

2. Install the "Rako MQTT Bridge" add-on
3. Configure the add-on (see configuration section below)
4. Start the add-on
5. Check the add-on log to ensure it's running correctly

## Configuration

Example configuration:

```yaml
rako_bridge_host: "192.168.1.100"  # Optional, will auto-discover if empty
mqtt_host: "core-mosquitto"
mqtt_user: "homeassistant"
mqtt_password: "your_password"
debug: false
default_fade_rate: "medium"
```

### Option: `rako_bridge_host`

The IP address or hostname of your Rako bridge. If left empty, the add-on will attempt to auto-discover the bridge on your network.

### Option: `mqtt_host`

The MQTT broker host. The default value "core-mosquitto" works with the Home Assistant Mosquitto broker add-on. Change this only if you're using a different MQTT broker.

### Option: `mqtt_user`

The username for connecting to your MQTT broker. If you're using the Mosquitto add-on, this can be found in the Mosquitto add-on configuration.

### Option: `mqtt_password`

The password for connecting to your MQTT broker. If you're using the Mosquitto add-on, this can be found in the Mosquitto add-on configuration.

### Option: `debug`

Enable or disable debug logging. Set to `true` to help troubleshoot issues. Default is `false`.

### Option: `default_fade_rate`

Default fade rate for light transitions. Available options:
- `instant`: No fade
- `fast`: ~2 seconds
- `medium`: ~4 seconds (default)
- `slow`: ~8 seconds
- `very_slow`: ~16 seconds
- `extra_slow`: ~32 seconds

## Network

The add-on requires network access to:
- Your Rako bridge (typically port 9761)
- MQTT broker (typically port 1883)

## Home Assistant MQTT Discovery

The add-on automatically configures devices in Home Assistant using MQTT discovery. After starting the add-on, your Rako devices should appear automatically in Home Assistant.

Supported device types:
- Lights (with brightness control)
- Covers (blinds and curtains)
- Switches
- Scenes

## Troubleshooting

### Bridge Not Found

If the add-on cannot find your Rako bridge:
1. Check that your bridge is powered and connected to your network
2. Try specifying the bridge IP address manually in the configuration
3. Check your network allows UDP broadcast (required for auto-discovery)
4. Ensure ports 9761 is accessible

### MQTT Connection Issues

If the add-on cannot connect to MQTT:
1. Verify your MQTT credentials
2. Check if the Mosquitto add-on is running
3. Ensure the MQTT broker is accessible

### Debug Logs

To get more detailed logging:
1. Set `debug: true` in the configuration
2. Restart the add-on
3. Check the add-on logs for more information

## Support

- For bugs and feature requests, open an issue on [GitHub](https://github.com/yourusername/rakomqtt/issues)
- For general questions, use the Home Assistant community forums

## License

This add-on and its source code are released under the MIT license.

## Credits

This add-on is based on the official Rako bridge protocol documentation and the work of the Home Assistant community.
