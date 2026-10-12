# Dev VM (Redroid in QEMU)

Status 2026-10-12: Redroid 12 (`redroid/redroid:12.0.0_64only-latest`) booted in an
Ubuntu 22.04 amd64 VM on the box; `sys.boot_completed=1`; 5/5 integration tests pass.
Screenshot: docs/img/redroid-boot.png.

The running VM (files in /workspace/vm) was started with **TCG** (`-accel tcg -cpu max`,
disk vm2.qcow2, serial2.log) because /dev/kvm was not usable when it launched. KVM works now;
new VMs from `dev/qemu/make-amd64-vm.sh` use KVM by default.

Host forwards listen on `127.0.0.1` only (`22022` SSH, `15555` ADB). Inside the guest,
Redroid's published port is `127.0.0.1:5555` (`dev/qemu/adb-localhost.sh` drops a wildcard
`docker-proxy` and DNATs NIC tcp/5555 onto that loopback port so the existing hostfwd
still works). `binder_linux` is listed in `/etc/modules-load.d/redroid.conf` with
`options binder_linux devices=binder,hwbinder,vndbinder` in `/etc/modprobe.d/redroid.conf`.

## Reconnect
    pgrep -a qemu-system-x86_64                      # check it is still running
    ssh -i /workspace/vm/vmkey -p 22022 ubuntu@127.0.0.1 'sudo docker ps'
    adb connect 127.0.0.1:15555
    adb -s 127.0.0.1:15555 shell getprop sys.boot_completed   # -> 1
    SLASH_ADB_SERIAL=127.0.0.1:15555 .venv/bin/pytest -q tests/integration

## Fresh VM
    WORKDIR=/workspace/vm-kvm SSH_PORT=22023 ADB_PORT=15556 dev/qemu/make-amd64-vm.sh
Cloud-init installs linux-modules-extra + docker.io, loads binder_linux
(binder,hwbinder,vndbinder) via modules-load.d and modprobe.d, publishes
`127.0.0.1:5555:5555`, and enables `slash-adb-localhost.service` so QEMU
hostfwd to guest tcp/5555 reaches that loopback port.
