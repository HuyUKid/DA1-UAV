#!/usr/bin/env python3
"""Read-only checks of the bundled X500 model and Gazebo Classic environment.

No simulator is started and no serial port or flight controller is opened.
--static checks repository assets without requiring installed simulation tools.
"""
import argparse
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as E
from paths import plugin_directory
from prebuilt import bundle_errors

HERE = Path(__file__).resolve().parent


def model_errors(generated):
    errors = []
    try:
        model = E.parse(generated / 'models/x500_hitl/model.sdf').getroot().find('model')
        world = E.parse(generated / 'x500_hitl.world').getroot().find('world')
        metadata = json.loads((generated / 'provenance.json').read_text())
        if model is None or world is None:
            return ['Missing model or world element']
        includes = [e.findtext('uri') for e in world.findall('include')]
        if includes != ['model://x500_hitl']:
            errors.append('World must include only the local X500 model')
        if world.find("model[@name='ground_plane']/link/collision/geometry/plane") is None:
            errors.append('Missing inline ground collision plane')
        if world.find("light[@name='sun']") is None:
            errors.append('Missing inline lighting')
        if world.findtext('gravity') != '0 0 -9.8066':
            errors.append('Unexpected world gravity')
        if world.find('physics/gravity') is not None or world.find('physics/magnetic_field') is not None:
            errors.append('Gravity and magnetic field belong to world, not physics')
        for uri in model.findall('.//uri'):
            value = (uri.text or '').strip()
            if value.startswith('model://'):
                path = generated / 'models' / value.removeprefix('model://')
                if not path.is_file():
                    errors.append(f'Missing model asset: {value}')
            elif value != 'file://media/materials/scripts/gazebo.material':
                errors.append(f'Unresolved resource URI: {value}')
        for mesh in (generated / 'models/x500_base/meshes').glob('*.dae'):
            for image in E.parse(mesh).findall('.//{*}library_images/{*}image/{*}init_from'):
                if not (mesh.parent / (image.text or '')).is_file():
                    errors.append(f'Missing mesh texture: {mesh.name}: {image.text}')
        mass = 0.0
        for inertial in model.findall('.//inertial'):
            m = float(inertial.findtext('mass'))
            mass += m
            inertia = inertial.find('inertia')
            xx, yy, zz = (float(inertia.findtext(k)) for k in ('ixx', 'iyy', 'izz'))
            xy, xz, yz = (float(inertia.findtext(k, '0')) for k in ('ixy', 'ixz', 'iyz'))
            det = xx * yy * zz + 2 * xy * xz * yz - xx * yz**2 - yy * xz**2 - zz * xy**2
            if not all(math.isfinite(v) for v in (m, xx, yy, zz, xy, xz, yz)) or min(m, xx, yy, zz, det, xx * yy - xy**2) <= 0:
                errors.append('Non-positive mass or inertia matrix')
        if not math.isclose(mass, metadata['total_link_mass_kg'], abs_tol=1e-9):
            errors.append('Model mass differs from recorded provenance')
        motors = model.findall("plugin[@filename='libgazebo_motor_model.so']")
        if sorted(p.findtext('motorNumber') for p in motors) != ['0', '1', '2', '3']:
            errors.append('Expected four distinct motor indices 0..3')
        if any(not p.get('filename') for p in model.findall('.//plugin')):
            errors.append('Model contains a plugin with no filename')
        for p in motors:
            for tag, kind in (('jointName', 'joint'), ('linkName', 'link')):
                if model.find(f"{kind}[@name='{p.findtext(tag)}']") is None:
                    errors.append(f'Motor references missing {tag}')
        for filename in ('libgazebo_imu_plugin.so', 'libgazebo_gps_plugin.so',
                         'libgazebo_magnetometer_plugin.so', 'libgazebo_barometer_plugin.so',
                         'libgazebo_mavlink_interface.so'):
            if model.find(f".//plugin[@filename='{filename}']") is None:
                errors.append(f'Missing sensor/transport plugin: {filename}')
    except (OSError, E.ParseError, ValueError, TypeError, KeyError, AttributeError) as exc:
        errors.append(f'Invalid model bundle: {exc}')
    return errors


def inspect_setup(px4=None, generated=None, require_device=False, headless=False, plugins=None):
    generated = generated or HERE / 'generated'
    static = model_errors(generated)
    runtime = []
    binaries = ('gzserver', 'gz') if headless else ('gazebo', 'gzserver', 'gz')
    for binary in binaries:
        if shutil.which(binary) is None:
            runtime.append(f'Missing executable: {binary}')
    if shutil.which('gzserver'):
        try:
            version = subprocess.run(['gzserver', '--version'], text=True,
                                     capture_output=True, timeout=5)
            banner = (version.stdout + version.stderr).lower()
            # Classic Server::ParseArgs returns false after printing --version;
            # gzserver consequently exits -1 (255), even on a valid install.
            classic_banner = 'gazebo multi-robot simulator, version '
            if version.returncode not in (0, 255) or (version.returncode and classic_banner not in banner):
                runtime.append(f'Gazebo version check failed (exit {version.returncode}): '
                               f'{(version.stderr or version.stdout).strip()}')
            elif classic_banner + '11.' not in banner:
                runtime.append('Gazebo Classic 11 is required; modern Gazebo plugins are incompatible')
        except (OSError, subprocess.TimeoutExpired) as exc:
            runtime.append(f'Cannot check Gazebo version: {exc}')
    plugins = plugin_directory(px4, plugins)
    runtime.extend(bundle_errors(plugins))
    device = None
    try:
        model = E.parse(generated / 'models/x500_hitl/model.sdf')
        filenames = [p.get('filename') for p in model.findall('.//plugin')]
        if any(not filename for filename in filenames):
            runtime.append('Model contains a plugin with no filename')
        required = sorted({name for name in filenames if name})
        for filename in required:
            if not (plugins / filename).is_file():
                runtime.append(f'Missing Classic plugin: {plugins / filename}')
        device = model.findtext("model/plugin[@name='mavlink_interface']/serialDevice")
        if require_device:
            if not device or not Path(device).exists():
                runtime.append(f'Pixhawk USB device unavailable: {device}')
            elif not os.access(device, os.R_OK | os.W_OK):
                runtime.append(f'No read/write permission for {device}')
    except (OSError, E.ParseError) as exc:
        runtime.append(str(exc))
    return {'static_ok': not static, 'static_errors': static,
            'runtime_ok': not runtime, 'runtime_errors': runtime,
            'observer_dependencies_ok': importlib.util.find_spec('pymavlink') is not None,
            'serial_device': device, 'device_checked': require_device,
            'plugin_directory': str(plugins), 'flight_verified': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument('--px4', type=Path, help='Use plugins from a PX4 source build')
    source.add_argument('--plugins', type=Path, help='Use a specific plugin directory')
    parser.add_argument('--static', action='store_true')
    parser.add_argument('--require-device', action='store_true')
    args = parser.parse_args()
    if args.static and args.require_device:
        parser.error('--static and --require-device are mutually exclusive')
    report = inspect_setup(args.px4, require_device=args.require_device, plugins=args.plugins)
    print(json.dumps(report, indent=2))
    return 0 if report['static_ok'] and (args.static or report['runtime_ok']) else 1


if __name__ == '__main__':
    raise SystemExit(main())
