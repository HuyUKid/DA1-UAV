#!/usr/bin/env python3
"""Read-only Pi power/boot diagnostics; no MAVLink or flight commands.

Run from controller/: python3 tools/diagnose_pi.py > pi-diagnostic.json
Missing utilities/permissions are reported rather than changing the system.
"""
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def read_file(path):
    try:
        return Path(path).read_text().strip()
    except OSError as error:
        return {'error': str(error)}


def run_command(args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=8,
                                check=False)
        return {'exit_code': result.returncode, 'stdout': result.stdout.strip(),
                'stderr': result.stderr.strip()}
    except (OSError, subprocess.TimeoutExpired) as error:
        return {'error': str(error)}


def snapshot():
    return {
        'timestamp_utc': datetime.now(timezone.utc).isoformat(),
        'boot_id': read_file('/proc/sys/kernel/random/boot_id'),
        'uptime_seconds_and_idle': read_file('/proc/uptime'),
        'temperature_millidegrees_c': read_file('/sys/class/thermal/thermal_zone0/temp'),
        'throttled': run_command(['vcgencmd', 'get_throttled']),
        'boot_started': run_command(['uptime', '-s']),
        'current_boot_kernel': run_command(
            ['journalctl', '-b', '-k', '-n', '200', '--no-pager']),
        'previous_boot_kernel': run_command(
            ['journalctl', '-b', '-1', '-k', '-n', '200', '--no-pager']),
        'previous_boot_tail': run_command(
            ['journalctl', '-b', '-1', '-n', '100', '--no-pager']),
        'current_shutdown_events': run_command(
            ['journalctl', '-b', '-n', '100', '--no-pager', '--grep',
             '(?i)power key|power button|powering off|shutdown|watchdog|panic']),
        'previous_shutdown_events': run_command(
            ['journalctl', '-b', '-1', '-n', '100', '--no-pager', '--grep',
             '(?i)power key|power button|powering off|shutdown|watchdog|panic']),
        'watchdog_bootstatus': read_file('/sys/class/watchdog/watchdog0/bootstatus'),
        'pi_model': read_file('/proc/device-tree/model'),
        'boot_gpio_uart_configuration': boot_configuration(),
        'serial_login_service': run_command(
            ['systemctl', 'show', 'serial-getty@ttyAMA0.service',
             '--property=ActiveState,UnitFileState']),
    }


def boot_configuration():
    result = {}
    for path in ('/boot/firmware/config.txt', '/boot/config.txt'):
        try:
            lines = Path(path).read_text().splitlines()
            result[path] = [line.strip() for line in lines
                            if any(key in line.lower() for key in
                                   ('gpio-shutdown', 'gpio-poweroff', 'enable_uart', 'uart0'))]
        except OSError as error:
            result[path] = {'error': str(error)}
    return result


if __name__ == '__main__':
    print(json.dumps(snapshot(), ensure_ascii=False, indent=2))
