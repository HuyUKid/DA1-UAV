"""The legacy MQTT monitor accepts fields but cannot trigger a flight."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'pi'))
from control.monitor import parse_control, parse_controls


class MqttMonitorTests(unittest.TestCase):
    def test_accepts_six_legacy_fields(self):
        for field, value in {
                'startlat': 47.397776, 'startlong': 8.545605,
                'endlat': 47.39781, 'endlong': 8.54565,
                'height': 10, 'spd': 0.5}.items():
            with self.subTest(field=field):
                self.assertEqual(parse_control(f'c:{field}:{value};'.encode()),
                                 (field, float(value)))

    def test_rejects_invalid_and_nonfinite_commands(self):
        for payload in (b'c:startlat:91;', b'c:endlong:181;', b'c:height:nan;',
                        b'c:spd:11;', b'c:arm:1;', b'c:startlat:1;garbage',
                        b'c:startlat:1;c:endlat:2;', b'c:startlat:1', b'\xff'):
            with self.subTest(payload=payload), self.assertRaises((ValueError, UnicodeError)):
                parse_control(payload)

    def test_accepts_web_bundle_as_one_message(self):
        payload = (b'c:spd:0.5;c:height:3;c:startlat:47.3977760;'
                   b'c:startlong:8.5456050;c:endlat:47.3978100;'
                   b'c:endlong:8.5456500;')
        self.assertEqual(parse_controls(payload), (
            ('spd', 0.5), ('height', 3.0), ('startlat', 47.397776),
            ('startlong', 8.545605), ('endlat', 47.39781),
            ('endlong', 8.54565)))
        self.assertEqual(parse_controls(b'c:startlat:47.397776;'),
                         (('startlat', 47.397776),))

    def test_rejects_invalid_bundle_without_partial_results(self):
        for payload in (b'c:spd:0.5;c:height:3',
                        b'c:spd:0.5;c:height:101;',
                        b'c:spd:0.5;c:spd:0.4;',
                        b'c:spd:0.5;;',
                        b'c:spd:0.5;c:arm:1;',
                        b'c:spd:0.5;garbage;',
                        b'c:spd:0.5;\xff'):
            with self.subTest(payload=payload), self.assertRaises((ValueError, UnicodeError)):
                parse_controls(payload)


if __name__ == '__main__':
    unittest.main()
