#!/usr/bin/env python3
"""Local supervisory console for a running flight service; no MAVSDK access."""
import argparse
import json
from pathlib import Path
import sys
import uuid

PI_DIR = Path(__file__).resolve().parents[1]
if str(PI_DIR) not in sys.path:
    sys.path.insert(0, str(PI_DIR))

from ipc.client import RpcClient


COMMANDS = {
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
  pause          Pause the active GPS/local target and wait for HOLD
  resume         Resume the previously paused target
  cancel         Discard the active target and HOLD at the current position
  return-home    Return to saved takeoff GPS at the current height; no auto-LAND
  return-height  Return vertically to TAKEOFF height; no auto-LAND
  land           Request PX4 LAND
  disarm         EMERGENCY: force motor stop; UAV will fall if airborne
  help           Show this list
  exit            Close this local console; flight service keeps running"""


def build_request(command):
    if command == 'status':
        return {'op': 'status'}
    try:
        command_type = COMMANDS[command]
    except KeyError:
        raise ValueError(f'Unknown command: {command}') from None
    params = {'confirm_force': True} if command_type == 'disarm' else {}
    return {'op': 'command', 'command': {
        'type': command_type,
        'command_id': f'local-{uuid.uuid4().hex}',
        'mission_id': 'local-supervision',
        'params': params,
    }}


def send(client, command):
    return client.request(build_request(command))


def interactive(client, input_fn=None, output=print):
    input_fn = input if input_fn is None else input_fn
    output('Local Flight Service console (no direct MAVSDK connection).')
    output(HELP)
    while True:
        try:
            command = input_fn('UAV-REMOTE> ').strip().lower()
        except (EOFError, KeyboardInterrupt):
            output('\nExit: Flight Service keeps running; no LAND command was sent.')
            return 0
        if not command:
            continue
        if command in {'exit', 'quit'}:
            output('Flight Service keeps running; no LAND command was sent.')
            return 0
        if command == 'help':
            output(HELP)
            continue
        try:
            if command == 'disarm':
                output('EMERGENCY MOTOR STOP requested; an airborne UAV will fall.')
            response = send(client, command)
            output(json.dumps(response, indent=2, allow_nan=False))
        except (OSError, ValueError) as error:
            output(f'Error: {error}')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', nargs='?', default='shell',
                        choices=['shell', 'status', *COMMANDS])
    parser.add_argument('--socket', default='/tmp/uav-flight.sock')
    args = parser.parse_args(argv)
    client = RpcClient(args.socket)
    if args.command == 'shell':
        return interactive(client)
    try:
        response = send(client, args.command)
    except ValueError as error:
        parser.error(str(error))
    except OSError as error:
        parser.exit(1, f'Flight service unavailable: {error}\n')
    print(json.dumps(response, indent=2, allow_nan=False))
    return 0 if response.get('ok') else 1


if __name__ == '__main__':
    raise SystemExit(main())
