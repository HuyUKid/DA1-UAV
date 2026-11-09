"""Validation for the single web MQTT control payload."""
import hashlib

from control.monitor import parse_controls


CONTROL_FIELDS = {'spd', 'height', 'startlat', 'startlong', 'endlat', 'endlong'}


def parse_control(payload):
    """Convert one atomic six-field control payload into a GPS start command."""
    fields = dict(parse_controls(payload))
    if set(fields) != CONTROL_FIELDS:
        raise ValueError('Web mission requires exactly six fields in one message')
    raw = payload if isinstance(payload, bytes) else payload.encode('utf-8')
    digest = hashlib.sha256(raw).hexdigest()
    return {
        'command_id': f'control-{digest[:24]}',
        'mission_id': f'control-{digest[24:48]}',
        'type': 'gps_start',
        'params': {
            'a': {'lat_deg': fields['startlat'], 'lon_deg': fields['startlong']},
            'b': {'lat_deg': fields['endlat'], 'lon_deg': fields['endlong']},
            'height_above_launch_m': fields['height'],
            'speed_m_s': fields['spd'],
        },
    }
