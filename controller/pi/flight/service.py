#!/usr/bin/env python3
"""Flight service owning MAVSDK and accepting validated local IPC commands."""
import argparse
from contextlib import ExitStack
import math
from pathlib import Path
import signal
import sys

PI_DIR = Path(__file__).resolve().parents[1]
if str(PI_DIR) not in sys.path:
    sys.path.insert(0, str(PI_DIR))

from flight.deployment import validate_connection
from flight.flight_policy import FlightPolicy
from flight.gps_mission import GpsLimits, GpsMissionControl
from flight.commands import FlightCommandRouter
from ipc.server import RpcServer
from observability.event_log import EventLog
from flight.serial_lock import serial_ownership, udp_ownership


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--connection', default='serial:///dev/ttyAMA0:921600')
    parser.add_argument('--profile', choices=['hitl', 'hardware'], default='hitl')
    parser.add_argument('--system-id', type=int, default=1)
    parser.add_argument('--height', type=float, default=2.0)
    parser.add_argument('--gps-max-leg', type=float, default=10.0)
    parser.add_argument('--gps-max-height', type=float, default=3.0)
    parser.add_argument('--gps-max-speed', type=float, default=0.5)
    parser.add_argument('--xy-tolerance', type=float, default=0.5)
    parser.add_argument('--z-tolerance', type=float, default=0.3)
    parser.add_argument('--yaw-tolerance', type=float, default=10.0)
    parser.add_argument('--settle-time', type=float, default=2.0)
    parser.add_argument('--target-timeout', type=float, default=60.0)
    parser.add_argument('--socket', default='/tmp/uav-flight.sock')
    parser.add_argument('--log-dir', default='session-logs/services')
    parser.add_argument('--enable-actuation', action='store_true')
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not math.isfinite(args.height) or not 0.5 <= args.height <= 100:
        parser.error('height must be 0.5..100 m')
    try:
        device = validate_connection(args.profile, args.connection)
        policy = FlightPolicy(xy_tolerance_m=args.xy_tolerance,
                              z_tolerance_m=args.z_tolerance,
                              yaw_tolerance_deg=args.yaw_tolerance,
                              settle_s=args.settle_time,
                              target_timeout_s=args.target_timeout)
        limits = GpsLimits(max_leg_m=args.gps_max_leg,
                           max_height_m=args.gps_max_height,
                           max_speed_m_s=args.gps_max_speed)
        if limits.max_height_m < args.height:
            raise ValueError('gps-max-height must be at least --height')
    except ValueError as error:
        parser.error(str(error))

    running = True

    def stop(*_):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    with ExitStack() as stack:
        events = stack.enter_context(EventLog(args.log_dir, 'flight'))
        events.write('SERVICE_STARTED', 'Flight service started',
                     profile=args.profile, connection=args.connection,
                     actuation_enabled=args.enable_actuation)
        ownership = udp_ownership if device.startswith('udpin://') else serial_ownership
        stack.enter_context(ownership(device))
        controller = GpsMissionControl(args.connection, args.profile,
                                       args.enable_actuation, args.system_id,
                                       args.height, policy=policy, gps_limits=limits)
        stack.callback(controller.close)
        router = FlightCommandRouter(controller, events)
        server = stack.enter_context(RpcServer(args.socket, router.handle))
        print(f'Flight service ready: {args.socket}; actuation={args.enable_actuation}', flush=True)
        while running:
            server.poll(0.2)
            router.poll_state()
        events.write('SERVICE_STOPPED', 'Flight service stopped')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
