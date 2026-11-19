"""Read-only diagnostics must describe observations without issuing flight commands."""
import io
import json
from collections import deque
from contextlib import redirect_stdout
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from types import ModuleType
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'pi'))
from observability.display import format_status, format_response
from observability.event_log import EventLog
from observability.flight_log import FlightTimeline, NativeSdkLog
from flight.client import build_request, main as client_main
import test_gps_mission as gps_fixture
from test_transport import fake_sdk
from flight.pixhawk import Pixhawk


class DisplayTests(unittest.TestCase):
    def test_battery_30_and_15_warnings_then_7_critical_never_issue_pi_land(self):
        with tempfile.TemporaryDirectory() as directory:
            with EventLog(directory, 'flight') as log:
                timeline = FlightTimeline(log)
                controller = Mock()
                controller.drain_observed_events.return_value = []
                status = {'phase': 'GPS_RUNNING', 'connected': True,
                          'battery_failsafe': {'BAT_LOW_THR': 0.30, 'BAT_CRIT_THR': 0.07,
                                               'BAT_EMERGEN_THR': 0.05, 'COM_LOW_BAT_ACT': 2},
                          'telemetry': {'battery': {'value': {}, 'age_s': 0.1}}}
                for percent in (31, 30, 15, 7, 5):
                    status['telemetry']['battery']['value']['remaining_percent'] = percent
                    timeline.update(controller, status)
                records = [json.loads(line) for line in log.path.read_text().splitlines()]
                self.assertEqual([r['battery_state'] for r in records if r['event'] == 'BATTERY_STATE'],
                                 ['NORMAL', 'LOW', 'RESERVE_LOW', 'CRITICAL', 'EMERGENCY'])
                controller.land.assert_not_called()
                controller.disarm.assert_not_called()
    def test_native_sdk_log_capture_preserves_raw_text_and_unsubscribes(self):
        module = ModuleType('mavsdk.logging')
        module.log_subscribe, module.log_unsubscribe = Mock(), Mock()
        events = Mock()
        with patch.dict(sys.modules, {'mavsdk.logging': module}):
            with NativeSdkLog(events):
                callback = module.log_subscribe.call_args.args[0]
                self.assertTrue(callback(SimpleNamespace(name='WARN'), 'raw PX4 warning', 'source.cpp', 12))
        events.write.assert_called_once_with('MAVSDK_MESSAGE', 'raw PX4 warning',
                                             severity='WARNING', source_file='source.cpp', source_line=12)
        module.log_unsubscribe.assert_called_once()
    def test_status_keeps_ned_position_and_signed_altitudes(self):
        status = {'height_above_launch_m': 2.0, 'telemetry': {
            'local_ned': {'value': {'north_m': 5.0, 'east_m': 4.0, 'down_m': -2.0}, 'age_s': 0.2},
            'position': {'value': {'latitude_deg': 21.005, 'longitude_deg': 105.84,
                                   'relative_altitude_m': -19.4}, 'age_s': 0.1}}}
        rendered = format_status(status)
        for text in ('NED (m)', 'POSITION', 'lat=21.0050000', 'home_m=-19.40', 'launch_m=2.00'):
            self.assertIn(text, rendered)
        self.assertIn('N/A', rendered)
        self.assertEqual(build_request('status --json'), {'op': 'status'})
        raw = format_response({'ok': True, 'status': status}, 'status', raw=True)
        self.assertEqual(json.loads(raw)['status'], status)

    def test_one_shot_status_json_flag_preserves_full_response(self):
        with patch('flight.client.RpcClient') as client, patch('builtins.print') as output:
            client.return_value.request.return_value = {'ok': True, 'status': {'phase': 'HOLD'}}
            self.assertEqual(client_main(['status', '--json']), 0)
            self.assertEqual(json.loads(output.call_args.args[0])['status']['phase'], 'HOLD')

    def test_terminal_events_and_file_snapshot_are_separate(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()) as stdout:
            with EventLog(directory, 'flight', terminal=True) as log:
                path = log.path
                log.write('ARM_CONFIRMED', 'ARM confirmed')
                log.write('FLIGHT_SNAPSHOT', 'Details', record_type='snapshot', status={'phase': 'ARMED'})
                log.write('MAVSDK_MESSAGE', 'raw debug', severity='DEBUG')
            self.assertIn('ARM_CONFIRMED', stdout.getvalue())
            self.assertNotIn('FLIGHT_SNAPSHOT', stdout.getvalue())
            self.assertEqual(len(path.read_text().splitlines()), 3)

    def test_timeline_logs_error_changes_and_fresh_battery_levels_without_actuation(self):
        with tempfile.TemporaryDirectory() as directory:
            with EventLog(directory, 'flight') as log:
                timeline = FlightTimeline(log)
                controller = Mock()
                controller.drain_observed_events.return_value = []
                status = {'phase': 'GPS_RUNNING', 'connected': True,
                          'battery_failsafe': {'BAT_LOW_THR': 0.3, 'BAT_CRIT_THR': 0.2, 'BAT_EMERGEN_THR': 0.15},
                          'telemetry': {'battery': {'value': {'remaining_percent': 25}, 'age_s': 0.1}}}
                timeline.update(controller, status)
                timeline.update(controller, status)
                status['last_error'] = 'Connection lost'
                status['telemetry']['battery']['age_s'] = 10
                timeline.update(controller, status)
                records = [json.loads(line) for line in log.path.read_text().splitlines()]
                battery = [r['battery_state'] for r in records if r['event'] == 'BATTERY_STATE']
                self.assertEqual(battery, ['LOW', 'UNKNOWN'])
                self.assertEqual(len([r for r in records if r['event'] == 'FLIGHT_STATE_CHANGED']), 2)
                controller.land.assert_not_called()
                controller.disarm.assert_not_called()

    def test_battery_subscription_units_and_no_parameter_writes(self):
        with fake_sdk() as (_, plugins):
            fc = Pixhawk('serial:///dev/fake:921600', 'hardware')
            callback = plugins['telemetry'].return_value.subscribe_battery.call_args.args[0]
            callback(SimpleNamespace(id=0, remaining_percent=0.25, voltage_v=23.4,
                                     current_battery_a=5.0, temperature_degc=float('nan')))
            self.assertEqual(fc.status()['telemetry']['battery']['value']['remaining_percent'], 25.0)
            callback(SimpleNamespace(id=0, remaining_percent=-1, voltage_v=23.4,
                                     current_battery_a=5.0, temperature_degc=30.0))
            self.assertIsNone(fc.status()['telemetry']['battery']['value']['remaining_percent'])
            plugins['param'].return_value.set_param_int.assert_not_called()
            plugins['param'].return_value.set_param_float.assert_not_called()


class WaypointObservationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = gps_fixture.GpsMissionTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fc = self.fixture.fc
        self.fc.observed_events = deque(maxlen=2048)
        self.fc.observed_events_dropped = 0
        self.fc.mavlink_direct = Mock()
        self.fc.drone.get_system_id.return_value = 1
        self.fixture.running()

    def test_target_progress_is_not_reported_as_reached(self):
        progress = self.fc.mission.subscribe_mission_progress.call_args.args[0]
        self.fc.drain_observed_events()
        progress(SimpleNamespace(current=0, total=3))
        progress(SimpleNamespace(current=1, total=3))
        progress(SimpleNamespace(current=1, total=3))
        events = self.fc.drain_observed_events()
        self.assertEqual([e['event'] for e in events], ['WAYPOINT_TARGET_CHANGED'])
        self.assertEqual(events[0]['target_label'], 'A')
        self.assertEqual(self.fc.status()['gps_mission']['progress']['target_label'], 'A')

    def test_reached_filters_source_duplicates_and_obsolete_generation(self):
        callback = self.fc.mavlink_direct.subscribe_message.call_args.args[1]
        self.fc.drain_observed_events()
        callback(SimpleNamespace(system_id=99, component_id=1, fields_json='{"seq":1}'))
        callback(SimpleNamespace(system_id=1, component_id=1, fields_json='{"seq":0}'))
        message = SimpleNamespace(system_id=1, component_id=1, fields_json='{"seq":1}')
        callback(message)
        callback(message)
        events = self.fc.drain_observed_events()
        self.assertEqual([e['event'] for e in events], ['WAYPOINT_REACHED'])
        self.fc._stop_mission_observation()
        callback(SimpleNamespace(system_id=1, component_id=1, fields_json='{"seq":2}'))
        self.assertEqual(self.fc.drain_observed_events(), [])

    def test_observer_cleanup_failure_cannot_block_land(self):
        self.fc.mission.unsubscribe_mission_progress.side_effect = RuntimeError('cleanup failed')
        self.fc.land()
        self.fc.action.land.assert_called_once()
        self.assertEqual(self.fc.phase, 'LANDING')
