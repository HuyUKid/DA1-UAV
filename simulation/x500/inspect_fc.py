#!/usr/bin/env python3
"""Read identity, heartbeat and parameters. Never ARM or write parameters."""
import argparse
import json
import time
from pymavlink import mavutil


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--device', default='/dev/serial/by-id/usb-Auterion_PX4_FMU_v6C.x_0-if00')
    parser.add_argument('--baud', type=int, default=921600)
    args = parser.parse_args()
    fc = mavutil.mavlink_connection(args.device, baud=args.baud, source_system=245, source_component=191)
    def heartbeat():
        fc.mav.heartbeat_send(mavutil.mavlink.MAV_TYPE_ONBOARD_CONTROLLER,
                              mavutil.mavlink.MAV_AUTOPILOT_INVALID, 0, 0, 0)
    heartbeat()
    msg = fc.wait_heartbeat(timeout=8)
    if msg is None:
        raise SystemExit('No PX4 heartbeat within 8 seconds')
    system, component = msg.get_srcSystem(), msg.get_srcComponent()
    if msg.autopilot != mavutil.mavlink.MAV_AUTOPILOT_PX4:
        raise SystemExit('Connected heartbeat is not PX4')
    result = {'system_id': system, 'component_id': component,
              'armed': bool(msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED),
              'mode': mavutil.mode_string_v10(msg), 'parameters': {}}
    fc.mav.command_long_send(system, component, mavutil.mavlink.MAV_CMD_REQUEST_MESSAGE,
                             0, mavutil.mavlink.MAVLINK_MSG_ID_AUTOPILOT_VERSION, 0, 0, 0, 0, 0, 0)
    version = fc.recv_match(type='AUTOPILOT_VERSION', blocking=True, timeout=3)
    if version:
        packed = version.flight_sw_version
        result['firmware'] = f'{packed >> 24}.{(packed >> 16) & 255}.{(packed >> 8) & 255}'
        result['board_version'] = version.board_version
    names = ['SYS_HITL', 'SYS_AUTOSTART', 'MAV_1_CONFIG', 'MAV_1_MODE', 'SER_TEL2_BAUD',
             'COM_OF_LOSS_T', 'COM_OBL_RC_ACT', 'MPC_THR_HOVER', 'CA_ROTOR_COUNT']
    names += [f'HIL_ACT_FUNC{i}' for i in range(1, 5)]
    for name in names:
        heartbeat()
        fc.mav.param_request_read_send(system, component, name.encode(), -1)
        deadline = time.monotonic() + 2
        result['parameters'][name] = None
        while time.monotonic() < deadline:
            value = fc.recv_match(type='PARAM_VALUE', blocking=True, timeout=0.2)
            if value and value.param_id == name:
                # PX4 bytewise encodes integer parameters in the float field.
                if value.param_type == mavutil.mavlink.MAV_PARAM_TYPE_INT32:
                    import struct
                    decoded = struct.unpack('<i', struct.pack('<f', value.param_value))[0]
                else:
                    decoded = value.param_value
                result['parameters'][name] = decoded
                break
    fc.close()
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
