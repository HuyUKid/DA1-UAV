"""Verify the shipped Classic plugins without starting a simulator or opening USB."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess

from paths import plugin_directory


def bundle_errors(directory):
    """Check manifest and host only for a directory marked as a binary bundle."""
    manifest = directory.parent / 'manifest.json'
    if not manifest.is_file():
        if directory.parent.name == 'ubuntu-22.04-x86_64':
            return ['Missing prebuilt manifest.json; restore the bundled files from Git']
        # Source-build directories do not have this manifest.
        return []
    errors = []
    try:
        data = json.loads(manifest.read_text())
        target = data['target']
        release = platform.freedesktop_os_release()
        if (release.get('ID'), release.get('VERSION_ID'), platform.machine()) != (
                target['id'], target['version_id'], target['machine']):
            errors.append('Bundled plugins require Ubuntu 22.04 x86_64. Use a compatible host or --px4 with your own build.')
        if not data['libraries']:
            errors.append('Empty prebuilt library manifest')
        for name, record in data['libraries'].items():
            if Path(name).name != name:
                errors.append(f'Invalid library name in manifest: {name}')
                continue
            path = directory / name
            if not path.is_file():
                errors.append(f'Missing bundled library: {name}')
            elif hashlib.sha256(path.read_bytes()).hexdigest() != record['sha256']:
                errors.append(f'Bundled library checksum mismatch: {name}')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        errors.append(f'Invalid prebuilt manifest: {exc}')
    return errors


def dependency_errors(directory):
    """ldd resolves sibling message libraries using the relocated bundle first."""
    env = os.environ.copy()
    env['LD_LIBRARY_PATH'] = str(directory) + ':' + env.get('LD_LIBRARY_PATH', '')
    libraries = sorted(directory.glob('*.so'))
    if not libraries:
        return ['No plugin libraries found']
    try:
        result = subprocess.run(['ldd', *(str(path) for path in libraries)],
                                text=True, capture_output=True, env=env, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [f'Cannot inspect plugin dependencies: {exc}']
    output = result.stdout + result.stderr
    missing = sorted({line.strip() for line in output.splitlines() if 'not found' in line})
    if missing:
        return [f'Missing system library: {line}' for line in missing]
    if result.returncode:
        return [f'Plugin dependency check failed: {output.strip()}']
    # No sibling library may silently resolve to the original PX4 build tree.
    names = {path.name for path in libraries}
    for line in output.splitlines():
        fields = line.split()
        if len(fields) >= 3 and fields[0] in names and fields[1] == '=>':
            if Path(fields[2]).resolve().parent != directory.resolve():
                return [f'Plugin dependency resolved outside bundle: {line.strip()}']
    return []


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plugins', type=Path)
    args = parser.parse_args()
    directory = plugin_directory(plugins=args.plugins)
    errors = bundle_errors(directory)
    if not errors:
        errors.extend(dependency_errors(directory))
    print(json.dumps({'plugin_directory': str(directory), 'ok': not errors,
                      'errors': errors, 'flight_verified': False}, indent=2))
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
