#!/usr/bin/env python3
"""Observe HIL telemetry; request stream rates only, never send flight commands."""
import argparse
from collections import Counter
import json
import math
from pathlib import Path
import time


def json_safe(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    return value


def ground_check(data, pose_text, pose_ok, simulator_running, max_age=3.0):
    """Reject stale/missing telemetry, any observed ARM, or an unrelated/dead simulator."""
    state = data.get('last_state', {})
    velocity = state.get('local_position_ned', {})
    ages = data.get('last_message_age_s', {})
    required = ('HEARTBEAT', 'HIL_ACTUATOR_CONTROLS', 'LOCAL_POSITION_NED', 'EXTENDED_SYS_STATE')
    fresh = all(isinstance(ages.get(k), (float, int)) and math.isfinite(ages[k])
                and 0 <= ages[k] <= max_age for k in required)
    try:
        v = [float(velocity[k]) for k in ('vx', 'vy', 'vz')]
        speed = math.hypot(*v)
        pose = [float(x) for x in pose_text.split()]
        pose_valid = len(pose) == 6 and all(math.isfinite(x) for x in pose)
    except (KeyError, ValueError, TypeError):
        speed, pose_valid = float('inf'), False
    consistent = (simulator_running and pose_ok and pose_valid and fresh
                  and data.get('heartbeat_and_actuator_seen') is True
                  and data.get('armed_seen') is False and state.get('armed') is False
                  and state.get('landed_state') == 1 and math.isfinite(speed) and speed < 0.5)
    return {'estimated_speed_m_s': speed if math.isfinite(speed) else None,
            'ground_estimate_consistent': bool(consistent), 'flight_verified': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=float, default=30)
    parser.add_argument('--system-id', type=int, default=1)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if not math.isfinite(args.seconds) or not 0 < args.seconds <= 600:
        parser.error('seconds must be finite and in (0, 600]')
    if not 1 <= args.system_id <= 255:
        parser.error('system-id must be 1..255')
    from pymavlink import mavutil
    fc = mavutil.mavlink_connection('udpin:127.0.0.1:14540', source_system=246, source_component=191)
    deadline, requested = time.monotonic() + args.seconds, False
    counts, state, last_seen = Counter(), {}, {}
    armed_seen = False
    try:
        while time.monotonic() < deadline:
            msg = fc.recv_match(blocking=True, timeout=0.25)
            if not msg or msg.get_srcSystem() != args.system_id or msg.get_srcComponent() != 1:
                continue
            name = msg.get_type()
            counts[name] += 1
            last_seen[name] = time.monotonic()
            if name == 'HEARTBEAT':
                state['armed'] = bool(msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
                armed_seen |= state['armed']
                state['mode'] = mavutil.mode_string_v10(msg)
                if not requested:
                    fc.mav.heartbeat_send(mavutil.mavlink.MAV_TYPE_ONBOARD_CONTROLLER,
                                          mavutil.mavlink.MAV_AUTOPILOT_INVALID, 0, 0, 0)
                    for message_id in (32, 65, 245):
                        fc.mav.command_long_send(args.system_id, 1, mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL,
                                                 0, message_id, 200000, 0, 0, 0, 0, 0)
                    requested = True
            elif name == 'LOCAL_POSITION_NED':
                state['local_position_ned'] = {k: getattr(msg, k) for k in ('x', 'y', 'z', 'vx', 'vy', 'vz')}
            elif name == 'EXTENDED_SYS_STATE':
                state['landed_state'] = msg.landed_state
            elif name == 'HIL_ACTUATOR_CONTROLS':
                state['actuator_controls'] = list(msg.controls[:4])
            elif name == 'HIGHRES_IMU':
                state['imu_time_usec'] = msg.time_usec
                state['imu'] = {k: getattr(msg, k) for k in ('xacc', 'yacc', 'zacc', 'xgyro', 'ygyro', 'zgyro')}
            elif name == 'ATTITUDE':
                state['attitude_rad'] = {k: getattr(msg, k) for k in ('roll', 'pitch', 'yaw')}
            elif name == 'ESTIMATOR_STATUS':
                state['estimator_flags'] = msg.flags
                state['estimator_ratios'] = {k: getattr(msg, k) for k in ('vel_ratio', 'pos_horiz_ratio', 'pos_vert_ratio')}
            elif name == 'GPS_RAW_INT':
                state['gps_fix_type'] = msg.fix_type
            elif name == 'STATUSTEXT':
                state.setdefault('status_text', []).append(msg.text)
    finally:
        fc.close()
    now = time.monotonic()
    ages = {k: now-t for k, t in last_seen.items()}
    fresh_link = all(k in ages and ages[k] <= 3 for k in ('HEARTBEAT', 'HIL_ACTUATOR_CONTROLS'))
    result = {'system_id': args.system_id, 'message_counts': dict(counts), 'last_state': state,
              'last_message_age_s': ages, 'armed_seen': armed_seen,
              'flight_commands_sent': False, 'communication_fresh': fresh_link,
              'heartbeat_and_actuator_seen': counts['HEARTBEAT'] > 0 and counts['HIL_ACTUATOR_CONTROLS'] > 0}
    text = json.dumps(json_safe(result), indent=2, allow_nan=False)
    print(text)
    if args.output:
        args.output.write_text(text + '\n')
    return 0 if fresh_link else 1


if __name__ == '__main__':
    raise SystemExit(main())
