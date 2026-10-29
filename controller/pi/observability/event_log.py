"""Append-only JSON Lines event log for Pi services."""
import json
import math
import os
import time
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

IMPORTANT_EVENTS = {'ARM_REQUESTED', 'ARM_CONFIRMED', 'LAND_REQUESTED',
                    'LAND_CONFIRMED', 'DISARM_REQUESTED', 'DISARM_CONFIRMED',
                    'COMMAND_REQUESTED', 'COMMAND_ACCEPTED', 'FLIGHT_STATE_CHANGED'}


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def boot_id():
    try:
        return Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    except OSError:
        return 'unavailable'


class EventLog:
    """Writes one JSON object per line and rotates without deleting old files."""

    def __init__(self, directory, service, session_id=None, max_bytes=20 * 1024 * 1024):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.service = service
        self.session_id = session_id or uuid.uuid4().hex
        self.boot_id = boot_id()
        self.max_bytes = max_bytes
        self.sequence = 0
        self._lock = threading.RLock()
        self._debug_until = {}
        self._last_debug_at = {}
        self._file = None
        self.path = None
        self._open()

    def _open(self):
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
        suffix = f'-{self.sequence}' if self.sequence else ''
        self.path = self.directory / f'{self.service}-{stamp}{suffix}.jsonl'
        self._file = self.path.open('a', encoding='utf-8')

    def _rotate(self):
        if self._file.tell() < self.max_bytes:
            return
        self._file.flush()
        self._file.close()
        self.sequence += 1
        self._open()

    def write(self, event, message='', severity='INFO', record_type='event', **fields):
        with self._lock:
            self._rotate()
            record = {'ts_utc': utc_now(), 'monotonic_ms': round(time.monotonic() * 1000),
                      'boot_id': self.boot_id, 'session_id': self.session_id,
                      'service': self.service, 'record_type': record_type,
                      'severity': severity, 'event': event, 'message': message}
            record.update(fields)
            encoded = json.dumps(record, separators=(',', ':'),
                                 ensure_ascii=False, allow_nan=False) + '\n'
            self._file.write(encoded)
            self._file.flush()
            if severity in {'ERROR', 'CRITICAL'} or event in IMPORTANT_EVENTS:
                os.fsync(self._file.fileno())
            return record

    def set_debug(self, module, enabled, duration_s=600):
        if module not in {'mqtt', 'control', 'flight', 'pixhawk', 'camera',
                          'ota', 'health'}:
            raise ValueError('Unsupported debug module')
        if not isinstance(enabled, bool):
            raise ValueError('enabled must be boolean')
        if (not isinstance(duration_s, (int, float)) or isinstance(duration_s, bool)
                or not math.isfinite(duration_s) or not 1 <= duration_s <= 3600):
            raise ValueError('duration_s must be 1..3600 seconds')
        with self._lock:
            self._debug_until[module] = time.monotonic() + duration_s if enabled else 0.0
            return self.write('DEBUG_CONFIG_CHANGED', f'{module} debug={enabled}',
                              module=module, enabled=enabled, duration_s=duration_s)

    def debug(self, module, event, message='', **fields):
        with self._lock:
            now = time.monotonic()
            if now >= self._debug_until.get(module, 0.0):
                return None
            key = (module, event)
            if now - self._last_debug_at.get(key, 0.0) < 1.0:
                return None
            self._last_debug_at[key] = now
            return self.write(event, message, severity='DEBUG', module=module, **fields)

    def close(self):
        with self._lock:
            if self._file is not None:
                self._file.flush()
                self._file.close()
                self._file = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
