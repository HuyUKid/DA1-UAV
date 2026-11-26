"""Guard the boundary between tested HITL values and a real-aircraft candidate."""
from pathlib import Path
import unittest

CONTROLLER = Path(__file__).resolve().parents[1]
SIM_PROFILE = CONTROLLER.parent / 'simulation/params/x500_hitl.params'
if not SIM_PROFILE.is_file():
    # Optional comparison fixture on a standalone Pi deployment.
    SIM_PROFILE = CONTROLLER / 'simulation/params/x500_hitl.params'
REAL_PROFILE = CONTROLLER / 'params/hardware.params'


def parse(path):
    result = {}
    for line in path.read_text().splitlines():
        if not line or line.startswith('#'):
            continue
        vehicle, component, param, value, kind = line.split('\t')
        if (vehicle, component) != ('1', '1') or param in result:
            raise ValueError(f'Invalid QGC overlay row: {line}')
        result[param] = (int(value) if kind == '6' else float(value), int(kind))
    return result


class ParamProfileTests(unittest.TestCase):
    @unittest.skipUnless(SIM_PROFILE.with_name('x500_hitl_20ms.params').is_file(),
                         'Optional high-speed HITL profile not included')
    def test_high_speed_hitl_changes_only_horizontal_speed_values(self):
        base = parse(SIM_PROFILE)
        fast = parse(SIM_PROFILE.with_name('x500_hitl_20ms.params'))
        expected = dict(base)
        for name in ('MPC_XY_VEL_MAX', 'MPC_XY_CRUISE'):
            expected[name] = (20.0, 9)
        self.assertEqual(fast, expected)

    def test_battery_land_policy_matches_both_profiles(self):
        for path in ([REAL_PROFILE, SIM_PROFILE] if SIM_PROFILE.is_file() else [REAL_PROFILE]):
            profile = parse(path)
            self.assertEqual(profile['BAT_LOW_THR'], (0.30, 9))
            self.assertEqual(profile['BAT_CRIT_THR'], (0.07, 9))
            self.assertEqual(profile['BAT_EMERGEN_THR'], (0.05, 9))
            self.assertEqual(profile['COM_LOW_BAT_ACT'], (2, 6))
    def test_real_profile_clears_hitl_without_transferring_hover_or_bypasses(self):
        real = parse(REAL_PROFILE)
        self.assertEqual(real['SYS_HITL'], (0, 6))
        self.assertEqual(real['SYS_AUTOSTART'], (4001, 6))
        self.assertEqual(real['COM_RC_IN_MODE'], (1, 6))
        self.assertEqual(real['MIS_TAKEOFF_ALT'], (2.0, 9))
        for name in ('CBRK_SUPPLY_CHK', 'HIL_ACT_FUNC1',
                     'HIL_ACT_FUNC2', 'HIL_ACT_FUNC3', 'HIL_ACT_FUNC4'):
            self.assertEqual(real[name], (0, 6))
        self.assertNotIn('CBRK_IO_SAFETY', real)
        for name in ('MPC_THR_HOVER', 'COM_OF_LOSS_T', 'COM_OBL_RC_ACT', 'MPC_USE_HTE'):
            self.assertNotIn(name, real)
        # Shared requested mission limits; matching them does not validate real tuning.
        for name in ('MPC_XY_VEL_MAX', 'MPC_XY_CRUISE'):
            self.assertEqual(real[name], (1.0, 9))
        for name in ('MPC_Z_VEL_MAX_UP', 'MPC_Z_VEL_MAX_DN'):
            self.assertEqual(real[name], (0.5, 9))
        self.assertEqual(real['MPC_TKO_SPEED'], (0.4, 9))
        self.assertEqual(real['MPC_LAND_SPEED'], (0.3, 9))

    @unittest.skipUnless(SIM_PROFILE.is_file(), 'HITL profile not included in standalone controller deployment')
    def test_hitl_profile_matches_requested_motion_limits_but_keeps_simulation_configuration(self):
        sim = parse(SIM_PROFILE)
        self.assertEqual(sim['SYS_HITL'], (1, 6))
        self.assertEqual(sim['SYS_AUTOSTART'], (1001, 6))
        self.assertEqual(sim['COM_RC_IN_MODE'], (4, 6))
        for name in ('CBRK_SUPPLY_CHK', 'HIL_ACT_FUNC1',
                     'HIL_ACT_FUNC2', 'HIL_ACT_FUNC3', 'HIL_ACT_FUNC4'):
            self.assertNotEqual(sim[name][0], 0)
        real = parse(REAL_PROFILE)
        for name in ('MPC_XY_VEL_MAX', 'MPC_XY_CRUISE'):
            self.assertEqual(sim[name], (1.0, 9))
            self.assertEqual(sim[name], real[name])
        for name in ('MPC_Z_VEL_MAX_UP', 'MPC_Z_VEL_MAX_DN'):
            self.assertEqual(sim[name], (0.5, 9))

    def test_native_takeoff_flip_lockdown_matches_both_profiles(self):
        paths = (SIM_PROFILE, REAL_PROFILE) if SIM_PROFILE.is_file() else (REAL_PROFILE,)
        for path in paths:
            profile = parse(path)
            self.assertEqual(profile['FD_FAIL_P'], (60, 6))
            self.assertEqual(profile['FD_FAIL_R'], (60, 6))
            self.assertEqual(profile['FD_FAIL_P_TTRI'], (0.3, 9))
            self.assertEqual(profile['FD_FAIL_R_TTRI'], (0.3, 9))
            self.assertEqual(profile['COM_LKDOWN_TKO'], (3.0, 9))


if __name__ == '__main__':
    unittest.main()
