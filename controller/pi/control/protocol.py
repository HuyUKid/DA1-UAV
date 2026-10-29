"""Validation for web MQTT commands and the transitional legacy payload."""
import hashlib
import json
import re
from datetime import datetime, timezone

from control.monitor import parse_controls

ID = re.compile(r'[A-Za-z0-9_.:-]{1,128}\Z')
FLIGHT_TYPES = {'gps_start', 'pause', 'resume', 'cancel', 'return_home',
                'return_height', 'land', 'disarm'}
CONTROL_TYPES = {'health_get', 'config_set', 'debug_set', 'camera_status', 'ota_status'}
LEGACY_FIELDS = {'spd', 'height', 'startlat', 'startlong', 'endlat', 'endlong'}


def _utc(value, field):
    if not isinstance(value, str):
        raise ValueError(f'{field} must be an ISO-8601 UTC string')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise ValueError(f'{field} must be an ISO-8601 UTC string') from None
    if parsed.tzinfo is None:
        raise ValueError(f'{field} must include timezone')
    return parsed.astimezone(timezone.utc)


def parse_v2(payload, now=None):
    if isinstance(payload, bytes):
        payload = payload.decode('utf-8', errors='strict')
    if not isinstance(payload, str) or len(payload) > 64 * 1024:
        raise ValueError('Command must be UTF-8 JSON within 64 KiB')
    try:
        command = json.loads(payload)
    except json.JSONDecodeError:
        raise ValueError('Command must be valid JSON') from None
    if not isinstance(command, dict) or command.get('schema') != 2:
        raise ValueError('Expected MQTT command schema 2')
    if not isinstance(command.get('command_id'), str) or not ID.fullmatch(command['command_id']):
        raise ValueError('Invalid or missing command_id')
    if not isinstance(command.get('mission_id'), str) or not ID.fullmatch(command['mission_id']):
        raise ValueError('Invalid or missing mission_id')
    if command.get('type') not in FLIGHT_TYPES | CONTROL_TYPES:
        raise ValueError('Unsupported command type')
    issued = _utc(command.get('issued_at_utc'), 'issued_at_utc')
    expires = _utc(command.get('expires_at_utc'), 'expires_at_utc')
    current = now or datetime.now(timezone.utc)
    if expires <= issued or expires < current:
        raise ValueError('Command is expired or has an invalid validity window')
    if (issued - current).total_seconds() > 30:
        raise ValueError('Command issued_at is too far in the future')
    if not isinstance(command.get('params', {}), dict):
        raise ValueError('params must be an object')
    return command


def parse_incoming(topic_kind, payload, allow_legacy_start=False):
    if topic_kind == 'v2':
        return parse_v2(payload)
    if topic_kind == 'legacy' and allow_legacy_start:
        return parse_legacy_web(payload)
    if topic_kind == 'legacy':
        raise ValueError('Legacy auto-start is disabled; use v2 command')
    raise ValueError('Unknown MQTT command topic')


def parse_legacy_web(payload):
    fields = dict(parse_controls(payload))
    if set(fields) != LEGACY_FIELDS:
        raise ValueError('Web mission requires exactly six fields in one message')
    raw = payload if isinstance(payload, bytes) else payload.encode('utf-8')
    digest = hashlib.sha256(raw).hexdigest()
    return {
        'schema': 1,
        'command_id': f'legacy-{digest[:24]}',
        'mission_id': f'legacy-{digest[24:48]}',
        'type': 'gps_start',
        'params': {
            'a': {'lat_deg': fields['startlat'], 'lon_deg': fields['startlong']},
            'b': {'lat_deg': fields['endlat'], 'lon_deg': fields['endlong']},
            'height_above_launch_m': fields['height'],
            'speed_m_s': fields['spd'],
        },
        'legacy': True,
    }
