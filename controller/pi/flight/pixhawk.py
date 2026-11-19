"""Native MAVSDK transport and telemetry; local-NED flight sequencing is in OffboardControl."""
import logging
import math
import threading
import time
from collections import deque
from flight.deployment import validate_connection


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
        validate_connection(profile, connection)
        from mavsdk import Mavsdk, Configuration, ComponentType, Autopilot, Vehicle
        from mavsdk.plugins.action import Action
        from mavsdk.plugins.telemetry import Telemetry
        from mavsdk.plugins.param import Param
        self.enabled, self.profile = enabled, profile
        self.lock = threading.Lock()
        self.cache, self.handles = {}, []
        self.observed_events = deque(maxlen=2048)
        self.observed_events_dropped = 0
        self.battery_failsafe = {}
        self.phase = 'IDLE'
        self.takeoff_complete = False
        self.operation_at = 0.0
        # PC HITL over UDP acts as a GCS; serial Pi control is a companion.
        component = (ComponentType.GROUND_STATION
                     if profile == 'hitl' and connection.startswith('udpin://')
                     else ComponentType.COMPANION_COMPUTER)
        self.sdk = Mavsdk(Configuration.create_with_component_type(component))
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
            # Optional diagnostics must not prevent connection if unavailable.
            try:
                def battery(value, user_data=None):
                    remaining = getattr(value, 'remaining_percent', None)
                    remaining = (remaining * 100 if isinstance(remaining, (int, float))
                                 and math.isfinite(remaining) and 0 <= remaining <= 1 else None)
                    data = {'id': value.id, 'remaining_percent': remaining,
                            'voltage_v': value.voltage_v, 'current_a': value.current_battery_a,
                            'temperature_c': value.temperature_degc}
                    with self.lock:
                        self.cache['battery'] = (json_safe(data), time.monotonic())
                self.handles.append(self.telemetry.subscribe_battery(battery))
                self.telemetry.set_rate_battery(1.0)
            except Exception as error:
                self.observe('BATTERY_MONITOR_UNAVAILABLE', str(error), severity='WARNING')
            for name in ('BAT_LOW_THR', 'BAT_CRIT_THR', 'BAT_EMERGEN_THR',
                         'COM_LOW_BAT_ACT', 'COM_ARM_BAT_MIN'):
                try:
                    getter = self.param.get_param_int if name == 'COM_LOW_BAT_ACT' else self.param.get_param_float
                    value = getter(name)
                    self.battery_failsafe[name] = (value if isinstance(value, (int, float))
                                                   and math.isfinite(value) else None)
                except Exception:
                    self.battery_failsafe[name] = None
            try:
                def status_text(value, user_data=None):
                    severity = getattr(getattr(value, 'type', None), 'name', 'INFO')
                    severity = {'WARNING': 'WARNING', 'ERROR': 'ERROR', 'CRITICAL': 'CRITICAL',
                                'ALERT': 'CRITICAL', 'EMERGENCY': 'CRITICAL', 'DEBUG': 'DEBUG'}.get(severity, 'INFO')
                    self.observe('PX4_MESSAGE', value.text, severity=severity)
                self.handles.append(self.telemetry.subscribe_status_text(status_text))
            except Exception as error:
                self.observe('PX4_TEXT_UNAVAILABLE', str(error), severity='WARNING')
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
        item = values.get('battery') or {}
        battery = item.get('value')
        if isinstance(battery, dict):
            battery = dict(battery)
            values['battery']['value'] = battery
            battery['warning'] = 'UNKNOWN'
            percent = battery.get('remaining_percent')
            limits = getattr(self, 'battery_failsafe', {})
            known = all(isinstance(limits.get(key), (int, float)) for key in
                        ('BAT_LOW_THR', 'BAT_CRIT_THR', 'BAT_EMERGEN_THR'))
            if known and isinstance(percent, (int, float)) and 0 <= percent <= 100 and 0 <= item['age_s'] <= 3:
                battery['warning'] = 'NORMAL'
                for key, label in (('BAT_EMERGEN_THR', 'EMERGENCY'),
                                   ('BAT_CRIT_THR', 'CRITICAL'), ('BAT_LOW_THR', 'LOW')):
                    threshold = getattr(self, 'battery_failsafe', {}).get(key)
                    if isinstance(threshold, (int, float)) and percent <= 100 * threshold:
                        battery['warning'] = label
                        break
                if (battery['warning'] == 'LOW' and percent <= 15
                        and limits['BAT_CRIT_THR'] * 100 < 15):
                    battery['warning'] = 'RESERVE_LOW'
            battery['pi_reserve_warning_percent'] = 15.0
        return json_safe({'connected': self.drone.is_connected(), 'SYS_HITL': self.hitl,
                          'profile': self.profile, 'actuation_enabled': self.enabled,
                          'phase': self.phase, 'takeoff_complete': self.takeoff_complete,
                          'battery_failsafe': getattr(self, 'battery_failsafe', {}),
                          'invalid_telemetry_fields': invalid, 'telemetry': values})

    def observe(self, event, message='', severity='INFO', **fields):
        """Queue diagnostics only; callbacks never issue flight commands or write files."""
        with self.lock:
            events = getattr(self, 'observed_events', None)
            if events is None:
                return
            if len(events) == events.maxlen:
                self.observed_events_dropped += 1
            events.append(dict(event=event, message=message, severity=severity,
                               observed_monotonic_s=time.monotonic(), **fields))

    def drain_observed_events(self):
        with self.lock:
            events = list(self.observed_events)
            self.observed_events.clear()
            dropped = self.observed_events_dropped
            self.observed_events_dropped = 0
        if dropped:
            events.append(dict(event='DIAGNOSTIC_EVENTS_DROPPED', message=f'{dropped} events dropped',
                               severity='WARNING'))
        return events

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
