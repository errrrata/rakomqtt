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

    @post_load
    def post_load(self, item: Dict[str, Any], many: bool, **kwargs) -> Dict[str, Any]:
        """Convert between different unit systems based on available fields."""
        if 'command' in item:
            return item

        if 'percentage' in item and 'brightness' not in item:
            item['brightness'] = int(item['percentage'] * 2.55)
        elif 'position' in item and 'brightness' not in item:
            item['brightness'] = int(item['position'] * 2.55)
        elif 'brightness' not in item:
            item['brightness'] = 255 if item['state'] == 'ON' else 0

        return item

mqtt_payload_schema = MqttPayloadSchema()
