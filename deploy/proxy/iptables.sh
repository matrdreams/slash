#!/usr/bin/env bash
# Redirect one Redroid docker network's outbound TCP to a local proxy (sing-box / redsocks).
# Usage: sudo ./deploy/proxy/iptables.sh <bridge-iface> <proxy-port> <device-cidr>
# Private destinations are returned (not redirected). Requires root on the host, not in CI.
set -euo pipefail

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" || $# -lt 3 ]]; then
  echo "Usage: sudo $0 <bridge-iface> <proxy-port> <device-cidr>" >&2
  exit 2
fi

IFACE=$1
PROXY_PORT=$2
CIDR=$3

if [[ "$(id -u)" -ne 0 ]]; then
  echo "run as root" >&2
  exit 1
fi

if [[ ! "${PROXY_PORT}" =~ ^[0-9]+$ ]]; then
  echo "proxy port must be numeric" >&2
  exit 2
fi

iptables -t nat -N SLASH_EGRESS 2>/dev/null || iptables -t nat -F SLASH_EGRESS
iptables -t nat -A SLASH_EGRESS -d 10.0.0.0/8 -j RETURN
iptables -t nat -A SLASH_EGRESS -d 127.0.0.0/8 -j RETURN
iptables -t nat -A SLASH_EGRESS -d 172.16.0.0/12 -j RETURN
iptables -t nat -A SLASH_EGRESS -d 192.168.0.0/16 -j RETURN
iptables -t nat -A SLASH_EGRESS -p tcp -j REDIRECT --to-ports "${PROXY_PORT}"

if ! iptables -t nat -C PREROUTING -i "${IFACE}" -s "${CIDR}" -j SLASH_EGRESS 2>/dev/null; then
  iptables -t nat -A PREROUTING -i "${IFACE}" -s "${CIDR}" -j SLASH_EGRESS
fi

echo "redirect ${CIDR} via ${IFACE} -> 127.0.0.1:${PROXY_PORT}"
