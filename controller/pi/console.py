#!/usr/bin/env python3
"""Type flight commands directly on Pi; local NED targets go to Pixhawk over UART."""
import argparse
import faulthandler
from contextlib import ExitStack
import json
import logging
import math
import select
import shlex
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from deployment import validate_connection
from serial_lock import serial_ownership
from offboard_control import OffboardControl
from flight_policy import FlightPolicy

HELP = '''arm         ARM only on ground; motors may spin; no Offboard or climb
takeoff     Start OFFBOARD climb; accepts separate ARM or arms from IDLE
x y         Target metres N/E; accepted only after selecting FLY
fly         Enable coordinate input from confirmed HOLD
fly x y     Explicitly leave HOLD and fly to absolute local NED x/y
land        Request PX4 LAND
disarm      Force motors off on ground OR in flight; vehicle may fall
status      Read PX4 telemetry, application phase, target confirmation and locks
help        Show commands
exit        End signal stream; does NOT send LAND
X/Y origin: PX4 estimator local origin. Nonzero x/y/z alone does not diagnose a GPS fault.
Z target: launch down_m minus --height; height stays fixed for this flight.
Targets stay locked during TAKEOFF, FLY, SETTLING and HOLD_REQUESTED.
At target: position/yaw dwell supervision on Pi, then native PX4 HOLD.
HOLD is indefinite. Raw coordinates stay locked until FLY is explicitly selected.
'''


def parse_command(line):
    words = shlex.split(line)
    if not words:
        return 'empty', None
    if len(words) == 1 and words[0].lower() in {
            'arm', 'takeoff', 'fly', 'land', 'disarm', 'status', 'help', 'exit', 'quit'}:
        return ('exit' if words[0].lower() == 'quit' else words[0].lower()), None
    if words[0].lower() == 'fly':
        words = words[1:]
    if len(words) != 2:
        raise ValueError('Use arm, takeoff, fly, fly x y, land, disarm, status, help or exit')
    try:
        xy = tuple(float(v) for v in words)
    except ValueError:
        raise ValueError('x y must be numeric metres') from None
    if not all(math.isfinite(v) and abs(v) <= 10000 for v in xy):
        raise ValueError('x y must be finite and within -10000..10000 metres')
    return 'fly', xy


def execute(fc, line, output=print):
    command, xy = parse_command(line)
    if command == 'exit':
        output('Exit stops Offboard signals; PX4 applies its configured failsafe. Land first.')
        return False
    if command == 'empty':
        return True
    if command == 'help':
        output(HELP)
    elif command == 'status':
        output(json.dumps(fc.status(), indent=2, allow_nan=False))
    else:
        if command == 'fly':
            if xy is None:
                fc.fly()
            else:
                explicit = shlex.split(line)[0].lower() == 'fly'
                fc.fly(*xy, explicit=explicit)
        else:
            getattr(fc, command)()
        if command == 'arm':
            output('PX4 confirmed armed=true on ground. No Offboard/climb requested. '
                   'Motors may spin; use status, disarm, or explicit takeoff. '
                   'PX4 may auto-disarm while waiting.')
        elif command == 'takeoff':
            output('PX4 confirmed ARMED + OFFBOARD. Observe climb; target arrival is not confirmed.')
        elif command == 'disarm':
            output('Forced DISARM acknowledged. Motors may stop in flight; vehicle may fall. '
                   'Check fresh armed=false; ACK alone does not confirm motors stopped.')
        elif command == 'land':
            output('LAND acknowledged. Connection remains open; check land_mode_confirmed, '
                   'then ON_GROUND and armed=false. Do not exit yet.')
        elif command == 'fly' and xy is None:
            output('FLY selected. PX4 remains in HOLD until you enter x y; no motion commanded yet.')
        else:
            output('Request sent. Observe PX4/Gazebo; this is not confirmation of arrival.')
    return True


def wait_initial_status(fc, timeout=3.0):
    """Let asynchronous telemetry and raw heartbeat populate before --check."""
    required = {'armed', 'landed_state', 'flight_mode', 'health_all_ok', 'local_ned'}
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        fc.refresh()
        with fc.lock:
            if fc.termination or required.issubset(fc.cache):
                return
        time.sleep(0.05)


def poll_controller(fc, logger, include_status=False):
    """A diagnostic/refresh error must not close the session before LAND/DISARM."""
    try:
        fc.refresh()
        if include_status:
            logger.info('Status %s', json.dumps(fc.status()))
    except Exception as error:
        fc.last_error = f'Polling failed: {error}; inspect state before motion commands'
        logger.exception('Polling failed; keeping console available for LAND/DISARM')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--connection', default='serial:///dev/ttyAMA0:921600')
    parser.add_argument('--profile', choices=['hitl', 'hardware'], default='hitl')
    parser.add_argument('--system-id', type=int, default=1)
    parser.add_argument('--height', type=float, default=2.0,
                        help='Climb in metres above the local NED position captured at takeoff')
    parser.add_argument('--xy-tolerance', type=float, default=0.5, help='Arrival horizontal tolerance, metres')
    parser.add_argument('--z-tolerance', type=float, default=0.3, help='Arrival vertical tolerance, metres')
    parser.add_argument('--yaw-tolerance', type=float, default=10.0, help='Arrival yaw tolerance, degrees')
    parser.add_argument('--settle-time', type=float, default=2.0, help='Fresh in-tolerance dwell before HOLD, seconds')
    parser.add_argument('--target-timeout', type=float, default=60.0, help='Target deadline before HOLD, seconds')
    parser.add_argument('--log-dir', default='session-logs', help='Pi diagnostic log directory')
    parser.add_argument('--enable-actuation', action='store_true')
    parser.add_argument('--check', action='store_true', help='Read state, never send flight commands')
    args = parser.parse_args()
    if not math.isfinite(args.height) or not 0.5 <= args.height <= 100:
        parser.error('height must be 0.5..100 m')
    if not 1 <= args.system_id <= 255:
        parser.error('system-id must be 1..255')
    try:
        policy = FlightPolicy(xy_tolerance_m=args.xy_tolerance, z_tolerance_m=args.z_tolerance,
                              yaw_tolerance_deg=args.yaw_tolerance, settle_s=args.settle_time,
                              target_timeout_s=args.target_timeout)
        if policy.z_tolerance_m >= args.height:
            raise ValueError('z-tolerance must be less than height')
    except ValueError as error:
        parser.error(str(error))
    try:
        device = validate_connection(args.profile, args.connection)
    except ValueError as error:
        parser.error(str(error))
    log_dir = Path(args.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / datetime.now(timezone.utc).strftime('pi-%Y%m%dT%H%M%S.%fZ.log')
    logging.basicConfig(filename=log_path, level=logging.INFO,
                        format='%(asctime)s %(levelname)s %(name)s %(message)s', force=True)
    logger = logging.getLogger(__name__)
    logger.info('Session started profile=%s connection=%s height=%s actuation=%s',
                args.profile, args.connection, args.height, args.enable_actuation and not args.check)
    for label, path in [('boot_id', '/proc/sys/kernel/random/boot_id'),
                        ('uptime', '/proc/uptime')]:
        try:
            logger.info('Pi %s=%s', label, Path(path).read_text().strip())
        except OSError:
            logger.warning('Cannot read Pi %s', label, exc_info=True)
    print(f'Diagnostic log: {log_path}')
    with ExitStack() as stack:
        fault_log = stack.enter_context(open(log_path.with_suffix('.fault.log'), 'a'))
        faulthandler.enable(file=fault_log, all_threads=True)
        stack.callback(faulthandler.disable)
        stack.enter_context(serial_ownership(device))
        fc = OffboardControl(args.connection, args.profile,
                             args.enable_actuation and not args.check, args.system_id, args.height,
                             policy=policy)
        stack.callback(fc.close)
        if args.check:
            wait_initial_status(fc)
            execute(fc, 'status')
            return 0
        print(f'Pi -> Pixhawk: {args.connection}; climb above launch={args.height:g} m')
        print(HELP)
        last_status_log = 0.0
        while True:
            try:
                print('Pi-UAV> ', end='', flush=True)
                # Keep watching takeover/landing while the user is not typing.
                # Setpoint transmission itself remains inside MAVSDK.
                while not select.select([sys.stdin], [], [], 0.2)[0]:
                    include_status = time.monotonic() - last_status_log >= 1.0
                    poll_controller(fc, logger, include_status=include_status)
                    if include_status:
                        last_status_log = time.monotonic()
                line = input()
            except (EOFError, KeyboardInterrupt):
                logger.warning('EOF/interrupt: closing session and stopping stream', exc_info=True)
                print('\nExit: signal stream stops; no LAND command. PX4 failsafe applies.')
                break
            try:
                # Diagnostics must not refresh/destroy a plugin before an
                # operator's LAND or DISARM can be dispatched.
                logger.info('Command %r', line)
                if not execute(fc, line):
                    break
            except KeyboardInterrupt:
                logger.exception('Command interrupted')
                print('Command interrupted; inspect status before retrying.')
            except Exception as error:
                logger.exception('Command failed: %r', line)
                print(f'Error: {error}. Inspect status before retrying; no automatic retry.')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception:
        logging.getLogger(__name__).exception('Fatal console error')
        raise
