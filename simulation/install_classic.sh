#!/usr/bin/env bash
# User setup: install runtime dependencies and use the prebuilt plugins in Git.
# Does not clone PX4, run a compiler, start Gazebo, or access a flight controller.
set -euo pipefail
simulation_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
install_system=true
case "${1:-}" in
    --skip-system) install_system=false; shift ;;
    --help|-h)
        echo 'Usage: bash simulation/install_classic.sh [--skip-system]'
        echo 'Ubuntu 22.04 x86_64: install Classic/Python runtime; use bundled plugins without building.'
        echo '--skip-system requires Gazebo Classic 11 and python3-venv already installed.'
        exit 0 ;;
esac
if (($#)); then
    echo 'Usage: bash simulation/install_classic.sh [--skip-system]' >&2
    exit 2
fi
# shellcheck disable=SC1091
source /etc/os-release
if [[ "${ID:-}" != ubuntu || "${VERSION_ID:-}" != 22.04 || "$(uname -m)" != x86_64 ]]; then
    echo 'The prebuilt plugins require Ubuntu 22.04 x86_64. See simulation/docs/SETUP.md for the source-build alternative.' >&2
    exit 1
fi
if ((EUID == 0)); then
    echo 'Run as your normal user; only apt uses sudo.' >&2
    exit 1
fi
if $install_system; then
    sudo apt-get update
    sudo apt-get install --no-install-recommends gazebo libgazebo11 python3-venv
fi
python3 -m venv "$simulation_dir/.venv"
# Require binary Python wheels so installation cannot silently compile Python dependencies.
"$simulation_dir/.venv/bin/python" -m pip install --only-binary=:all: -r "$simulation_dir/requirements.txt"
plugins="$simulation_dir/prebuilt/ubuntu-22.04-x86_64/lib"
"$simulation_dir/.venv/bin/python" "$simulation_dir/x500/prebuilt.py" --plugins "$plugins"
"$simulation_dir/.venv/bin/python" "$simulation_dir/x500/check_setup.py" --plugins "$plugins"
"$simulation_dir/.venv/bin/python" "$simulation_dir/x500/launch.py" --plugins "$plugins" --serial /dev/null --validate
printf '\nClassic runtime ready; no compilation performed. Configure Pixhawk/Pi before HITL.\n'
printf 'Launch: simulation/.venv/bin/python simulation/x500/launch.py --serial auto\n'
