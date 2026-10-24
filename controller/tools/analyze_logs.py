"""Read-only ULog evidence extraction. Requires pyulog and numpy.

Run from the project root: python controller/tools/analyze_logs.py --log-dir logs/2026-10-24 --output logs/2026-10-24/analysis.json
Times are seconds relative to the start of logged data, not wall-clock time.
"""
import argparse
import json
from pathlib import Path

import numpy as np
from pyulog import ULog


def analyze(path):
    u = ULog(str(path))

    def span(values):
        return [round(float(np.min(values)), 4), round(float(np.max(values)), 4)]

    def seconds(timestamp):
        return round((int(timestamp) - u.start_timestamp) / 1e6, 4)

    def transitions(name, field):
        d = u.get_dataset(name).data
        a = d[field]
        return [{'t_s': seconds(d['timestamp'][i]), 'value': int(a[i])}
                for i in range(len(a)) if i == 0 or a[i] != a[i-1]]

    def horizontal_tracking():
        local = u.get_dataset('vehicle_local_position').data
        target = u.get_dataset('trajectory_setpoint').data
        nav = u.get_dataset('vehicle_status').data
        offboard = u.get_dataset('offboard_control_mode').data
        ni = np.searchsorted(nav['timestamp'], local['timestamp'], side='right') - 1
        si = np.searchsorted(target['timestamp'], local['timestamp'], side='right') - 1
        valid = (ni >= 0) & (si >= 0)
        mode = nav['nav_state'][np.maximum(ni, 0)]
        tx = target['position[0]'][np.maximum(si, 0)]
        ty = target['position[1]'][np.maximum(si, 0)]
        error = np.hypot(local['x'] - tx, local['y'] - ty)
        valid &= np.isfinite(error)
        result = {}
        stages = {
            'offboard_until_last_received_setpoint': (mode == 14) &
                (local['timestamp'] <= offboard['timestamp'][-1]),
            'all_offboard_samples': mode == 14,
            'rtl_samples': mode == 5,
        }
        for stage, mask in stages.items():
            indices = np.flatnonzero(valid & mask)
            if not len(indices):
                result[stage] = None
                continue
            i = int(indices[np.argmax(error[indices])])
            result[stage] = {
                'sample_count': len(indices),
                'max_estimated_xy_tracking_error_m': round(float(error[i]), 4),
                'at_s': seconds(local['timestamp'][i]),
                'estimated_xy_m': [round(float(local[k][i]), 4) for k in ('x', 'y')],
                'target_xy_m': [round(float(tx[i]), 4), round(float(ty[i]), 4)],
                'axis_tracking': {},
            }
            for axis, desired in (('x', tx), ('y', ty)):
                signed = local[axis][indices] - desired[indices]
                worst = int(np.argmax(np.abs(signed)))
                j = int(indices[worst])
                exceeds = indices[np.abs(signed) > 0.5]
                result[stage]['axis_tracking'][axis] = {
                    'max_abs_error_m': round(float(abs(signed[worst])), 4),
                    'signed_error_at_max_m': round(float(signed[worst]), 4),
                    'at_s': seconds(local['timestamp'][j]),
                    'target_min_max_m': span(desired[indices]),
                    'first_abs_error_over_0_5m_s': (
                        seconds(local['timestamp'][exceeds[0]]) if len(exceeds) else None),
                }
        resets = []
        for field, delta_fields in (
            ('xy_reset_counter', ('delta_xy[0]', 'delta_xy[1]')),
            ('heading_reset_counter', ('delta_heading',)),
            ('z_reset_counter', ('delta_z',)),
        ):
            # delta fields retain old values: report only on counter changes.
            for i in np.flatnonzero(np.diff(local[field].astype(int))) + 1:
                resets.append({'counter': field, 'at_s': seconds(local['timestamp'][i]),
                               'delta': {k: round(float(local[k][i]), 4) for k in delta_fields}})
        result['resets'] = sorted(resets, key=lambda item: item['at_s'])
        result['note'] = ('Estimator position versus most recent logged trajectory setpoint, '
                          'matched by preceding timestamp; not independent ground truth. '
                          'RTL targets differ from the takeoff hold target.')
        return result

    gps = u.get_dataset('vehicle_gps_position').data
    local = u.get_dataset('vehicle_local_position').data
    offboard = u.get_dataset('offboard_control_mode').data
    flags = u.get_dataset('failsafe_flags').data
    lost = np.flatnonzero(flags['offboard_control_signal_lost'])
    result = {
        'file': path.name,
        'firmware_branch': u.msg_info_dict.get('ver_sw_branch'),
        'duration_s': seconds(u.last_timestamp),
        'parameters': {k: u.initial_parameters.get(k) for k in (
            'SYS_HITL', 'COM_OF_LOSS_T', 'COM_OBL_RC_ACT', 'COM_RCL_EXCEPT',
            'NAV_RCL_ACT', 'MPC_THR_HOVER', 'EKF2_HGT_REF', 'BAT1_N_CELLS',
            'CBRK_IO_SAFETY', 'COM_PREARM_MODE', 'COM_MOT_TEST_EN',
            'SYS_AUTOSTART', 'PWM_AUX_FUNC1', 'PWM_AUX_FUNC2', 'PWM_AUX_FUNC3',
            'PWM_AUX_FUNC4', 'PWM_AUX_DIS1', 'PWM_AUX_DIS2', 'PWM_AUX_DIS3',
            'PWM_AUX_DIS4', 'PWM_AUX_MIN1', 'PWM_AUX_MIN2', 'PWM_AUX_MIN3',
            'PWM_AUX_MIN4')},
        'gps': {k: span(gps[k]) for k in (
            'fix_type', 'satellites_used', 'eph', 'epv', 'jamming_state')},
        'initial_local_xyz_m': [round(float(local[k][0]), 4) for k in ('x', 'y', 'z')],
        'old_target_minus2_climb_from_initial_m': round(float(local['z'][0]) + 2, 4),
        'local_valid': {k: span(local[k]) for k in ('xy_valid', 'z_valid')},
        'local_reset_counters': {k: span(local[k]) for k in ('xy_reset_counter', 'z_reset_counter')},
        'last_offboard_message_s': seconds(offboard['timestamp'][-1]),
        'first_offboard_lost_s': seconds(flags['timestamp'][lost[0]]) if len(lost) else None,
        'nav_state_changes': transitions('vehicle_status', 'nav_state'),
        'failsafe_changes': transitions('vehicle_status', 'failsafe'),
        'estimator_checks': [],
        'imu_clipping_max_per_axis': [],
        'horizontal_tracking': horizontal_tracking(),
        'messages': [{'t_s': seconds(m.timestamp), 'text': m.message.strip()}
                     for m in u.logged_messages],
    }
    motors = u.get_dataset('actuator_motors').data
    # Exclude initial two seconds of arming/spool-up; these are normalized
    # commands, not measured RPM or evidence that any motor is defective.
    motor_mask = ((motors['timestamp'] >= u.start_timestamp + 2_000_000)
                  & (motors['timestamp'] <= offboard['timestamp'][-1]))
    result['motor_commands_before_offboard_loss'] = []
    for i in range(4):
        values = motors[f'control[{i}]']
        indices = np.flatnonzero(motor_mask & np.isfinite(values))
        saturated = indices[values[indices] >= 0.99]
        result['motor_commands_before_offboard_loss'].append({
            'motor_number': i + 1,
            'normalized_command_range': span(values[indices]) if len(indices) else None,
            'first_command_ge_0_99_s': (seconds(motors['timestamp'][saturated[0]])
                                      if len(saturated) else None),
        })
    for ds in u.data_list:
        if ds.name == 'estimator_status':
            result['estimator_checks'].append({
                'instance': ds.multi_id,
                **{k: span(ds.data[k]) for k in ('gps_check_fail_flags', 'filter_fault_flags')}})
        elif ds.name == 'vehicle_imu_status':
            result['imu_clipping_max_per_axis'].append({
                'instance': ds.multi_id,
                'max': [int(np.max(ds.data[f'accel_clipping[{i}]'])) for i in range(3)]})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--log-dir', type=Path,
                        default=Path(__file__).resolve().parents[2] / 'logs')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    paths = sorted(args.log_dir.rglob('*.ulg'))
    if not paths:
        parser.error(f'No .ulg files found in {args.log_dir}')
    result = json.dumps([analyze(p) for p in paths], indent=2,
                        ensure_ascii=False, allow_nan=False) + '\n'
    if args.output:
        args.output.write_text(result, encoding='utf-8')
    else:
        print(result, end='')


if __name__ == '__main__':
    main()
