"""Guard the boundary between tested HITL values and a real-aircraft candidate."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


def parse(name):
    result = {}
    for line in (ROOT / name).read_text().splitlines():
        if not line or line.startswith('#'):
            continue
        vehicle, component, param, value, kind = line.split('\t')
        if (vehicle, component) != ('1', '1') or param in result:
            raise ValueError(f'Invalid QGC overlay row: {line}')
        result[param] = (int(value) if kind == '6' else float(value), int(kind))
    return result


class ParamProfileTests(unittest.TestCase):
    def test_real_profile_clears_hitl_without_transferring_hover_or_bypasses(self):
        sim = parse('simulation/params/x500_hitl.params')
        real = parse('controller/params/hardware.params')
        self.assertEqual(sim['SYS_HITL'], (1, 6))
        self.assertEqual(real['SYS_HITL'], (0, 6))
        self.assertEqual(sim['SYS_AUTOSTART'], (1001, 6))
        self.assertEqual(real['SYS_AUTOSTART'], (4001, 6))
        self.assertEqual(sim['COM_RC_IN_MODE'], (4, 6))
        self.assertEqual(real['COM_RC_IN_MODE'], (3, 6))
        for name in ('CBRK_SUPPLY_CHK', 'CBRK_IO_SAFETY', 'HIL_ACT_FUNC1',
                     'HIL_ACT_FUNC2', 'HIL_ACT_FUNC3', 'HIL_ACT_FUNC4'):
            self.assertNotEqual(sim[name][0], 0)
            self.assertEqual(real[name], (0, 6))
        for name in ('MPC_THR_HOVER', 'COM_OF_LOSS_T', 'COM_OBL_RC_ACT', 'MPC_USE_HTE'):
            self.assertNotIn(name, real)
        for name in ('MPC_XY_VEL_MAX', 'MPC_XY_CRUISE', 'MPC_Z_VEL_MAX_UP',
                     'MPC_Z_VEL_MAX_DN', 'MPC_TKO_SPEED', 'MPC_LAND_SPEED'):
            self.assertEqual(sim[name], real[name])


if __name__ == '__main__':
    unittest.main()
