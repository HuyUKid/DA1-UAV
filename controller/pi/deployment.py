"""Connection validation only; does not tune or write PX4 parameters."""
import re
from pathlib import Path


def validate_connection(profile, connection):
    if profile not in {'hitl', 'hardware'}:
        raise ValueError('Expected hardware or hitl profile')
    match = re.fullmatch(r'serial://(/dev/[^:]+):([0-9]+)', connection)
    if not match or int(match[2]) <= 0:
        raise ValueError('HITL/hardware requires serial:///dev/DEVICE:BAUD')
    return str(Path(match[1]).resolve())
