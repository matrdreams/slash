#!/usr/bin/env bash
# Publish the redroid container's ADB port on 127.0.0.1 only.
#
# QEMU user-net hostfwd delivers to the guest NIC (10.0.2.15), not to the
# guest loopback. After docker publishes 127.0.0.1:5555, this script DNATs
# other local destinations on tcp/5555 to 127.0.0.1:5555 (route_localnet)
# and drops any docker-proxy that is still bound to a wildcard address.
#
# Safe to run more than once. Does not restart the container or the VM.
set -euo pipefail

PORT="${ADB_CONTAINER_PORT:-5555}"
NAME="${REDROID_NAME:-redroid}"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is not installed" >&2
  exit 1
fi
if ! docker inspect "$NAME" >/dev/null 2>&1; then
  echo "container ${NAME} is not present; nothing to rebind" >&2
  exit 0
fi

cip=""
for _ in 1 2 3 4 5 6 7 8 9 10; do
  cip=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$NAME" 2>/dev/null || true)
  if [[ -n "$cip" ]]; then
    break
  fi
  sleep 2
done
if [[ -z "$cip" ]]; then
  echo "container ${NAME} has no IP address" >&2
  exit 1
fi

sysctl -w net.ipv4.conf.all.route_localnet=1 >/dev/null
if [[ -e /proc/sys/net/ipv4/conf/eth0/route_localnet ]]; then
  sysctl -w net.ipv4.conf.eth0.route_localnet=1 >/dev/null || true
fi
install -d /etc/sysctl.d
printf '%s\n' 'net.ipv4.conf.all.route_localnet=1' > /etc/sysctl.d/99-slash-adb.conf

# Remove DNAT rules that publish this port on every address. Keep rules that
# already match only 127.0.0.1.
if iptables -t nat -S >/dev/null 2>&1; then
  while IFS= read -r rule; do
    [[ -n "$rule" ]] || continue
    case "$rule" in
      *"--dport ${PORT}"*) ;;
      *) continue ;;
    esac
    case "$rule" in
      *"-j DNAT"*) ;;
      *) continue ;;
    esac
    case "$rule" in
      *"-d 127.0.0.1"*) continue ;;
    esac
    case "$rule" in
      -A\ *)
        # shellcheck disable=SC2086
        iptables -t nat -D ${rule#-A } || true
        ;;
    esac
  done < <(iptables -t nat -S | grep -F -- "--dport ${PORT}" || true)

  if iptables -t nat -S DOCKER >/dev/null 2>&1; then
    if ! iptables -t nat -C DOCKER ! -i docker0 -d 127.0.0.1/32 -p tcp -m tcp --dport "$PORT" -j DNAT --to-destination "${cip}:${PORT}" 2>/dev/null; then
      iptables -t nat -A DOCKER ! -i docker0 -d 127.0.0.1/32 -p tcp -m tcp --dport "$PORT" -j DNAT --to-destination "${cip}:${PORT}"
    fi
  fi
  if ! iptables -t nat -C PREROUTING -p tcp -m tcp --dport "$PORT" ! -d 127.0.0.1/32 -j DNAT --to-destination "127.0.0.1:${PORT}" 2>/dev/null; then
    iptables -t nat -I PREROUTING 1 -p tcp -m tcp --dport "$PORT" ! -d 127.0.0.1/32 -j DNAT --to-destination "127.0.0.1:${PORT}"
  fi
fi

# Wildcard docker-proxy listeners (0.0.0.0 and ::). Leave a 127.0.0.1 proxy alone.
if [[ -r /proc/net/tcp || -d /proc ]]; then
  ps -ww -eo pid=,args= | while read -r pid args; do
    case "$args" in
      *docker-proxy*"host-port ${PORT}"*|*"host-port ${PORT}"*docker-proxy*) ;;
      *) continue ;;
    esac
    case "$args" in
      *"host-ip 127.0.0.1"*) continue ;;
    esac
    kill "$pid" 2>/dev/null || true
  done
fi
sleep 0.3

# docker-proxy without the daemon's listen fd exits with EBADF on this host.
# A tiny Python forwarder stays bound to 127.0.0.1 and proxies to the container.
if ! ss -lntH "sport = :${PORT}" | awk '{print $4}' | grep -qx "127.0.0.1:${PORT}"; then
  if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 is required to bind 127.0.0.1:${PORT}" >&2
    exit 1
  fi
  cat > /usr/local/sbin/slash-adb-proxy.py <<'PY'
import socket
import sys
import threading

listen, dest = sys.argv[1], sys.argv[2]
host, port_s = listen.rsplit(":", 1)
dest_host, dest_port_s = dest.rsplit(":", 1)

def pipe(src, dst):
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
    except OSError:
        pass
    finally:
        for sock in (src, dst):
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

def handle(client):
    try:
        remote = socket.create_connection((dest_host, int(dest_port_s)), 5)
    except OSError:
        client.close()
        return
    threading.Thread(target=pipe, args=(client, remote), daemon=True).start()
    pipe(remote, client)
    client.close()
    remote.close()

server = socket.socket()
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind((host, int(port_s)))
server.listen(32)
while True:
    client, _addr = server.accept()
    threading.Thread(target=handle, args=(client,), daemon=True).start()
PY
  chmod 755 /usr/local/sbin/slash-adb-proxy.py
  setsid python3 /usr/local/sbin/slash-adb-proxy.py "127.0.0.1:${PORT}" "${cip}:${PORT}" \
    >>/var/log/slash-adb-proxy.log 2>&1 < /dev/null &
  sleep 0.3
fi

echo "redroid ${cip} adb listeners:"
# Local address only. `ss` also prints the peer, which is often 0.0.0.0:*.
ss -lntH "sport = :${PORT}" || true
bad=0
while read -r local _; do
  [[ -n "${local}" ]] || continue
  case "${local}" in
    127.0.0.1:${PORT}|[::1]:${PORT}) ;;
    *)
      echo "warning: tcp/${PORT} is listening on ${local}" >&2
      bad=1
      ;;
  esac
done < <(ss -lntH "sport = :${PORT}" | awk '{print $4}')
if [[ "$bad" -ne 0 ]]; then
  exit 1
fi
if ! ss -lntH "sport = :${PORT}" | awk '{print $4}' | grep -qx "127.0.0.1:${PORT}"; then
  echo "127.0.0.1:${PORT} is not listening" >&2
  exit 1
fi
