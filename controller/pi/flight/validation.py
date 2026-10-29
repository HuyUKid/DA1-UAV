"""Numeric validation shared by the local-NED controller and flight policy."""
import math


def number(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'{name} must be numeric')
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'{name} must be in {low}..{high}')
    return value
