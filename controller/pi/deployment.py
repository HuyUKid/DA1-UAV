"""Connection validation only; does not tune or write PX4 parameters."""
import re
from pathlib import Path


def validate_connection(profile, connection):
    if profile not in {'hitl', 'hardware'}:
        raise ValueError('Expected hardware or hitl profile')
    udp = re.fullmatch(r'udpin://127\.0\.0\.1:([0-9]+)', connection)
    if profile == 'hitl' and udp and 1 <= int(udp[1]) <= 65535:
        return f'udpin://127.0.0.1:{int(udp[1])}'
    match = re.fullmatch(r'serial://(/dev/[^:]+):([0-9]+)', connection)
    if not match or int(match[2]) <= 0:
        raise ValueError('Use serial:///dev/DEVICE:BAUD; HITL on PC also accepts udpin://127.0.0.1:PORT')
    return str(Path(match[1]).resolve())
