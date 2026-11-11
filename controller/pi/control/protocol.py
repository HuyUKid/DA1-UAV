"""Validation for the single web MQTT control payload."""
import uuid

from control.monitor import parse_controls


CONTROL_FIELDS = {'spd', 'height', 'startlat', 'startlong', 'endlat', 'endlong'}
WEB_ACTIONS = {
    'd:pause': 'pause',
    'd:resume': 'resume',
    'd:rtl': 'return_home',
    'd:land': 'land',
    'd:abort': 'cancel',
}


def parse_control(payload):
    """Convert one web GPS plan or button press into a flight command."""
    if isinstance(payload, bytes):
        payload = payload.decode('utf-8', errors='strict')
    if not isinstance(payload, str):
        raise ValueError('Web payload must be UTF-8 text')
    action = WEB_ACTIONS.get(payload.removesuffix(';'))
    if action is not None:
        # The same button must remain usable later in this service session.
        return {'command_id': f'action-{uuid.uuid4().hex}',
                'type': action, 'params': {}}
    fields = dict(parse_controls(payload))
    if set(fields) != CONTROL_FIELDS:
        raise ValueError('Web mission requires exactly six fields in one message')
    request_id = uuid.uuid4().hex
    return {
        'command_id': f'control-{request_id}',
        'mission_id': f'mission-{request_id}',
        'type': 'gps_start',
        'params': {
            'a': {'lat_deg': fields['startlat'], 'lon_deg': fields['startlong']},
            'b': {'lat_deg': fields['endlat'], 'lon_deg': fields['endlong']},
            'height_above_launch_m': fields['height'],
            'speed_m_s': fields['spd'],
        },
    }
