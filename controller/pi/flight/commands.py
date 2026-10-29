"""Web flight command routing for the sole MAVSDK owner."""

WEB_FLIGHT_COMMANDS = {
    'gps_start', 'pause', 'resume', 'cancel', 'return_home',
    'return_height', 'land', 'disarm',
}


class FlightCommandRouter:
    """Maps web-level commands to the existing flight controller API.

    Local-NED ``fly x y`` is intentionally absent: it remains a console-only
    engineering command and is not part of the web contract.
    """

    def __init__(self, controller, event_log):
        self.controller = controller
        self.log = event_log
        self.last_state = None

    def status(self):
        self.controller.refresh()
        return self.controller.status()

    @staticmethod
    def _mission_values(params):
        try:
            a, b = params['a'], params['b']
            return (a['lat_deg'], a['lon_deg'], b['lat_deg'], b['lon_deg'],
                    params['height_above_launch_m'], params['speed_m_s'])
        except (KeyError, TypeError):
            raise ValueError('gps_start requires a/b lat_deg/lon_deg, height and speed') from None

    def handle(self, request):
        if not isinstance(request, dict):
            raise ValueError('IPC request must be an object')
        if request.get('op') == 'status':
            return {'ok': True, 'status': self.status()}
        if request.get('op') == 'debug_set':
            params = request.get('params', {})
            if not isinstance(params, dict) or params.get('module') not in {'flight', 'pixhawk'}:
                raise ValueError('Flight debug module must be flight or pixhawk')
            if params.get('level') not in {'DEBUG', 'INFO'}:
                raise ValueError('Flight debug level must be DEBUG or INFO')
            self.log.set_debug(params['module'], params.get('level') == 'DEBUG',
                               params.get('duration_s', 600))
            return {'ok': True, 'debug': {'module': params['module'],
                                          'level': params['level'],
                                          'duration_s': params.get('duration_s', 600)}}
        if request.get('op') != 'command':
            raise ValueError('Unsupported IPC operation')
        command = request.get('command')
        if not isinstance(command, dict):
            raise ValueError('Missing command object')
        kind = command.get('type')
        command_id = command.get('command_id')
        mission_id = command.get('mission_id')
        if kind not in WEB_FLIGHT_COMMANDS:
            raise ValueError(f'Unsupported web flight command: {kind}')
        self.log.write('COMMAND_REQUESTED', f'{kind} requested', command_id=command_id,
                       mission_id=mission_id, command_type=kind)
        try:
            if kind == 'gps_start':
                plan = self.controller.gps_plan(*self._mission_values(command.get('params', {})))
                self.controller.gps_start()
                result = {'plan': plan}
            elif kind == 'disarm':
                if command.get('params', {}).get('confirm_force') is not True:
                    raise ValueError('disarm requires params.confirm_force=true; it may stop motors in flight')
                self.controller.disarm()
                result = {}
            else:
                getattr(self.controller, kind)()
                result = {}
            try:
                status = self.controller.status()
            except Exception as status_error:
                status = None
                self.log.write('STATUS_AFTER_COMMAND_FAILED', str(status_error),
                               severity='WARNING', command_id=command_id,
                               command_type=kind)
            self.log.write('COMMAND_ACCEPTED', f'{kind} accepted by controller',
                           command_id=command_id, mission_id=mission_id,
                           command_type=kind,
                           phase_after=status.get('phase') if status else None)
            return {'ok': True, 'result': result, 'status': status}
        except Exception as error:
            self.log.write('COMMAND_REJECTED', str(error), severity='WARNING',
                           command_id=command_id, mission_id=mission_id,
                           command_type=kind, error_type=type(error).__name__)
            raise

    def poll_state(self):
        try:
            status = self.status()
        except Exception as error:
            self.log.write('FLIGHT_POLL_FAILED', str(error), severity='ERROR')
            return
        current = {key: status.get(key) for key in ('phase', 'connected')}
        telemetry = status.get('telemetry', {})
        for key in ('armed', 'flight_mode', 'landed_state'):
            item = telemetry.get(key, {})
            current[key] = item.get('value') if isinstance(item, dict) else None
        if self.last_state is not None and current != self.last_state:
            self.log.write('FLIGHT_STATE_CHANGED', 'Observed flight state changed',
                           phase_before=self.last_state.get('phase'),
                           phase_after=current.get('phase'), details=current)
        self.last_state = current
        self.log.debug('flight', 'FLIGHT_STATUS_DEBUG', 'Current flight status',
                       status=status)
        self.log.debug('pixhawk', 'PIXHAWK_TELEMETRY_DEBUG',
                       'Current PX4 telemetry snapshot', telemetry=telemetry)
