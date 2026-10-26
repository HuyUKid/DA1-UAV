#!/usr/bin/env python3
"""Maintainer tool: package an existing Classic build; never compile or change it."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as E

SIMULATION = Path(__file__).resolve().parents[1]


def run(*command):
    return subprocess.check_output(command, text=True).strip()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--px4', required=True, type=Path)
    parser.add_argument('--output', type=Path,
                        default=SIMULATION / 'prebuilt/ubuntu-22.04-x86_64')
    args = parser.parse_args()
    release = platform.freedesktop_os_release()
    if (release.get('ID'), release.get('VERSION_ID'), platform.machine()) != ('ubuntu', '22.04', 'x86_64'):
        parser.error('Package on an Ubuntu 22.04 x86_64 host')
    if args.output.exists():
        parser.error('Output already exists. Review/remove the previous bundle explicitly before replacing it.')
    px4 = args.px4.resolve()
    build = px4 / 'build/px4_sitl_default/build_gazebo-classic'
    classic = px4 / 'Tools/simulation/gazebo-classic/sitl_gazebo-classic'
    model = SIMULATION / 'x500/generated/models/x500_hitl/model.sdf'
    plugins = sorted({p.get('filename') for p in E.parse(model).findall('.//plugin')})
    names = set(plugins)
    pending = list(plugins)
    while pending:
        name = pending.pop()
        if Path(name).name != name or not (build / name).is_file():
            parser.error(f'Missing/invalid library: {name}')
        for line in run('ldd', str(build / name)).splitlines():
            fields = line.split()
            if 'not found' in line:
                parser.error(f'Missing dependency in original build: {line}')
            if len(fields) >= 3 and fields[1] == '=>' and Path(fields[2]).parent == build:
                if fields[0] not in names:
                    names.add(fields[0])
                    pending.append(fields[0])

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='classic-package-', dir=args.output.parent) as tmp:
        bundle = Path(tmp) / 'bundle'
        library_dir = bundle / 'lib'
        library_dir.mkdir(parents=True)
        cmake = Path(tmp) / 'relocate.cmake'
        cmake.write_text('file(RPATH_CHANGE FILE "${BINARY}" OLD_RPATH "${OLD_RPATH}" NEW_RPATH "$ORIGIN")\n')
        records = {}
        for name in sorted(names):
            source, target = build / name, library_dir / name
            shutil.copy2(source, target)
            dynamic = run('readelf', '-d', str(target))
            match = re.search(r'\((?:RUNPATH|RPATH)\).*?\[(.*?)\]', dynamic)
            if match:
                run('cmake', f'-DBINARY={target}', f'-DOLD_RPATH={match.group(1)}', '-P', str(cmake))
            run('strip', '--strip-unneeded', str(target))
            target.chmod(0o644)
            records[name] = {'sha256': digest(target), 'bytes': target.stat().st_size,
                             'original_sha256': digest(source)}

        licenses = bundle / 'licenses'
        licenses.mkdir()
        shutil.copyfile('/usr/share/common-licenses/Apache-2.0', licenses / 'Apache-2.0.txt')
        shutil.copyfile(px4 / 'LICENSE', licenses / 'PX4-BSD-3-Clause.txt')
        shutil.copyfile(px4 / 'src/modules/mavlink/mavlink/COPYING', licenses / 'MAVLink-COPYING.txt')
        notices = []
        for directory in ('src', 'include'):
            for source in sorted((classic / directory).rglob('*')):
                if source.suffix not in ('.h', '.hpp', '.cc', '.cpp', '.c'):
                    continue
                text = source.read_text(errors='replace')
                match = re.match(r'\s*(/\*.*?\*/)', text, re.S)
                if match and ('copyright' in match.group(1).lower() or 'license' in match.group(1).lower()):
                    notices.append(str(source.relative_to(classic)) + '\n' + match.group(1))
        (licenses / 'CLASSIC-NOTICES.txt').write_text('\n\n'.join(notices) + '\n')
        changes = run('git', '-C', str(classic), 'diff', '--binary', 'HEAD')
        manifest = {
            'format': 1,
            'packaged_at_utc': datetime.now(timezone.utc).isoformat(),
            'target': {'id': 'ubuntu', 'version_id': '22.04', 'machine': 'x86_64', 'gazebo_major': 11},
            'gazebo_package_version': run('dpkg-query', '-W', '-f=${Version}', 'libgazebo11'),
            'compiler_comment': run('readelf', '-p', '.comment', str(build / plugins[0])),
            'px4_revision': run('git', '-C', str(px4), 'rev-parse', 'HEAD'),
            'classic_revision': run('git', '-C', str(classic), 'rev-parse', 'HEAD'),
            'classic_worktree_status': run('git', '-C', str(classic), 'status', '--short'),
            'classic_tracked_diff_sha256': hashlib.sha256(changes.encode()).hexdigest(),
            'provenance_limit': 'Packaged from an existing local build; checkout metadata was recorded at packaging time, not at original compilation.',
            'transformations': ['CMake RPATH_CHANGE to $ORIGIN on copies', 'strip --strip-unneeded on copies'],
            'model_plugins': plugins,
            'libraries': records,
            'validation_scope': 'Checksums, relocated loader/dependency checks and SDF validation are separate checks; no HIL/flight claim.',
        }
        (bundle / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        bundle.rename(args.output)
    print(f'Packaged {len(records)} libraries ({sum(r["bytes"] for r in records.values())} bytes) at {args.output}')


if __name__ == '__main__':
    main()
