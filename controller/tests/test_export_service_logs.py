"""Merged service log export preserves time order and health columns."""
import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'pi'))
from observability.export_logs import export


class ExportServiceLogsTests(unittest.TestCase):
    def test_csv_merges_services_and_flattens_metrics(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            control = root / 'control-a.jsonl'
            flight = root / 'flight-a.jsonl'
            control.write_text(json.dumps({
                'ts_utc': '2026-10-29T00:00:02Z', 'service': 'control',
                'event': 'HOST_HEALTH', 'metrics': {
                    'cpu_percent': 25, 'memory': {'used_bytes': 100,
                                                  'available_bytes': 200,
                                                  'swap_used_bytes': 10},
                    'temperature_c': 45, 'disk': {'used_bytes': 250,
                                                  'available_bytes': 300},
                    'uptime_s': 123, 'process': {'max_rss_kib': 456}},
            }) + '\n')
            flight.write_text(json.dumps({
                'ts_utc': '2026-10-29T00:00:01Z', 'service': 'flight',
                'event': 'COMMAND_REQUESTED', 'command_id': 'cmd-1',
            }) + '\n')
            output = root / 'combined.csv'
            export([control, flight], output, 'csv')
            with output.open(newline='') as source:
                rows = list(csv.DictReader(source))
            self.assertEqual([row['event'] for row in rows],
                             ['COMMAND_REQUESTED', 'HOST_HEALTH'])
            self.assertEqual(rows[0]['command_id'], 'cmd-1')
            self.assertEqual(rows[1]['cpu_percent'], '25')
            self.assertEqual(rows[1]['ram_used_bytes'], '100')
            self.assertEqual(rows[1]['swap_used_bytes'], '10')
            self.assertEqual(rows[1]['disk_used_bytes'], '250')
            self.assertEqual(rows[1]['process_max_rss_kib'], '456')
            with self.assertRaises(FileExistsError):
                export([control, flight], output, 'csv')


if __name__ == '__main__':
    unittest.main()
