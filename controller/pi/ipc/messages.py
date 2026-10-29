"""Bounded JSON-line messages shared by IPC client and server."""

import json

MAX_MESSAGE_BYTES = 64 * 1024


def encode(value):
    return (json.dumps(value, separators=(',', ':'), allow_nan=False) + '\n').encode()


def receive_line(connection):
    data = bytearray()
    while b'\n' not in data:
        chunk = connection.recv(4096)
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > MAX_MESSAGE_BYTES:
            raise ValueError('IPC message exceeds 64 KiB')
    if not data:
        raise ValueError('Empty IPC request')
    return json.loads(bytes(data).split(b'\n', 1)[0].decode('utf-8'))
