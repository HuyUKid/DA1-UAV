from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'x500'))

from copy import deepcopy
import unittest
from observe import ground_check


class ObservationTests(unittest.TestCase):
    def setUp(self):
        self.data = {
            'armed_seen': False, 'heartbeat_and_actuator_seen': True,
            'last_state': {'armed': False, 'landed_state': 1,
                           'local_position_ned': dict(vx=0.01, vy=0.02, vz=0.03)},
            'last_message_age_s': {k: 0.2 for k in (
                'HEARTBEAT', 'HIL_ACTUATOR_CONTROLS', 'LOCAL_POSITION_NED', 'EXTENDED_SYS_STATE')}}

    def check(self, data=None, pose='0 0 0.25 0 0 0', pose_ok=True, running=True):
        return ground_check(self.data if data is None else data, pose, pose_ok, running)

    def test_fresh_ground_estimate_is_not_a_flight_certificate(self):
        result = self.check()
        self.assertTrue(result['ground_estimate_consistent'])
        self.assertFalse(result['flight_verified'])

    def test_transient_arm_cannot_pass_after_disarm(self):
        self.data['armed_seen'] = True
        self.assertFalse(self.check()['ground_estimate_consistent'])

    def test_dead_simulator_cannot_pass_using_other_telemetry(self):
        self.assertFalse(self.check(running=False)['ground_estimate_consistent'])

    def test_stale_missing_and_future_samples_fail(self):
        for name in self.data['last_message_age_s']:
            for age in (None, -0.01, 3.01, float('nan')):
                with self.subTest(name=name, age=age):
                    data = deepcopy(self.data)
                    if age is None:
                        data['last_message_age_s'].pop(name)
                    else:
                        data['last_message_age_s'][name] = age
                    self.assertFalse(self.check(data)['ground_estimate_consistent'])

    def test_missing_nonfinite_or_fast_velocity_fails(self):
        for value in (None, float('nan'), float('inf'), 1.0):
            data = deepcopy(self.data)
            data['last_state']['local_position_ned']['vx'] = value
            self.assertFalse(self.check(data)['ground_estimate_consistent'])

    def test_unparseable_or_failed_pose_fails(self):
        for pose in ('', 'error output', '0 0 0', '0 0 nan 0 0 0'):
            self.assertFalse(self.check(pose=pose)['ground_estimate_consistent'])
        self.assertFalse(self.check(pose_ok=False)['ground_estimate_consistent'])

    def test_airborne_or_unknown_arming_state_fails(self):
        for field, value in (('armed', True), ('armed', None), ('landed_state', 2)):
            data = deepcopy(self.data)
            data['last_state'][field] = value
            self.assertFalse(self.check(data)['ground_estimate_consistent'])


if __name__ == '__main__':
    unittest.main()
