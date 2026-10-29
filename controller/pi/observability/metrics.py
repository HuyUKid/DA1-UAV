"""Dependency-free Pi/Linux host metrics with explicit unavailable values."""
import os
import resource
import time
from pathlib import Path


def _read(path):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return None


class HostMetrics:
    def __init__(self):
        self._previous_cpu = None

    def _cpu_percent(self):
        line = _read('/proc/stat')
        if not line:
            return None
        values = [int(value) for value in line.splitlines()[0].split()[1:]]
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        total = sum(values)
        current = (idle, total)
        previous, self._previous_cpu = self._previous_cpu, current
        if previous is None or total == previous[1]:
            return None
        return round(100 * (1 - (idle - previous[0]) / (total - previous[1])), 2)

    @staticmethod
    def _memory():
        text = _read('/proc/meminfo')
        if not text:
            return {'total_bytes': None, 'available_bytes': None, 'used_bytes': None,
                    'swap_total_bytes': None, 'swap_used_bytes': None}
        values = {line.split(':', 1)[0]: int(line.split()[1]) * 1024
                  for line in text.splitlines() if ':' in line}
        total, available = values.get('MemTotal'), values.get('MemAvailable')
        swap_total, swap_free = values.get('SwapTotal'), values.get('SwapFree')
        return {'total_bytes': total, 'available_bytes': available,
                'used_bytes': total - available if total is not None and available is not None else None,
                'swap_total_bytes': swap_total,
                'swap_used_bytes': (swap_total - swap_free
                                    if swap_total is not None and swap_free is not None else None)}

    @staticmethod
    def _temperature():
        raw = _read('/sys/class/thermal/thermal_zone0/temp')
        try:
            return round(float(raw) / 1000, 2)
        except (TypeError, ValueError):
            return None

    def snapshot(self, disk_path='/'):
        usage = os.statvfs(disk_path)
        uptime = _read('/proc/uptime')
        disk_total = usage.f_blocks * usage.f_frsize
        disk_free = usage.f_bfree * usage.f_frsize
        disk_available = usage.f_bavail * usage.f_frsize
        return {
            'observed_monotonic_ms': round(time.monotonic() * 1000),
            'boot_id': _read('/proc/sys/kernel/random/boot_id') or 'unavailable',
            'cpu_percent': self._cpu_percent(), 'load_1m': round(os.getloadavg()[0], 2),
            'memory': self._memory(), 'temperature_c': self._temperature(),
            'disk': {'total_bytes': disk_total,
                     'used_bytes': disk_total - disk_free,
                     'free_bytes': disk_free,
                     'available_bytes': disk_available},
            'uptime_s': float(uptime.split()[0]) if uptime else None,
            'process': {'pid': os.getpid(),
                        'max_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss},
        }
