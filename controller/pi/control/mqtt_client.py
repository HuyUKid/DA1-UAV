"""Create the authenticated TLS broker connection for Control Service."""

import ssl
import uuid


def create_client(mqtt, device_id, username, password, ca_file):
    client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                         client_id=f'uav-control-{device_id}-{uuid.uuid4().hex[:8]}',
                         protocol=mqtt.MQTTv311, clean_session=True)
    client.username_pw_set(username, password)
    client.tls_set_context(ssl.create_default_context(cafile=ca_file))
    return client
