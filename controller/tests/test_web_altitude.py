"""External telemetry integration: no flight calls and no fabricated web altitude."""
import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'pi'))
from observability.web_altitude import FlightAltitudeReader, launch_height_fields


class WebAltitudeTests(unittest.TestCase):
    def setUp(self):
        self.status = {'connected': True, 'launch_ned': {'down_m': 5.231},
                       'height_above_launch_m': 2.0,
                       'telemetry': {'local_ned': {'age_s': 0.1, 'value': {'down_m': 3.231}},
                                     'position': {'value': {'relative_altitude_m': -19.4}}}}

    def test_home_altitude_drift_does_not_change_launch_height(self):
        first = launch_height_fields(self.status)
        self.status['telemetry']['position']['value']['relative_altitude_m'] = 9.9
        self.assertEqual(launch_height_fields(self.status), first)
        self.assertEqual(first['height_above_launch_m'], 2.0)
        self.assertTrue(first['height_above_launch_valid'])

    def test_zero_and_negative_estimated_height_are_preserved(self):
        for height in (0.0, -0.2, 3.5):
            with self.subTest(height=height):
                self.status['height_above_launch_m'] = height
                self.status['telemetry']['local_ned']['value']['down_m'] = 5.231 - height
                self.assertEqual(launch_height_fields(self.status)['height_above_launch_m'], height)

    def test_invalid_or_stale_height_is_unknown_without_fallback(self):
        for kind in ('offline', 'no_launch', 'stale', 'future', 'nan', 'bool', 'missing_local', 'mismatch'):
            with self.subTest(kind=kind):
                status = copy.deepcopy(self.status)
                if kind == 'offline':
                    status['connected'] = False
                elif kind == 'no_launch':
                    status['launch_ned'] = None
                elif kind in ('stale', 'future'):
                    status['telemetry']['local_ned']['age_s'] = 1.1 if kind == 'stale' else -1
                elif kind in ('nan', 'bool'):
                    status['height_above_launch_m'] = float('nan') if kind == 'nan' else True
                elif kind == 'missing_local':
                    status['telemetry'] = {}
                else:
                    status['height_above_launch_m'] = 8.0
                result = launch_height_fields(status)
                self.assertIsNone(result['height_above_launch_m'])
                self.assertFalse(result['height_above_launch_valid'])

    def test_reader_requests_only_status_and_does_not_reuse_old_height(self):
        reader = FlightAltitudeReader()
        reader.client = Mock()
        reader.client.request.side_effect = [
            {'ok': True, 'status': self.status}, TimeoutError(),
            {'ok': False, 'error': 'unavailable'}]
        self.assertEqual(reader.snapshot()['height_above_launch_m'], 2.0)
        self.assertIsNone(reader.snapshot()['height_above_launch_m'])
        self.assertIsNone(reader.snapshot()['height_above_launch_m'])
        for call in reader.client.request.call_args_list:
            self.assertEqual(call.args, ({'op': 'status'},))
