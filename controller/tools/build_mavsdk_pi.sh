#!/usr/bin/env bash
# Build the native library locally; never connect to a flight controller.
set -euo pipefail

HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PROJECT_ROOT=$(cd -- "$HERE/.." && pwd)
PY="${MAVSDK_PYTHON:-$PROJECT_ROOT/.venv/bin/python}"
VERSION=4.0.6
BUILD_ROOT="${MAVSDK_BUILD_ROOT:-$PROJECT_ROOT/.native/mavsdk-$VERSION}"
PREFIX="$BUILD_ROOT/install"
JOBS="${MAVSDK_BUILD_JOBS:-2}"

if [[ $(uname -m) != aarch64 ]]; then
    echo 'Run this script on the ARM64 Raspberry Pi.' >&2
    exit 1
fi
for tool in git cmake make g++ pkg-config; do
    command -v "$tool" >/dev/null || { echo "Missing tool: $tool" >&2; exit 1; }
done
[[ -x "$PY" ]] || { echo "Missing virtual environment: $PY" >&2; exit 1; }
LIB_DIR=$("$PY" -c 'from importlib.metadata import distribution; d=distribution("mavsdk"); assert d.version == "4.0.6", "Install mavsdk==4.0.6 first"; print(d.locate_file("mavsdk/lib"))')
OLD_LIB="$LIB_DIR/libcmavsdk.so"
[[ -f "$OLD_LIB" ]] || { echo "Missing library: $OLD_LIB" >&2; exit 1; }

# Preloading a second C++ runtime was only a diagnostic workaround.
unset LD_PRELOAD
mkdir -p "$BUILD_ROOT"
if [[ ! -d "$BUILD_ROOT/source" ]]; then
    git clone --depth 1 --branch "v$VERSION" --recurse-submodules --shallow-submodules \
        https://github.com/mavlink/MAVSDK.git "$BUILD_ROOT/source"
fi
[[ $(git -C "$BUILD_ROOT/source" describe --tags --exact-match) == "v$VERSION" ]] || {
    echo 'Source checkout does not match the required release.' >&2; exit 1;
}

cmake -S "$BUILD_ROOT/source/cpp" -B "$BUILD_ROOT/core" \
    -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$PREFIX" \
    -DCMAKE_INSTALL_LIBDIR=lib -DCMAKE_POSITION_INDEPENDENT_CODE=ON \
    -DBUILD_SHARED_LIBS=OFF -DBUILD_TESTING=OFF -DBUILD_MAVSDK_SERVER=OFF \
    -DBUILD_WITHOUT_CURL=ON
cmake --build "$BUILD_ROOT/core" --target install --parallel "$JOBS"

# Static MAVSDK core, but dynamic system libstdc++/libgcc. No bundled runtime.
cmake -S "$BUILD_ROOT/source/c" -B "$BUILD_ROOT/wrapper" \
    -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$PREFIX" \
    -DCMAKE_INSTALL_LIBDIR=lib \
    "-DCMAKE_PREFIX_PATH=$PREFIX;$BUILD_ROOT/core/third_party/install" \
    -DCMAKE_INSTALL_RPATH="$PREFIX/lib" \
    -DCMAKE_SHARED_LINKER_FLAGS=-Wl,-z,defs \
    -DBUILD_SHARED_LIBS=ON -DBUILD_EXAMPLES=OFF -DBUNDLE_STATIC_RUNTIME=OFF
cmake --build "$BUILD_ROOT/wrapper" --target install --parallel "$JOBS"

NEW_LIB="$PREFIX/lib/libcmavsdk.so"
ldd -r "$NEW_LIB" > "$BUILD_ROOT/link-check.txt" 2>&1
cat "$BUILD_ROOT/link-check.txt"
if grep -Eq 'not found|undefined symbol' "$BUILD_ROOT/link-check.txt"; then
    echo 'Library dependencies are unresolved; original library was not changed.' >&2
    exit 1
fi

BACKUP="$OLD_LIB.before-native-$(date +%Y%m%d_%H%M%S)-$$"
cp -p "$OLD_LIB" "$BACKUP"
cp -L "$NEW_LIB" "$OLD_LIB.native-tmp"
mv "$OLD_LIB.native-tmp" "$OLD_LIB"
echo "Backup: $BACKUP"
if "$PY" -X faulthandler -u -c \
    'from mavsdk import Mavsdk, Configuration, ComponentType; c=Configuration.create_with_component_type(ComponentType.COMPANION_COMPUTER); print("CONFIG OK", flush=True); s=Mavsdk(c); print("MAVSDK INIT OK", s.version(), flush=True); s.destroy(); c.destroy(); print("CLEANUP OK", flush=True)'; then
    echo 'Native initialization passed. UART and flight commands have NOT been tested.'
else
    cp -p "$BACKUP" "$OLD_LIB.restore-tmp"
    mv "$OLD_LIB.restore-tmp" "$OLD_LIB"
    echo 'Initialization failed; original library restored. Keep the full output.' >&2
    exit 1
fi
