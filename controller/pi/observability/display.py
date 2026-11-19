"""Human-readable terminal output; IPC status stays machine-readable."""
import json
import math


def text(value, digits=2):
    if value is None:
        return 'N/A'
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, float):
        return f'{value:.{digits}f}' if math.isfinite(value) else 'N/A'
    return str(value).replace('\n', ' ').replace('\r', ' ')


def format_status(status):
    telemetry = status.get('telemetry') or {}
    def sample(key):
        item = telemetry.get(key) or {}
        return item.get('value'), item.get('age_s')
    def line(label, data, age=None):
        values = '  '.join(f'{key}={text(value, 7 if key in {"lat", "lon"} else 2)}'
                           for key, value in data.items())
        return f'{label:<10} {values}' + (f'  age={text(age)}s' if age is not None else '')
    ned, ned_age = sample('local_ned')
    gps, gps_age = sample('position')
    velocity, vel_age = sample('local_velocity')
    battery, bat_age = sample('battery')
    ned, gps, velocity, battery = ned or {}, gps or {}, velocity or {}, battery or {}
    mission = status.get('gps_mission') or {}
    plan = mission.get('plan') or {}
    target_height = plan.get('height_above_launch_m')
    if target_height is None:
        launch, target = status.get('launch_ned') or {}, status.get('target_ned') or {}
        if isinstance(launch.get('down_m'), (int, float)) and isinstance(target.get('down_m'), (int, float)):
            target_height = launch['down_m'] - target['down_m']
    progress = mission.get('progress') or {}
    host = status.get('host_health') or {}
    memory = host.get('memory') or {}
    disk = host.get('disk') or {}
    def mib(value):
        return value / (1024 ** 2) if isinstance(value, (int, float)) else None
    lines = [line('SYSTEM', dict(profile=status.get('profile'), connected=status.get('connected'),
                                 actuation=status.get('actuation_enabled'))),
             line('FLIGHT', dict(phase=status.get('phase'), mode=sample('flight_mode')[0],
                                 armed=sample('armed')[0], landed=sample('landed_state')[0])),
             line('NED (m)', dict(north=ned.get('north_m'), east=ned.get('east_m'), down=ned.get('down_m')), ned_age),
             line('POSITION', dict(lat=gps.get('latitude_deg'), lon=gps.get('longitude_deg'),
                                   msl_m=gps.get('absolute_altitude_m'), home_m=gps.get('relative_altitude_m')), gps_age),
             line('HEIGHT', dict(launch_m=status.get('height_above_launch_m'),
                                 target_m=target_height)),
             line('VEL (m/s)', {key: velocity.get(key) for key in ('north_m_s', 'east_m_s', 'down_m_s')}, vel_age),
             line('HEALTH', dict(all_ok=sample('health_all_ok')[0],
                                 invalid=status.get('invalid_telemetry_fields')),
                  sample('health_all_ok')[1]),
             line('BATTERY', dict(percent=battery.get('remaining_percent'), voltage_v=battery.get('voltage_v'),
                                  current_a=battery.get('current_a'), warning=battery.get('warning')), bat_age),
             line('MISSION', dict(phase=mission.get('phase'), points=plan.get('waypoint_count'),
                                  target=progress.get('target_label'), speed_m_s=plan.get('speed_m_s'))),
             line('CONTROL', dict(takeoff_complete=status.get('takeoff_complete'),
                                  can_send_target=status.get('can_send_target'), locked=status.get('target_locked'))),
             line('PI HEALTH', dict(cpu_pct=host.get('cpu_percent'), temp_c=host.get('temperature_c'),
                                    ram_used_mib=mib(memory.get('used_bytes')),
                                    ram_available_mib=mib(memory.get('available_bytes')),
                                    disk_available_mib=mib(disk.get('available_bytes')))),
             line('BAT LIMITS', status.get('battery_failsafe') or {}),
             f'LAST_ERROR {text(status.get("last_error"))}']
    return '\n'.join(lines)


def format_response(response, command='', raw=False):
    if raw:
        return json.dumps(response, indent=2, allow_nan=False)
    if not response.get('ok'):
        return f'REJECTED {command}: {text(response.get("error"))}'
    if command.split()[:1] == ['status']:
        return format_status(response.get('status') or {})
    phase = (response.get('status') or {}).get('phase')
    return f'ACCEPTED {command} | phase={text(phase)} | Check status for completion.'
