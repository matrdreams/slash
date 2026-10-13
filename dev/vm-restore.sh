#!/usr/bin/env bash
# Bring up the Redroid VM (QEMU **TCG only** -- KVM crashes this host kernel).
# 1) If $CACHE_DIR has slash-vm.qcow2.pNN parts (from Google Drive Code/slash-cache,
#    fetched by the agent's Drive connector -- files are private, no public URL),
#    reassemble + verify sha256 and boot the ready disk (Android up in ~3-10 min).
# 2) Else build from scratch with dev/qemu/make-amd64-vm.sh (ACCEL=tcg, ~30-60 min).
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
WORKDIR=${WORKDIR:-/workspace/vm}; CACHE_DIR=${CACHE_DIR:-/workspace/cache}
SMP=${SMP:-6}; MEM=${MEM:-8192}; SSH_PORT=${SSH_PORT:-22022}; ADB_PORT=${ADB_PORT:-15555}
DISK=$WORKDIR/vm-ready.qcow2
if pgrep -f "hostfwd=tcp:127.0.0.1:${ADB_PORT}-" >/dev/null; then echo "VM already running"; exec "$ROOT/qemu/post-boot.sh" "127.0.0.1:$ADB_PORT"; fi
mkdir -p "$WORKDIR"
if [[ ! -f $DISK ]] && ls "$CACHE_DIR"/slash-vm.qcow2.p[0-9][0-9] >/dev/null 2>&1; then
  echo "restoring from cache $CACHE_DIR"
  cat "$CACHE_DIR"/slash-vm.qcow2.p[0-9][0-9] > "$DISK.tmp"
  if [[ -f $CACHE_DIR/SHA256SUMS ]]; then
    want=$(awk '$2=="slash-vm.qcow2"{print $1}' "$CACHE_DIR/SHA256SUMS")
    [[ -z $want || $(sha256sum < "$DISK.tmp" | cut -d' ' -f1) == "$want" ]] || { echo "sha256 mismatch" >&2; exit 1; }
  fi
  mv "$DISK.tmp" "$DISK"
  [[ -f $CACHE_DIR/ADBKeyboard.apk ]] && cp "$CACHE_DIR/ADBKeyboard.apk" "$WORKDIR/"
fi
if [[ ! -f $DISK ]]; then
  echo "no cache: building from scratch (TCG)"
  WORKDIR=$WORKDIR ACCEL=tcg "$ROOT/qemu/make-amd64-vm.sh"
  exec env APK="$WORKDIR/ADBKeyboard.apk" "$ROOT/qemu/post-boot.sh" "127.0.0.1:$ADB_PORT"
fi
cd "$WORKDIR"
# Cached disk has the redroid container stopped (docker stop before snapshot); the seed restarts it.
# Private ssh key is never cached; make a fresh one and inject via a new cloud-init instance.
if [[ ! -f vmkey || ! -f restore-seed.img ]]; then
  [[ -f vmkey ]] || ssh-keygen -q -t ed25519 -N '' -f vmkey
  printf '#cloud-config\nusers:\n  - name: ubuntu\n    sudo: ALL=(ALL) NOPASSWD:ALL\n    ssh_authorized_keys: ["%s"]\nruncmd:\n  - docker update --restart always redroid\n  - docker start redroid\n' "$(cat vmkey.pub)" > restore-user-data
  printf 'instance-id: slash-restore-%s\nlocal-hostname: slash\n' "$(date +%s)" > restore-meta-data
  cloud-localds restore-seed.img restore-user-data restore-meta-data
fi
setsid nohup qemu-system-x86_64 -accel tcg,thread=multi -cpu max -smp "$SMP" -m "$MEM" \
  -drive file="$DISK",if=virtio -drive file=restore-seed.img,if=virtio,format=raw \
  -nic user,hostfwd=tcp:127.0.0.1:${SSH_PORT}-:22,hostfwd=tcp:127.0.0.1:${ADB_PORT}-:5555 \
  -display none -serial file:serial.log -pidfile qemu.pid </dev/null >qemu.out 2>&1 &
echo "qemu started (pid $!)"
APK=${APK:-$WORKDIR/ADBKeyboard.apk} exec "$ROOT/qemu/post-boot.sh" "127.0.0.1:$ADB_PORT"
