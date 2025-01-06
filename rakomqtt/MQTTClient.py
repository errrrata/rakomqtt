import logging
import paho.mqtt.client as mqtt

_LOGGER = logging.getLogger(__name__)

class MQTTClient:
    def __init__(self, host, user, pwd):
        self.mqttc = mqtt.Client()
        self.mqttc.enable_logger()
        self.host = host
        self.user = user
        self.pwd = pwd
        self.last_will_topic = "rako/bridge/status"

        def on_disconnect(client, userdata, rc):
            if rc != 0:
                _LOGGER.info(f"Unexpected MQTT disconnection. rc = {rc}. Will auto-reconnect")

        def on_connect(client, userdata, flags, rc):
            _LOGGER.info(f"Connected with result code {rc}")
            # Publish online status
            self.publish(self.last_will_topic, "online", retain=True)

        self.mqttc.on_disconnect = on_disconnect
        self.mqttc.on_connect = on_connect
        self.mqttc.username_pw_set(self.user, self.pwd)
        self.mqttc.reconnect_delay_set()
        
        # Set Last Will and Testament (LWT)
        self.mqttc.will_set(self.last_will_topic, "offline", retain=True)

    def publish(self, topic, payload=None, qos=0, retain=False):
        (rc, message_id) = self.mqttc.publish(topic, payload, qos, retain)
        _LOGGER.debug(f"published to {topic}: {payload}. response: {(rc, message_id)}")

    def connect(self):
        self.mqttc.connect(self.host, 1883, 60)
