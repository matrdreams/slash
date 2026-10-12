#!/usr/bin/env bash
# Ubuntu 22.04 amd64 VM with KVM for day-to-day Redroid development (L1).
# Official amd64 Redroid images include libndk_translation. This path is the fast
# one; use make-arm64-vm.sh before an arm64 release check.
#
# Requires /dev/kvm. There is no silent TCG fallback.
#
# Dependencies (Ubuntu host):
#   sudo apt install -y qemu-system-x86 qemu-utils cloud-image-utils
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
WORKDIR=${WORKDIR:-"${PWD}/.slash-vm-x86"}
DISK_SIZE=${DISK_SIZE:-40G}
MEM=${MEM:-8G}
SMP=${SMP:-4}
SSH_PORT=${SSH_PORT:-2222}
API_PORT=${API_PORT:-8787}
IMAGE_URL=${IMAGE_URL:-https://cloud-images.ubuntu.com/jammy/current/jammy-server-cloudimg-amd64.img}
BASE_NAME=jammy-server-cloudimg-amd64.img

if [[ ! -e /dev/kvm ]]; then
  echo "/dev/kvm is missing. make-x86-vm.sh requires KVM." >&2
  echo "Enable nested virtualization or run on a Linux host with KVM." >&2
  exit 1
fi
if [[ ! -r /dev/kvm ]]; then
  echo "/dev/kvm is not readable. Add this user to the kvm group." >&2
  exit 1
fi

mkdir -p "${WORKDIR}"
cd "${WORKDIR}"

if [[ ! -f "${BASE_NAME}" ]]; then
  echo "downloading ${IMAGE_URL}"
  wget -O "${BASE_NAME}" "${IMAGE_URL}"
fi

if [[ ! -f slash-amd64.qcow2 ]]; then
  qemu-img create -f qcow2 -F qcow2 -b "${BASE_NAME}" slash-amd64.qcow2 "${DISK_SIZE}"
fi

cloud-localds seed.img "${ROOT}/cloud-init/user-data" "${ROOT}/cloud-init/meta-data"

echo "ssh: ssh -p ${SSH_PORT} slash@127.0.0.1   (password: slash)"
echo "ADB stays inside the guest. Forward it with:"
echo "  ssh -p ${SSH_PORT} -L 5555:127.0.0.1:5555 slash@127.0.0.1"

exec qemu-system-x86_64 \
  -machine q35,accel=kvm \
  -cpu host \
  -smp "${SMP}" \
  -m "${MEM}" \
  -drive if=virtio,file=slash-amd64.qcow2 \
  -drive if=virtio,format=raw,file=seed.img \
  -netdev user,id=n0,hostfwd=tcp:127.0.0.1:"${SSH_PORT}"-:22,hostfwd=tcp:127.0.0.1:"${API_PORT}"-:8787 \
  -device virtio-net-pci,netdev=n0 \
  -nographic \
  -serial mon:stdio
