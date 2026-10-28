"""Two-waypoint A-then-B PX4 Mission, operated from one Pi session.

No network protocol is assumed here. A future MQTT adapter must call these
methods, rather than send latitude/longitude to the local-NED fly command.
"""
import math
import time
from dataclasses import dataclass

from offboard_control import OffboardControl
from validation import number


def distance_m(lat1, lon1, lat2, lon2):
    """Great-circle distance, used as an input guard, not as path planning."""
    a, b = math.radians(lat1), math.radians(lat2)
    da, db = b - a, math.radians(lon2 - lon1)
    h = math.sin(da / 2) ** 2 + math.cos(a) * math.cos(b) * math.sin(db / 2) ** 2
    return 6371000.0 * 2 * math.asin(min(1.0, math.sqrt(h)))


@dataclass(frozen=True)
class GpsLimits:
    start_error_m: float = 5.0
    max_leg_m: float = 10.0
    max_height_m: float = 3.0
    max_speed_m_s: float = 0.5
    confirmation_s: float = 5.0

    def __post_init__(self):
        number(self.start_error_m, 'start_error_m', 0.5, 100)
        number(self.max_leg_m, 'max_leg_m', 1, 10000)
        number(self.max_height_m, 'max_height_m', 1, 100)
        number(self.max_speed_m_s, 'max_speed_m_s', 0.1, 10)
        number(self.confirmation_s, 'confirmation_s', 1, 30)


class GpsMissionControl(OffboardControl):
    GPS_PHASES = {'GPS_STARTING', 'GPS_RUNNING', 'GPS_PAUSE_REQUESTED',
                  'GPS_PAUSED', 'GPS_RESUME_REQUESTED', 'GPS_CANCEL_REQUESTED',
                  'GPS_CANCELLED', 'GPS_COMPLETE', 'GPS_UNCONFIRMED',
                  'HOME_HOLD_REQUESTED', 'HOME_COMPLETE'}
    PENDING = {'GPS_STARTING', 'GPS_PAUSE_REQUESTED', 'GPS_RESUME_REQUESTED',
               'GPS_CANCEL_REQUESTED', 'HOME_HOLD_REQUESTED'}

    def __init__(self, *args, gps_limits=None, **kwargs):
        self.gps_limits = gps_limits or GpsLimits()
        self.gps_plan_data = None
        self.gps_epoch = None
        self.gps_hold_seen_at = None
        self.gps_finish_hold_requested_at = None
        self.gps_mission_stored = False
        self.gps_cancel_position = None
        self.gps_launch_pending = False
        self.gps_deploying = False
        self.launch_gps = None
        self.home_return_target = None
        self.home_returning = False
        self.home_epoch = None
        self.home_started_at = None
        self.px4_xy_vel_max = None
        self.mission = None
        super().__init__(*args, **kwargs)
        try:
            self.px4_xy_vel_max = number(
                self.param.get_param_float('MPC_XY_VEL_MAX'),
                'MPC_XY_VEL_MAX', 0.1, 100)
            from mavsdk.plugins.mission import Mission, MissionItem, MissionPlan
            self.mission = Mission(self.drone)
            self.MissionItem, self.MissionPlan = MissionItem, MissionPlan
        except BaseException:
            super().close()
            raise

    def record_mode(self, name):
        if self.phase in self.GPS_PHASES:
            expected = ({'OFFBOARD', 'HOLD', 'MISSION'}
                        if self.phase in {'HOME_HOLD_REQUESTED', 'GPS_CANCEL_REQUESTED'} else
                        {'HOLD', 'MISSION'} if self.phase in self.PENDING | {
                            'GPS_RUNNING', 'GPS_UNCONFIRMED'} else {'HOLD'})
            if name not in expected:
                self.external = True
            return
        super().record_mode(name)

    def pause(self):
        if self.phase in self.GPS_PHASES:
            return self.gps_pause()
        return super().pause()

    def resume(self):
        if self.phase in self.GPS_PHASES:
            return self.gps_resume()
        return super().resume()

    def cancel(self):
        if self.phase in self.GPS_PHASES:
            return self.gps_cancel()
        return super().cancel()

    def takeoff(self):
        if not self.gps_deploying:
            self.gps_plan_data = None
        try:
            lat, lon, _ = self._position()
            launch = dict(latitude_deg=lat, longitude_deg=lon)
        except (ValueError, KeyError, TypeError):
            launch = None
        result = super().takeoff()
        self.launch_gps = launch
        self.home_return_target = None
        self.home_returning = False
        return result

    def fly(self, north, east):
        self._adopt_completed_gps_hold()
        result = super().fly(north, east)
        self.gps_plan_data = None
        return result

    def return_height(self):
        self._adopt_completed_gps_hold()
        return super().return_height()

    def _adopt_completed_gps_hold(self):
        """Hand a cancelled/completed GPS HOLD back to local NED control."""
        self.refresh()
        if self.phase not in {'GPS_CANCELLED', 'GPS_COMPLETE', 'HOME_COMPLETE'}:
            return
        self._in_air_hold()
        local = self.state('local_ned', self.policy.telemetry_max_age_s)
        target = dict(north_m=number(local['north_m'], 'north_m', -10000, 10000),
                      east_m=number(local['east_m'], 'east_m', -10000, 10000),
                      down_m=number(local['down_m'], 'down_m', -10000, 10000),
                      yaw_deg=number(self.state('yaw_deg', self.policy.telemetry_max_age_s),
                                     'yaw_deg', -180, 180))
        if self.gps_mission_stored:
            self.mission.clear_mission()
            self.gps_mission_stored = False
        self.gps_plan_data = None
        self.target = target
        self.phase = 'HOLD'

    def _position(self):
        p = self.state('position', self.policy.telemetry_max_age_s)
        lat = number(p['latitude_deg'], 'latitude', -90, 90)
        lon = number(p['longitude_deg'], 'longitude', -180, 180)
        rel = number(p['relative_altitude_m'], 'relative_altitude_m', -100, 10000)
        return lat, lon, rel

    def _in_air_hold(self):
        self.require()
        if (self.state('armed') is not True
                or self.state('landed_state', self.policy.telemetry_max_age_s) != 'IN_AIR'
                or self.state('flight_mode') != 'HOLD'):
            raise ValueError('GPS mission requires fresh ARMED, IN_AIR and PX4 HOLD')
        if self.state('health_all_ok') is not True:
            raise ValueError('PX4 health is not ready')
        return self._position()

    def gps_plan(self, start_lat, start_lon, end_lat, end_lon, height_m, speed_m_s):
        """Stage A then B; record current PX4 position to guard plan freshness."""
        self.refresh()
        ground = (self.phase in {'IDLE', 'ARMED'}
                  and self.state('landed_state', self.policy.telemetry_max_age_s) == 'ON_GROUND'
                  and self.state('armed') is (self.phase == 'ARMED'))
        air = (self.phase in {'HOLD', 'GPS_CANCELLED', 'GPS_COMPLETE', 'HOME_COMPLETE'}
               and self.takeoff_complete and not self.external
               and self.state('armed') is True
               and self.state('landed_state', self.policy.telemetry_max_age_s) == 'IN_AIR'
               and self.state('flight_mode') == 'HOLD')
        if not (ground or air):
            raise ValueError('Plan requires ON_GROUND or confirmed in-air HOLD')
        if self.state('health_all_ok') is not True:
            raise ValueError('PX4 health is not ready for a GPS plan')
        if not self.drone.is_connected() or self.termination:
            raise ValueError('PX4 connection or flight state is not ready')
        if ground and self.nav_min_ltr_alt > self.height:
            raise ValueError('NAV_MIN_LTR_ALT exceeds the configured takeoff height')
        lat, lon, _ = self._position()
        start_lat = number(start_lat, 'start_lat', -90, 90)
        start_lon = number(start_lon, 'start_lon', -180, 180)
        end_lat = number(end_lat, 'end_lat', -90, 90)
        end_lon = number(end_lon, 'end_lon', -180, 180)
        height_m = number(height_m, 'height_m', self.height, self.gps_limits.max_height_m)
        speed_m_s = number(speed_m_s, 'speed_m_s', 0.1,
                           min(self.gps_limits.max_speed_m_s, self.px4_xy_vel_max))
        approach = distance_m(lat, lon, start_lat, start_lon)
        leg = distance_m(start_lat, start_lon, end_lat, end_lon)
        if not 0.5 <= approach <= self.gps_limits.max_leg_m:
            raise ValueError('Current-to-A leg is outside the configured distance limit')
        if not 0.5 <= leg <= self.gps_limits.max_leg_m:
            raise ValueError('A-to-B leg is outside the configured distance limit')
        self.gps_plan_data = dict(start_lat=start_lat, start_lon=start_lon,
                                  end_lat=end_lat, end_lon=end_lon,
                                  origin_lat=lat, origin_lon=lon,
                                  height_above_launch_m=height_m,
                                  speed_m_s=speed_m_s, approach_m=approach,
                                  leg_m=leg,
                                  start_in_air=air)
        return dict(self.gps_plan_data)

    def gps_start(self):
        """Deploy A then B: TAKEOFF first on ground; reuse HOLD in air."""
        self.require()
        self.refresh()
        if self.gps_plan_data is None:
            raise ValueError('Deploy requires a staged GPS plan')
        if self.gps_plan_data['start_in_air']:
            if self.phase not in {'HOLD', 'GPS_CANCELLED', 'GPS_COMPLETE', 'HOME_COMPLETE'}:
                raise ValueError('New in-air mission requires confirmed HOLD')
            self._launch_gps_leg()
            return
        if (self.phase not in {'IDLE', 'ARMED'}
                or self.state('landed_state', self.policy.telemetry_max_age_s) != 'ON_GROUND'):
            raise ValueError('Ground plan requires ON_GROUND before deploy')
        lat, lon, _ = self._position()
        if distance_m(lat, lon, self.gps_plan_data['origin_lat'],
                      self.gps_plan_data['origin_lon']) > self.gps_limits.start_error_m:
            raise ValueError('UAV moved away from plan origin before deploy')
        self.gps_deploying = True
        try:
            self.takeoff()
        finally:
            self.gps_deploying = False
        if self.phase != 'TAKEOFF':
            raise RuntimeError('TAKEOFF was not confirmed; GPS leg was not started')
        self.gps_launch_pending = True

    def _launch_gps_leg(self):
        if (self.gps_plan_data is None or self.phase not in {
                'HOLD', 'GPS_CANCELLED', 'GPS_COMPLETE', 'HOME_COMPLETE'}
                or not self.takeoff_complete or self.external):
            raise ValueError('GPS leg requires confirmed in-air HOLD')
        lat, lon, rel = self._in_air_hold()
        plan = self.gps_plan_data
        if distance_m(lat, lon, plan['origin_lat'], plan['origin_lon']) > self.gps_limits.start_error_m:
            raise ValueError('UAV moved away from plan origin since staging')
        if distance_m(lat, lon, plan['start_lat'], plan['start_lon']) > self.gps_limits.max_leg_m:
            raise ValueError('Current-to-A distance exceeds configured limit')
        local = self.state('local_ned', self.policy.telemetry_max_age_s)
        current_above_launch = self.launch_ned['down_m'] - number(
            local['down_m'], 'down_m', -10000, 10000)
        # MAVSDK MissionItem uses altitude above PX4 Home. Convert the desired
        # altitude above this session's launch point using fresh PX4 estimates.
        target_rel = number(rel + plan['height_above_launch_m'] - current_above_launch,
                            'target_relative_altitude_m', 0.5, 100)
        mission_takeoff_min = number(self.param.get_param_float('MIS_TAKEOFF_ALT'),
                                     'MIS_TAKEOFF_ALT', 0, 100)
        if target_rel < mission_takeoff_min:
            raise ValueError('GPS cruise height is below PX4 MIS_TAKEOFF_ALT; '
                             'mission could climb above the selected height')
        first = self.MissionItem(latitude_deg=plan['start_lat'],
                                 longitude_deg=plan['start_lon'],
                                 relative_altitude_m=target_rel,
                                 speed_m_s=plan['speed_m_s'], is_fly_through=False)
        last = self.MissionItem(latitude_deg=plan['end_lat'],
                                longitude_deg=plan['end_lon'],
                                relative_altitude_m=target_rel,
                                speed_m_s=plan['speed_m_s'], is_fly_through=False,
                                loiter_time_s=1.0)
        mission_plan = self.MissionPlan(mission_items=[first, last])
        # This option affects the next upload, so it must precede upload.
        self.mission.set_return_to_launch_after_mission(False)
        self.mission.upload_mission(mission_plan)
        self.gps_mission_stored = True
        self.stop_stream()  # Native PX4 HOLD already owns the vehicle.
        self.gps_epoch = time.monotonic()
        self.gps_finish_hold_requested_at = None
        self.phase = 'GPS_STARTING'
        try:
            self.mission.start_mission()
        except Exception as error:
            self._gps_unconfirmed(f'Start ACK failed: {error}')
            raise

    def return_home(self):
        """Return to the GPS position captured at TAKEOFF and HOLD at current height."""
        self.require()
        self.refresh()
        if (not self.takeoff_complete or self.launch_gps is None
                or self.phase not in {'HOLD', 'GPS_CANCELLED', 'GPS_COMPLETE', 'HOME_COMPLETE'}):
            raise ValueError('Return-home requires completed TAKEOFF, saved launch GPS '
                             'and HOLD after cancel/completion of the current target')
        if (self.state('armed') is not True
                or self.state('landed_state', self.policy.telemetry_max_age_s) != 'IN_AIR'):
            raise ValueError('Return-home requires fresh ARMED and IN_AIR telemetry')
        lat, lon, rel = self._position()
        local = self.state('local_ned', self.policy.telemetry_max_age_s)
        distance = distance_m(lat, lon, self.launch_gps['latitude_deg'],
                              self.launch_gps['longitude_deg'])
        if distance > 2 * self.gps_limits.max_leg_m + self.gps_limits.start_error_m:
            raise ValueError('Launch point exceeds configured return distance limit')
        self._check_hold_altitude()
        speed = (self.gps_plan_data['speed_m_s'] if self.gps_plan_data is not None
                 else min(self.gps_limits.max_speed_m_s, self.px4_xy_vel_max))
        self.home_return_target = {
            'latitude_deg': self.launch_gps['latitude_deg'],
            'longitude_deg': self.launch_gps['longitude_deg'],
            'height_above_launch_m': self.launch_ned['down_m'] - number(
                local['down_m'], 'down_m', -10000, 10000),
            'speed_m_s': speed,
            'distance_m': distance,
            'request_relative_altitude_m': rel,
        }
        self.gps_plan_data = None
        self.gps_launch_pending = False
        self.home_returning = False
        self.home_epoch = time.monotonic()
        self.phase = 'HOME_HOLD_REQUESTED'
        try:
            self.action.hold()
        except Exception as error:
            self.last_error = f'Return-home HOLD ACK failed: {error}; awaiting mode confirmation'
            raise

    def _launch_home_leg(self):
        """Replace the old mission with one launch-position waypoint at held height."""
        lat, lon, rel = self._in_air_hold()
        target = self.home_return_target
        if target is None:
            raise ValueError('Return-home target was lost')
        if distance_m(lat, lon, target['latitude_deg'], target['longitude_deg']) > (
                2 * self.gps_limits.max_leg_m + self.gps_limits.start_error_m):
            raise ValueError('Launch point exceeds configured return distance limit')
        local = self.state('local_ned', self.policy.telemetry_max_age_s)
        current_height = self.launch_ned['down_m'] - number(
            local['down_m'], 'down_m', -10000, 10000)
        target_rel = number(rel + target['height_above_launch_m'] - current_height,
                            'return_relative_altitude_m', 0.5, 100)
        mission_min = number(self.param.get_param_float('MIS_TAKEOFF_ALT'),
                             'MIS_TAKEOFF_ALT', 0, 100)
        if target_rel < mission_min:
            raise ValueError('PX4 MIS_TAKEOFF_ALT would force a climb during return-home')
        if self.gps_mission_stored:
            self.mission.clear_mission()
            self.gps_mission_stored = False
        item = self.MissionItem(latitude_deg=target['latitude_deg'],
                                longitude_deg=target['longitude_deg'],
                                relative_altitude_m=target_rel,
                                speed_m_s=target['speed_m_s'],
                                is_fly_through=False, loiter_time_s=1.0)
        self.mission.set_return_to_launch_after_mission(False)
        self.mission.upload_mission(self.MissionPlan(mission_items=[item]))
        self.gps_mission_stored = True
        self.stop_stream()
        self.gps_epoch = self.home_started_at = time.monotonic()
        self.gps_finish_hold_requested_at = None
        self.home_returning = True
        self.phase = 'GPS_STARTING'
        try:
            self.mission.start_mission()
        except Exception as error:
            self._gps_unconfirmed(f'Return-home start ACK failed: {error}')
            raise

    def _home_completion_confirmed(self, hold_mode_at):
        try:
            lat, lon, _ = self._position()
            local = self.state('local_ned', self.policy.telemetry_max_age_s)
            with self.lock:
                sample_at = min(self.cache['position'][1], self.cache['local_ned'][1])
            if sample_at < hold_mode_at:
                return None
            distance = distance_m(lat, lon, self.home_return_target['latitude_deg'],
                                  self.home_return_target['longitude_deg'])
            height = self.launch_ned['down_m'] - number(
                local['down_m'], 'down_m', -10000, 10000)
            return (distance <= max(2.0, 2 * self.policy.xy_tolerance_m)
                    and abs(height - self.home_return_target['height_above_launch_m'])
                    <= self.policy.z_tolerance_m)
        except (ValueError, KeyError, TypeError):
            return None

    def gps_pause(self):
        self.refresh()
        if self.phase != 'GPS_RUNNING':
            raise ValueError('Pause requires confirmed running GPS mission')
        self.gps_epoch = time.monotonic()
        self.phase = 'GPS_PAUSE_REQUESTED'
        try:
            self.mission.pause_mission()
        except Exception as error:
            self._gps_unconfirmed(f'Pause ACK failed: {error}')
            raise

    def gps_resume(self):
        self.refresh()
        if self.phase != 'GPS_PAUSED' or not self.gps_mission_stored:
            raise ValueError('Resume requires confirmed pause of the same stored mission')
        self._in_air_hold()
        self.gps_epoch = time.monotonic()
        self.gps_finish_hold_requested_at = None
        self.phase = 'GPS_RESUME_REQUESTED'
        try:
            self.mission.start_mission()
            if self.home_returning:
                self.home_started_at = time.monotonic()
        except Exception as error:
            self._gps_unconfirmed(f'Resume ACK failed: {error}')
            raise

    def _check_hold_altitude(self):
        if self.nav_min_ltr_alt > 0:
            rel = self._position()[2]
            if rel < self.nav_min_ltr_alt:
                raise ValueError('NAV_MIN_LTR_ALT would force a climb in HOLD')

    def gps_cancel(self):
        """Stop the A-B leg and clear it after PX4 HOLD at current altitude."""
        self.require()
        self.refresh()
        if self.phase not in {'GPS_STARTING', 'GPS_RUNNING', 'GPS_PAUSE_REQUESTED',
                              'GPS_PAUSED', 'GPS_RESUME_REQUESTED', 'GPS_UNCONFIRMED',
                              'HOME_HOLD_REQUESTED'}:
            raise ValueError('No active GPS mission to cancel')
        self._check_hold_altitude()
        if self.phase in {'GPS_PAUSED', 'HOME_HOLD_REQUESTED'} and self.state('flight_mode') == 'HOLD':
            with self.lock:
                self.gps_epoch = self.cache['flight_mode'][1]
            self.phase = 'GPS_CANCEL_REQUESTED'
            self._gps_finish_cancel()
            return
        self.gps_epoch = time.monotonic()
        self.phase = 'GPS_CANCEL_REQUESTED'
        try:
            self.action.hold()
        except Exception as error:
            self._gps_unconfirmed(f'Cancel HOLD failed: {error}')
            raise

    def _gps_finish_cancel(self):
        """Confirm fresh GPS after HOLD, then clear the old PX4 Mission."""
        try:
            lat, lon, rel = self._in_air_hold()
            with self.lock:
                position_at = self.cache['position'][1]
                mode_at = self.cache['flight_mode'][1]
            if position_at < mode_at:
                return
            self.mission.clear_mission()
            self.gps_mission_stored = False
            self.gps_plan_data = None
            self.home_returning = False
            self.home_return_target = None
            self.gps_cancel_position = dict(latitude_deg=lat, longitude_deg=lon,
                                            relative_altitude_m=rel)
            self.phase = 'GPS_CANCELLED'
        except Exception as error:
            self._gps_unconfirmed(f'Cancel HOLD or clear mission failed: {error}')
            raise

    def _gps_target_height_confirmed(self, hold_mode_at):
        """Check fresh estimated B position and selected height after HOLD."""
        try:
            if self.gps_plan_data is None:
                return False
            lat, lon, _ = self._position()
            local = self.state('local_ned', self.policy.telemetry_max_age_s)
            with self.lock:
                position_at = min(self.cache['local_ned'][1], self.cache['position'][1])
            if position_at < hold_mode_at:
                return None  # Wait for position sampled after entering HOLD.
            above_launch = self.launch_ned['down_m'] - number(
                local['down_m'], 'down_m', -10000, 10000)
            distance = distance_m(lat, lon, self.gps_plan_data['end_lat'],
                                  self.gps_plan_data['end_lon'])
            return (distance <= max(2.0, 2 * self.policy.xy_tolerance_m)
                    and abs(above_launch - self.gps_plan_data['height_above_launch_m'])
                    <= self.policy.z_tolerance_m)
        except (ValueError, KeyError, TypeError):
            return None

    def _gps_unconfirmed(self, reason):
        self.last_error = reason + '; requesting HOLD, inspect mode and position'
        self.phase = 'GPS_UNCONFIRMED'
        try:
            self._check_hold_altitude()
            self.action.hold()
        except Exception as error:
            self.last_error += f'; HOLD failed: {error}'

    def land(self):
        self.gps_plan_data = None
        self.gps_launch_pending = False
        self.home_returning = False
        self.home_return_target = None
        return super().land()

    def disarm(self):
        self.gps_plan_data = None
        self.gps_launch_pending = False
        self.home_returning = False
        self.home_return_target = None
        return super().disarm()

    def refresh(self):
        super().refresh()
        if self.gps_launch_pending:
            if self.phase == 'HOLD':
                self.gps_launch_pending = False
                if self.takeoff_complete and self.hold_reason == 'TARGET_REACHED':
                    try:
                        self._launch_gps_leg()
                    except Exception as error:
                        self.last_error = f'GPS leg did not start after TAKEOFF/HOLD: {error}'
                else:
                    self.last_error = 'TAKEOFF did not reach its target; GPS leg was not started'
            elif self.phase in {'IDLE', 'LAND_REQUESTED', 'LANDING', 'EXTERNAL',
                                'FAULT', 'TERMINATION', 'EMERGENCY_STOP'}:
                self.gps_launch_pending = False
                self.last_error = 'TAKEOFF interrupted; GPS leg was not started'
            return
        if self.phase not in self.GPS_PHASES:
            return
        if not self.drone.is_connected() or self.external:
            self.phase = 'EXTERNAL'
            self.last_error = 'GPS mission mode/link changed; no automatic resume'
            return
        try:
            mode = self.state('flight_mode')
            armed = self.state('armed')
            landed = self.state('landed_state', self.policy.telemetry_max_age_s)
            with self.lock:
                mode_at = self.cache['flight_mode'][1]
        except ValueError:
            return
        if armed is False and landed == 'ON_GROUND':
            self.phase = 'IDLE'
            self.gps_plan_data = None
            self.takeoff_complete = False
            return
        expected_modes = ({'OFFBOARD', 'MISSION', 'HOLD'}
                          if self.phase in {'HOME_HOLD_REQUESTED', 'GPS_CANCEL_REQUESTED'}
                          else {'MISSION', 'HOLD'})
        if armed is not True or landed != 'IN_AIR' or mode not in expected_modes:
            self.phase = 'EXTERNAL'
            self.last_error = 'PX4 left the expected GPS mission state'
            return
        if self.phase == 'HOME_HOLD_REQUESTED':
            if mode == 'HOLD' and mode_at >= self.home_epoch:
                try:
                    self._launch_home_leg()
                except Exception as error:
                    self._gps_unconfirmed(f'Return-home mission did not start: {error}')
            elif time.monotonic() - self.home_epoch > self.gps_limits.confirmation_s:
                self._gps_unconfirmed('Return-home HOLD mode confirmation timed out')
            return
        if (self.phase == 'GPS_RUNNING' and self.home_returning
                and self.home_started_at is not None
                and time.monotonic() - self.home_started_at > self.policy.target_timeout_s):
            self._gps_unconfirmed('Return-home target deadline exceeded')
            return
        if self.phase in {'GPS_STARTING', 'GPS_RESUME_REQUESTED'} and mode == 'MISSION':
            if mode_at >= self.gps_epoch:
                self.phase = 'GPS_RUNNING'
        elif self.phase == 'GPS_PAUSE_REQUESTED' and mode == 'HOLD':
            if mode_at >= self.gps_epoch:
                self.phase = 'GPS_PAUSED'
        elif self.phase == 'GPS_CANCEL_REQUESTED' and mode == 'HOLD':
            if mode_at >= self.gps_epoch:
                self._gps_finish_cancel()
        elif self.phase == 'GPS_RUNNING' and mode == 'HOLD':
            try:
                finished = self.mission.is_mission_finished()
            except Exception as error:
                self.last_error = f'Cannot verify mission completion: {error}'
                return
            if finished:
                verified = (self._home_completion_confirmed(mode_at) if self.home_returning
                            else self._gps_target_height_confirmed(mode_at))
                if verified is True:
                    self.phase = 'HOME_COMPLETE' if self.home_returning else 'GPS_COMPLETE'
                    self.home_returning = False
                elif verified is False:
                    self.phase = 'GPS_UNCONFIRMED'
                    self.last_error = ('Return-home finished/HOLD but launch position or '
                                       'held height is outside tolerance' if self.home_returning else
                                       'PX4 finished mission/HOLD but B position or selected height is outside tolerance')
                elif self.gps_hold_seen_at is None:
                    self.gps_hold_seen_at = time.monotonic()
                elif time.monotonic() - self.gps_hold_seen_at > self.gps_limits.confirmation_s:
                    self.phase = 'GPS_UNCONFIRMED'
                    self.last_error = ('Return-home finished/HOLD but fresh position was not received'
                                       if self.home_returning else
                                       'Mission finished/HOLD but fresh height estimate was not received')
            elif self.gps_hold_seen_at is None:
                self.gps_hold_seen_at = time.monotonic()
            elif time.monotonic() - self.gps_hold_seen_at > 3:
                self.phase = 'EXTERNAL'
                self.last_error = 'Uncommanded HOLD before mission completion'
        elif self.phase == 'GPS_RUNNING' and mode == 'MISSION':
            self.gps_hold_seen_at = None
            if self.gps_finish_hold_requested_at is not None:
                if (time.monotonic() - self.gps_finish_hold_requested_at
                        > self.gps_limits.confirmation_s):
                    self._gps_unconfirmed('Finished mission did not enter HOLD')
            else:
                try:
                    finished = self.mission.is_mission_finished()
                    if finished:
                        self._check_hold_altitude()
                        self.gps_finish_hold_requested_at = time.monotonic()
                        self.action.hold()
                except Exception as error:
                    self._gps_unconfirmed(f'Cannot confirm finished Mission/HOLD: {error}')
        elif self.phase in {'GPS_PAUSED', 'GPS_CANCELLED', 'GPS_COMPLETE',
                            'HOME_COMPLETE'} and mode != 'HOLD':
            self.phase = 'EXTERNAL'
            self.last_error = 'PX4 left HOLD without a Pi command'
        if (self.phase in self.PENDING and self.gps_epoch is not None
                and time.monotonic() - self.gps_epoch > self.gps_limits.confirmation_s):
            self._gps_unconfirmed('GPS command mode confirmation timed out')

    def status(self):
        result = super().status()
        available_hold = {'GPS_CANCELLED', 'GPS_COMPLETE', 'HOME_COMPLETE'}
        if self.phase in available_hold:
            try:
                can_target = (self.takeoff_complete and not self.external
                              and self.state('armed') is True
                              and self.state('flight_mode') == 'HOLD'
                              and self.state('landed_state', self.policy.telemetry_max_age_s) == 'IN_AIR'
                              and self.state('health_all_ok') is True)
            except ValueError:
                can_target = False
            result['can_send_target'] = can_target
            result['coordinates_enabled'] = can_target
        if self.phase in self.GPS_PHASES - available_hold:
            result['target_locked'] = True
        elif self.phase in available_hold:
            result['target_locked'] = False
        result['gps_mission'] = {
            'phase': self.phase if self.phase in self.GPS_PHASES else None,
            'plan': self.gps_plan_data,
            'waiting_for_takeoff_hold': self.gps_launch_pending,
            'uploaded_this_session': self.gps_mission_stored,
            'last_cancel_position': self.gps_cancel_position,
            'launch_gps': self.launch_gps,
            'return_home_target': self.home_return_target,
            'returning_home': self.home_returning or self.phase == 'HOME_HOLD_REQUESTED',
            'return_position_confirmed': self.phase == 'HOME_COMPLETE',
            'limits': vars(self.gps_limits),
            'px4_xy_vel_max_m_s': self.px4_xy_vel_max,
            'source': 'PX4 Mission; completion requires mission-finished, HOLD and fresh target position/height',
        }
        return result

    def close(self):
        try:
            if self.mission is not None:
                self.mission.destroy()
                self.mission = None
        finally:
            super().close()
