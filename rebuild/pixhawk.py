from mavsdk import Mavsdk, Configuration, ComponentType, ConnectionResult
from mavsdk.plugins.telemetry import Telemetry
from mavsdk.plugins.param import Param
from deployment import validate_connection

class Pixhawk:
    def __init__(self, connection, profile):
        if profile not in {"hitl", "hardware"}:
            raise ValueError("profile phải là hitl hoặc hardware")
        self.profile = profile
        validate_connection(connection)
        component = (
            ComponentType.GROUND_STATION
            if profile == "hitl" and connection.startswith("udpin://")
            else ComponentType.COMPANION_COMPUTER
        )
        config = Configuration.create_with_component_type(component)
        self.sdk = Mavsdk(config)
        result = self.sdk.add_any_connection(connection)
        if result != ConnectionResult.SUCCESS:
            self.sdk.destroy()
            raise RuntimeError(f"Không mở được kết nối: {result.name}")
        self.drone = self.sdk.first_autopilot(10.0)

        if self.drone is None:
            self.sdk.destroy()
            raise RuntimeError("No autopilot found")
        self.telemetry = Telemetry(self.drone)
        self.param = Param(self.drone)
        self.hitl = self.param.get_param_int("SYS_HITL")
        expected_hitl = 1 if profile == "hitl" else 0
        if self.hitl != expected_hitl:
            self.param.destroy()
            self.telemetry.destroy()
            self.sdk.destroy()
            raise RuntimeError(
                f"SYS_HITL={self.hitl} không khớp profile={profile}"
            )

    def is_connected(self):
        return self.drone.is_connected()

    def armed_status(self):
        return self.telemetry.armed()

    def landed_status(self):
        return self.telemetry.landed_state().name

    def local_position(self):
        reading = self.telemetry.position_velocity_ned()
        position = reading.position
        return {
            'north_m': position.north_m,
            'east_m': position.east_m,
            'down_m': position.down_m
        }

    def health_status(self):
        return self.telemetry.health_all_ok()

    def health_details(self):
        health = self.telemetry.health()
        return {
            'local_position_ok': health.is_local_position_ok,
            'global_position_ok': health.is_global_position_ok,
            'armable': health.is_armable,
        }

    def flight_mode_status(self):
        return self.telemetry.flight_mode().name
    def status(self):
        connected = self.is_connected()
        if not connected:
            return {'connected': False}
        return {
            "connected": connected,
            "armed": self.armed_status(),
            "health_all_ok": self.health_status(),
            "health": self.health_details(),
            "landed_state": self.landed_status(),
            "local_position": self.local_position(),
            "flight_mode": self.flight_mode_status(),
            "profile": self.profile,
            "SYS_HITL": self.hitl,
        }

    def close(self):
        self.param.destroy()
        self.telemetry.destroy()
        self.sdk.destroy()