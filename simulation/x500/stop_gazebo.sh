#!/usr/bin/env bash
set -u

if [[ ${1:-} != --disarmed ]]; then
    echo 'Refusing to stop HITL without operator confirmation.' >&2
    echo 'After PX4 reports armed=false and ON_GROUND, run:' >&2
    echo '  stop_gazebo.sh --disarmed' >&2
    exit 2
fi

pkill -INT -x gzserver 2>/dev/null || true
for _ in {1..20}; do
    pgrep -x gzserver >/dev/null || break
    sleep 0.1
done
pkill -TERM -x gzserver 2>/dev/null || true
pkill -TERM -x gzclient 2>/dev/null || true
pkill -TERM -f '[s]imulation/x500/launch.py' 2>/dev/null || true

if pgrep -x gzserver >/dev/null || pgrep -x gzclient >/dev/null; then
    echo 'A Gazebo process is still running:' >&2
    pgrep -a -x gzserver >&2 || true
    pgrep -a -x gzclient >&2 || true
    exit 1
fi

echo 'Gazebo server/client stopped. Port 11345 should now be free.'
