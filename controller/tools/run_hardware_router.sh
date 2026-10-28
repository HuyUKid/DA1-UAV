#!/usr/bin/env bash
# Run one MAVLink Router for real-aircraft USB, local Pi console and remote QGC.
set -euo pipefail

if [[ $# -ne 2 ]]; then
  printf 'Usage: %s PC_IPV4 PIXHAWK_USB_DEVICE\n' "$0" >&2
  exit 2
fi

pc_ip=$1
serial_device=$2

python3 - "$pc_ip" <<'PY'
import ipaddress
import sys

address = ipaddress.IPv4Address(sys.argv[1])
if address.is_multicast or address.is_loopback or address.is_unspecified or address.is_reserved:
    raise SystemExit('PC_IPV4 must be the reachable IPv4 address of the QGC computer')
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

[UdpEndpoint pi_console]
Mode = Normal
Address = 127.0.0.1
Port = 14540

[UdpEndpoint qgc_pc]
Mode = Normal
Address = $pc_ip
Port = 14550
EOF

printf 'Router: Pixhawk %s ↔ Pi console 127.0.0.1:14540 ↔ QGC %s:14550\n' "$serial_device" "$pc_ip"
mavlink-routerd -c "$config_dir/main.conf" -d "$config_dir/empty"
