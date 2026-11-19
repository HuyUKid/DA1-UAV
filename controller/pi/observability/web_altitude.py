"""Read launch-relative height for an external telemetry publisher, without MAVLink.

Keep GLOBAL_POSITION_INT.relative_alt as altitude_relative (above PX4 Home).
Publish the additional fields returned here and explicitly map the web display
and history to height_above_launch_m. No fallback or sign correction is applied.
"""
import math

from ipc.client import RpcClient


def finite(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def launch_height_fields(status):
    """Return unknown if the launch reference or fresh local position is missing."""
    fields = {'height_above_launch_m': None,
              'height_above_launch_valid': False,
              'height_above_launch_source': None}
    if not isinstance(status, dict) or status.get('connected') is not True:
        return fields
    launch = status.get('launch_ned')
    if not isinstance(launch, dict) or not finite(launch.get('down_m')):
        return fields
    telemetry = status.get('telemetry')
    if not isinstance(telemetry, dict):
        return fields
    local = telemetry.get('local_ned')
    if not isinstance(local, dict):
        return fields
    age, position = local.get('age_s'), local.get('value')
    # Bound display freshness independently of a long controller timeout.
    if not finite(age) or not 0 <= age <= 1.0 or not isinstance(position, dict):
        return fields
    if not finite(position.get('down_m')):
        return fields
    height = status.get('height_above_launch_m')
    if not finite(height):
        return fields
    expected = launch['down_m'] - position['down_m']
    if not math.isclose(height, expected, rel_tol=1e-9, abs_tol=1e-6):
        return fields
    fields.update(height_above_launch_m=height,
                  height_above_launch_valid=True,
                  height_above_launch_source='flight_service_local_ned')
    return fields


class FlightAltitudeReader:
    """Poll the local Flight Service once per publisher snapshot; never cache height."""

    def __init__(self, socket_path='/tmp/uav-flight.sock', timeout=0.2):
        self.client = RpcClient(socket_path, timeout=timeout)

    def snapshot(self):
        try:
            response = self.client.request({'op': 'status'})
            if isinstance(response, dict) and response.get('ok') is True:
                return launch_height_fields(response.get('status'))
        except (OSError, ValueError, UnicodeError):
            pass
        return launch_height_fields(None)
