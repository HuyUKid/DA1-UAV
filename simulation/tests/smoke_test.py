#!/usr/bin/env python3
"""Bounded DISARM-only HIL communications check. Does not test flight."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'simulation/x500'))
from prepare import HERE
from observe import ground_check


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=int, default=40)
    parser.add_argument('--px4', type=Path, help='Optional PX4 source build instead of bundled plugins')
    parser.add_argument('--serial', default='auto')
    parser.add_argument('--baud', type=int, default=921600)
    parser.add_argument('--system-id', type=int, default=1)
    parser.add_argument('--confirm-disarmed', action='store_true',
                        help='Operator confirms props removed, DISARM, and no ARM during this check')
    args = parser.parse_args()
    if not 15 <= args.seconds <= 120:
        parser.error('Duration must be 15..120 seconds')
    if not 1 <= args.system_id <= 255:
        parser.error('system-id must be 1..255')
    if not args.confirm_disarmed:
        parser.error('Remove props and confirm DISARM with --confirm-disarmed; never ARM during this check')
    output = HERE.parent / 'artifacts'
    output.mkdir(parents=True, exist_ok=True)
    report = output / f'connection-{time.time_ns()}.json'
    data = {}
    with report.with_suffix('.log').open('w') as log:
        source = ['--px4', str(args.px4)] if args.px4 is not None else []
        sim = subprocess.Popen([sys.executable, str(HERE / 'launch.py'), '--headless',
                                *source, '--serial', args.serial, '--baud', str(args.baud)],
                               stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            # Observer can bind before Gazebo is fully loaded.
            result = subprocess.run([sys.executable, str(HERE / 'observe.py'), '--seconds', str(args.seconds),
                                     '--system-id', str(args.system_id), '--output', str(report)],
                                    check=False, timeout=args.seconds + 10)
            if report.exists():
                data = json.loads(report.read_text())
                pose = subprocess.run(['gz', 'model', '-m', 'x500_hitl', '-p'],
                                      capture_output=True, text=True, timeout=5)
                data['gazebo_pose_xyz_rpy'] = pose.stdout.strip()
                data.update(ground_check(data, pose.stdout, pose.returncode == 0, sim.poll() is None))
                report.write_text(json.dumps(data, indent=2) + '\n')
                print('Gazebo pose:', data['gazebo_pose_xyz_rpy'])
                print('Ground estimate consistent:', data['ground_estimate_consistent'])
                # Fail on estimator drift even if bidirectional communications work.
                return 0 if result.returncode == 0 and data['ground_estimate_consistent'] else 1
            return 1
        finally:
            if sim.poll() is None:
                if data.get('last_state', {}).get('armed') is True:
                    print(f'ARM detected: leaving Gazebo running (PID {sim.pid}). '
                          'Recover/disarm PX4 before stopping HIL.', file=sys.stderr)
                else:
                    try:
                        os.killpg(sim.pid, signal.SIGINT)
                        try:
                            sim.wait(timeout=8)
                        except subprocess.TimeoutExpired:
                            os.killpg(sim.pid, signal.SIGTERM)
                            sim.wait(timeout=5)
                    except ProcessLookupError:
                        pass


if __name__ == '__main__':
    raise SystemExit(main())
