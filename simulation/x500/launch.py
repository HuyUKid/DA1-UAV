#!/usr/bin/env python3
"""Run x500 Gazebo Classic HITL, never PX4 SITL and never ARM."""
import argparse
import os
from pathlib import Path
import subprocess
import shutil
import tempfile
import xml.etree.ElementTree as E
from prepare import HERE
from check_setup import inspect_setup
from paths import plugin_directory, serial_device


def main():
    # The temporary model remains available for the full simulator lifetime.
    with tempfile.TemporaryDirectory(prefix='uav-hitl-') as temporary:
        return launch(Path(temporary))


def launch(temporary):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument('--px4', type=Path, help='Use plugins from a PX4 source build')
    source.add_argument('--plugins', type=Path, help='Use a specific plugin directory')
    parser.add_argument('--serial', default='auto', help='USB device path, or auto for exactly one by-id device')
    parser.add_argument('--baud', type=int, default=921600)
    parser.add_argument('--headless', action='store_true')
    parser.add_argument('--validate', action='store_true')
    args = parser.parse_args()
    if args.baud <= 0:
        parser.error('--baud must be positive')
    try:
        device = serial_device(args.serial)
    except ValueError as exc:
        parser.error(str(exc))
    generated = temporary / 'generated'
    shutil.copytree(HERE / 'generated', generated)
    sdf = generated / 'models/x500_hitl/model.sdf'
    if not sdf.is_file():
        parser.error('Run prepare.py first')
    tree = E.parse(sdf)
    bridge = tree.find("model/plugin[@name='mavlink_interface']")
    bridge.find('serialDevice').text = device
    bridge.find('baudRate').text = str(args.baud)
    tree.write(sdf, encoding='utf-8', xml_declaration=True)
    options = {'plugins': args.plugins} if args.plugins is not None else {}
    report = inspect_setup(args.px4, generated=generated,
                           require_device=not args.validate, headless=args.headless, **options)
    errors = report['static_errors'] + report['runtime_errors']
    if errors:
        parser.error('\n'.join(errors))
    plugins = plugin_directory(args.px4, args.plugins)
    env = os.environ.copy()
    for key, values in {
        'GAZEBO_MODEL_PATH': [generated / 'models', Path('/usr/share/gazebo-11/models')],
        'GAZEBO_PLUGIN_PATH': [plugins],
        'LD_LIBRARY_PATH': [plugins],
        'GAZEBO_RESOURCE_PATH': [Path('/usr/share/gazebo-11')],
    }.items():
        env[key] = ':'.join([*(str(p) for p in values), env.get(key, '')])
    env['GAZEBO_MODEL_DATABASE_URI'] = ''
    if args.validate:
        for path in (sdf, generated / 'x500_hitl.world'):
            result = subprocess.run(['gz', 'sdf', '-k', str(path)], env=env, check=False)
            if result.returncode:
                return result.returncode
        return 0
    # The process opens the real USB port and exchanges HIL data, but sends no flight command.
    command = ['gzserver' if args.headless else 'gazebo', '--verbose', str(generated / 'x500_hitl.world')]
    print('Starting x500 HITL; Pixhawk USB owned by simulator. No ARM command is sent.', flush=True)
    child = subprocess.Popen(command, env=env)
    try:
        return child.wait()
    except KeyboardInterrupt:
        # Terminal Ctrl-C already reaches Gazebo in the same process group.
        import signal
        child.send_signal(signal.SIGINT)
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.terminate()
            child.wait(timeout=5)
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
