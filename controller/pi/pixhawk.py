"""Native MAVSDK transport and telemetry; local-NED flight sequencing is in OffboardControl."""
import logging
import math
import threading
import time


def json_safe(value):
    """Keep diagnostics JSON readable without altering raw control telemetry."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    return value


def has_nonfinite(value):
    if isinstance(value, float):
        return not math.isfinite(value)
    if isinstance(value, dict):
        return any(has_nonfinite(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(has_nonfinite(v) for v in value)
    return False


class Pixhawk:
    def __init__(self, connection, profile, enabled=False, system_id=1):
        if profile not in {'hardware', 'hitl'}:
            raise ValueError('Expected hardware or hitl profile')
        from mavsdk import Mavsdk, Configuration, ComponentType, Autopilot, Vehicle
        from mavsdk.plugins.action import Action
        from mavsdk.plugins.telemetry import Telemetry
        from mavsdk.plugins.param import Param
        self.enabled, self.profile = enabled, profile
        self.lock = threading.Lock()
        self.cache, self.handles = {}, []
        self.phase = 'IDLE'
        self.takeoff_complete = False
        self.operation_at = 0.0
        self.sdk = Mavsdk(Configuration.create_with_component_type(ComponentType.COMPANION_COMPUTER))
        try:
            self.sdk.add_any_connection(connection)
            self.drone = self.sdk.first_autopilot(10.0)
            if self.drone is None:
                raise RuntimeError('No autopilot heartbeat')
            if (self.drone.get_system_id() != system_id or
                    self.drone.autopilot_type() != Autopilot.PX4 or
                    self.drone.vehicle_type() != Vehicle.MULTICOPTER):
                raise RuntimeError('Expected configured PX4 multicopter')
            self.action, self.telemetry = Action(self.drone), Telemetry(self.drone)
            self.param = Param(self.drone)
            self.hitl = self.param.get_param_int('SYS_HITL')
            if self.hitl != (1 if profile == 'hitl' else 0):
                raise RuntimeError(f'SYS_HITL={self.hitl} does not match {profile}')
            for name in ('armed', 'landed_state', 'flight_mode', 'health_all_ok', 'position'):
                def callback(value, user_data=None, name=name):
                    if name == 'position':
                        value = {key: getattr(value, key) for key in
                                 ('latitude_deg', 'longitude_deg', 'absolute_altitude_m', 'relative_altitude_m')}
                    value = getattr(value, 'name', value)
                    with self.lock:
                        self.cache[name] = (value, time.monotonic())
                self.handles.append(getattr(self.telemetry, 'subscribe_' + name)(callback))
            self.telemetry.set_rate_health(2.0)
            self.telemetry.set_rate_landed_state(2.0)
        except BaseException:
            try:
                self.sdk.destroy()
            except Exception:
                logging.getLogger(__name__).exception('SDK cleanup after connection failure failed')
            raise

    def status(self):
        self.refresh()
        now = time.monotonic()
        with self.lock:
            values = {k: {'value': v, 'age_s': now-t} for k, (v, t) in self.cache.items()}
            invalid = [k for k, (v, _) in self.cache.items() if has_nonfinite(v)]
        return json_safe({'connected': self.drone.is_connected(), 'SYS_HITL': self.hitl,
                          'profile': self.profile, 'actuation_enabled': self.enabled,
                          'phase': self.phase, 'takeoff_complete': self.takeoff_complete,
                          'invalid_telemetry_fields': invalid, 'telemetry': values})

    def require(self):
        if not self.enabled:
            raise ValueError('Inspection only: use --enable-actuation to send commands')
        if not self.drone.is_connected():
            raise ValueError('PX4 disconnected')

    def state(self, key, max_age=3.0):
        with self.lock:
            value, at = self.cache.get(key, (None, 0))
        if not 0 <= time.monotonic()-at <= max_age:
            raise ValueError(f'Missing/stale {key} telemetry')
        return value

    def refresh(self):
        """Flight-state transitions are implemented by OffboardControl."""
