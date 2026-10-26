#!/usr/bin/env bash
# Install the PC simulator only. Never flash PX4, open USB, or start HIL.
set -euo pipefail

simulation_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
px4_dir="$simulation_dir/.external/PX4-Autopilot-v1.16"
px4_revision=6ea3539157ca358c70a515878b77077af7d4611d
classic_revision=70683dc759cbd3ebccfa78429b564f8b1fb5d149
install_system=true
build_plugins=true

usage() {
    cat <<'USAGE'
Optional source-build setup (maintainers). Users: run simulation/install_classic.sh instead.
Usage: bash simulation/setup_classic.sh [options]
  --px4 PATH       Reuse PX4 v1.16.0 at PATH instead of simulation/.external/...
  --skip-system    Skip apt and upstream system/Python dependency installation
  --skip-build     Reuse built plugins; still verify model and SDF
  --help           Show this help

Requires Ubuntu 22.04, internet for the first installation, and sudo for apt.
Downloads pinned PX4 sources, installs Classic 11, builds plugins and creates
simulation/.venv. Does not run a simulator, flash firmware, or access Pixhawk.
USAGE
}

while (($#)); do
    case "$1" in
        --px4)
            [[ $# -ge 2 && -n "$2" && "$2" != --* ]] || { usage >&2; exit 2; }
            px4_dir="$2"; shift 2 ;;
        --skip-system) install_system=false; shift ;;
        --skip-build) build_plugins=false; shift ;;
        --help|-h) usage; exit 0 ;;
        *) usage >&2; exit 2 ;;
    esac
done

# This recipe deliberately targets the supported Classic host rather than
# silently replacing the simulator or removing conflicting packages elsewhere.
# shellcheck disable=SC1091
source /etc/os-release
if [[ "${ID:-}" != ubuntu || "${VERSION_ID:-}" != 22.04 ]]; then
    echo 'This Classic setup requires Ubuntu 22.04. Use a separate 22.04 host/VM with GUI and USB passthrough.' >&2
    exit 1
fi
if ((EUID == 0)); then
    echo 'Run as your normal user; only package installation uses sudo.' >&2
    exit 1
fi

if $install_system; then
    sudo apt-get update
    sudo apt-get install --no-install-recommends \
        git python3-venv gazebo libgazebo11 libgazebo-dev \
        libboost-system-dev libboost-thread-dev libboost-filesystem-dev \
        libopencv-dev libtinyxml-dev libeigen3-dev libprotobuf-dev protobuf-compiler \
        libgstreamer1.0-dev libgstreamer-plugins-base1.0-dev
fi

px4_dir=$(realpath -m -- "$px4_dir")
if [[ ! -e "$px4_dir" ]]; then
    mkdir -p -- "$(dirname -- "$px4_dir")"
    git clone --branch v1.16.0 --recursive https://github.com/PX4/PX4-Autopilot.git "$px4_dir"
fi
if [[ ! -d "$px4_dir/.git" ]] || [[ "$(git -C "$px4_dir" rev-parse HEAD)" != "$px4_revision" ]]; then
    echo "Expected PX4 v1.16.0 ($px4_revision) at $px4_dir. Existing files have been left in place." >&2
    exit 1
fi
classic_dir="$px4_dir/Tools/simulation/gazebo-classic/sitl_gazebo-classic"
if [[ ! -f "$classic_dir/CMakeLists.txt" ]] || \
   [[ "$(git -C "$classic_dir" rev-parse HEAD)" != "$classic_revision" ]]; then
    echo 'Missing or different Classic submodule. Use a fresh recursive v1.16.0 clone; existing sources are not reset.' >&2
    exit 1
fi
if [[ -n "$(git -C "$px4_dir" status --porcelain --untracked-files=no)" ]]; then
    echo 'Notice: this PX4 checkout has local changes. They are preserved; results may differ from the pinned sources.' >&2
fi

python3 -m venv "$simulation_dir/.venv"
# Activate so upstream ubuntu.sh installs its Python requirements into the venv.
# shellcheck disable=SC1091
source "$simulation_dir/.venv/bin/activate"
python -m pip install -r "$simulation_dir/requirements.txt"
if $install_system; then
    bash "$px4_dir/Tools/setup/ubuntu.sh" --no-nuttx --no-sim-tools
fi
if $build_plugins; then
    (cd -- "$px4_dir" && DONT_RUN=1 make px4_sitl_default gazebo-classic)
fi

python -B -m unittest discover -s "$simulation_dir/tests" -p 'test_*.py'
python "$simulation_dir/x500/check_setup.py" --px4 "$px4_dir"
# /dev/null is only written into a temporary model; --validate never opens it.
python "$simulation_dir/x500/launch.py" --px4 "$px4_dir" --serial /dev/null --validate
printf '\nClassic setup completed. Configure Pixhawk/Pi using simulation/docs/SETUP.md before starting HITL.\n'
printf 'PX4 source: %s\n' "$px4_dir"
printf 'Launch: simulation/.venv/bin/python simulation/x500/launch.py --px4 "%s" --serial auto\n' "$px4_dir"
