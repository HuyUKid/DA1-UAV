#!/usr/bin/env python3
"""Merge Pi control/flight JSONL logs into one chronological JSONL or CSV."""
import argparse
import csv
import heapq
import json
from pathlib import Path


COLUMNS = (
    'ts_utc', 'service', 'severity', 'record_type', 'event', 'message',
    'command_id', 'mission_id', 'phase_before', 'phase_after',
    'cpu_percent', 'ram_used_bytes', 'ram_available_bytes',
    'swap_used_bytes', 'temperature_c', 'disk_used_bytes',
    'disk_available_bytes', 'uptime_s', 'process_max_rss_kib',
    'px4_mode', 'armed',
    'landed_state', 'session_id', 'boot_id',
)


def records_from(path):
    with path.open(encoding='utf-8') as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f'{path}:{line_number}: invalid JSON: {error}') from error
            if not isinstance(record, dict) or 'ts_utc' not in record:
                raise ValueError(f'{path}:{line_number}: missing ts_utc object')
            yield record


def merged_records(paths):
    return heapq.merge(*(records_from(path) for path in paths),
                       key=lambda record: record['ts_utc'])


def csv_row(record):
    metrics = record.get('metrics') or {}
    memory = metrics.get('memory') or {}
    disk = metrics.get('disk') or {}
    process = metrics.get('process') or {}
    details = record.get('details') or {}
    telemetry = (record.get('status') or {}).get('telemetry') or {}

    def telemetry_value(name):
        item = telemetry.get(name) or {}
        return item.get('value') if isinstance(item, dict) else None

    values = dict(record)
    values.update({
        'cpu_percent': metrics.get('cpu_percent'),
        'ram_used_bytes': memory.get('used_bytes'),
        'ram_available_bytes': memory.get('available_bytes'),
        'swap_used_bytes': memory.get('swap_used_bytes'),
        'temperature_c': metrics.get('temperature_c'),
        'disk_used_bytes': disk.get('used_bytes'),
        'disk_available_bytes': disk.get('available_bytes'),
        'uptime_s': metrics.get('uptime_s'),
        'process_max_rss_kib': process.get('max_rss_kib'),
        'px4_mode': details.get('flight_mode') or telemetry_value('flight_mode'),
        'armed': details.get('armed') if 'armed' in details else telemetry_value('armed'),
        'landed_state': (details.get('landed_state')
                         or telemetry_value('landed_state')),
    })
    return {name: values.get(name) for name in COLUMNS}


def export(paths, output, output_format):
    if not paths:
        raise ValueError('No service JSONL logs found')
    # Exclusive creation prevents replacing an earlier investigation export.
    with Path(output).open('x', encoding='utf-8', newline='') as target:
        if output_format == 'csv':
            writer = csv.DictWriter(target, fieldnames=COLUMNS)
            writer.writeheader()
            for record in merged_records(paths):
                writer.writerow(csv_row(record))
        else:
            for record in merged_records(paths):
                target.write(json.dumps(record, ensure_ascii=False,
                                        allow_nan=False) + '\n')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--log-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--format', choices=['jsonl', 'csv'], default='csv')
    args = parser.parse_args(argv)
    paths = sorted((*args.log_dir.glob('control-*.jsonl'),
                    *args.log_dir.glob('flight-*.jsonl')))
    try:
        export(paths, args.output, args.format)
    except (OSError, ValueError) as error:
        parser.exit(1, f'Export failed: {error}\n')
    print(f'Exported {len(paths)} service log files to {args.output}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
