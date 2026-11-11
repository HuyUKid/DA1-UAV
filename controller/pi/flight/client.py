#!/usr/bin/env python3
"""Local engineering console for a running flight service; no MAVSDK access."""
import argparse
import json
import math
from pathlib import Path
import shlex
import sys
import uuid

PI_DIR = Path(__file__).resolve().parents[1]
if str(PI_DIR) not in sys.path:
    sys.path.insert(0, str(PI_DIR))

from ipc.client import RpcClient


COMMANDS = {
    'arm': 'arm',
    'takeoff': 'takeoff',
    'gps-start': 'gps_start',
    'pause': 'pause',
    'resume': 'resume',
    'cancel': 'cancel',
    'return-home': 'return_home',
    'return-height': 'return_height',
    'land': 'land',
    'disarm': 'disarm',
}
HELP = """Commands:
  status         Show current PX4/controller state
  arm            ARM on ground; motors may spin
  takeoff        Climb to configured TAKEOFF height (default 2 m)
  fly x y        Fly to absolute local NED north/east metres (also: fly x,y)
  gps-plan A_lat A_lon B_lat B_lon height speed  Stage GPS waypoints
  gps-start      Start the staged GPS plan
  pause          Pause the active GPS/local target and wait for HOLD
  resume         Resume the previously paused target
  cancel         Discard the active target and HOLD at the current position
  return-home    Return to saved takeoff GPS at the current height; no auto-LAND
  return-height  Return vertically to TAKEOFF height; no auto-LAND
  land           Request PX4 LAND
  disarm         EMERGENCY: force motor stop; UAV will fall if airborne
  help           Show this list
  exit           Close this local console; flight service keeps running"""


def _numbers(words, count, usage):
    if len(words) != count:
        raise ValueError(usage)
    try:
        values = tuple(float(word) for word in words)
    except ValueError:
        raise ValueError(usage) from None
    if not all(math.isfinite(value) for value in values):
        raise ValueError('Coordinates, height and speed must be finite')
    return values


def build_request(line):
    words = shlex.split(line)
    if not words:
        raise ValueError('Enter a command; use help to see available commands')
    command = words[0].lower()
    if command == 'status' and len(words) == 1:
        return {'op': 'status'}
    if command == 'fly':
        coordinates = words[1].split(',') if len(words) == 2 else words[1:]
        north, east = _numbers(coordinates, 2, 'Use fly x y (or fly x,y)')
        if abs(north) > 10000 or abs(east) > 10000:
            raise ValueError('x/y must be within -10000..10000 metres')
        command_type = 'fly'
        params = {'north_m': north, 'east_m': east}
    elif command == 'gps-plan':
        a_lat, a_lon, b_lat, b_lon, height, speed = _numbers(
            words[1:], 6, 'Use gps-plan A_lat A_lon B_lat B_lon height_m speed_m_s')
        command_type = 'gps_plan'
        params = {'a': {'lat_deg': a_lat, 'lon_deg': a_lon},
                  'b': {'lat_deg': b_lat, 'lon_deg': b_lon},
                  'height_above_launch_m': height, 'speed_m_s': speed}
    elif len(words) == 1 and command in COMMANDS:
        command_type = COMMANDS[command]
        params = {'confirm_force': True} if command_type == 'disarm' else {}
    else:
        raise ValueError(f'Unknown or malformed command: {line}; use help')
    return {'op': 'local_command', 'command': {
        'type': command_type,
        'command_id': f'local-{uuid.uuid4().hex}',
        'mission_id': 'local-supervision',
        'params': params,
    }}


def send(client, line):
    return client.request(build_request(line))


def interactive(client, input_fn=None, output=print):
    input_fn = input if input_fn is None else input_fn
    output('Engineering Flight Service console (no direct MAVSDK connection).')
    output(HELP)
    while True:
        try:
            command = input_fn('UAV-REMOTE> ').strip()
        except (EOFError, KeyboardInterrupt):
            output('\nExit: Flight Service keeps running; no LAND command was sent.')
            return 0
        if not command:
            continue
        if command.lower() in {'exit', 'quit'}:
            output('Flight Service keeps running; no LAND command was sent.')
            return 0
        if command.lower() == 'help':
            output(HELP)
            continue
        try:
            if command.lower() == 'disarm':
                output('EMERGENCY MOTOR STOP requested; an airborne UAV will fall.')
            response = send(client, command)
            output(json.dumps(response, indent=2, allow_nan=False))
        except (OSError, ValueError) as error:
            output(f'Error: {error}')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', nargs='*', help='One command and its arguments; omit for interactive shell')
    parser.add_argument('--socket', default='/tmp/uav-flight.sock')
    args = parser.parse_args(argv)
    client = RpcClient(args.socket)
    if not args.command or args.command == ['shell']:
        return interactive(client)
    if args.command == ['help']:
        print(HELP)
        return 0
    try:
        response = send(client, ' '.join(args.command))
    except ValueError as error:
        parser.error(str(error))
    except OSError as error:
        parser.exit(1, f'Flight service unavailable: {error}\n')
    print(json.dumps(response, indent=2, allow_nan=False))
    return 0 if response.get('ok') else 1


if __name__ == '__main__':
    raise SystemExit(main())
