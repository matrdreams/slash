# Alibaba Cloud Linux 2/3, Amazon Linux 2, openEuler 20.03.
# These kernels usually need https://github.com/remote-android/redroid-modules (4.14+, DKMS /
# manual / Docker / K8s). Kernel >= 5.7 should prefer the distro modprobe path when binder_linux
# is already built. This script does not clone or build that tree: it loads the module when the
# running kernel already provides it, and otherwise tells the operator exactly what to install.

install_distro() {
  if command -v dnf >/dev/null 2>&1; then
    dnf install -y python3 || true
    if [[ "${NO_DOCKER:-0}" -eq 0 ]]; then
      dnf install -y docker || yum install -y docker || true
      systemctl enable --now docker || true
    fi
    dnf install -y android-tools || true
  elif command -v yum >/dev/null 2>&1; then
    yum install -y python3 || true
    if [[ "${NO_DOCKER:-0}" -eq 0 ]]; then
      yum install -y docker || true
      systemctl enable --now docker || true
    fi
  fi

  install -d /etc/modules-load.d /etc/modprobe.d
  install -m 0644 "${ROOT}/modules-load.d/redroid.conf" /etc/modules-load.d/redroid.conf
  install -m 0644 "${ROOT}/modprobe.d/redroid.conf" /etc/modprobe.d/redroid.conf

  if modprobe binder_linux devices="binder,hwbinder,vndbinder"; then
    return 0
  fi

  cat >&2 <<'EOF'
binder_linux is not loadable on this kernel.
Install redroid-modules (kernel >= 4.14) from
https://github.com/remote-android/redroid-modules
using the DKMS, manual, Docker, or K8s method for AL2 / Alinux 2/3 / openEuler,
then re-run host/install.sh.
Kernels >= 5.7 should use a distro kernel that already ships binder (Ubuntu generic)
or a custom kernel with CONFIG_ANDROID_BINDER_IPC and CONFIG_ANDROID_BINDERFS.
EOF
  return 1
}
