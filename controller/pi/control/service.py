#!/usr/bin/env python3
"""Always-on MQTT control service routing validated web commands to flight."""
import argparse
from collections import deque
import getpass
import json
import queue
import signal
import sys
import threading
import time
from pathlib import Path

PI_DIR = Path(__file__).resolve().parents[1]
if str(PI_DIR) not in sys.path:
    sys.path.insert(0, str(PI_DIR))

from control.config_manager import RuntimeConfig
from control.command_router import ControlRouter
from control.mqtt_client import create_client
from control.protocol import parse_incoming
from ipc.client import RpcClient
from control.monitor import DEVICE_ID
from observability.event_log import EventLog, utc_now
from observability.metrics import HostMetrics


class RecentCommandIds:
    """Bound duplicate tracking so an always-on service cannot grow forever."""

    def __init__(self, capacity=4096):
        self.capacity = capacity
        self._order = deque()
        self._values = set()

    def add_if_new(self, command_id):
        if command_id in self._values:
            return False
        if len(self._order) >= self.capacity:
            self._values.remove(self._order.popleft())
        self._order.append(command_id)
        self._values.add(command_id)
        return True


def _password(args):
    if args.password_file:
        return Path(args.password_file).read_text().strip()
    return getpass.getpass('MQTT password: ')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--device-id', required=True)
    parser.add_argument('--username', required=True)
    parser.add_argument('--password-file', help='Read MQTT password from a protected local file')
    parser.add_argument('--host', default='mqtt.lacais.com')
    parser.add_argument('--port', type=int, default=8883)
    parser.add_argument('--ca-file')
    parser.add_argument('--flight-socket', default='/tmp/uav-flight.sock')
    parser.add_argument('--config-file', default='runtime/uav-control.json')
    parser.add_argument('--log-dir', default='session-logs/services')
    parser.add_argument('--allow-legacy-start', action='store_true',
                        help='Enable the six-field web start payload for controlled HITL testing')
    args = parser.parse_args(argv)
    if not DEVICE_ID.fullmatch(args.device_id):
        parser.error('Invalid device ID')
    if not 1 <= args.port <= 65535:
        parser.error('port must be 1..65535')
    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        parser.error('Install controller/pi/control/requirements.txt first')

    running = True
    inbox = queue.Queue(maxsize=64)
    seen = RecentCommandIds()
    config = RuntimeConfig(args.config_file)
    metrics = HostMetrics()
    events = EventLog(args.log_dir, 'control')
    router = ControlRouter(RpcClient(args.flight_socket), config, metrics, events)
    base = f'lac/{args.device_id}'
    legacy_topic, command_topic = f'{base}/control', f'{base}/v2/command'
    topics = {legacy_topic: 'legacy', command_topic: 'v2'}
    mqtt_lock = threading.Lock()
    mqtt_state = {'connected': False, 'last_rx_utc': None, 'last_tx_utc': None,
                  'reconnect_count': 0, 'connect_count': 0}

    offline = json.dumps({'online': False, 'observed_at_utc': utc_now()})
    client = create_client(mqtt, args.device_id, args.username, _password(args),
                           args.ca_file, offline)

    def publish(suffix, value, qos=0, retain=False):
        result = client.publish(f'{base}/v2/{suffix}', json.dumps(value, allow_nan=False),
                                qos=qos, retain=retain)
        with mqtt_lock:
            mqtt_state['last_tx_utc'] = utc_now()
        return result

    def on_connect(connection, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            print(f'MQTT connection rejected: {reason_code}', flush=True)
            events.write('MQTT_CONNECT_REJECTED', str(reason_code), severity='ERROR')
            return
        with mqtt_lock:
            mqtt_state['connected'] = True
            mqtt_state['connect_count'] += 1
            mqtt_state['reconnect_count'] = max(0, mqtt_state['connect_count'] - 1)
        for topic in topics:
            connection.subscribe(topic, qos=1 if topic == command_topic else 0)
        print(f'MQTT connected successfully: {args.host}:{args.port}', flush=True)
        print(f'Subscribed: {legacy_topic}', flush=True)
        print(f'Subscribed: {command_topic}', flush=True)
        if args.allow_legacy_start:
            print('Legacy six-field GPS auto-start: ENABLED', flush=True)
        else:
            print('Legacy six-field GPS auto-start: DISABLED; use v2 commands', flush=True)
        publish('availability', {'online': True, 'observed_at_utc': utc_now(),
                                 'boot_id': events.boot_id}, qos=1, retain=True)
        events.write('MQTT_CONNECTED', 'Connected and subscribed')

    def on_disconnect(connection, userdata, disconnect_flags, reason_code, properties):
        with mqtt_lock:
            mqtt_state['connected'] = False
        print(f'MQTT disconnected: {reason_code}; client will retry automatically', flush=True)
        events.write('MQTT_DISCONNECTED', str(reason_code), severity='WARNING')

    def on_message(connection, userdata, message):
        with mqtt_lock:
            mqtt_state['last_rx_utc'] = utc_now()
        if message.retain:
            events.write('COMMAND_REJECTED', 'Retained MQTT command ignored',
                         severity='WARNING', topic=message.topic)
            return
        if len(message.payload) > 64 * 1024:
            events.write('COMMAND_REJECTED', 'MQTT payload exceeds 64 KiB',
                         severity='WARNING', topic=message.topic)
            return
        try:
            inbox.put_nowait((message.topic, bytes(message.payload)))
            events.debug('mqtt', 'MQTT_RECEIVED_DEBUG', 'MQTT command queued',
                         topic=message.topic, payload_bytes=len(message.payload),
                         queue_size=inbox.qsize())
        except queue.Full:
            events.write('COMMAND_QUEUE_FULL', 'MQTT command queue full', severity='ERROR')

    client.on_connect, client.on_disconnect, client.on_message = on_connect, on_disconnect, on_message

    def stop(*_):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    events.write('SERVICE_STARTED', 'Control service started', device_id=args.device_id)
    print(f'Connecting to MQTT broker {args.host}:{args.port} as {args.username} ...',
          flush=True)
    client.connect(args.host, args.port, keepalive=30)
    client.loop_start()
    last_state = last_health = 0.0
    last_flight_signature = None
    try:
        while running:
            try:
                topic, payload = inbox.get(timeout=0.2)
            except queue.Empty:
                topic = None
            if topic is not None:
                command = None
                try:
                    command = parse_incoming(topics[topic], payload, args.allow_legacy_start)
                    command_id = command['command_id']
                    if not seen.add_if_new(command_id):
                        raise ValueError('Duplicate command_id in this service session')
                    # Never auto-retry after partial execution.
                    record = events.write('COMMAND_RECEIVED', command['type'],
                                          command_id=command_id,
                                          mission_id=command.get('mission_id'), topic=topic)
                    publish('event', record, qos=1)
                    publish('ack', {'command_id': command_id, 'status': 'received',
                                    'observed_at_utc': utc_now()}, qos=1)
                    response = router.dispatch(command)
                    events.debug('control', 'CONTROL_DISPATCH_DEBUG',
                                 'Command dispatch finished', command_id=command_id,
                                 command_type=command['type'], response_ok=response.get('ok'))
                    if not response.get('ok'):
                        raise RuntimeError(response.get('error', 'Flight service rejected command'))
                    publish('ack', {'command_id': command_id, 'status': 'accepted',
                                    'observed_at_utc': utc_now(), 'result': response}, qos=1)
                    record = events.write('COMMAND_ACCEPTED', command['type'],
                                          command_id=command_id,
                                          mission_id=command.get('mission_id'),
                                          command_type=command['type'])
                    publish('event', record, qos=1)
                except Exception as error:
                    command_id = command.get('command_id') if command else None
                    record = events.write('COMMAND_REJECTED', str(error),
                                          severity='WARNING', command_id=command_id,
                                          error_type=type(error).__name__)
                    publish('event', record, qos=1)
                    publish('ack', {'command_id': command_id, 'status': 'rejected',
                                    'reason': str(error), 'observed_at_utc': utc_now()}, qos=1)
            now = time.monotonic()
            if now - last_state >= config.values['state_interval_s']:
                try:
                    response = router.flight.request({'op': 'status'})
                    flight_status = response.get('status') if response.get('ok') else None
                    publish('state', {'online': response.get('ok', False),
                                      'observed_at_utc': utc_now(),
                                      'flight': flight_status,
                                      'error': response.get('error')}, retain=True)
                    telemetry = (flight_status or {}).get('telemetry', {})
                    signature = (flight_status.get('phase') if flight_status else None,
                                 tuple((telemetry.get(key) or {}).get('value')
                                       for key in ('flight_mode', 'armed', 'landed_state')))
                    if signature != last_flight_signature:
                        record = events.write('FLIGHT_STATE_CHANGED', 'Flight state observed',
                                              details={'phase': signature[0],
                                                       'flight_mode': signature[1][0],
                                                       'armed': signature[1][1],
                                                       'landed_state': signature[1][2]})
                        publish('event', record, qos=1)
                        last_flight_signature = signature
                except Exception as error:
                    publish('state', {'online': False, 'observed_at_utc': utc_now(),
                                      'error': str(error)}, retain=True)
                    if last_flight_signature != ('unavailable',):
                        record = events.write('FLIGHT_UNAVAILABLE', str(error),
                                              severity='WARNING')
                        publish('event', record, qos=1)
                        last_flight_signature = ('unavailable',)
                last_state = now
            if now - last_health >= config.values['health_interval_s']:
                health = metrics.snapshot(args.log_dir)
                with mqtt_lock:
                    health['mqtt'] = dict(mqtt_state)
                health['command_queue_size'] = inbox.qsize()
                publish('health', health, retain=True)
                events.write('HOST_HEALTH', 'Periodic host health', record_type='metric',
                             metrics=health)
                last_health = now
    finally:
        publish('availability', {'online': False, 'observed_at_utc': utc_now()}, qos=1, retain=True)
        client.disconnect()
        client.loop_stop()
        events.write('SERVICE_STOPPED', 'Control service stopped')
        events.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
