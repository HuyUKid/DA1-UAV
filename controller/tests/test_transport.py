from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'pi'))

from contextlib import contextmanager
import json
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from deployment import validate_connection
from pixhawk import Pixhawk


@contextmanager
def fake_sdk(hitl=0, connected=True):
    module = ModuleType('mavsdk')
    sdk, drone = Mock(), Mock()
    sdk.first_autopilot.return_value = drone if connected else None
    drone.get_system_id.return_value = 1
    drone.is_connected.return_value = True
    drone.autopilot_type.return_value = 'PX4'
    drone.vehicle_type.return_value = 'MULTICOPTER'
    module.Mavsdk = Mock(return_value=sdk)
    module.Configuration = Mock()
    module.ComponentType = SimpleNamespace(COMPANION_COMPUTER='COMPANION')
    module.Autopilot = SimpleNamespace(PX4='PX4')
    module.Vehicle = SimpleNamespace(MULTICOPTER='MULTICOPTER')
    modules = {'mavsdk': module}
    factories = {}
    for name, cls in (('action', 'Action'), ('telemetry', 'Telemetry'), ('param', 'Param')):
        plugin = ModuleType(f'mavsdk.plugins.{name}')
        factories[name] = Mock()
        setattr(plugin, cls, factories[name])
        modules[plugin.__name__] = plugin
    factories['param'].return_value.get_param_int.return_value = hitl
    with patch.dict(sys.modules, modules):
        yield sdk, factories


class TransportTests(unittest.TestCase):
    def test_only_current_profiles_and_serial_connections_are_allowed(self):
        for profile in ('hardware', 'hitl'):
            self.assertEqual(validate_connection(profile, 'serial:///dev/ttyAMA0:921600'), '/dev/ttyAMA0')
        for profile, uri in [('sitl', 'udpin://127.0.0.1:14540'),
                             ('unknown', 'serial:///dev/ttyAMA0:921600'),
                             ('hardware', 'serial:///dev/ttyAMA0:0'),
                             ('hitl', 'udpin://127.0.0.1:14540')]:
            with self.subTest(profile=profile, uri=uri), self.assertRaises(ValueError):
                validate_connection(profile, uri)

    def test_constructor_only_reads_and_subscribes_without_mission_or_arm(self):
        with fake_sdk() as (sdk, plugins):
            fc = Pixhawk('serial:///dev/fake:921600', 'hardware')
        self.assertEqual(fc.profile, 'hardware')
        self.assertEqual(fc.phase, 'IDLE')
        plugins['action'].return_value.arm.assert_not_called()
        plugins['param'].return_value.get_param_int.assert_called_once_with('SYS_HITL')
        self.assertFalse(hasattr(Pixhawk, 'point_command'))
        self.assertFalse(hasattr(Pixhawk, 'command'))
        self.assertFalse(hasattr(Pixhawk, 'upload'))
        sdk.destroy.assert_not_called()

    def test_connection_timeout_releases_sdk_without_actuation(self):
        with fake_sdk(connected=False) as (sdk, plugins):
            with self.assertRaisesRegex(RuntimeError, 'heartbeat'):
                Pixhawk('serial:///dev/fake:921600', 'hardware')
        sdk.destroy.assert_called_once()
        plugins['action'].assert_not_called()

    def test_profile_mismatch_releases_sdk_without_arm(self):
        with fake_sdk(hitl=1) as (sdk, plugins):
            with self.assertRaisesRegex(RuntimeError, 'does not match'):
                Pixhawk('serial:///dev/fake:921600', 'hardware')
        sdk.destroy.assert_called_once()
        plugins['action'].return_value.arm.assert_not_called()

    def test_subscription_failure_releases_sdk(self):
        with fake_sdk() as (sdk, plugins):
            plugins['telemetry'].return_value.subscribe_armed.side_effect = RuntimeError('subscription error')
            with self.assertRaisesRegex(RuntimeError, 'subscription error'):
                Pixhawk('serial:///dev/fake:921600', 'hardware')
        sdk.destroy.assert_called_once()

    def test_bad_telemetry_remains_invalid_but_status_is_valid_json(self):
        with fake_sdk() as (_, _plugins):
            fc = Pixhawk('serial:///dev/fake:921600', 'hardware')
        fc.cache['position'] = ({'relative_altitude_m': float('nan')}, 0)
        data = fc.status()
        self.assertIsNone(data['telemetry']['position']['value']['relative_altitude_m'])
        self.assertEqual(data['invalid_telemetry_fields'], ['position'])
        json.dumps(data, allow_nan=False)
        self.assertNotEqual(fc.cache['position'][0]['relative_altitude_m'], None)


if __name__ == '__main__':
    unittest.main()
