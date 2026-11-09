"""Forward the validated web GPS command to the sole Flight Service."""


class ControlRouter:
    """Keep MQTT processing separate from the MAVSDK owner."""

    def __init__(self, flight_client):
        self.flight = flight_client

    def dispatch(self, command):
        if command.get('type') != 'gps_start':
            raise ValueError('Only the validated GPS start command is supported')
        return self.flight.request({'op': 'command', 'command': command})
