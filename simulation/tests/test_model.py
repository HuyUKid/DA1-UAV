"""Checks that the port preserves x500 dynamics and uses a real-hardware HIL transport."""
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import xml.etree.ElementTree as E

HERE = Path(__file__).resolve().parents[2] / 'simulation/x500'
sys.path.insert(0, str(HERE))
from check_setup import model_errors, inspect_setup
from prepare import make_world_self_contained


class X500HitlTests(unittest.TestCase):
    def setUp(self):
        self.model = E.parse(HERE / 'generated/models/x500_hitl/model.sdf').getroot().find('model')
        self.original = E.parse(HERE / 'generated/models/x500_base/model.sdf').getroot().find('model')

    def test_x500_rigid_body_dynamics_preserved(self):
        for source in self.original.findall('link'):
            ported = self.model.find(f"link[@name='{source.get('name')}']")
            self.assertIsNotNone(ported)
            for tag in ('pose', 'inertial'):
                a, b = source.find(tag), ported.find(tag)
                if a is not None:
                    def values(node):
                        return [(e.tag, e.attrib, (e.text or "").strip()) for e in node.iter()]
                    self.assertEqual(values(a), values(b))

    def test_motor_mapping_is_px4_quad_x_in_flu(self):
        motors = self.model.findall("plugin[@filename='libgazebo_motor_model.so']")
        self.assertEqual(len(motors), 4)
        expected = [(1, -1, 'ccw'), (-1, 1, 'ccw'), (1, 1, 'cw'), (-1, -1, 'cw')]
        for i, (xsign, ysign, direction) in enumerate(expected):
            p = next(m for m in motors if m.findtext('motorNumber') == str(i))
            self.assertEqual(p.findtext('turningDirection'), direction)
            xyz = self.model.findtext(f"link[@name='rotor_{i}']/pose").split()
            self.assertGreater(float(xyz[0])*xsign, 0)
            self.assertGreater(float(xyz[1])*ysign, 0)
            self.assertEqual(p.findtext('motorConstant'), '8.54858e-06')
            self.assertEqual(p.findtext('maxRotVelocity'), '1000.0')
            self.assertEqual(p.findtext('momentConstant'), '0.016')

    def test_hil_bridge_uses_usb_and_no_lockstep(self):
        bridge = self.model.find("plugin[@name='mavlink_interface']")
        for tag, expected in [('hil_mode', '1'), ('hil_state_level', '0'),
                              ('enable_lockstep', '0'), ('serialEnabled', '1'), ('use_tcp', '0')]:
            self.assertEqual(bridge.findtext(tag), expected)
        self.assertTrue(bridge.findtext('serialDevice').startswith('/dev/'))
        channels = bridge.findall('control_channels/channel')
        self.assertEqual([c.findtext('input_index') for c in channels], ['0', '1', '2', '3'])
        for channel in channels:
            self.assertEqual(float(channel.findtext('input_scaling')) + float(channel.findtext('zero_position_armed')), 1000)

    def test_imu_uses_explicit_x500_noise_instead_of_binary_defaults(self):
        import math
        source = self.original.find("link[@name='base_link']/sensor[@type='imu']")
        rate = float(source.findtext('update_rate'))
        imu = self.model.find("plugin[@filename='libgazebo_imu_plugin.so']")
        gyro_std = max(float(e.text) for e in source.findall('imu/angular_velocity/*/noise/stddev'))
        self.assertAlmostEqual(float(imu.findtext('gyroscopeNoiseDensity'))*math.sqrt(rate), gyro_std)
        self.assertEqual(imu.findtext('gyroscopeTurnOnBiasSigma'), '0')
        self.assertEqual(imu.findtext('accelerometerTurnOnBiasSigma'), '0')

    def test_no_iris_geometry_dependencies_or_gz_system_plugins(self):
        for uri in self.model.findall('.//uri'):
            self.assertNotIn('model://iris', uri.text or '')
        for plugin in self.model.findall('.//plugin'):
            self.assertNotIn('gz-sim-', plugin.get('filename'))
        self.assertEqual(len(self.model.findall("plugin[@filename='libgazebo_imu_plugin.so']")), 1)

    def test_all_resources_and_physical_values_are_valid(self):
        self.assertEqual(model_errors(HERE / 'generated'), [])

    def test_world_has_correct_physics_and_offline_ground(self):
        world = E.parse(HERE / 'generated/x500_hitl.world').getroot().find('world')
        self.assertEqual(world.findtext('gravity'), '0 0 -9.8066')
        self.assertEqual(float(world.findtext('physics/max_step_size')), 0.004)
        self.assertEqual(float(world.findtext('physics/real_time_update_rate')), 250)
        self.assertIsNone(world.find('physics/gravity'))
        self.assertEqual([n.findtext('uri') for n in world.findall('include')], ['model://x500_hitl'])
        self.assertIsNotNone(world.find("model[@name='ground_plane']/link/collision/geometry/plane"))
        self.assertIsNotNone(world.find("light[@name='sun']"))

    def test_world_regeneration_is_idempotent_and_replaces_remote_models(self):
        world = E.ElementTree(E.fromstring('''<sdf version="1.5"><world name="test">
          <include><uri>model://sun</uri></include>
          <include><uri>model://ground_plane</uri></include>
          <include><uri>model://asphalt_plane</uri></include>
          <include><uri>model://iris_hitl</uri></include>
          <physics><gravity>0 0 -9.8066</gravity><magnetic_field>1 2 3</magnetic_field></physics>
          </world></sdf>'''))
        make_world_self_contained(world)
        once = E.tostring(world.getroot())
        make_world_self_contained(world)
        self.assertEqual(once, E.tostring(world.getroot()))
        self.assertEqual(world.findtext('world/include/uri'), 'model://x500_hitl')
        self.assertEqual(world.findtext('world/gravity'), '0 0 -9.8066')

    def test_missing_mesh_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp) / 'generated'
            shutil.copytree(HERE / 'generated', bundle)
            (bundle / 'models/x500_base/meshes/NXP-HGD-CF.dae').unlink()
            self.assertTrue(any('Missing model asset' in e for e in model_errors(bundle)))

    def test_invalid_inertia_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp) / 'generated'
            shutil.copytree(HERE / 'generated', bundle)
            path = bundle / 'models/x500_hitl/model.sdf'
            tree = E.parse(path)
            tree.find('model/link/inertial/inertia/ixx').text = '-1'
            tree.write(path)
            self.assertIn('Non-positive mass or inertia matrix', model_errors(bundle))

    def test_missing_tools_do_not_masquerade_as_a_flight_test(self):
        from unittest.mock import patch
        with patch('check_setup.shutil.which', return_value=None):
            report = inspect_setup(Path('/nonexistent-px4-check-only'))
        self.assertTrue(report['static_ok'])
        self.assertFalse(report['runtime_ok'])
        self.assertFalse(report['device_checked'])
        self.assertFalse(report['flight_verified'])
        self.assertTrue(any('Missing executable' in e for e in report['runtime_errors']))

    def test_bad_plugin_is_reported_without_crashing_environment_check(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp) / 'generated'
            shutil.copytree(HERE / 'generated', bundle)
            p = bundle / 'models/x500_hitl/model.sdf'
            tree = E.parse(p)
            tree.find('model/plugin').attrib.pop('filename')
            tree.write(p)
            with patch('check_setup.shutil.which', return_value=None):
                report = inspect_setup(Path(tmp), generated=bundle)
        self.assertFalse(report['runtime_ok'])
        self.assertTrue(any('no filename' in e for e in report['runtime_errors']))
        self.assertFalse(report['static_ok'])


if __name__ == '__main__':
    unittest.main()
