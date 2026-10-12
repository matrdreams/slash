#!/usr/bin/env bash
# Prepare a Linux host to run Redroid: distro packages, binder_linux, optional Docker.
# Usage: sudo ./host/install.sh [--arch auto|arm64|amd64] [--docker-mirror URL] [--no-docker]
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

ARCH="auto"
DOCKER_MIRROR=""
NO_DOCKER=0

usage() {
  cat <<'EOF'
Usage: sudo ./host/install.sh [--arch auto|arm64|amd64] [--docker-mirror URL] [--no-docker]

Detects the distro, installs adb (and Docker unless --no-docker), writes
/etc/modules-load.d/redroid.conf and /etc/modprobe.d/redroid.conf, and loads binder_linux.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    --arch)
      ARCH="${2:?--arch requires auto|arm64|amd64}"
      shift 2
      ;;
    --docker-mirror)
      DOCKER_MIRROR="${2:?--docker-mirror requires a URL}"
      shift 2
      ;;
    --no-docker)
      NO_DOCKER=1
      shift
      ;;
    *)
      echo "unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

case "${ARCH}" in
  auto|arm64|amd64) ;;
  *)
    echo "--arch must be auto, arm64, or amd64" >&2
    exit 2
    ;;
esac

if [[ "$(id -u)" -ne 0 ]]; then
  echo "run as root: sudo $0 ..." >&2
  exit 1
fi

HOST_ARCH=$(uname -m)
case "${HOST_ARCH}" in
  aarch64|arm64) HOST_NORM="arm64" ;;
  x86_64|amd64) HOST_NORM="amd64" ;;
  *) HOST_NORM="${HOST_ARCH}" ;;
esac

if [[ "${ARCH}" != "auto" && "${ARCH}" != "${HOST_NORM}" ]]; then
  echo "warning: --arch ${ARCH} does not match host ${HOST_ARCH}." >&2
  echo "warning: x86_64 Redroid images rely on libndk_translation; arm64 is the preferred host." >&2
fi

if [[ ! -r /etc/os-release ]]; then
  echo "/etc/os-release is missing; cannot detect the distro" >&2
  exit 1
fi

# shellcheck disable=SC1091
. /etc/os-release

DISTRO_ID="${ID:-unknown}"
case "${DISTRO_ID}" in
  ubuntu)
    # shellcheck disable=SC1091
    source "${ROOT}/distro/ubuntu.sh"
    ;;
  debian)
    # shellcheck disable=SC1091
    source "${ROOT}/distro/debian.sh"
    ;;
  alinux|alios|alinux3|openEuler|amzn|anolis)
    # shellcheck disable=SC1091
    source "${ROOT}/distro/alinux.sh"
    ;;
  *)
    # Other distros with kernel >= 5.7: try the generic modprobe path.
    echo "distro ${DISTRO_ID} is not in the support matrix; trying generic binder load" >&2
    # shellcheck disable=SC1091
    source "${ROOT}/distro/ubuntu.sh"
    ;;
esac

install_distro

if [[ -n "${DOCKER_MIRROR}" && "${NO_DOCKER}" -eq 0 ]]; then
  install -d /etc/docker
  if [[ -f /etc/docker/daemon.json ]]; then
    cp /etc/docker/daemon.json "/etc/docker/daemon.json.bak.$(date +%s)"
  fi
  cat > /etc/docker/daemon.json <<EOF
{"registry-mirrors": ["${DOCKER_MIRROR}"]}
EOF
  systemctl restart docker || service docker restart || true
fi

echo "binder config installed; running host/check.sh" >&2
if [[ -x "${ROOT}/check.sh" ]]; then
  "${ROOT}/check.sh" --json || {
    echo "host/check.sh reported issues (see JSON above)" >&2
    exit 1
  }
fi
