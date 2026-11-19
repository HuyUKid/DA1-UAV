#!/usr/bin/env bash
# Run one MAVLink Router for Pixhawk USB, Pi flight service, observers and QGC.
set -euo pipefail

if [[ $# -lt 2 || $# -gt 3 ]]; then
  printf 'Usage: %s PC_IPV4 PIXHAWK_USB_DEVICE [SECOND_QGC_IPV4]\n' "$0" >&2
  exit 2
fi

pc_ip=$1
serial_device=$2
second_pc_ip=${3:-}

python3 - "$pc_ip" "$second_pc_ip" <<'PY'
import ipaddress
import sys

for value in sys.argv[1:]:
    if not value:
        continue
    address = ipaddress.IPv4Address(value)
    if address.is_multicast or address.is_loopback or address.is_unspecified or address.is_reserved:
        raise SystemExit('QGC IPv4 must be a reachable unicast address')
if sys.argv[2] and sys.argv[1] == sys.argv[2]:
    raise SystemExit('Second QGC IPv4 must differ from the first')
PY

case "$serial_device" in
  /dev/*) ;;
  *) printf 'Pixhawk USB device must be under /dev/\n' >&2; exit 2 ;;
esac
if [[ ! -c "$serial_device" ]]; then
  printf 'Pixhawk USB device is not an accessible character device: %s\n' "$serial_device" >&2
  exit 2
fi
if ! command -v mavlink-routerd >/dev/null 2>&1; then
  printf 'mavlink-routerd is missing; install MAVLink Router on Pi first\n' >&2
  exit 2
fi

config_dir=$(mktemp -d /tmp/uav-hardware-router.XXXXXXXX)
trap 'rm -rf -- "$config_dir"' EXIT
mkdir "$config_dir/empty"

cat > "$config_dir/main.conf" <<EOF
[General]
TcpServerPort = 0

[UartEndpoint pixhawk]
Device = $serial_device
Baud = 921600

[UdpEndpoint pi_flight]
Mode = Normal
Address = 127.0.0.1
Port = 14540

[UdpEndpoint pi_observer]
Mode = Normal
Address = 127.0.0.1
Port = 14541

[UdpEndpoint qgc_pc]
Mode = Normal
Address = $pc_ip
Port = 14550
EOF

if [[ -n "$second_pc_ip" ]]; then
  cat >> "$config_dir/main.conf" <<EOF

[UdpEndpoint second_qgc_pc]
Mode = Normal
Address = $second_pc_ip
Port = 14550
EOF
fi

printf 'Router: Pixhawk %s ↔ Pi flight 127.0.0.1:14540 ↔ observer 127.0.0.1:14541 ↔ QGC %s:14550' "$serial_device" "$pc_ip"
if [[ -n "$second_pc_ip" ]]; then
  printf ' ↔ second QGC %s:14550' "$second_pc_ip"
fi
printf '\n'
mavlink-routerd -c "$config_dir/main.conf" -d "$config_dir/empty"
