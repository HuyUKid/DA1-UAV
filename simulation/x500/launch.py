#!/usr/bin/env python3
"""Run x500 Gazebo Classic HITL, never PX4 SITL and never ARM."""
import argparse
import os
from pathlib import Path
import subprocess
from prepare import HERE
from check_setup import inspect_setup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--px4', type=Path, default=Path.home() / 'PX4-Autopilot-v1.16')
    parser.add_argument('--headless', action='store_true')
    parser.add_argument('--validate', action='store_true')
    args = parser.parse_args()
    generated = HERE / 'generated'
    sdf = generated / 'models/x500_hitl/model.sdf'
    if not sdf.is_file():
        parser.error('Run prepare.py first')
    report = inspect_setup(args.px4, require_device=not args.validate, headless=args.headless)
    errors = report['static_errors'] + report['runtime_errors']
    if errors:
        parser.error('\n'.join(errors))
    plugins = args.px4 / 'build/px4_sitl_default/build_gazebo-classic'
    classic = args.px4 / 'Tools/simulation/gazebo-classic/sitl_gazebo-classic'
    env = os.environ.copy()
    for key, values in {
        'GAZEBO_MODEL_PATH': [generated / 'models', classic / 'models', Path('/usr/share/gazebo-11/models')],
        'GAZEBO_PLUGIN_PATH': [plugins],
        'LD_LIBRARY_PATH': [plugins],
        'GAZEBO_RESOURCE_PATH': [classic, Path('/usr/share/gazebo-11')],
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
