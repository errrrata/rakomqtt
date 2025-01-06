"""Data models for MQTT payloads."""
from typing import Any, Dict, Literal, Optional
from dataclasses import dataclass
from marshmallow import Schema, fields, post_load, validate

class MqttPayloadSchema(Schema):
    """Schema for MQTT payloads with support for different device types."""
    state = fields.Str(validate=validate.OneOf(choices=('ON', 'OFF')))
    brightness = fields.Int(validate=validate.Range(min=0, max=255))
    percentage = fields.Int(validate=validate.Range(min=0, max=100))
    position = fields.Int(validate=validate.Range(min=0, max=100))
    command = fields.Str(validate=validate.OneOf(choices=('OPEN', 'CLOSE', 'STOP')))
    transition = fields.Int(validate=validate.Range(min=0))

    @post_load
    def post_load(self, item: Dict[str, Any], many: bool, **kwargs) -> Dict[str, Any]:
        """Convert between different unit systems based on available fields."""
        if isinstance(item, str) and item in ('OPEN', 'CLOSE', 'STOP'):
            return {'command': item}

        if 'command' in item:
            return item

        # Ensure state and brightness are always consistent
        if 'state' in item:
            if 'brightness' not in item:  # Only set brightness if not explicitly provided
                item['brightness'] = 255 if item['state'] == 'ON' else 0
        elif 'brightness' in item:
            item['state'] = 'ON' if item['brightness'] > 0 else 'OFF'
        else:
            item['state'] = 'OFF'
            item['brightness'] = 0

        return item

mqtt_payload_schema = MqttPayloadSchema()
