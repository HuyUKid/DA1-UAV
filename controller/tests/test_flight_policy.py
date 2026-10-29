from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pi"))

import unittest
from dataclasses import replace
from flight.flight_policy import ArrivalMonitor, FlightPolicy


class ArrivalTests(unittest.TestCase):
    def setUp(self):
        self.policy = FlightPolicy(settle_s=1.0)
        self.monitor = ArrivalMonitor(self.policy)
        self.target = dict(north_m=1.0, east_m=2.0, down_m=-2.0, yaw_deg=179.0)
        self.p = {k: self.target[k] for k in ('north_m', 'east_m', 'down_m')}

    def observe(self, t, now=None, p=None, yaw=179.0):
        return self.monitor.observe(self.target, self.p if p is None else p, yaw,
                                    t, t if now is None else now)

    def test_fresh_samples_dwell_then_complete(self):
        for i in range(5):
            self.assertFalse(self.observe(i * 0.2))
        self.assertTrue(self.observe(1.0))

    def test_polling_cached_sample_never_completes(self):
        self.assertFalse(self.observe(0))
        for i in range(1, 10):
            self.assertFalse(self.observe(0, now=i * 0.1))
        self.assertFalse(self.observe(0, now=2.0))
        self.assertIsNone(self.monitor.since)

    def test_gap_resets_dwell(self):
        self.observe(0)
        self.observe(0.4)
        self.assertFalse(self.observe(1.1))
        self.assertEqual(self.monitor.since, 1.1)

    def test_outside_position_or_yaw_resets_dwell(self):
        for p, yaw in [(dict(self.p, north_m=3), 179), (dict(self.p, down_m=-1), 179),
                       (self.p, 90)]:
            with self.subTest(p=p, yaw=yaw):
                self.monitor.reset()
                self.observe(0)
                self.observe(0.4)
                self.assertFalse(self.observe(0.6, p=p, yaw=yaw))
                self.assertIsNone(self.monitor.since)
                self.assertFalse(self.observe(0.8))

    def test_yaw_wrap_is_two_degrees_not_358(self):
        self.observe(0, yaw=-179)
        self.assertAlmostEqual(self.monitor.errors['yaw_deg'], 2)
        self.assertEqual(self.monitor.since, 0)

    def test_future_stale_nan_and_inf_samples_reset(self):
        for stamp, now, p, yaw in [(2, 0, self.p, 179), (0, 2, self.p, 179),
                                  (0, 0, dict(self.p, east_m=float('nan')), 179),
                                  (0, 0, self.p, float('inf'))]:
            with self.subTest(stamp=stamp, now=now, p=p, yaw=yaw):
                self.observe(0)
                self.assertFalse(self.observe(stamp, now=now, p=p, yaw=yaw))
                self.assertIsNone(self.monitor.since)

    def test_out_of_order_samples_cannot_complete(self):
        self.observe(1)
        self.observe(1.4)
        self.assertFalse(self.observe(1.2))

    def test_large_jump_into_target_requires_full_new_dwell(self):
        self.observe(0, p=dict(self.p, east_m=10))
        self.assertFalse(self.observe(0.2))
        self.assertFalse(self.observe(0.6))
        self.assertFalse(self.observe(1.0))
        self.assertTrue(self.observe(1.4))

    def test_policy_validation_and_defaults(self):
        self.assertEqual(FlightPolicy().settle_s, 2.0)
        for key, value in [('xy_tolerance_m', 0), ('z_tolerance_m', float('nan')),
                           ('yaw_tolerance_deg', float('inf')), ('settle_s', -1),
                           ('target_timeout_s', True), ('sample_gap_s', 2)]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                replace(self.policy, **{key: value})
        with self.assertRaises(ValueError):
            FlightPolicy(settle_s=10, target_timeout_s=5)
        with self.assertRaises(ValueError):
            FlightPolicy(telemetry_max_age_s=0.2, sample_gap_s=0.6)

    def test_both_horizontal_axes_share_a_radial_tolerance(self):
        for dx, dy, inside in [(0.6, 0, False), (0, 0.6, False),
                               (0.4, 0.4, False), (0.3, -0.3, True)]:
            with self.subTest(dx=dx, dy=dy):
                self.monitor.reset()
                p = dict(self.p, north_m=self.p['north_m'] + dx,
                         east_m=self.p['east_m'] + dy)
                for i in range(7):
                    complete = self.observe(i * 0.2, p=p)
                self.assertEqual(complete, inside)


if __name__ == '__main__':
    unittest.main()
