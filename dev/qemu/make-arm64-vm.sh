#!/usr/bin/env bash
# Create and boot an Ubuntu 22.04 arm64 cloud VM for Redroid development.
# On an arm64 host with /dev/kvm this uses KVM (-accel kvm -cpu host).
# On x86_64 it falls back to TCG, which is only fast enough to check the scripts.
#
# Dependencies (Ubuntu host):
#   sudo apt install -y qemu-system-arm qemu-efi-aarch64 qemu-utils cloud-image-utils
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
WORKDIR=${WORKDIR:-"${PWD}/.slash-vm"}
DISK_SIZE=${DISK_SIZE:-40G}
MEM=${MEM:-8G}
SMP=${SMP:-4}
SSH_PORT=${SSH_PORT:-2222}
API_PORT=${API_PORT:-8787}
IMAGE_URL=${IMAGE_URL:-https://cloud-images.ubuntu.com/jammy/current/jammy-server-cloudimg-arm64.img}
BASE_NAME=jammy-server-cloudimg-arm64.img

mkdir -p "${WORKDIR}"
cd "${WORKDIR}"

if [[ ! -f "${BASE_NAME}" ]]; then
  echo "downloading ${IMAGE_URL}"
  wget -O "${BASE_NAME}" "${IMAGE_URL}"
fi

if [[ ! -f slash-arm64.qcow2 ]]; then
  qemu-img create -f qcow2 -F qcow2 -b "${BASE_NAME}" slash-arm64.qcow2 "${DISK_SIZE}"
fi

cloud-localds seed.img "${ROOT}/cloud-init/user-data" "${ROOT}/cloud-init/meta-data"

CODE_FD=${CODE_FD:-/usr/share/AAVMF/AAVMF_CODE.fd}
VARS_SRC=${VARS_SRC:-/usr/share/AAVMF/AAVMF_VARS.fd}
if [[ ! -f "${CODE_FD}" || ! -f "${VARS_SRC}" ]]; then
  echo "AAVMF firmware not found. Install qemu-efi-aarch64." >&2
  echo "looked for ${CODE_FD} and ${VARS_SRC}" >&2
  exit 1
fi
if [[ ! -f vars.fd ]]; then
  cp "${VARS_SRC}" vars.fd
fi

ACCEL="-accel tcg,thread=multi -cpu max"
if [[ "$(uname -m)" == "aarch64" && -e /dev/kvm ]]; then
  ACCEL="-accel kvm -cpu host"
fi

echo "boot accel: ${ACCEL}"
echo "ssh: ssh -p ${SSH_PORT} slash@127.0.0.1   (password: slash)"
echo "forward ADB from the guest with: ssh -p ${SSH_PORT} -L 5555:127.0.0.1:5555 slash@127.0.0.1"

# shellcheck disable=SC2086
exec qemu-system-aarch64 -M virt ${ACCEL} -smp "${SMP}" -m "${MEM}" \
  -drive if=pflash,format=raw,readonly=on,file="${CODE_FD}" \
  -drive if=pflash,format=raw,file=vars.fd \
  -drive if=virtio,file=slash-arm64.qcow2 \
  -drive if=virtio,format=raw,file=seed.img \
  -netdev user,id=n0,hostfwd=tcp:127.0.0.1:"${SSH_PORT}"-:22,hostfwd=tcp:127.0.0.1:"${API_PORT}"-:8787 \
  -device virtio-net-pci,netdev=n0 \
  -nographic
