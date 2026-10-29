"""Cooperative serial ownership lock for this controller (Linux/Pi).

This does not detect unrelated applications opening the UART. Give a serial
device to a single MAVLink process; use routing for additional consumers.
"""
import fcntl
import hashlib
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def serial_ownership(device):
    key = hashlib.sha256(str(Path(device).resolve()).encode()).hexdigest()[:24]
    with open(f'/tmp/uav-serial-{key}.lock', 'a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError(f'Another controller owns serial device: {device}') from None
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


@contextmanager
def udp_ownership(endpoint):
    """Prevent two cooperating consoles from taking the same local HIL port.

    Unrelated observers do not share this lock; use one consumer on UDP 14540.
    """
    key = hashlib.sha256(endpoint.encode()).hexdigest()[:24]
    with open(f'/tmp/uav-udp-{key}.lock', 'a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError(f'Another controller owns UDP endpoint: {endpoint}') from None
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
