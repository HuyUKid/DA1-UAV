"""Web and local flight command routing for the sole MAVSDK owner."""
from observability.flight_log import FlightTimeline
import time
import traceback

WEB_FLIGHT_COMMANDS = {
    'arm', 'takeoff', 'gps_start', 'pause', 'resume', 'cancel', 'return_home', 'land',
}
LOCAL_FLIGHT_COMMANDS = WEB_FLIGHT_COMMANDS | {
    'fly', 'gps_plan', 'return_height', 'disarm',
}


class FlightCommandRouter:
    """Dispatches serialized flight requests on the sole MAVSDK owner thread."""

    def __init__(self, controller, event_log):
        self.controller = controller
        self.log = event_log
        self.last_state = None
        self.timeline = FlightTimeline(event_log)
        self.host_health = None
        self.host_health_at = -float('inf')

    def status(self):
        self.controller.refresh()
        status = self.controller.status()
        if time.monotonic() - self.host_health_at >= 5:
            self.host_health = self.timeline.metrics.snapshot(self.log.directory)
            self.host_health_at = time.monotonic()
        status['host_health'] = self.host_health
        return status

    @staticmethod
    def _mission_values(params):
        try:
            a, b = params['a'], params['b']
            values = (a['lat_deg'], a['lon_deg'], b['lat_deg'], b['lon_deg'],
                      params['height_above_launch_m'], params['speed_m_s'])
            if 'intermediate_waypoints' in params:
                points = params['intermediate_waypoints']
                if not isinstance(points, list):
                    raise ValueError('intermediate_waypoints must be a list')
                values += (points,)
            return values
        except (KeyError, TypeError):
            raise ValueError('GPS plan requires a/b lat_deg/lon_deg, height and speed') from None

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
        operation = request.get('op')
        if operation not in {'command', 'local_command'}:
            raise ValueError('Unsupported IPC operation')
        command = request.get('command')
        if not isinstance(command, dict):
            raise ValueError('Missing command object')
        kind = command.get('type')
        command_id = command.get('command_id')
        mission_id = command.get('mission_id')
        allowed = LOCAL_FLIGHT_COMMANDS if operation == 'local_command' else WEB_FLIGHT_COMMANDS
        if kind not in allowed:
            raise ValueError(f'Unsupported {"local" if operation == "local_command" else "web"} '
                             f'flight command: {kind}')
        self.log.write('COMMAND_REQUESTED', f'{kind} requested', command_id=command_id,
                       mission_id=mission_id, command_type=kind, source=operation,
                       params=command.get('params', {}))
        linked_mission = (self.timeline.context.get('mission_id')
                          if kind in {'pause', 'resume', 'cancel', 'land', 'disarm'}
                          and mission_id == 'local-supervision' else mission_id)
        self.timeline.context = dict(command_id=command_id, mission_id=linked_mission)
        try:
            if kind == 'gps_start':
                if operation != 'command':
                    self.controller.gps_start()
                    result = {}
                else:
                    plan = self.controller.gps_plan(*self._mission_values(command.get('params', {})))
                    self.log.write('MISSION_VALIDATED', 'GPS plan validated', plan=plan,
                                   command_id=command_id, mission_id=mission_id)
                    self.controller.gps_start()
                    result = {'plan': plan}
            elif kind == 'gps_plan':
                plan = self.controller.gps_plan(*self._mission_values(command.get('params', {})))
                result = {'plan': plan}
            elif kind == 'fly':
                params = command.get('params')
                if not isinstance(params, dict) or set(params) != {'north_m', 'east_m'}:
                    raise ValueError('fly requires north_m and east_m')
                self.controller.fly(params['north_m'], params['east_m'])
                result = {}
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
                self.timeline.update(self.controller, status)
            except Exception as status_error:
                status = None
                self.log.write('STATUS_AFTER_COMMAND_FAILED', str(status_error),
                               severity='WARNING', command_id=command_id,
                               command_type=kind)
            self.log.write('COMMAND_ACCEPTED', f'{kind} accepted by controller',
                           command_id=command_id, mission_id=mission_id,
                           command_type=kind, source=operation,
                           phase_after=status.get('phase') if status else None)
            return {'ok': True, 'result': result, 'status': status}
        except Exception as error:
            self.log.write('COMMAND_REJECTED', str(error), severity='WARNING',
                           command_id=command_id, mission_id=mission_id,
                           command_type=kind, source=operation,
                           error_type=type(error).__name__, traceback=traceback.format_exc())
            raise

    def poll_state(self):
        try:
            status = self.status()
        except Exception as error:
            self.log.write('FLIGHT_POLL_FAILED', str(error), severity='ERROR')
            return
        self.timeline.update(self.controller, status)
        telemetry = status.get('telemetry', {})
        self.log.debug('flight', 'FLIGHT_STATUS_DEBUG', 'Current flight status',
                       status=status)
        self.log.debug('pixhawk', 'PIXHAWK_TELEMETRY_DEBUG',
                       'Current PX4 telemetry snapshot', telemetry=telemetry)
