#!/usr/bin/env python3
"""Read-only monitor for legacy MQTT control fields, separate or bundled.

This process never opens MAVLink or sends a flight command. Receiving a
six-field bundle here is not a flight ACK; the control service is the
web-command entry point.
"""

import argparse
import getpass
import math
import re
import ssl
import uuid


FIELD_BOUNDS = {
    'startlat': (-90.0, 90.0),
    'startlong': (-180.0, 180.0),
    'endlat': (-90.0, 90.0),
    'endlong': (-180.0, 180.0),
    'height': (0.0, 100.0),
    'spd': (0.0, 10.0),
}
MESSAGE = re.compile(r'c:([a-z]+):([^;\s]+);\Z')
DEVICE_ID = re.compile(r'[A-Za-z0-9_-]{1,64}\Z')


def parse_control(payload):
    """Return (field, value) for one supported legacy command, or raise."""
    if isinstance(payload, bytes):
        payload = payload.decode('utf-8', errors='strict')
    if not isinstance(payload, str):
        raise ValueError('Payload must be UTF-8 text')
    match = MESSAGE.fullmatch(payload)
    if not match or match[1] not in FIELD_BOUNDS:
        raise ValueError('Expected one legacy c:field:value; command')
    field = match[1]
    try:
        value = float(match[2])
    except ValueError:
        raise ValueError('Value must be numeric') from None
    low, high = FIELD_BOUNDS[field]
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'{field} must be finite and within {low}..{high}')
    return field, value


def parse_controls(payload):
    """Parse one or more concatenated c:field:value; commands atomically."""
    if isinstance(payload, bytes):
        payload = payload.decode('utf-8', errors='strict')
    if not isinstance(payload, str) or len(payload) > 2048 or not payload.endswith(';'):
        raise ValueError('Expected one or more c:field:value; commands')
    parts = payload[:-1].split(';')
    if not 1 <= len(parts) <= len(FIELD_BOUNDS):
        raise ValueError('Expected 1..6 control fields')
    fields = tuple(parse_control(part + ';') for part in parts)
    if len({field for field, _ in fields}) != len(fields):
        raise ValueError('Duplicate control field in one message')
    return fields


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--device-id', required=True, help='Exact deviceID used by the backend')
    parser.add_argument('--host', default='mqtt.lacais.com')
    parser.add_argument('--port', type=int, default=8883)
    parser.add_argument('--username', required=True)
    parser.add_argument('--ca-file', help='Optional CA PEM file; system trust is used by default')
    args = parser.parse_args(argv)
    if not DEVICE_ID.fullmatch(args.device_id):
        parser.error('device-id must contain 1..64 letters, digits, underscore or hyphen')
    if not 1 <= args.port <= 65535:
        parser.error('port must be 1..65535')

    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        parser.error('Install controller/pi/control/requirements.txt first')

    topic = f'lac/{args.device_id}/control'
    client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                         client_id=f'uav-monitor-{uuid.uuid4().hex[:12]}',
                         protocol=mqtt.MQTTv311, clean_session=True)
    client.username_pw_set(args.username, getpass.getpass('MQTT password: '))
    client.tls_set_context(ssl.create_default_context(cafile=args.ca_file))

    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            print(f'MQTT connection rejected: {reason_code}', flush=True)
            return
        client.subscribe(topic, qos=0)
        print(f'Listening on {topic} (read-only; no flight commands)', flush=True)

    def on_message(client, userdata, message):
        if message.retain:
            print('Ignored retained control message', flush=True)
            return
        try:
            fields = parse_controls(message.payload)
        except (UnicodeError, ValueError) as error:
            print(f'Ignored unsupported control message: {error}', flush=True)
            return
        for field, value in fields:
            print(f'Received {field}={value:.9g}', flush=True)

    client.on_connect = on_connect
    client.on_message = on_message
    try:
        client.connect(args.host, args.port, keepalive=30)
        client.loop_forever()
    except KeyboardInterrupt:
        print('\nStopped MQTT monitor', flush=True)
    finally:
        client.disconnect()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
