"""Service split tests; no MAVSDK connection or flight actuation."""
import ast
import json
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'pi'))

from control.config_manager import RuntimeConfig
from control.protocol import parse_incoming, parse_legacy_web, parse_v2
from control.command_router import ControlRouter
from control.service import RecentCommandIds
from flight.commands import FlightCommandRouter
from ipc.client import RpcClient
from ipc.server import RpcServer
from ipc.messages import encode, receive_line
from observability.event_log import EventLog
from observability.metrics import HostMetrics


LEGACY = ('c:spd:0.5;c:height:3;c:startlat:47.3977760;'
          'c:startlong:8.5456050;c:endlat:47.3978100;'
          'c:endlong:8.5456500;')
PI_ROOT = Path(__file__).resolve().parents[1] / 'pi'
SYSTEMD_ROOT = Path(__file__).resolve().parents[1] / 'systemd'


class LayoutBoundaryTests(unittest.TestCase):
    def _imports(self, path):
        tree = ast.parse(path.read_text(), filename=str(path))
        names = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module)
        return names

    def test_required_two_service_layout_exists(self):
        expected = {
            'console.py', 'control/service.py', 'control/mqtt_client.py',
            'control/protocol.py', 'control/command_router.py',
            'control/config_manager.py', 'flight/service.py',
            'flight/commands.py', 'flight/pixhawk.py',
            'flight/offboard_control.py', 'flight/gps_mission.py',
            'ipc/client.py', 'ipc/server.py', 'ipc/messages.py',
            'observability/event_log.py', 'observability/metrics.py',
            'observability/export_logs.py',
            'config/defaults.json', 'config/schema.json',
        }
        missing = sorted(item for item in expected if not (PI_ROOT / item).is_file())
        self.assertEqual(missing, [])

    def test_control_never_imports_flight_or_mavsdk(self):
        imports = {name for path in (PI_ROOT / 'control').glob('*.py')
                   for name in self._imports(path)}
        self.assertFalse(any(name == 'flight' or name.startswith('flight.')
                             or name == 'mavsdk' or name.startswith('mavsdk.')
                             for name in imports), imports)

    def test_flight_never_imports_control_or_mqtt(self):
        imports = {name for path in (PI_ROOT / 'flight').glob('*.py')
                   for name in self._imports(path)}
        self.assertFalse(any(name == 'control' or name.startswith('control.')
                             or name == 'paho' or name.startswith('paho.')
                             for name in imports), imports)

    def test_engineering_console_does_not_open_mqtt(self):
        imports = self._imports(PI_ROOT / 'console.py')
        self.assertFalse(any(name == 'paho' or name.startswith('paho.')
                             or name.startswith('control.') for name in imports), imports)

    def test_only_two_system_services_use_current_entry_points(self):
        units = sorted(path.name for path in SYSTEMD_ROOT.glob('*.service'))
        self.assertEqual(units, ['uav-control.service', 'uav-flight.service'])
        control = (SYSTEMD_ROOT / 'uav-control.service').read_text()
        flight = (SYSTEMD_ROOT / 'uav-flight.service').read_text()
        self.assertIn('pi/control/service.py', control)
        self.assertIn('--flight-socket /run/uav/flight.sock', control)
        self.assertIn('pi/flight/service.py', flight)
        self.assertIn('--socket /run/uav/flight.sock', flight)
        self.assertNotIn('--enable-actuation', flight)


class ProtocolTests(unittest.TestCase):
    def test_legacy_web_button_becomes_one_atomic_gps_start(self):
        command = parse_legacy_web(LEGACY)
        self.assertEqual(command['type'], 'gps_start')
        self.assertEqual(command['params']['a']['lat_deg'], 47.397776)
        self.assertEqual(command['params']['b']['lon_deg'], 8.54565)
        self.assertEqual(command['params']['height_above_launch_m'], 3.0)

    def test_v2_requires_ids_and_rejects_expired_command(self):
        now = datetime.now(timezone.utc)
        command = {'schema': 2, 'command_id': 'cmd-1', 'mission_id': 'mission-1',
                   'issued_at_utc': (now - timedelta(seconds=2)).isoformat(),
                   'expires_at_utc': (now + timedelta(seconds=8)).isoformat(),
                   'type': 'land', 'params': {}}
        self.assertEqual(parse_v2(json.dumps(command), now=now)['type'], 'land')
        command['expires_at_utc'] = (now - timedelta(seconds=1)).isoformat()
        with self.assertRaisesRegex(ValueError, 'expired'):
            parse_v2(json.dumps(command), now=now)

    def test_v2_rejects_null_ids_and_legacy_requires_explicit_opt_in(self):
        now = datetime.now(timezone.utc)
        command = {'schema': 2, 'command_id': None, 'mission_id': 'm1',
                   'issued_at_utc': now.isoformat(),
                   'expires_at_utc': (now + timedelta(seconds=5)).isoformat(),
                   'type': 'land', 'params': {}}
        with self.assertRaisesRegex(ValueError, 'command_id'):
            parse_v2(json.dumps(command), now=now)
        with self.assertRaisesRegex(ValueError, 'disabled'):
            parse_incoming('legacy', LEGACY.encode())
        self.assertEqual(parse_incoming('legacy', LEGACY.encode(), True)['type'],
                         'gps_start')

    def test_recent_command_ids_are_bounded_and_reject_duplicates(self):
        recent = RecentCommandIds(capacity=2)
        self.assertTrue(recent.add_if_new('a'))
        self.assertFalse(recent.add_if_new('a'))
        self.assertTrue(recent.add_if_new('b'))
        self.assertTrue(recent.add_if_new('c'))
        self.assertTrue(recent.add_if_new('a'))


class IpcTests(unittest.TestCase):
    def test_json_line_transport_round_trip(self):
        class Connection:
            def __init__(self, chunks):
                self.chunks = iter(chunks)

            def recv(self, _):
                return next(self.chunks, b'')

        encoded = encode({'op': 'status'})
        self.assertEqual(receive_line(Connection([encoded[:3], encoded[3:]])),
                         {'op': 'status'})

    def test_unix_socket_round_trip_and_single_owner(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'flight.sock'
            with RpcServer(path, lambda request: {'ok': True, 'op': request['op']}) as server:
                with self.assertRaisesRegex(RuntimeError, 'Another flight service'):
                    RpcServer(path, lambda _: {})
                worker = threading.Thread(target=lambda: (server.poll(2), server.poll(2)))
                worker.start()
                response = RpcClient(path).request({'op': 'status'})
                worker.join(timeout=2)
                self.assertFalse(worker.is_alive())
            self.assertEqual(response, {'ok': True, 'op': 'status'})
            self.assertFalse(path.exists())


class FlightRouterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.events = EventLog(self.temporary.name, 'flight-test')
        self.addCleanup(self.events.close)
        self.controller = Mock()
        self.controller.status.return_value = {'phase': 'GPS_STARTING'}
        self.router = FlightCommandRouter(self.controller, self.events)

    def test_web_gps_start_plans_then_starts(self):
        self.controller.gps_plan.return_value = {'leg_m': 5.0}
        command = parse_legacy_web(LEGACY)
        result = self.router.handle({'op': 'command', 'command': command})
        self.assertTrue(result['ok'])
        self.controller.gps_plan.assert_called_once_with(
            47.397776, 8.545605, 47.39781, 8.54565, 3.0, 0.5)
        self.controller.gps_start.assert_called_once_with()

    def test_local_xy_fly_is_not_exposed_to_web(self):
        with self.assertRaisesRegex(ValueError, 'Unsupported web flight'):
            self.router.handle({'op': 'command', 'command': {
                'type': 'fly', 'command_id': 'x', 'mission_id': 'm', 'params': {}}})
        self.controller.fly.assert_not_called()

    def test_remote_disarm_requires_explicit_force_confirmation(self):
        command = {'type': 'disarm', 'command_id': 'x', 'mission_id': 'm', 'params': {}}
        with self.assertRaisesRegex(ValueError, 'confirm_force'):
            self.router.handle({'op': 'command', 'command': command})
        self.controller.disarm.assert_not_called()

    def test_flight_debug_set_is_local_ipc_not_flight_actuation(self):
        response = self.router.handle({'op': 'debug_set', 'params': {
            'module': 'flight', 'level': 'DEBUG', 'duration_s': 5}})
        self.assertTrue(response['ok'])
        self.controller.gps_start.assert_not_called()

    def test_land_remains_accepted_when_followup_status_fails(self):
        self.controller.status.side_effect = RuntimeError('telemetry temporarily unavailable')
        result = self.router.handle({'op': 'command', 'command': {
            'type': 'land', 'command_id': 'land-1', 'mission_id': 'm', 'params': {}}})
        self.assertTrue(result['ok'])
        self.assertIsNone(result['status'])
        self.controller.land.assert_called_once_with()


class ControlRouterTests(unittest.TestCase):
    def test_legacy_web_payload_crosses_ipc_to_gps_controller(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            controller = Mock()
            controller.gps_plan.return_value = {'leg_m': 5.0}
            controller.status.return_value = {'phase': 'GPS_STARTING'}
            with EventLog(root, 'flight-test') as flight_log, \
                    EventLog(root, 'control-test') as control_log:
                flight_router = FlightCommandRouter(controller, flight_log)
                socket_path = root / 'flight.sock'
                with RpcServer(socket_path, flight_router.handle) as server:
                    worker = threading.Thread(target=server.poll, kwargs={'timeout': 2})
                    worker.start()
                    control_router = ControlRouter(RpcClient(socket_path),
                                                   RuntimeConfig(root / 'config.json'),
                                                   Mock(), control_log)
                    result = control_router.dispatch(parse_legacy_web(LEGACY))
                    worker.join(timeout=2)
                self.assertTrue(result['ok'])
                self.assertFalse(worker.is_alive())
                controller.gps_plan.assert_called_once()
                controller.gps_start.assert_called_once()

    def test_flight_command_is_forwarded_and_control_queries_stay_local(self):
        with tempfile.TemporaryDirectory() as temporary:
            flight, metrics = Mock(), Mock()
            flight.request.return_value = {'ok': True}
            metrics.snapshot.return_value = {'cpu_percent': 1}
            with EventLog(temporary, 'control-test') as events:
                router = ControlRouter(flight, RuntimeConfig(Path(temporary) / 'config.json'),
                                       metrics, events)
                command = parse_legacy_web(LEGACY)
                self.assertTrue(router.dispatch(command)['ok'])
                flight.request.assert_called_once()
                health = dict(command, type='health_get')
                self.assertEqual(router.dispatch(health)['health']['cpu_percent'], 1)
                flight.request.assert_called_once()

    def test_invalid_config_does_not_change_runtime_values(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = RuntimeConfig(Path(temporary) / 'config.json')
            before = json.loads(json.dumps(config.values))
            with self.assertRaisesRegex(ValueError, 'health_interval_s'):
                config.update({'state_interval_s': 2, 'health_interval_s': float('nan')})
            self.assertEqual(config.values, before)
            self.assertFalse(config.path.exists())

    def test_debug_command_uses_level_and_supports_health_module(self):
        with tempfile.TemporaryDirectory() as temporary:
            flight, metrics = Mock(), Mock()
            with EventLog(temporary, 'control-test') as events:
                router = ControlRouter(flight,
                                       RuntimeConfig(Path(temporary) / 'config.json'),
                                       metrics, events)
                command = {'type': 'debug_set', 'command_id': 'debug-1',
                           'params': {'module': 'health', 'level': 'DEBUG',
                                      'duration_s': 30}}
                response = router.dispatch(command)
                self.assertEqual(response['debug']['level'], 'DEBUG')
                with self.assertRaisesRegex(ValueError, 'level'):
                    router.dispatch(dict(command, params={
                        'module': 'health', 'enabled': True}))


class ObservabilityTests(unittest.TestCase):
    def test_event_log_is_jsonl_and_host_metrics_have_required_columns(self):
        with tempfile.TemporaryDirectory() as temporary:
            with EventLog(temporary, 'test') as events:
                path = events.path
                events.write('TEST', 'hello', command_id='c1')
            record = json.loads(path.read_text().splitlines()[0])
            self.assertEqual(record['event'], 'TEST')
            self.assertIn('boot_id', record)
            metrics = HostMetrics().snapshot(temporary)
            self.assertIn('cpu_percent', metrics)
            self.assertIn('memory', metrics)
            self.assertIn('swap_used_bytes', metrics['memory'])
            self.assertIn('disk', metrics)
            self.assertIn('used_bytes', metrics['disk'])
            self.assertIn('boot_id', metrics)
            self.assertIn('temperature_c', metrics)

    def test_debug_expires_without_disabling_important_events(self):
        with tempfile.TemporaryDirectory() as temporary:
            with EventLog(temporary, 'debug-test') as events:
                with patch('observability.event_log.time.monotonic', return_value=100):
                    events.set_debug('mqtt', True, 2)
                    self.assertIsNotNone(events.debug('mqtt', 'PACKET', 'accepted'))
                with patch('observability.event_log.time.monotonic', return_value=103):
                    self.assertIsNone(events.debug('mqtt', 'PACKET', 'expired'))
                    events.write('LAND_REQUESTED', 'land remains logged')
                records = [json.loads(line) for line in events.path.read_text().splitlines()]
                self.assertIn('LAND_REQUESTED', [item['event'] for item in records])


if __name__ == '__main__':
    unittest.main()
