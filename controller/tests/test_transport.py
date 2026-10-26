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
from serial_lock import udp_ownership


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
    sdk.configuration_factory = module.Configuration.create_with_component_type
    module.ComponentType = SimpleNamespace(COMPANION_COMPUTER='COMPANION', GROUND_STATION='GCS')
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
    def test_serial_profiles_and_loopback_hitl_connections(self):
        for profile in ('hardware', 'hitl'):
            self.assertEqual(validate_connection(profile, 'serial:///dev/ttyAMA0:921600'), '/dev/ttyAMA0')
        for profile, uri in [('sitl', 'udpin://127.0.0.1:14540'),
                             ('unknown', 'serial:///dev/ttyAMA0:921600'),
                             ('hardware', 'serial:///dev/ttyAMA0:0'),
                             ('hardware', 'udpin://127.0.0.1:14540'),
                             ('hitl', 'udpin://0.0.0.0:14540'),
                             ('hitl', 'udpin://192.168.0.1:14540'),
                             ('hitl', 'udpin://127.0.0.1:0'),
                             ('hitl', 'udpin://127.0.0.1:65536')]:
            with self.subTest(profile=profile, uri=uri), self.assertRaises(ValueError):
                validate_connection(profile, uri)
        self.assertEqual(validate_connection('hitl', 'udpin://127.0.0.1:14540'),
                         'udpin://127.0.0.1:14540')

    def test_pc_hitl_constructor_still_checks_sys_hitl_without_actuation(self):
        with fake_sdk(hitl=1) as (sdk, plugins):
            fc = Pixhawk('udpin://127.0.0.1:14540', 'hitl')
        self.assertEqual(fc.hitl, 1)
        sdk.add_any_connection.assert_called_once_with('udpin://127.0.0.1:14540')
        sdk.configuration_factory.assert_called_once_with('GCS')
        plugins['action'].return_value.arm.assert_not_called()
        plugins['param'].return_value.set_param_int.assert_not_called()

    def test_pc_hitl_rejects_hardware_board_and_releases_sdk(self):
        with fake_sdk(hitl=0) as (sdk, plugins):
            with self.assertRaisesRegex(RuntimeError, 'does not match'):
                Pixhawk('udpin://127.0.0.1:14540', 'hitl')
        sdk.destroy.assert_called_once()
        plugins['action'].return_value.arm.assert_not_called()

    def test_hardware_udp_is_rejected_before_opening_sdk(self):
        with fake_sdk() as (sdk, plugins):
            with self.assertRaises(ValueError):
                Pixhawk('udpin://127.0.0.1:14540', 'hardware')
        sdk.add_any_connection.assert_not_called()

    def test_two_consoles_cannot_own_same_udp_endpoint(self):
        endpoint = 'udpin://127.0.0.1:14540'
        with udp_ownership(endpoint):
            with self.assertRaisesRegex(RuntimeError, 'Another controller'):
                with udp_ownership(endpoint):
                    self.fail('Second controller acquired the port lock')
        with udp_ownership(endpoint):
            pass

    def test_constructor_only_reads_and_subscribes_without_mission_or_arm(self):
        with fake_sdk() as (sdk, plugins):
            fc = Pixhawk('serial:///dev/fake:921600', 'hardware')
        sdk.configuration_factory.assert_called_once_with('COMPANION')
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
