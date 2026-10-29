"""Arrival supervision only. PX4 retains all flight-control loops."""
from dataclasses import dataclass
import math
from flight.validation import number


@dataclass(frozen=True)
class FlightPolicy:
    xy_tolerance_m: float = 0.5
    z_tolerance_m: float = 0.3
    yaw_tolerance_deg: float = 10.0
    settle_s: float = 2.0
    target_timeout_s: float = 60.0
    telemetry_max_age_s: float = 1.0
    sample_gap_s: float = 0.6

    def __post_init__(self):
        for key, low, high in (
            ('xy_tolerance_m', 0.1, 5), ('z_tolerance_m', 0.05, 2),
            ('yaw_tolerance_deg', 1, 45), ('settle_s', 0.5, 30),
            ('target_timeout_s', 5, 600), ('telemetry_max_age_s', 0.2, 3),
            ('sample_gap_s', 0.2, 1.0),
        ):
            number(getattr(self, key), key, low, high)
        if self.target_timeout_s <= self.settle_s:
            raise ValueError('target_timeout_s must exceed settle_s')
        if self.sample_gap_s > self.telemetry_max_age_s:
            raise ValueError('sample_gap_s must not exceed telemetry_max_age_s')


class ArrivalMonitor:
    def __init__(self, policy):
        self.policy = policy
        self.reset()

    def reset(self):
        self.since = None
        self.last_sample = None
        self.errors = None

    def observe(self, target, position, yaw, sample_at, now):
        """Require successive fresh position/yaw samples; never use velocity."""
        values = [position[k] for k in ('north_m', 'east_m', 'down_m')]
        if (not all(math.isfinite(v) for v in values + [yaw])
                or not 0 <= now - sample_at <= self.policy.telemetry_max_age_s):
            self.reset()
            return False
        xy = math.hypot(position['north_m'] - target['north_m'],
                        position['east_m'] - target['east_m'])
        z = abs(position['down_m'] - target['down_m'])
        yaw_error = abs((yaw - target['yaw_deg'] + 180) % 360 - 180)
        self.errors = dict(xy_m=xy, z_m=z, yaw_deg=yaw_error)
        inside = (xy <= self.policy.xy_tolerance_m and z <= self.policy.z_tolerance_m
                  and yaw_error <= self.policy.yaw_tolerance_deg)
        if not inside:
            self.since = None
        if self.last_sample is not None and sample_at <= self.last_sample:
            return False  # Polling the same cached sample cannot finish HOLD.
        if self.last_sample is None or sample_at - self.last_sample > self.policy.sample_gap_s:
            self.since = None
        self.last_sample = sample_at
        if not inside:
            return False
        if self.since is None:
            self.since = sample_at
        return sample_at - self.since >= self.policy.settle_s
