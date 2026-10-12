#!/usr/bin/env bash
# Boot an Ubuntu 22.04 amd64 VM that runs Redroid in docker, with adb forwarded
# to 127.0.0.1:${ADB_PORT}. Reproduces the setup verified on 2026-10-12.
#   ACCEL=kvm (default) | tcg   -- tcg works but is slow (~10 min to boot Android)
# Usage: WORKDIR=/workspace/vm dev/qemu/make-amd64-vm.sh   (runs qemu in background)
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
WORKDIR=${WORKDIR:-/workspace/vm}
ACCEL=${ACCEL:-kvm}
SMP=${SMP:-6}; MEM=${MEM:-8192}; DISK_SIZE=${DISK_SIZE:-40G}
SSH_PORT=${SSH_PORT:-22022}; ADB_PORT=${ADB_PORT:-15555}
REDROID_IMAGE=${REDROID_IMAGE:-redroid/redroid:12.0.0_64only-latest}
IMAGE_URL=${IMAGE_URL:-https://cloud-images.ubuntu.com/jammy/current/jammy-server-cloudimg-amd64.img}

mkdir -p "$WORKDIR"; cd "$WORKDIR"
[[ -f jammy.img ]] || { [[ -f /workspace/vm/jammy.img ]] && cp /workspace/vm/jammy.img .; } || true
[[ -f jammy.img ]] || wget -O jammy.img "$IMAGE_URL"
[[ -f vmkey ]] || ssh-keygen -t ed25519 -N '' -f vmkey
[[ -f vm.qcow2 ]] || qemu-img create -f qcow2 -F qcow2 -b jammy.img vm.qcow2 "$DISK_SIZE"
ADB_B64=$(base64 -w0 "${ROOT}/adb-localhost.sh")
cat > user-data <<UD
#cloud-config
users:
  - name: ubuntu
    sudo: ALL=(ALL) NOPASSWD:ALL
    ssh_authorized_keys: ["$(cat vmkey.pub)"]
package_update: true
runcmd:
  - apt-get install -y linux-modules-extra-\$(uname -r) docker.io
  - modprobe binder_linux devices="binder,hwbinder,vndbinder"
  - echo binder_linux > /etc/modules-load.d/redroid.conf
  - echo 'options binder_linux devices=binder,hwbinder,vndbinder' > /etc/modprobe.d/redroid.conf
  - docker run -d --privileged --restart unless-stopped --name redroid -p 127.0.0.1:5555:5555 ${REDROID_IMAGE}
  - bash -lc 'echo ${ADB_B64} | base64 -d > /usr/local/sbin/slash-adb-localhost.sh && chmod 755 /usr/local/sbin/slash-adb-localhost.sh && /usr/local/sbin/slash-adb-localhost.sh'
  - bash -lc 'printf "%s\n" "[Unit]" "Description=Keep Redroid ADB on 127.0.0.1" "After=docker.service" "Wants=docker.service" "" "[Service]" "Type=oneshot" "RemainAfterExit=yes" "ExecStart=/usr/local/sbin/slash-adb-localhost.sh" "" "[Install]" "WantedBy=multi-user.target" > /etc/systemd/system/slash-adb-localhost.service && systemctl daemon-reload && systemctl enable slash-adb-localhost.service'
  - touch /root/ready
UD
printf 'instance-id: slash-amd64\nlocal-hostname: slash\n' > meta-data
cloud-localds seed.img user-data meta-data

if [[ $ACCEL == kvm ]]; then
  [[ -r /dev/kvm && -w /dev/kvm ]] || { echo "/dev/kvm not usable; set ACCEL=tcg" >&2; exit 1; }
  # /dev/kvm can be rw yet broken (2026-10-12 box: host oops in kvm_arch_vcpu_create, qemu hangs
  # forever at 0 CPU). Probe with a throwaway VM first.
  if ! printf 'quit\n' | timeout 15 qemu-system-x86_64 -accel kvm -cpu host -display none -nodefaults -S -monitor stdio >/dev/null 2>&1; then
    echo "KVM probe failed/hung (check dmesg for kvm_spurious_fault); rerun with ACCEL=tcg" >&2; exit 1
  fi
  ACC=(-accel kvm -cpu host)
else
  ACC=(-accel tcg,thread=multi -cpu max)
fi
setsid nohup qemu-system-x86_64 "${ACC[@]}" -smp "$SMP" -m "$MEM" \
  -drive file=vm.qcow2,if=virtio -drive file=seed.img,if=virtio,format=raw \
  -nic user,hostfwd=tcp:127.0.0.1:${SSH_PORT}-:22,hostfwd=tcp:127.0.0.1:${ADB_PORT}-:5555 \
  -display none -serial file:serial.log -monitor unix:mon.sock,server,nowait -pidfile qemu.pid < /dev/null > qemu.out 2>&1 &
echo "qemu pid $!  ssh: ssh -i $WORKDIR/vmkey -p $SSH_PORT ubuntu@127.0.0.1"
echo "then: adb connect 127.0.0.1:$ADB_PORT && adb -s 127.0.0.1:$ADB_PORT shell getprop sys.boot_completed"
echo "after boot: dev/qemu/post-boot.sh 127.0.0.1:$ADB_PORT  (waits for boot, installs ADBKeyBoard)"
