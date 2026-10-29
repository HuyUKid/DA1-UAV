"""State and command tests with mocks; no MAVLink connection is opened."""
import math
import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'pi'))
from flight.flight_policy import ArrivalMonitor, FlightPolicy
from flight.gps_mission import GpsMissionControl, GpsLimits, distance_m
from console import execute


class GpsMissionTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        clock = patch('time.monotonic', side_effect=lambda: self.now)
        clock.start()
        self.addCleanup(clock.stop)
        sleep = patch('flight.offboard_control.time.sleep', side_effect=self.advance)
        sleep.start()
        self.addCleanup(sleep.stop)
        fc = GpsMissionControl.__new__(GpsMissionControl)
        self.fc = fc
        fc.enabled, fc.hitl, fc.height, fc.profile = True, 0, 2.0, 'hardware'
        fc.lock = threading.Lock()
        fc.phase, fc.operation_at = 'IDLE', 0.0
        fc.policy = FlightPolicy(settle_s=0.6, target_timeout_s=10)
        fc.arrival = ArrivalMonitor(fc.policy)
        fc.nav_min_ltr_alt = -1.0
        fc.gps_limits = GpsLimits()
        fc.gps_plan_data = None
        fc.gps_epoch = fc.gps_hold_seen_at = fc.gps_finish_hold_requested_at = None
        fc.gps_mission_stored = False
        fc.gps_cancel_position = None
        fc.gps_launch_pending = False
        fc.gps_deploying = False
        fc.launch_gps = None
        fc.home_return_target = None
        fc.home_returning = False
        fc.home_epoch = None
        fc.home_started_at = None
        fc.px4_xy_vel_max = 0.5
        fc.mission = Mock()
        fc.MissionItem = Mock(side_effect=lambda **kw: SimpleNamespace(**kw))
        fc.MissionItem.CameraAction.NONE = 0
        fc.MissionItem.VehicleAction.NONE = 0
        fc.MissionPlan = lambda **kw: SimpleNamespace(**kw)
        fc.motor_stop_kind = None
        fc.paused_target = None
        fc.pause_operation_at = None
        fc.cancel_operation_at = None
        fc.cancel_confirmed = False
        for key in ('target', 'launch_ned', 'offboard', 'target_started_at',
                    'hold_operation_at', 'motion_kind', 'hold_reason', 'last_error',
                    'arm_operation_at', 'disarm_operation_at', 'land_request_context',
                    'mavlink_direct', 'direct_handle'):
            setattr(fc, key, None)
        for key in ('external', 'offboard_seen', 'termination', 'target_reached',
                    'takeoff_complete', 'arm_acknowledged', 'disarm_acknowledged',
                    'land_acknowledged', 'hold_acknowledged'):
            setattr(fc, key, False)
        fc.drone, fc.action, fc.sdk = Mock(), Mock(), Mock()
        fc.param = Mock()
        fc.param.get_param_float.return_value = 2.0
        fc.drone.is_connected.return_value = True
        fc.mission.is_mission_finished.return_value = False
        fc.make_offboard = Mock(return_value=Mock())
        fc.Position = lambda **kw: SimpleNamespace(**kw)
        fc.cache = {k: (v, self.now) for k, v in {
            'armed': False, 'landed_state': 'ON_GROUND', 'flight_mode': 'HOLD',
            'health_all_ok': True, 'yaw_deg': 37.0,
            'local_ned': dict(north_m=0.4, east_m=-0.7, down_m=5.231),
            'local_velocity': dict(north_m_s=0, east_m_s=0, down_m_s=0),
            'position': dict(latitude_deg=10.0, longitude_deg=106.0,
                             absolute_altitude_m=100.0, relative_altitude_m=0.0),
        }.items()}
        fc.action.arm.side_effect = lambda: self.put('armed', True)
        fc.action.land.side_effect = lambda: self.put('flight_mode', 'LAND')
        fc.action.hold.side_effect = lambda: self.put('flight_mode', 'HOLD')

        def offboard_start():
            self.put('armed', True)
            self.put('flight_mode', 'OFFBOARD')
            fc.record_mode('OFFBOARD')
        fc.make_offboard.return_value.start.side_effect = offboard_start

    def put(self, key, value):
        self.fc.cache[key] = (value, self.now)

    def advance(self, seconds):
        self.now += seconds
        self.fc.cache = {k: (v, self.now) for k, (v, _) in self.fc.cache.items()}

    def ready(self):
        self.fc.takeoff()
        self.finish_takeoff('HOLD')

    def finish_takeoff(self, expected, lat=10.0):
        self.put('landed_state', 'IN_AIR')
        self.put('local_ned', {k: self.fc.target[k] for k in
                                ('north_m', 'east_m', 'down_m')})
        self.put('yaw_deg', self.fc.target['yaw_deg'])
        self.put('position', dict(latitude_deg=lat, longitude_deg=106.0,
                                  absolute_altitude_m=102.0, relative_altitude_m=2.0))
        for _ in range(5):
            self.advance(0.2)
            self.fc.refresh()
        self.fc.refresh()
        self.assertEqual(self.fc.phase, expected)

    def plan(self):
        return self.fc.gps_plan(10.0, 106.00002, 10.0, 106.00005, 2.5, 0.4)

    def running(self):
        self.plan()
        self.fc.gps_start()
        self.finish_takeoff('GPS_STARTING')
        self.put('flight_mode', 'MISSION')
        self.fc.record_mode('MISSION')
        self.fc.refresh()
        self.assertEqual(self.fc.phase, 'GPS_RUNNING')

    def cancel_running(self):
        self.fc.gps_cancel()
        self.put('flight_mode', 'HOLD')
        self.fc.refresh()
        self.assertEqual(self.fc.phase, 'GPS_CANCELLED')
        self.advance(0.1)

    def test_mission_item_has_native_binding_fields(self):
        item = self.fc._mission_item(10.0, 106.0, 3.0, 0.5)
        for value in vars(item).values():
            self.assertIsNotNone(value)
        self.assertTrue(math.isnan(item.gimbal_pitch_deg))
        self.assertEqual(item.camera_action, 0)
        self.assertEqual(item.vehicle_action, 0)
        self.assertEqual(item.camera_photo_interval_s, 1.0)

    def test_plan_only_stages_and_rejects_bad_inputs(self):
        with self.assertRaises(ValueError):
            self.fc.gps_resume()
        plan = self.plan()
        self.assertAlmostEqual(plan['leg_m'], distance_m(10, 106.00002, 10, 106.00005))
        self.assertAlmostEqual(plan['approach_m'], distance_m(10, 106, 10, 106.00002))
        self.assertNotEqual(plan['start_lon'], plan['origin_lon'])
        self.fc.mission.upload_mission.assert_not_called()
        self.fc.action.arm.assert_not_called()
        with self.assertRaisesRegex(ValueError, 'distance limit'):
            self.fc.gps_plan(10, 106.001, 10, 106.00005, 2, 0.4)
        with self.assertRaisesRegex(ValueError, 'distance limit'):
            self.fc.gps_plan(10, 106.00002, 10, 106.01, 2, 0.4)
        for bad in (math.nan, math.inf, 15.0):
            with self.subTest(speed=bad), self.assertRaises(ValueError):
                self.fc.gps_plan(10, 106.00002, 10, 106.00005, 2, bad)

    def test_same_current_A_and_B_is_a_single_vertical_only_waypoint(self):
        plan = self.fc.gps_plan(10.0, 106.0, 10.0, 106.0, 2.5, 0.4)
        self.assertTrue(plan['vertical_only'])
        self.assertEqual(plan['approach_m'], 0.0)
        self.assertEqual(plan['leg_m'], 0.0)
        self.fc.gps_start()
        self.finish_takeoff('GPS_STARTING')
        uploaded = self.fc.mission.upload_mission.call_args.args[0].mission_items
        self.assertEqual(len(uploaded), 1)
        self.assertEqual(uploaded[0].latitude_deg, 10.0)
        self.assertEqual(uploaded[0].longitude_deg, 106.0)
        self.assertEqual(uploaded[0].relative_altitude_m, 2.5)

    def test_rounded_same_A_and_B_within_freshness_radius_pins_current_gps(self):
        plan = self.fc.gps_plan(10.0, 106.00003, 10.0, 106.00003, 2.5, 0.4)
        self.assertTrue(plan['vertical_only'])
        self.assertEqual(plan['start_lat'], 10.0)
        self.assertEqual(plan['start_lon'], 106.0)
        self.assertEqual(plan['end_lat'], 10.0)
        self.assertEqual(plan['end_lon'], 106.0)

    def test_same_A_and_B_far_from_vehicle_is_not_mistaken_for_vertical_only(self):
        with self.assertRaisesRegex(ValueError, 'distance limit'):
            self.fc.gps_plan(10.0, 106.001, 10.0, 106.001, 2.5, 0.4)

    def test_ground_A_is_rechecked_before_takeoff(self):
        self.plan()
        self.put('position', dict(latitude_deg=10.0001, longitude_deg=106.0,
                                  absolute_altitude_m=100.0, relative_altitude_m=0.0))
        with self.assertRaisesRegex(ValueError, 'plan origin'):
            self.fc.gps_start()
        self.fc.action.arm.assert_not_called()

    def test_A_drift_after_takeoff_never_starts_GPS_leg(self):
        self.plan()
        self.fc.gps_start()
        self.finish_takeoff('HOLD', lat=10.0001)
        self.assertIn('origin', self.fc.last_error)
        self.fc.mission.upload_mission.assert_not_called()

    def test_takeoff_timeout_never_starts_GPS_leg(self):
        self.plan()
        self.fc.gps_start()
        self.put('landed_state', 'IN_AIR')
        self.advance(10.1)
        self.fc.refresh()
        self.fc.refresh()
        self.assertEqual(self.fc.phase, 'HOLD')
        self.assertFalse(self.fc.gps_launch_pending)
        self.fc.mission.upload_mission.assert_not_called()

    def test_upload_uses_two_waypoints_and_holds_at_B_selected_height(self):
        self.plan()
        order = Mock()
        order.attach_mock(self.fc.mission.set_return_to_launch_after_mission, 'no_rtl')
        order.attach_mock(self.fc.mission.upload_mission, 'upload')
        order.attach_mock(self.fc.mission.start_mission, 'start')
        self.fc.gps_start()
        self.assertEqual(self.fc.phase, 'TAKEOFF')
        self.assertTrue(self.fc.gps_launch_pending)
        self.fc.mission.upload_mission.assert_not_called()
        self.finish_takeoff('GPS_STARTING')
        self.assertEqual([call[0] for call in order.mock_calls], ['no_rtl', 'upload', 'start'])
        items = self.fc.mission.upload_mission.call_args.args[0].mission_items
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].latitude_deg, 10.0)
        self.assertAlmostEqual(items[0].longitude_deg, 106.00002)
        self.assertEqual(items[1].longitude_deg, 106.00005)
        self.assertAlmostEqual(items[0].relative_altitude_m, 2.5)
        self.assertAlmostEqual(items[1].relative_altitude_m, 2.5)
        self.assertEqual(items[1].speed_m_s, 0.4)
        self.assertEqual(self.fc.phase, 'GPS_STARTING')
        self.fc.action.arm.assert_called_once()  # TAKEOFF only; Mission never arms again.

    def test_pause_resume_cancel_requires_mode_confirmation(self):
        self.running()
        self.fc.gps_pause()
        self.assertEqual(self.fc.phase, 'GPS_PAUSE_REQUESTED')
        with self.assertRaises(ValueError):
            self.fc.gps_resume()
        self.put('flight_mode', 'HOLD')
        self.fc.refresh()
        self.assertEqual(self.fc.phase, 'GPS_PAUSED')
        self.fc.gps_resume()
        self.assertEqual(self.fc.phase, 'GPS_RESUME_REQUESTED')
        self.put('flight_mode', 'MISSION')
        self.fc.refresh()
        self.assertEqual(self.fc.phase, 'GPS_RUNNING')
        self.fc.gps_cancel()
        self.assertEqual(self.fc.phase, 'GPS_CANCEL_REQUESTED')
        self.fc.mission.clear_mission.assert_not_called()
        self.put('flight_mode', 'HOLD')
        self.fc.refresh()
        self.assertEqual(self.fc.phase, 'GPS_CANCELLED')
        self.assertEqual(self.fc.mission.clear_mission.call_count, 1)
        self.assertEqual(self.fc.mission.upload_mission.call_count, 1)
        self.assertEqual(self.fc.gps_cancel_position['relative_altitude_m'], 2.0)
        self.fc.action.land.assert_not_called()
        self.fc.action.kill.assert_not_called()
        with self.assertRaises(ValueError):
            self.fc.gps_resume()

    def test_completion_requires_finished_flag_and_hold(self):
        self.running()
        self.fc.mission.is_mission_finished.return_value = False
        self.put('flight_mode', 'HOLD')
        self.fc.refresh()
        self.assertEqual(self.fc.phase, 'GPS_RUNNING')
        self.fc.mission.is_mission_finished.return_value = True
        self.put('local_ned', dict(north_m=0.4, east_m=-0.7, down_m=2.731))
        self.put('position', dict(latitude_deg=10.0, longitude_deg=106.00005,
                                  absolute_altitude_m=102.5, relative_altitude_m=2.5))
        self.fc.refresh()
        self.assertEqual(self.fc.phase, 'GPS_COMPLETE')

    def test_finished_does_not_claim_selected_height_when_estimator_disagrees(self):
        self.running()
        self.fc.mission.is_mission_finished.return_value = True
        self.put('flight_mode', 'HOLD')
        self.put('local_ned', dict(north_m=0.4, east_m=-0.7, down_m=1.231))
        self.put('position', dict(latitude_deg=10.0, longitude_deg=106.00005,
                                  absolute_altitude_m=104.0, relative_altitude_m=4.0))
        self.fc.refresh()
        self.assertEqual(self.fc.phase, 'GPS_UNCONFIRMED')
        self.assertIn('selected height', self.fc.last_error)

    def test_finished_does_not_claim_B_when_gps_position_is_far(self):
        self.running()
        self.fc.mission.is_mission_finished.return_value = True
        self.put('flight_mode', 'HOLD')
        self.put('local_ned', dict(north_m=0.4, east_m=-0.7, down_m=2.731))
        self.put('position', dict(latitude_deg=10.0, longitude_deg=106.0,
                                  absolute_altitude_m=102.5, relative_altitude_m=2.5))
        self.fc.refresh()
        self.assertEqual(self.fc.phase, 'GPS_UNCONFIRMED')
        self.assertIn('B position', self.fc.last_error)

    def test_pause_and_cancel_hold_current_altitude(self):
        self.running()
        # Simulate the UAV already at the selected 2.5 m cruise altitude.
        self.put('local_ned', dict(north_m=0.4, east_m=-0.7, down_m=2.731))
        self.put('position', dict(latitude_deg=10.0, longitude_deg=106.0,
                                  absolute_altitude_m=100.5, relative_altitude_m=2.5))
        self.fc.gps_pause()
        self.put('flight_mode', 'HOLD')
        self.fc.refresh()
        self.assertEqual(self.fc.phase, 'GPS_PAUSED')
        self.fc.mission.upload_mission.assert_called_once()  # No descent for Pause.
        self.fc.gps_cancel()
        self.assertEqual(self.fc.phase, 'GPS_CANCELLED')
        self.assertEqual(self.fc.mission.upload_mission.call_count, 1)
        self.assertAlmostEqual(self.fc.gps_cancel_position['relative_altitude_m'], 2.5)
        self.fc.make_offboard.assert_called_once()  # TAKEOFF only, no cancel descent.

    def test_cancel_updates_A_and_new_in_air_mission_uses_new_B_height_speed(self):
        self.running()
        self.put('position', dict(latitude_deg=10.0, longitude_deg=106.00003,
                                  absolute_altitude_m=102.5, relative_altitude_m=2.5))
        self.put('local_ned', dict(north_m=0.4, east_m=-0.7, down_m=2.731))
        self.fc.gps_cancel()
        self.put('flight_mode', 'HOLD')
        self.fc.refresh()
        self.assertEqual(self.fc.phase, 'GPS_CANCELLED')
        self.assertAlmostEqual(self.fc.gps_cancel_position['longitude_deg'], 106.00003)
        plan = self.fc.gps_plan(10.0, 106.00005, 10.0, 106.00007, 3.0, 0.3)
        self.assertAlmostEqual(plan['start_lon'], 106.00005)
        self.assertAlmostEqual(plan['origin_lon'], 106.00003)
        self.assertTrue(plan['start_in_air'])
        self.fc.gps_start()
        self.assertEqual(self.fc.phase, 'GPS_STARTING')
        self.assertEqual(self.fc.mission.upload_mission.call_count, 2)
        self.assertEqual(self.fc.mission.set_current_mission_item.call_count, 2)
        self.fc.mission.set_current_mission_item.assert_called_with(0)
        items = self.fc.mission.upload_mission.call_args.args[0].mission_items
        self.assertAlmostEqual(items[0].longitude_deg, 106.00005)
        self.assertAlmostEqual(items[1].longitude_deg, 106.00007)
        self.assertAlmostEqual(items[1].relative_altitude_m, 3.0)
        self.assertAlmostEqual(items[1].speed_m_s, 0.3)
        self.fc.action.arm.assert_called_once()  # Initial TAKEOFF only.

    def test_in_air_replacement_does_not_start_if_item_zero_is_denied(self):
        self.running()
        self.cancel_running()
        self.fc.gps_plan(10.0, 106.00002, 10.0, 106.00005, 2.5, 0.4)
        self.fc.mission.start_mission.reset_mock()
        self.fc.mission.set_current_mission_item.side_effect = RuntimeError('DENIED')
        with self.assertRaisesRegex(RuntimeError, 'DENIED'):
            self.fc.gps_start()
        self.assertEqual(self.fc.phase, 'GPS_UNCONFIRMED')
        self.assertIn('New GPS mission was not ready', self.fc.last_error)
        self.fc.mission.start_mission.assert_not_called()
        self.fc.action.land.assert_not_called()

    def test_cancel_waits_for_gps_sample_after_hold_before_clearing(self):
        self.running()
        self.fc.gps_cancel()
        self.advance(0.1)
        self.put('flight_mode', 'HOLD')
        self.fc.cache['position'] = (self.fc.cache['position'][0], self.now - 0.05)
        self.fc.refresh()
        self.assertEqual(self.fc.phase, 'GPS_CANCEL_REQUESTED')
        self.fc.mission.clear_mission.assert_not_called()
        self.put('position', dict(latitude_deg=10.0, longitude_deg=106.00002,
                                  absolute_altitude_m=102.0, relative_altitude_m=2.0))
        self.fc.refresh()
        self.assertEqual(self.fc.phase, 'GPS_CANCELLED')
        self.assertAlmostEqual(self.fc.gps_cancel_position['longitude_deg'], 106.00002)

    def test_cancel_clear_failure_blocks_replacement_plan(self):
        self.running()
        self.fc.mission.clear_mission.side_effect = RuntimeError('DENIED')
        self.fc.gps_cancel()
        self.put('flight_mode', 'HOLD')
        with self.assertRaises(RuntimeError):
            self.fc.refresh()
        self.assertEqual(self.fc.phase, 'GPS_UNCONFIRMED')
        with self.assertRaises(ValueError):
            self.fc.gps_plan(10.0, 106.00005, 10.0, 106.00007, 2.5, 0.3)

    def test_short_terminal_commands_follow_gps_state_machine(self):
        self.running()
        execute(self.fc, 'pause', output=lambda _: None)
        self.assertEqual(self.fc.phase, 'GPS_PAUSE_REQUESTED')
        self.put('flight_mode', 'HOLD')
        self.fc.refresh()
        execute(self.fc, 'resume', output=lambda _: None)
        self.assertEqual(self.fc.phase, 'GPS_RESUME_REQUESTED')
        self.put('flight_mode', 'MISSION')
        self.fc.refresh()
        execute(self.fc, 'cancel', output=lambda _: None)
        self.assertEqual(self.fc.phase, 'GPS_CANCEL_REQUESTED')

    def test_short_pause_dispatches_to_local_fly_when_no_gps_mission(self):
        self.ready()
        self.fc.fly(1, 2)
        execute(self.fc, 'pause', output=lambda _: None)
        self.assertEqual(self.fc.phase, 'PAUSE_REQUESTED')
        self.put('flight_mode', 'HOLD')
        self.fc.refresh()
        self.assertEqual(self.fc.phase, 'PAUSED')

    def test_px4_speed_and_hold_height_limits_are_enforced(self):
        self.fc.gps_limits = GpsLimits(max_speed_m_s=2.0)
        with self.assertRaisesRegex(ValueError, 'speed_m_s'):
            self.fc.gps_plan(10, 106.00002, 10, 106.00005, 2.5, 1.0)
        self.fc.nav_min_ltr_alt = 5.0
        with self.assertRaisesRegex(ValueError, 'NAV_MIN_LTR_ALT'):
            self.plan()

    def test_mission_takeoff_minimum_cannot_force_extra_climb(self):
        self.plan()
        self.fc.gps_start()
        self.fc.param.get_param_float.return_value = 5.0
        self.finish_takeoff('HOLD')
        self.assertIn('MIS_TAKEOFF_ALT', self.fc.last_error)
        self.fc.mission.upload_mission.assert_not_called()

    def test_start_failure_requests_hold_and_never_claims_running(self):
        self.plan()
        self.fc.mission.start_mission.side_effect = RuntimeError('DENIED')
        self.fc.gps_start()
        self.finish_takeoff('GPS_UNCONFIRMED')
        self.assertEqual(self.fc.phase, 'GPS_UNCONFIRMED')
        self.fc.action.hold.assert_called()
        self.assertTrue(self.fc.gps_mission_stored)

    def test_mission_mode_timeout_requests_hold_without_auto_resume(self):
        self.plan()
        self.fc.gps_start()
        self.finish_takeoff('GPS_STARTING')
        self.advance(5.1)
        self.fc.refresh()
        self.assertEqual(self.fc.phase, 'GPS_UNCONFIRMED')
        self.fc.action.hold.assert_called()
        self.fc.mission.start_mission.assert_called_once()

    def test_external_mode_blocks_resume(self):
        self.running()
        self.fc.record_mode('RETURN_TO_LAUNCH')
        self.fc.refresh()
        self.assertEqual(self.fc.phase, 'EXTERNAL')
        with self.assertRaises(ValueError):
            self.fc.gps_resume()

    def test_land_invalidates_staged_plan(self):
        self.plan()
        self.fc.gps_start()
        self.fc.land()
        self.assertIsNone(self.fc.gps_plan_data)
        self.assertFalse(self.fc.gps_launch_pending)
        self.assertEqual(self.fc.phase, 'LANDING')

    def test_terminal_land_preempts_running_gps_mission(self):
        self.running()
        execute(self.fc, 'land', output=lambda _: None)
        self.fc.action.land.assert_called_once()
        self.assertEqual(self.fc.phase, 'LANDING')
        self.assertIsNone(self.fc.gps_plan_data)

    def test_return_home_replaces_gps_mission_and_holds_at_current_height(self):
        self.running()
        self.cancel_running()
        self.put('position', dict(latitude_deg=10.0, longitude_deg=106.00005,
                                  absolute_altitude_m=102.5, relative_altitude_m=2.5))
        self.put('local_ned', dict(north_m=0.4, east_m=-0.7, down_m=2.731))
        execute(self.fc, 'return-home', output=lambda _: None)
        self.assertEqual(self.fc.phase, 'HOME_HOLD_REQUESTED')
        self.assertIsNone(self.fc.gps_plan_data)
        self.assertFalse(self.fc.gps_mission_stored)
        self.fc.mission.clear_mission.assert_called_once()
        self.put('flight_mode', 'HOLD')
        self.fc.refresh()
        self.assertEqual(self.fc.phase, 'GPS_STARTING')
        self.fc.mission.clear_mission.assert_called_once()
        self.assertEqual(self.fc.mission.upload_mission.call_count, 2)
        self.assertEqual(self.fc.mission.set_current_mission_item.call_count, 2)
        self.fc.mission.set_current_mission_item.assert_called_with(0)
        items = self.fc.mission.upload_mission.call_args.args[0].mission_items
        self.assertEqual(len(items), 1)
        self.assertAlmostEqual(items[0].latitude_deg, 10.0)
        self.assertAlmostEqual(items[0].longitude_deg, 106.0)
        self.assertAlmostEqual(items[0].relative_altitude_m, 2.5)
        self.fc.action.return_to_launch.assert_not_called()
        self.put('flight_mode', 'MISSION')
        self.fc.refresh()
        self.assertEqual(self.fc.phase, 'GPS_RUNNING')
        self.fc.mission.is_mission_finished.return_value = True
        self.put('position', dict(latitude_deg=10.0, longitude_deg=106.0,
                                  absolute_altitude_m=102.5, relative_altitude_m=2.5))
        self.put('flight_mode', 'HOLD')
        self.fc.refresh()
        self.assertEqual(self.fc.phase, 'HOME_COMPLETE')
        self.assertTrue(self.fc.status()['gps_mission']['return_position_confirmed'])
        self.fc.action.land.assert_not_called()

    def test_return_home_can_be_cancelled_before_new_mission_starts(self):
        self.running()
        self.cancel_running()
        self.fc.action.hold.side_effect = None
        self.fc.return_home()
        self.fc.gps_cancel()
        self.put('flight_mode', 'HOLD')
        self.fc.refresh()
        self.assertEqual(self.fc.phase, 'GPS_CANCELLED')
        self.assertIsNone(self.fc.home_return_target)
        uploads_at_cancel = self.fc.mission.upload_mission.call_count
        self.fc.refresh()
        self.assertEqual(self.fc.mission.upload_mission.call_count, uploads_at_cancel)

    def test_return_home_requires_completed_takeoff_and_saved_launch_gps(self):
        with self.assertRaises(ValueError):
            self.fc.return_home()
        self.ready()
        self.fc.launch_gps = None
        with self.assertRaisesRegex(ValueError, 'saved launch GPS'):
            self.fc.return_home()

    def test_return_home_from_paused_gps_cancels_before_replacement(self):
        self.running()
        self.fc.pause()
        self.put('flight_mode', 'HOLD')
        self.fc.refresh()
        self.assertEqual(self.fc.phase, 'GPS_PAUSED')
        self.fc.return_home()
        self.assertEqual(self.fc.phase, 'HOME_HOLD_REQUESTED')
        self.assertAlmostEqual(self.fc.home_return_target['speed_m_s'], 0.4)
        self.assertEqual(self.fc.mission.clear_mission.call_count, 1)
        self.put('flight_mode', 'HOLD')
        self.fc.refresh()
        self.assertEqual(self.fc.mission.set_current_mission_item.call_count, 2)
        self.fc.mission.set_current_mission_item.assert_called_with(0)
        self.assertEqual(self.fc.phase, 'GPS_STARTING')

    def test_return_home_does_not_start_when_new_mission_index_is_denied(self):
        self.running()
        self.cancel_running()
        self.fc.mission.start_mission.reset_mock()
        self.fc.mission.set_current_mission_item.side_effect = RuntimeError('DENIED')
        self.fc.return_home()
        self.put('flight_mode', 'HOLD')
        self.fc.refresh()
        self.assertEqual(self.fc.phase, 'GPS_UNCONFIRMED')
        self.assertIn('DENIED', self.fc.last_error)
        self.fc.mission.start_mission.assert_not_called()
        self.assertFalse(self.fc.status()['gps_mission']['return_position_confirmed'])

    def test_return_home_from_paused_waits_for_fresh_cancel_position(self):
        self.running()
        self.fc.pause()
        self.put('flight_mode', 'HOLD')
        self.fc.refresh()
        value, _ = self.fc.cache['position']
        self.fc.cache['position'] = (value, self.now - 0.2)
        with self.assertRaisesRegex(RuntimeError, 'cancel is pending'):
            self.fc.return_home()
        self.assertEqual(self.fc.phase, 'GPS_CANCEL_REQUESTED')
        self.assertEqual(self.fc.mission.upload_mission.call_count, 1)

    def test_return_home_paused_below_min_keeps_resumable_mission(self):
        self.running()
        self.fc.pause()
        self.put('flight_mode', 'HOLD')
        self.fc.refresh()
        self.fc.param.get_param_float.return_value = 2.5
        with self.assertRaisesRegex(ValueError, 'MIS_TAKEOFF_ALT'):
            self.fc.return_home()
        self.assertEqual(self.fc.phase, 'GPS_PAUSED')
        self.fc.mission.clear_mission.assert_not_called()
        self.assertTrue(self.fc.gps_mission_stored)

    def test_return_home_rejects_below_mission_takeoff_alt_before_hold(self):
        self.ready()
        self.fc.action.hold.reset_mock()
        self.fc.param.get_param_float.return_value = 2.5
        with self.assertRaisesRegex(ValueError, 'MIS_TAKEOFF_ALT 2.50 m'):
            self.fc.return_home()
        self.assertEqual(self.fc.phase, 'HOLD')
        self.fc.action.hold.assert_not_called()
        self.fc.mission.upload_mission.assert_not_called()

    def test_return_home_clamps_small_estimator_error_to_mission_minimum(self):
        self.ready()
        self.fc.param.get_param_float.return_value = 2.5
        self.put('position', dict(latitude_deg=10.0, longitude_deg=106.00002,
                                  absolute_altitude_m=102.49,
                                  relative_altitude_m=2.49))
        self.fc.return_home()
        self.assertEqual(self.fc.home_return_target['request_relative_altitude_m'], 2.5)
        self.put('flight_mode', 'HOLD')
        self.fc.refresh()
        item = self.fc.mission.upload_mission.call_args.args[0].mission_items[0]
        self.assertEqual(item.relative_altitude_m, 2.5)
        self.fc.action.land.assert_not_called()

    def test_return_home_from_local_fly_uses_launch_gps_and_current_height(self):
        self.ready()
        self.fc.fly(1, 2)
        self.fc.cancel()
        self.fc.refresh()
        self.put('position', dict(latitude_deg=10.0, longitude_deg=106.00002,
                                  absolute_altitude_m=102.0, relative_altitude_m=2.0))
        self.fc.return_home()
        self.put('flight_mode', 'HOLD')
        self.fc.refresh()
        self.assertEqual(self.fc.phase, 'GPS_STARTING')
        item = self.fc.mission.upload_mission.call_args.args[0].mission_items[0]
        self.assertAlmostEqual(item.longitude_deg, 106.0)
        self.assertAlmostEqual(item.relative_altitude_m, 2.0)
        self.assertAlmostEqual(item.speed_m_s, 0.5)
        self.fc.action.land.assert_not_called()

    def test_return_home_rejects_active_local_fly_until_cancel(self):
        self.ready()
        self.fc.fly(1, 2)
        with self.assertRaisesRegex(ValueError, 'after cancel'):
            self.fc.return_home()
        self.fc.mission.upload_mission.assert_not_called()

    def test_return_home_rejects_running_gps_until_cancel(self):
        self.running()
        with self.assertRaisesRegex(ValueError, 'after cancel'):
            self.fc.return_home()
        self.fc.mission.clear_mission.assert_not_called()

    def test_cancelled_gps_mission_accepts_local_fly_at_held_height(self):
        self.running()
        self.put('local_ned', dict(north_m=0.4, east_m=-0.7, down_m=2.731))
        self.cancel_running()
        self.fc.fly(1.0, 2.0)
        self.assertEqual(self.fc.phase, 'FLY')
        self.assertAlmostEqual(self.fc.target['down_m'], 2.731)
        self.assertEqual(self.fc.target['north_m'], 1.0)
        self.fc.make_offboard.assert_called()  # Recreate stream after PX4 Mission.

    def test_return_height_from_paused_gps_cancels_and_moves_vertically(self):
        self.running()
        self.put('local_ned', dict(north_m=1.0, east_m=2.0, down_m=2.731))
        self.put('position', dict(latitude_deg=10.0, longitude_deg=106.00004,
                                  absolute_altitude_m=102.5, relative_altitude_m=2.5))
        self.fc.pause()
        self.put('flight_mode', 'HOLD')
        self.fc.refresh()
        self.assertEqual(self.fc.phase, 'GPS_PAUSED')
        self.fc.return_height()
        self.assertEqual(self.fc.phase, 'FLY')
        self.assertAlmostEqual(self.fc.target['down_m'], 3.231)
        self.assertAlmostEqual(self.fc.target['north_m'], 1.0)
        self.assertAlmostEqual(self.fc.target['east_m'], 2.0)
        self.assertEqual(self.fc.mission.clear_mission.call_count, 1)
        self.fc.action.land.assert_not_called()

    def test_return_height_paused_invalid_hold_height_keeps_mission(self):
        self.running()
        self.fc.pause()
        self.put('flight_mode', 'HOLD')
        self.fc.refresh()
        self.fc.nav_min_ltr_alt = 3.0
        with self.assertRaisesRegex(ValueError, 'NAV_MIN_LTR_ALT'):
            self.fc.return_height()
        self.assertEqual(self.fc.phase, 'GPS_PAUSED')
        self.fc.mission.clear_mission.assert_not_called()

    def test_return_height_from_cancelled_gps_keeps_current_xy(self):
        self.running()
        self.put('local_ned', dict(north_m=1.0, east_m=2.0, down_m=2.731))
        self.put('position', dict(latitude_deg=10.0, longitude_deg=106.00004,
                                  absolute_altitude_m=102.5, relative_altitude_m=2.5))
        self.cancel_running()
        self.fc.return_height()
        self.assertEqual(self.fc.phase, 'FLY')
        self.assertAlmostEqual(self.fc.target['north_m'], 1.0)
        self.assertAlmostEqual(self.fc.target['east_m'], 2.0)
        self.assertAlmostEqual(self.fc.target['down_m'], 3.231)

    def test_return_height_from_completed_B_then_hold_at_takeoff_height(self):
        self.running()
        self.fc.mission.is_mission_finished.return_value = True
        self.put('flight_mode', 'HOLD')
        self.put('local_ned', dict(north_m=1.0, east_m=2.0, down_m=2.731))
        self.put('position', dict(latitude_deg=10.0, longitude_deg=106.00005,
                                  absolute_altitude_m=102.5, relative_altitude_m=2.5))
        self.fc.refresh()
        self.assertEqual(self.fc.phase, 'GPS_COMPLETE')
        self.fc.return_height()
        self.assertEqual(self.fc.phase, 'FLY')
        self.assertAlmostEqual(self.fc.target['down_m'], 3.231)
        self.assertEqual(self.fc.target['north_m'], 1.0)
        self.assertEqual(self.fc.target['east_m'], 2.0)
        self.fc.action.land.assert_not_called()

    def test_return_home_mission_pause_resume_cancel(self):
        self.running()
        self.cancel_running()
        self.fc.return_home()
        self.put('flight_mode', 'HOLD')
        self.fc.refresh()
        self.put('flight_mode', 'MISSION')
        self.fc.refresh()
        execute(self.fc, 'pause', output=lambda _: None)
        self.put('flight_mode', 'HOLD')
        self.fc.refresh()
        self.assertEqual(self.fc.phase, 'GPS_PAUSED')
        execute(self.fc, 'resume', output=lambda _: None)
        self.put('flight_mode', 'MISSION')
        self.fc.refresh()
        self.assertEqual(self.fc.phase, 'GPS_RUNNING')
        execute(self.fc, 'cancel', output=lambda _: None)
        self.put('flight_mode', 'HOLD')
        self.fc.refresh()
        self.assertEqual(self.fc.phase, 'GPS_CANCELLED')
        self.assertIsNone(self.fc.home_return_target)
        self.fc.action.land.assert_not_called()

    def test_return_home_does_not_confirm_wrong_altitude(self):
        self.running()
        self.cancel_running()
        self.fc.return_home()
        self.put('flight_mode', 'HOLD')
        self.fc.refresh()
        self.put('flight_mode', 'MISSION')
        self.fc.refresh()
        self.fc.mission.is_mission_finished.return_value = True
        self.put('position', dict(latitude_deg=10.0, longitude_deg=106.0,
                                  absolute_altitude_m=102.0, relative_altitude_m=2.0))
        self.put('local_ned', dict(north_m=0.4, east_m=-0.7, down_m=1.231))
        self.put('flight_mode', 'HOLD')
        self.fc.refresh()
        self.assertEqual(self.fc.phase, 'GPS_UNCONFIRMED')
        self.assertIn('held height', self.fc.last_error)

    def test_finished_return_home_explicitly_enters_hold_before_completion(self):
        self.running()
        self.cancel_running()
        self.fc.return_home()
        self.put('flight_mode', 'HOLD')
        self.fc.refresh()
        self.put('flight_mode', 'MISSION')
        self.fc.refresh()
        self.fc.mission.is_mission_finished.return_value = True
        self.put('position', dict(latitude_deg=10.0, longitude_deg=106.0,
                                  absolute_altitude_m=102.0, relative_altitude_m=2.0))
        self.fc.refresh()
        self.assertEqual(self.fc.phase, 'GPS_RUNNING')
        self.fc.action.hold.assert_called()
        self.fc.refresh()
        self.assertEqual(self.fc.phase, 'HOME_COMPLETE')
        self.fc.action.land.assert_not_called()

    def test_land_preempts_return_home_during_hold_request(self):
        self.running()
        self.cancel_running()
        self.fc.return_home()
        self.fc.land()
        self.assertEqual(self.fc.phase, 'LANDING')
        self.fc.action.land.assert_called_once()
        self.put('flight_mode', 'LAND')
        self.fc.refresh()
        self.assertEqual(self.fc.mission.upload_mission.call_count, 1)

    def test_cancel_hold_rejection_does_not_claim_return(self):
        self.running()
        self.fc.action.hold.side_effect = RuntimeError('DENIED')
        with self.assertRaises(RuntimeError):
            self.fc.gps_cancel()
        self.assertEqual(self.fc.phase, 'GPS_UNCONFIRMED')
        self.fc.mission.clear_mission.assert_not_called()


if __name__ == '__main__':
    unittest.main()
