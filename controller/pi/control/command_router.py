"""Route validated control commands; only Flight Service may own MAVSDK."""

from control import camera_manager, ota_manager


class ControlRouter:
    """Route local management commands or forward flight commands over IPC."""

    def __init__(self, flight_client, config, metrics, event_log):
        self.flight = flight_client
        self.config = config
        self.metrics = metrics
        self.log = event_log

    def dispatch(self, command):
        kind = command['type']
        if kind == 'health_get':
            return {'ok': True, 'health': self.metrics.snapshot()}
        if kind == 'config_set':
            values = self.config.update(command.get('params', {}))
            self.log.write('CONFIG_UPDATED', 'Runtime config updated',
                           command_id=command['command_id'], details=values)
            return {'ok': True, 'config': values}
        if kind == 'debug_set':
            params = command.get('params', {})
            module = params.get('module')
            level = params.get('level')
            if level not in {'DEBUG', 'INFO'}:
                raise ValueError('debug_set level must be DEBUG or INFO')
            enabled = level == 'DEBUG'
            if module in {'flight', 'pixhawk'}:
                return self.flight.request({'op': 'debug_set', 'params': params})
            if module not in {'mqtt', 'control', 'camera', 'ota', 'health'}:
                raise ValueError('Unsupported debug module')
            self.log.set_debug(module, enabled,
                               params.get('duration_s', 600))
            return {'ok': True, 'debug': {'module': module, 'level': level,
                                          'duration_s': params.get('duration_s', 600)}}
        if kind == 'camera_status':
            return {'ok': True, 'camera': camera_manager.status()}
        if kind == 'ota_status':
            return {'ok': True, 'ota': ota_manager.status()}
        return self.flight.request({'op': 'command', 'command': command})
