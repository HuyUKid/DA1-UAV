"""Flight timeline, periodic snapshots and read-only host/battery monitoring."""
import logging
import time
from observability.metrics import HostMetrics


PHASE_MESSAGES = {
    'TAKEOFF': 'Climb started; waiting for target and HOLD',
    'HOLD': 'Holding position; check takeoff_complete and hold_reason',
    'GPS_STARTING': 'Mission start requested; waiting for PX4 MISSION',
    'GPS_RUNNING': 'PX4 MISSION confirmed',
    'GPS_PAUSED': 'Pause confirmed; PX4 HOLD',
    'GPS_CANCELLED': 'Cancel confirmed; mission cleared, PX4 HOLD',
    'GPS_COMPLETE': 'Mission complete; final position, height and HOLD confirmed',
    'HOME_COMPLETE': 'Return complete; launch position, held height and HOLD confirmed',
    'LANDING': 'PX4 LAND confirmed; waiting for ground and disarm',
    'IDLE': 'Idle; inspect armed and landed state before a new flight',
    'ARMED': 'ARM confirmed on ground',
    'EXTERNAL': 'Unexpected mode or link change; no automatic resume',
    'GPS_UNCONFIRMED': 'Mission confirmation failed; inspect last_error',
}


class FlightTimeline:
    def __init__(self, events):
        self.events = events
        self.last_state = None
        self.last_snapshot = self.last_health = -float('inf')
        self.last_battery = None
        self.last_confirmations = {}
        self.metrics = HostMetrics()
        self.context = {}

    def update(self, controller, status):
        drain = getattr(controller, 'drain_observed_events', None)
        if drain is not None:
            for event in drain():
                self.events.write(**dict(self.context, **event))
        telemetry = status.get('telemetry') or {}
        def value(key):
            return (telemetry.get(key) or {}).get('value')
        current = dict(phase=status.get('phase'), mode=value('flight_mode'),
                       armed=value('armed'), landed=value('landed_state'),
                       connected=status.get('connected'), last_error=status.get('last_error'))
        if current != self.last_state:
            previous = self.last_state or {}
            phase = current['phase']
            self.events.write('FLIGHT_STATE_CHANGED', PHASE_MESSAGES.get(phase, f'State changed: {phase}'),
                              severity='WARNING' if phase in {'EXTERNAL', 'GPS_UNCONFIRMED', 'FAULT'} else 'INFO',
                              phase_before=(self.last_state or {}).get('phase'), phase_after=phase,
                              details=current, **self.context)
            self.last_state = current
            if (phase == 'IDLE' and previous.get('phase') in {'LAND_REQUESTED', 'LANDING'}
                    and current['armed'] is False and current['landed'] == 'ON_GROUND'):
                self.events.write('LAND_CONFIRMED', 'Landed and disarmed', **self.context)
        for flag in ('arm_acknowledged', 'land_acknowledged', 'disarm_acknowledged',
                     'hold_acknowledged', 'arm_confirmed', 'land_mode_confirmed',
                     'disarm_confirmed', 'takeoff_complete', 'cancel_confirmed'):
            confirmed = status.get(flag) is True
            if confirmed and not self.last_confirmations.get(flag, False):
                self.events.write(flag.upper(), flag.replace('_', ' ').capitalize(),
                                  height_above_launch_m=status.get('height_above_launch_m'),
                                  phase_after=status.get('phase'), **self.context)
            self.last_confirmations[flag] = confirmed
        now = time.monotonic()
        if now - self.last_snapshot >= 0.5:
            self.events.write('FLIGHT_SNAPSHOT', 'Flight status', record_type='snapshot',
                              status=status, **self.context)
            self.last_snapshot = now
        if now - self.last_health >= 5:
            self.events.write('HOST_HEALTH', 'Flight process health', record_type='metric',
                              metrics=self.metrics.snapshot(self.events.directory))
            self.last_health = now
        item = telemetry.get('battery') or {}
        battery = item.get('value') or {}
        percent = battery.get('remaining_percent')
        limits = status.get('battery_failsafe') or {}
        warning = 'UNKNOWN'
        age = item.get('age_s')
        known = all(isinstance(limits.get(key), (int, float)) for key in
                    ('BAT_LOW_THR', 'BAT_CRIT_THR', 'BAT_EMERGEN_THR'))
        if (known and isinstance(age, (int, float)) and 0 <= age <= 3
                and isinstance(percent, (int, float)) and 0 <= percent <= 100):
            warning = 'NORMAL'
            for name, level in (('BAT_EMERGEN_THR', 'EMERGENCY'),
                                ('BAT_CRIT_THR', 'CRITICAL'), ('BAT_LOW_THR', 'LOW')):
                threshold = limits.get(name)
                if isinstance(threshold, (int, float)) and percent <= threshold * 100:
                    warning = level
                    break
            if warning == 'LOW' and percent <= 15 and limits['BAT_CRIT_THR'] * 100 < 15:
                warning = 'RESERVE_LOW'
        if warning != self.last_battery:
            self.events.write('BATTERY_STATE', f'Battery {warning}; PX4 owns failsafe action',
                              severity='WARNING' if warning in {'LOW', 'RESERVE_LOW', 'CRITICAL', 'EMERGENCY'} else 'INFO',
                              remaining_percent=percent, battery_state=warning,
                              failsafe=limits)
            self.last_battery = warning


class PythonEventHandler(logging.Handler):
    def __init__(self, events):
        super().__init__(logging.INFO)
        self.events = events

    def emit(self, record):
        try:
            self.events.write('PYTHON_LOG', self.format(record), severity=record.levelname,
                              logger=record.name)
        except Exception:
            self.handleError(record)


class NativeSdkLog:
    """Store raw SDK messages; callbacks never call the controller."""
    def __init__(self, events):
        self.events = events

    def __enter__(self):
        try:
            from mavsdk.logging import log_subscribe, log_unsubscribe
            self.unsubscribe = log_unsubscribe
            def callback(level, message, file, line):
                severity = {'WARN': 'WARNING'}.get(level.name, level.name)
                try:
                    self.events.write('MAVSDK_MESSAGE', message, severity=severity,
                                      source_file=file, source_line=line)
                    return True
                except Exception:
                    return False
            log_subscribe(callback)
        except (ImportError, AttributeError) as error:
            self.unsubscribe = None
            self.events.write('SDK_LOG_CAPTURE_UNAVAILABLE', str(error), severity='WARNING')
        return self

    def __exit__(self, *_):
        if self.unsubscribe:
            self.unsubscribe()
