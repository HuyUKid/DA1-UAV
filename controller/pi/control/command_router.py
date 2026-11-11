"""Forward validated web commands to the sole Flight Service."""


WEB_COMMANDS = {'gps_start', 'pause', 'resume', 'cancel', 'return_home', 'land'}


class ControlRouter:
    """Keep MQTT processing separate from the MAVSDK owner."""

    def __init__(self, flight_client):
        self.flight = flight_client

    def dispatch(self, command):
        if command.get('type') not in WEB_COMMANDS:
            raise ValueError('Unsupported web command')
        return self.flight.request({'op': 'command', 'command': command})
