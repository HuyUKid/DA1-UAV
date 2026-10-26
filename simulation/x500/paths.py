"""Locate locally installed simulation dependencies without machine-specific paths."""
from pathlib import Path


def default_px4():
    managed = Path(__file__).resolve().parents[1] / '.external/PX4-Autopilot-v1.16'
    return managed if managed.is_dir() else Path.home() / 'PX4-Autopilot-v1.16'


def plugin_directory(px4=None, plugins=None):
    if plugins is not None:
        return Path(plugins).resolve()
    if px4 is not None:
        return Path(px4) / 'build/px4_sitl_default/build_gazebo-classic'
    bundled = Path(__file__).resolve().parents[1] / 'prebuilt/ubuntu-22.04-x86_64/lib'
    if bundled.is_dir():
        return bundled
    return default_px4() / 'build/px4_sitl_default/build_gazebo-classic'


def serial_device(value):
    """Resolve auto only when one USB serial identity is present; never open it."""
    if value != 'auto':
        path = Path(value)
        if not path.is_absolute() or not path.is_relative_to('/dev') or '..' in path.parts:
            raise ValueError('Serial device must be an absolute path below /dev')
        return str(path)
    devices = sorted(Path('/dev/serial/by-id').glob('*'))
    if len(devices) != 1:
        raise ValueError(f'Found {len(devices)} USB serial identities; use --serial /dev/serial/by-id/DEVICE')
    return str(devices[0])
