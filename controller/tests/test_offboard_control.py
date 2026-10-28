from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pi"))

import threading
import sys
import unittest
from types import SimpleNamespace
from types import ModuleType
from unittest.mock import Mock, patch
from console import execute, parse_command
from flight_policy import ArrivalMonitor, FlightPolicy
from offboard_control import OffboardControl


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        clock = patch('time.monotonic', side_effect=lambda: self.now)
        clock.start()
        self.addCleanup(clock.stop)
        self.sleep = patch('offboard_control.time.sleep', side_effect=self.advance)
        self.sleep_mock = self.sleep.start()
        self.addCleanup(self.sleep.stop)
        self.fc = self.make_fc()

    def make_fc(self):
        fc = OffboardControl.__new__(OffboardControl)
        fc.enabled, fc.hitl, fc.height = True, 0, 2.0
        fc.profile = 'hardware'
        fc.lock = threading.Lock()
        fc.phase, fc.operation_at = 'IDLE', 0.0
        fc.policy = FlightPolicy(settle_s=0.6, target_timeout_s=10)
        fc.arrival = ArrivalMonitor(fc.policy)
        fc.nav_min_ltr_alt = -1.0
        fc.motor_stop_kind = None
        fc.paused_target = None
        fc.pause_operation_at = None
        fc.cancel_operation_at = None
        fc.cancel_confirmed = False
        for key in ('target', 'launch_ned', 'offboard', 'target_started_at', 'hold_operation_at',
                    'motion_kind', 'hold_reason', 'last_error', 'arm_operation_at',
                    'disarm_operation_at', 'land_request_context', 'mavlink_direct', 'direct_handle'):
            setattr(fc, key, None)
        for key in ('external', 'offboard_seen', 'termination', 'target_reached', 'takeoff_complete',
                    'arm_acknowledged', 'disarm_acknowledged', 'land_acknowledged',
                    'hold_acknowledged'):
            setattr(fc, key, False)
        fc.drone, fc.action, fc.sdk = Mock(), Mock(), Mock()
        fc.drone.is_connected.return_value = True
        fc.make_offboard = Mock(return_value=Mock())
        fc.Position = lambda **kw: SimpleNamespace(**kw)
        fc.cache = {k: (v, self.now) for k, v in {
            'armed': False, 'landed_state': 'ON_GROUND', 'flight_mode': 'HOLD',
            'health_all_ok': True, 'yaw_deg': 37.0,
            'local_ned': dict(north_m=0.4, east_m=-0.7, down_m=5.231),
            'local_velocity': dict(north_m_s=0, east_m_s=0, down_m_s=0),
            'position': dict(latitude_deg=10, longitude_deg=106, relative_altitude_m=2),
        }.items()}
        def state(key, value):
            fc.cache[key] = (value, self.now)
        fc.action.arm.side_effect = lambda: state('armed', True)
        fc.action.disarm.side_effect = lambda: state('armed', False)
        fc.action.kill.side_effect = lambda: state('armed', False)
        fc.action.land.side_effect = lambda: state('flight_mode', 'LAND')
        fc.action.hold.side_effect = lambda: state('flight_mode', 'HOLD')
        def started():
            state('armed', True)
            state('flight_mode', 'OFFBOARD')
            fc.record_mode('OFFBOARD')
        fc.make_offboard.return_value.start.side_effect = started
        return fc

    def put(self, key, value):
        self.fc.cache[key] = (value, self.now)

    def advance(self, seconds, publish=True):
        self.now += seconds
        if publish:
            self.fc.cache = {k: (v, self.now) for k, (v, _) in self.fc.cache.items()}

    def takeoff(self):
        self.fc.takeoff()
        self.assertEqual(self.fc.phase, 'TAKEOFF')
        self.put('landed_state', 'IN_AIR')

    def arrive(self):
        self.put('local_ned', {k: self.fc.target[k] for k in ('north_m', 'east_m', 'down_m')})
        self.put('yaw_deg', self.fc.target['yaw_deg'])
        for _ in range(5):
            self.advance(0.2)
            self.fc.refresh()
        self.fc.refresh()
        self.assertEqual(self.fc.phase, 'HOLD')

    def held(self):
        self.takeoff()
        self.arrive()

    def test_takeoff_order_and_relative_height(self):
        order = Mock()
        order.attach_mock(self.fc.make_offboard.return_value.set_position_ned, 'setpoint')
        order.attach_mock(self.fc.action.arm, 'arm')
        order.attach_mock(self.fc.make_offboard.return_value.start, 'start')
        self.takeoff()
        self.assertEqual([c[0] for c in order.mock_calls], ['setpoint', 'arm', 'start'])
        self.assertAlmostEqual(self.fc.target['down_m'], 3.231)
        self.assertEqual(self.fc.target['north_m'], 0.4)
        self.assertFalse(self.fc.status()['target_reached'])
        self.assertFalse(self.fc.ready_for_fly())

    def test_arm_only_and_single_forced_disarm_command(self):
        execute(self.fc, 'arm', output=lambda _: None)
        self.assertEqual(self.fc.phase, 'ARMED')
        self.assertTrue(self.fc.status()['arm_confirmed'])
        execute(self.fc, 'disarm', output=lambda _: None)
        self.fc.make_offboard.assert_not_called()
        self.fc.action.disarm.assert_not_called()
        self.fc.action.kill.assert_called_once()
        self.fc.action.land.assert_not_called()
        self.assertTrue(self.fc.status()['disarm_confirmed'])
        self.assertEqual(self.fc.phase, 'IDLE')
        self.fc.sdk.destroy.assert_not_called()

    def test_arm_then_takeoff_does_not_arm_twice(self):
        self.fc.arm()
        self.takeoff()
        self.fc.action.arm.assert_called_once()

    def test_arm_then_land_has_ground_context_and_no_offboard(self):
        self.fc.arm()
        self.fc.land()
        self.fc.action.land.assert_called_once()
        self.fc.make_offboard.assert_not_called()
        self.assertEqual(self.fc.land_request_context['phase_before'], 'ARMED')
        self.assertEqual(self.fc.land_request_context['landed_state'], 'ON_GROUND')
        self.assertFalse(self.fc.land_request_context['offboard_plugin_present'])

    def test_arm_ack_requires_new_telemetry(self):
        self.fc.action.arm.side_effect = None
        with self.assertRaisesRegex(RuntimeError, 'no fresh armed=true'):
            self.fc.arm()
        self.assertEqual(self.fc.phase, 'ARM_REQUESTED')
        self.assertTrue(self.fc.arm_acknowledged)
        self.assertFalse(self.fc.status()['arm_confirmed'])
        self.fc.disarm()

    def test_arm_timeout_allows_land_without_retry(self):
        self.fc.action.arm.side_effect = RuntimeError('ACK timeout')
        with self.assertRaises(RuntimeError):
            self.fc.arm()
        self.assertFalse(self.fc.arm_acknowledged)
        self.fc.land()
        self.fc.action.arm.assert_called_once()
        self.fc.action.kill.assert_not_called()

    def test_auto_disarm_does_not_rearm(self):
        self.fc.arm()
        self.advance(1)
        self.put('armed', False)
        self.fc.refresh()
        self.assertEqual(self.fc.phase, 'IDLE')
        self.fc.action.arm.assert_called_once()

    def test_prearmed_disarm_during_prestream_does_not_rearm(self):
        self.fc.arm()
        def auto_disarm(seconds):
            self.advance(seconds)
            self.put('armed', False)
        self.sleep_mock.side_effect = auto_disarm
        with self.assertRaisesRegex(ValueError, 'state changed'):
            self.fc.takeoff()
        self.fc.action.arm.assert_called_once()
        self.fc.action.land.assert_called_once()
        self.fc.make_offboard.return_value.start.assert_not_called()

    def test_arm_preconditions(self):
        for key, value in [('armed', True), ('landed_state', 'IN_AIR'), ('health_all_ok', False)]:
            with self.subTest(key=key):
                self.fc = self.make_fc()
                self.put(key, value)
                with self.assertRaises(ValueError):
                    self.fc.arm()
                self.fc.action.arm.assert_not_called()

    def test_zero_velocity_far_from_target_does_not_unlock(self):
        self.takeoff()
        for _ in range(10):
            self.advance(0.2)
            self.fc.refresh()
        self.assertEqual(self.fc.phase, 'TAKEOFF')
        self.assertFalse(self.fc.target_reached)
        self.fc.action.hold.assert_not_called()

    def test_arrival_native_hold_is_indefinite(self):
        self.held()
        self.assertTrue(self.fc.takeoff_complete)
        self.assertTrue(self.fc.status()['target_reached'])
        self.assertTrue(self.fc.status()['hold_mode_confirmed'])
        self.advance(200)
        self.fc.refresh()
        self.assertEqual(self.fc.phase, 'HOLD')
        self.fc.action.hold.assert_called_once()

    def test_busy_commands_never_mutate_target(self):
        self.takeoff()
        target = dict(self.fc.target)
        for line in ('fly', '2 3', 'fly 2 3', 'takeoff'):
            with self.subTest(line=line), self.assertRaises(ValueError):
                execute(self.fc, line, output=lambda _: None)
        self.assertEqual(self.fc.target, target)
        self.fc.offboard.set_position_ned.assert_called_once()

    def test_hold_accepts_only_explicit_fly_with_coordinates(self):
        self.held()
        for line in ('2 3', 'fly'):
            with self.subTest(line=line), self.assertRaises(ValueError):
                execute(self.fc, line, output=lambda _: None)
        self.assertEqual(self.fc.phase, 'HOLD')
        execute(self.fc, 'fly 2,3', output=lambda _: None)
        self.assertEqual(self.fc.phase, 'FLY')
        self.assertEqual(self.fc.target['north_m'], 2)
        self.assertAlmostEqual(self.fc.target['down_m'], 3.231)
        self.fc.action.arm.assert_called_once()
        self.arrive()

    def test_combined_fly_explicitly_exits_hold(self):
        self.held()
        execute(self.fc, 'fly -2 4', output=lambda _: None)
        self.assertEqual(self.fc.phase, 'FLY')

    def test_pause_then_resume_reuses_exact_local_target_without_rearm(self):
        self.held()
        self.fc.fly(5, 6)
        original = dict(self.fc.target)
        self.put('local_ned', dict(north_m=2, east_m=3, down_m=original['down_m']))
        execute(self.fc, 'pause', output=lambda _: None)
        self.assertEqual(self.fc.phase, 'PAUSE_REQUESTED')
        self.assertEqual(self.fc.paused_target, original)
        self.put('flight_mode', 'HOLD')
        self.fc.refresh()
        self.assertEqual(self.fc.phase, 'PAUSED')
        self.assertTrue(self.fc.status()['pause_confirmed'])
        self.assertTrue(self.fc.status()['hold_mode_confirmed'])
        execute(self.fc, 'resume', output=lambda _: None)
        self.assertEqual(self.fc.phase, 'FLY')
        self.assertEqual(self.fc.target, original)
        self.assertIsNone(self.fc.paused_target)
        self.fc.action.arm.assert_called_once()

    def test_pause_ack_without_new_hold_mode_does_not_enable_resume(self):
        self.held()
        self.fc.fly(5, 6)
        self.fc.action.hold.side_effect = None
        execute(self.fc, 'pause', output=lambda _: None)
        self.assertEqual(self.fc.phase, 'PAUSE_REQUESTED')
        with self.assertRaises(ValueError):
            execute(self.fc, 'resume', output=lambda _: None)
        self.put('flight_mode', 'HOLD')
        self.fc.refresh()
        self.assertEqual(self.fc.phase, 'PAUSED')

    def test_pause_ack_error_can_still_confirm_late_hold(self):
        self.held()
        self.fc.fly(5, 6)
        self.fc.action.hold.side_effect = RuntimeError('ACK timeout')
        with self.assertRaises(RuntimeError):
            execute(self.fc, 'pause', output=lambda _: None)
        self.assertEqual(self.fc.phase, 'PAUSE_REQUESTED')
        self.fc.action.land.assert_not_called()
        self.put('flight_mode', 'HOLD')
        self.fc.refresh()
        self.assertEqual(self.fc.phase, 'PAUSED')

    def test_cancel_from_paused_local_fly_drops_saved_target(self):
        self.held()
        self.fc.fly(5, 6)
        execute(self.fc, 'pause', output=lambda _: None)
        self.put('flight_mode', 'HOLD')
        self.fc.refresh()
        self.put('local_ned', dict(north_m=2, east_m=3, down_m=3.231))
        execute(self.fc, 'cancel', output=lambda _: None)
        self.assertEqual(self.fc.phase, 'HOLD')
        self.assertIsNone(self.fc.paused_target)
        self.assertTrue(self.fc.cancel_confirmed)
        with self.assertRaises(ValueError):
            execute(self.fc, 'resume', output=lambda _: None)

    def test_cancel_local_fly_holds_at_current_xy_and_takeoff_height(self):
        self.held()
        self.fc.fly(5, 6)
        self.put('local_ned', dict(north_m=2, east_m=3, down_m=3.231))
        execute(self.fc, 'cancel', output=lambda _: None)
        self.assertEqual(self.fc.phase, 'CANCEL_REQUESTED')
        self.put('flight_mode', 'HOLD')
        self.fc.refresh()
        self.assertEqual(self.fc.phase, 'HOLD')
        self.assertEqual(self.fc.hold_reason, 'CANCELLED')
        self.assertTrue(self.fc.status()['cancel_confirmed'])
        self.assertTrue(self.fc.status()['hold_mode_confirmed'])
        self.assertEqual((self.fc.target['north_m'], self.fc.target['east_m']), (2, 3))
        with self.assertRaises(ValueError):
            execute(self.fc, 'resume', output=lambda _: None)

    def test_cancel_ack_error_can_still_confirm_late_hold(self):
        self.held()
        self.fc.fly(5, 6)
        self.put('local_ned', dict(north_m=2, east_m=3, down_m=3.231))
        self.fc.action.hold.side_effect = RuntimeError('ACK timeout')
        with self.assertRaises(RuntimeError):
            execute(self.fc, 'cancel', output=lambda _: None)
        self.assertEqual(self.fc.phase, 'CANCEL_REQUESTED')
        self.fc.action.land.assert_not_called()
        self.put('flight_mode', 'HOLD')
        self.fc.refresh()
        self.assertTrue(self.fc.cancel_confirmed)

    def test_cancel_local_fly_keeps_current_height_and_allows_new_fly(self):
        self.held()
        self.fc.fly(5, 6)
        self.put('local_ned', dict(north_m=2, east_m=3, down_m=2.731))
        self.put('position', dict(latitude_deg=10, longitude_deg=106,
                                  relative_altitude_m=2.5))
        execute(self.fc, 'cancel', output=lambda _: None)
        self.put('flight_mode', 'HOLD')
        self.fc.refresh()
        self.assertEqual(self.fc.phase, 'HOLD')
        self.assertEqual(self.fc.hold_reason, 'CANCELLED')
        self.assertAlmostEqual(self.fc.target['down_m'], 2.731)
        self.assertTrue(self.fc.cancel_confirmed)
        self.fc.fly(3, 4)
        self.assertEqual(self.fc.phase, 'FLY')




    def test_target_timeout_does_not_fake_completion(self):
        self.takeoff()
        self.advance(10.1)
        self.fc.refresh()
        self.fc.refresh()
        self.assertEqual(self.fc.phase, 'HOLD')
        self.assertEqual(self.fc.hold_reason, 'TARGET_TIMEOUT')
        self.assertFalse(self.fc.target_reached)
        self.assertFalse(self.fc.takeoff_complete)

    def test_hold_failure_recovers_land_without_destroy(self):
        self.takeoff()
        self.fc.action.hold.side_effect = RuntimeError('DENIED')
        self.fc._request_hold('TARGET_REACHED')
        self.assertEqual(self.fc.phase, 'LANDING')
        self.assertIn('DENIED', self.fc.last_error)
        self.fc.action.land.assert_called_once()
        self.fc.offboard.destroy.assert_not_called()

    def test_hold_ack_without_mode_stays_locked_then_lands_on_timeout(self):
        self.takeoff()
        self.fc.action.hold.side_effect = None
        self.fc._request_hold('TARGET_REACHED')
        self.assertEqual(self.fc.phase, 'HOLD_REQUESTED')
        self.assertFalse(self.fc.ready_for_fly())
        self.advance(5.1)
        self.fc.refresh()
        self.fc.action.land.assert_called_once()

    def test_native_hold_minimum_altitude_guard(self):
        self.takeoff()
        self.fc.nav_min_ltr_alt = 5
        self.fc._request_hold('TARGET_REACHED')
        self.fc.action.hold.assert_not_called()
        self.fc.action.land.assert_called_once()
        self.assertIn('NAV_MIN_LTR_ALT', self.fc.last_error)

    def test_takeoff_rejects_known_hold_minimum_above_requested_height(self):
        self.fc.nav_min_ltr_alt = 5
        with self.assertRaisesRegex(ValueError, 'NAV_MIN_LTR_ALT'):
            self.fc.takeoff()
        self.fc.action.arm.assert_not_called()

    def test_land_preempts_all_flight_phases(self):
        for phase in ('TAKEOFF', 'FLY', 'SETTLING', 'HOLD_REQUESTED', 'HOLD'):
            with self.subTest(phase=phase):
                self.fc = self.make_fc()
                self.takeoff()
                self.fc.phase = phase
                self.fc.land()
                self.assertEqual(self.fc.phase, 'LANDING')
                self.fc.offboard.destroy.assert_not_called()
                self.fc.offboard.stop.assert_not_called()
                self.fc.sdk.destroy.assert_not_called()

    def test_land_ack_and_mode_confirmation_are_separate(self):
        self.takeoff()
        self.fc.action.land.side_effect = None
        self.fc.land()
        self.assertTrue(self.fc.status()['land_acknowledged'])
        self.assertFalse(self.fc.status()['land_mode_confirmed'])
        self.put('flight_mode', 'LAND')
        self.assertTrue(self.fc.status()['land_mode_confirmed'])

    def test_land_timeout_keeps_connection_and_observes_late_land(self):
        self.takeoff()
        self.fc.action.land.side_effect = RuntimeError('ACK timeout')
        with self.assertRaises(RuntimeError):
            self.fc.land()
        self.put('flight_mode', 'LAND')
        self.assertTrue(self.fc.status()['land_mode_confirmed'])
        self.fc.offboard.destroy.assert_not_called()

    def test_disarm_preempts_takeoff_even_if_still_on_ground(self):
        self.takeoff()
        self.put('landed_state', 'ON_GROUND')
        self.fc.disarm()
        self.fc.action.disarm.assert_not_called()
        self.fc.action.kill.assert_called_once()

    def test_forced_disarm_does_not_require_ground_and_timeout_does_not_close(self):
        self.fc.arm()
        self.fc.cache['landed_state'] = ('ON_GROUND', self.now - 10)
        self.fc.action.kill.side_effect = RuntimeError('DENIED')
        with self.assertRaises(RuntimeError):
            self.fc.disarm()
        self.assertEqual(self.fc.phase, 'DISARM_REQUESTED')
        self.fc.sdk.destroy.assert_not_called()

    def test_disarm_in_flight_is_sent_before_any_native_teardown(self):
        self.takeoff()
        self.fc.offboard.destroy.side_effect = RuntimeError('broken teardown')
        execute(self.fc, 'disarm', output=lambda _: None)
        self.fc.action.kill.assert_called_once()
        self.fc.offboard.destroy.assert_not_called()
        self.assertEqual(self.fc.phase, 'EMERGENCY_STOP')

    def test_ground_landing_keeps_plugin_until_explicit_exit(self):
        self.takeoff()
        plugin = self.fc.offboard
        self.fc.land()
        self.put('armed', False)
        self.put('landed_state', 'ON_GROUND')
        self.fc.refresh()
        self.assertEqual(self.fc.phase, 'IDLE')
        plugin.destroy.assert_not_called()
        self.assertFalse(execute(self.fc, 'exit', output=lambda _: None))
        self.fc.close()
        plugin.destroy.assert_called_once()
        self.fc.sdk.destroy.assert_called_once()

    def test_external_takeover_latches_even_if_mode_returns(self):
        self.held()
        self.fc.record_mode('RTL')
        self.fc.record_mode('HOLD')
        with self.assertRaises(ValueError):
            self.fc.fly(1, 2)
        self.assertEqual(self.fc.phase, 'EXTERNAL')
        self.fc.action.arm.assert_called_once()

    def test_disconnect_never_automatically_resumes(self):
        self.takeoff()
        self.fc.drone.is_connected.return_value = False
        self.fc.refresh()
        self.assertEqual(self.fc.phase, 'EXTERNAL')
        self.fc.drone.is_connected.return_value = True
        with self.assertRaises(ValueError):
            self.fc.fly(1, 2)

    def test_stale_hold_blocks_new_targets(self):
        self.held()
        self.advance(2, publish=False)
        self.assertFalse(self.fc.ready_for_fly())
        with self.assertRaises(ValueError):
            self.fc.fly(1, 2)

    def test_inspection_and_termination_block_actuation(self):
        for termination in (False, True):
            self.fc = self.make_fc()
            self.fc.enabled = termination
            self.fc.termination = termination
            for cmd in ('arm', 'takeoff', 'fly', 'fly 1 2', 'land', 'disarm'):
                with self.subTest(termination=termination, cmd=cmd), self.assertRaises(ValueError):
                    execute(self.fc, cmd, output=lambda _: None)
            self.fc.action.arm.assert_not_called()
            self.fc.action.kill.assert_not_called()

    def test_nonfinite_launch_and_future_telemetry_never_arm(self):
        for z in (float('nan'), float('inf'), 10001):
            self.fc = self.make_fc()
            self.fc.cache['local_ned'][0]['down_m'] = z
            with self.assertRaises(ValueError):
                self.fc.takeoff()
            self.fc.action.arm.assert_not_called()
        self.fc = self.make_fc()
        self.fc.cache['armed'] = (False, self.now + 10)
        with self.assertRaises(ValueError):
            self.fc.arm()

    def test_parser(self):
        self.assertEqual(parse_command('fly 2 3'), ('fly', (2, 3)))
        self.assertEqual(parse_command('FLY 2,3'), ('fly', (2, 3)))
        for line in ('fly', '2 3', 'NaN 0', 'inf 1', '10001 0', 'fly 1',
                     '1 2 3', 'arm 1', 'kill', 'unarm', 'hold'):
            with self.subTest(line=line), self.assertRaises(ValueError):
                parse_command(line)

    def test_repeated_target_needs_dwell_but_no_observed_motion(self):
        self.held()
        target = dict(self.fc.target)
        self.fc.fly(target['north_m'], target['east_m'])
        self.assertEqual(self.fc.phase, 'FLY')
        self.assertFalse(self.fc.target_reached)
        self.arrive()

    def test_health_failure_does_not_replace_target(self):
        self.held()
        target = dict(self.fc.target)
        sent = self.fc.offboard.set_position_ned.call_count
        self.put('health_all_ok', False)
        with self.assertRaises(ValueError):
            self.fc.fly(8, 9)
        self.assertEqual(self.fc.target, target)
        self.assertEqual(self.fc.offboard.set_position_ned.call_count, sent)

    def test_stale_arrival_sample_does_not_finish_settling(self):
        self.takeoff()
        self.put('local_ned', {k: self.fc.target[k] for k in ('north_m', 'east_m', 'down_m')})
        self.fc.refresh()
        self.assertEqual(self.fc.phase, 'SETTLING')
        self.advance(1.1, publish=False)
        self.fc.refresh()
        self.assertEqual(self.fc.phase, 'TAKEOFF')
        self.fc.action.hold.assert_not_called()

    def test_old_disarmed_state_does_not_confirm_new_disarm(self):
        self.fc.action.kill.side_effect = None
        self.advance(0.1, publish=False)
        self.fc.disarm()
        self.assertTrue(self.fc.disarm_acknowledged)
        self.assertFalse(self.fc.status()['disarm_confirmed'])
        self.advance(0.1)
        self.assertTrue(self.fc.status()['disarm_confirmed'])

    def test_takeoff_start_failure_lands_before_native_teardown(self):
        self.fc.make_offboard.return_value.start.side_effect = RuntimeError('DENIED')
        with self.assertRaises(RuntimeError):
            self.fc.takeoff()
        self.fc.action.land.assert_called_once()
        self.fc.make_offboard.return_value.destroy.assert_not_called()


    def test_constructor_subscriptions_are_read_only_and_filter_heartbeat_source(self):
        base = self.fc
        base.param = Mock()
        base.param.get_param_float.return_value = -1.0
        base.telemetry = Mock()
        base.handles = []
        def base_init(obj, *args):
            for key in ('lock', 'cache', 'sdk', 'drone', 'action', 'param', 'telemetry',
                        'handles', 'phase', 'operation_at', 'hitl', 'profile'):
                setattr(obj, key, getattr(base, key))
            obj.enabled = False
        direct_factory, offboard_factory = Mock(), Mock()
        direct = ModuleType('mavsdk.plugins.mavlink_direct')
        direct.MavlinkDirect = direct_factory
        offboard = ModuleType('mavsdk.plugins.offboard')
        offboard.Offboard, offboard.PositionNedYaw = offboard_factory, Mock()
        with patch.dict(sys.modules, {'mavsdk.plugins.mavlink_direct': direct,
                                     'mavsdk.plugins.offboard': offboard}), \
                patch('offboard_control.Pixhawk.__init__', new=base_init):
            fc = OffboardControl('serial:///dev/fake:921600', 'hardware')
        offboard_factory.assert_not_called()
        fc.action.arm.assert_not_called()
        base.param.get_param_float.assert_called_once_with('NAV_MIN_LTR_ALT')
        callback = direct_factory.return_value.subscribe_message.call_args.args[1]
        message = dict(message_name='HEARTBEAT', system_id=2, component_id=1,
                       fields_json='{"custom_mode": 655360, "system_status": 8}')
        callback(SimpleNamespace(**message))
        self.assertFalse(fc.termination)
        callback(SimpleNamespace(**dict(message, system_id=1)))
        self.assertTrue(fc.termination)
        local_callback = base.telemetry.subscribe_position_velocity_ned.call_args.args[0]
        local_callback(SimpleNamespace(position=SimpleNamespace(north_m=1, east_m=2, down_m=3),
                                       velocity=SimpleNamespace(north_m_s=0, east_m_s=0, down_m_s=0)))
        self.assertEqual(fc.cache['local_ned'][0]['east_m'], 2)

    def test_heartbeat_age_is_separate_from_fast_position_sample_age(self):
        self.takeoff()
        self.put('local_ned', {k: self.fc.target[k] for k in ('north_m', 'east_m', 'down_m')})
        armed = self.fc.cache['armed']
        mode = self.fc.cache['flight_mode']
        for _ in range(8):
            self.advance(0.2)
            self.fc.cache['armed'] = armed
            if self.fc.phase not in {'HOLD', 'HOLD_REQUESTED'}:
                self.fc.cache['flight_mode'] = mode
            self.fc.refresh()
        self.assertEqual(self.fc.phase, 'HOLD')

    def test_land_then_idle_then_arm_then_takeoff(self):
        self.held()
        self.fc.land()
        self.advance(0.1)
        self.put('armed', False)
        self.put('landed_state', 'ON_GROUND')
        self.fc.refresh()
        self.assertEqual(self.fc.phase, 'IDLE')
        self.fc.arm()
        self.assertEqual(self.fc.phase, 'ARMED')
        self.assertEqual(self.fc.state('flight_mode'), 'HOLD')
        self.fc.takeoff()
        self.assertEqual(self.fc.phase, 'TAKEOFF')
        self.assertEqual(self.fc.action.arm.call_count, 2)

    def test_disarm_airborne_waits_for_ground_and_prepares_hold_before_rearm(self):
        self.takeoff()
        self.fc.disarm()
        self.assertEqual(self.fc.status()['phase'], 'EMERGENCY_STOP')
        for cmd in ('arm', 'takeoff'):
            with self.subTest(cmd=cmd), self.assertRaises(ValueError):
                execute(self.fc, cmd, output=lambda _: None)
        self.advance(0.1)
        self.put('landed_state', 'ON_GROUND')
        self.fc.refresh()
        self.assertEqual(self.fc.phase, 'IDLE')
        self.assertEqual(self.fc.state('flight_mode'), 'OFFBOARD')
        order = Mock()
        order.attach_mock(self.fc.action.hold, 'hold')
        order.attach_mock(self.fc.action.arm, 'arm')
        self.fc.arm()
        self.assertEqual([c[0] for c in order.mock_calls], ['hold', 'arm'])
        self.assertEqual(self.fc.state('flight_mode'), 'HOLD')
        self.assertEqual(self.fc.phase, 'ARMED')

    def test_rearm_is_blocked_if_ground_hold_not_confirmed(self):
        self.put('flight_mode', 'OFFBOARD')
        self.fc.action.hold.side_effect = None
        with self.assertRaisesRegex(RuntimeError, 'ARM was not sent'):
            self.fc.arm()
        with self.assertRaisesRegex(RuntimeError, 'ARM was not sent'):
            self.fc.takeoff()
        self.fc.action.arm.assert_not_called()
        self.fc.make_offboard.assert_not_called()

    def test_direct_takeoff_after_land_is_available_from_idle(self):
        self.takeoff()
        self.fc.land()
        self.advance(0.1)
        self.put('armed', False)
        self.put('landed_state', 'ON_GROUND')
        self.fc.refresh()
        self.fc.takeoff()
        self.assertEqual(self.fc.phase, 'TAKEOFF')

    def test_two_metre_target_requires_vertical_tolerance_and_dwell(self):
        self.takeoff()
        ground = self.fc.launch_ned['down_m']
        self.put('local_ned', dict(north_m=0.4, east_m=-0.7, down_m=ground - 1.6))
        for _ in range(5):
            self.advance(0.2)
            self.fc.refresh()
        self.assertEqual(self.fc.phase, 'TAKEOFF')
        self.arrive()
        self.assertAlmostEqual(self.fc.status()['height_above_launch_m'], 2.0)
        self.assertTrue(self.fc.takeoff_complete)

    def test_xy_drift_never_recenters_takeoff_target(self):
        self.takeoff()
        target = dict(self.fc.target)
        self.put('local_ned', dict(north_m=3.4, east_m=-2.7, down_m=4.0))
        self.advance(0.2)
        status = self.fc.status()
        self.assertEqual(self.fc.target, target)
        self.assertEqual(self.fc.phase, 'TAKEOFF')
        self.fc.offboard.set_position_ned.assert_called_once()
        self.assertAlmostEqual(status['target_error_ned_m']['north_m'], 3.0)
        self.assertAlmostEqual(status['target_error_ned_m']['east_m'], -2.0)
        self.fc.action.hold.assert_not_called()

    def test_axis_errors_remain_visible_in_hold(self):
        self.held()
        p = {k: self.fc.target[k] for k in ('north_m', 'east_m', 'down_m')}
        p['north_m'] += 1.0
        p['east_m'] -= 2.0
        self.put('local_ned', p)
        status = self.fc.status()
        self.assertAlmostEqual(status['horizontal_target_error_m'], 5 ** 0.5)
        self.assertAlmostEqual(status['target_error_ned_m']['north_m'], 1.0)
        self.assertAlmostEqual(status['target_error_ned_m']['east_m'], -2.0)

    def test_fly_absolute_targets_across_legs_never_accumulate_position_or_height(self):
        self.put('local_ned', dict(north_m=10.0, east_m=5.0, down_m=7.0))
        self.held()
        fixed_down = self.fc.target['down_m']
        self.assertEqual(fixed_down, 5.0)
        for north, east in ((1, 2), (1, 2), (-3, 4)):
            with self.subTest(target=(north, east)):
                execute(self.fc, f'fly {north} {east}', output=lambda _: None)
                sent = self.fc.offboard.set_position_ned.call_args.args[0]
                self.assertEqual((sent.north_m, sent.east_m, sent.down_m),
                                 (north, east, fixed_down))
                target = dict(self.fc.target)
                self.put('local_ned', dict(north_m=north + 2, east_m=east - 3,
                                           down_m=fixed_down + 0.8))
                self.advance(0.2)
                self.fc.refresh()
                self.assertEqual(self.fc.target, target)
                self.assertEqual(self.fc.phase, 'FLY')
                self.arrive()
        self.fc.action.arm.assert_called_once()
        self.assertEqual(self.fc.offboard.set_position_ned.call_count, 4)

    def test_new_coordinates_stay_locked_through_fly_settling_and_hold_confirmation(self):
        self.held()
        self.fc.fly(1, 2)
        target = dict(self.fc.target)
        sent = self.fc.offboard.set_position_ned.call_count
        def reject_new_targets(expected_phase):
            self.assertEqual(self.fc.phase, expected_phase)
            for line in ('fly 8 9', '8 9', 'fly', 'takeoff'):
                with self.subTest(phase=expected_phase, line=line), self.assertRaises(ValueError):
                    execute(self.fc, line, output=lambda _: None)
            self.assertEqual(self.fc.target, target)
            self.assertEqual(self.fc.offboard.set_position_ned.call_count, sent)
        reject_new_targets('FLY')
        self.put('local_ned', {k: target[k] for k in ('north_m', 'east_m', 'down_m')})
        self.advance(0.2)
        self.fc.refresh()
        reject_new_targets('SETTLING')
        self.fc.action.hold.side_effect = None  # ACK without a new HOLD mode.
        for _ in range(5):
            self.advance(0.2)
            self.fc.refresh()
        reject_new_targets('HOLD_REQUESTED')
        self.put('flight_mode', 'HOLD')
        self.fc.refresh()
        self.assertEqual(self.fc.phase, 'HOLD')
        self.assertTrue(self.fc.ready_for_fly())

    def test_passing_fly_target_then_overshooting_resets_arrival_dwell(self):
        self.held()
        self.fc.fly(1, 2)
        target = dict(self.fc.target)
        hold_count = self.fc.action.hold.call_count
        self.put('local_ned', {k: target[k] for k in ('north_m', 'east_m', 'down_m')})
        self.fc.refresh()
        self.advance(0.2)
        self.fc.refresh()
        self.assertEqual(self.fc.phase, 'SETTLING')
        self.put('local_ned', dict(north_m=2.0, east_m=2.0, down_m=target['down_m']))
        for _ in range(5):
            self.advance(0.2)
            self.fc.refresh()
        self.assertEqual(self.fc.phase, 'FLY')
        self.assertFalse(self.fc.target_reached)
        self.assertIsNone(self.fc.arrival.since)
        self.assertEqual(self.fc.action.hold.call_count, hold_count)
        self.assertEqual(self.fc.target, target)
        self.arrive()
        self.assertTrue(self.fc.target_reached)

    def test_fly_timeout_holds_without_reporting_success_or_retrying_target(self):
        self.held()
        self.fc.fly(1, 2)
        target = dict(self.fc.target)
        sent = self.fc.offboard.set_position_ned.call_count
        self.advance(10.1)
        self.fc.refresh()
        self.fc.refresh()
        self.assertEqual(self.fc.phase, 'HOLD')
        self.assertEqual(self.fc.hold_reason, 'TARGET_TIMEOUT')
        self.assertFalse(self.fc.target_reached)
        self.assertTrue(self.fc.takeoff_complete)
        self.advance(100)
        self.fc.refresh()
        self.assertEqual(self.fc.target, target)
        self.assertEqual(self.fc.offboard.set_position_ned.call_count, sent)
        self.fc.fly(3, 4)
        self.assertEqual(self.fc.target['north_m'], 3)
        self.assertEqual(self.fc.target['east_m'], 4)
        self.assertEqual(self.fc.target['down_m'], target['down_m'])
        self.fc.action.arm.assert_called_once()

    def test_nonfinite_status_does_not_crash_or_complete_arrival(self):
        import json
        self.takeoff()
        self.put('local_ned', dict(north_m=float('nan'), east_m=0.0, down_m=float('inf')))
        status = self.fc.status()
        json.dumps(status, allow_nan=False)
        self.assertIn('local_ned', status['invalid_telemetry_fields'])
        self.assertIsNone(status['height_above_launch_m'])
        self.assertFalse(status['target_reached'])
        self.assertEqual(status['phase'], 'TAKEOFF')
        self.fc.action.hold.assert_not_called()
        self.assertNotEqual(self.fc.cache['local_ned'][0]['north_m'], 0.0)

    def test_termination_advice_matches_profile(self):
        self.fc.termination = True
        hardware = self.fc.status()['required_action']
        self.assertNotIn('Gazebo', hardware)
        self.assertIn('on the ground', hardware)
        self.fc.profile = 'hitl'
        self.assertIn('Gazebo', self.fc.status()['required_action'])

    def test_failed_offboard_initialization_closes_sdk(self):
        def base_init(obj, *args):
            obj.sdk, obj.param = Mock(), Mock()
            obj.param.get_param_float.side_effect = RuntimeError('parameter timeout')
            self.created = obj
        with patch('offboard_control.Pixhawk.__init__', new=base_init):
            with self.assertRaisesRegex(RuntimeError, 'parameter timeout'):
                OffboardControl('serial:///dev/fake:921600', 'hardware')
        self.created.sdk.destroy.assert_called_once()


if __name__ == '__main__':
    unittest.main()
