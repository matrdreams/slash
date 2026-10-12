# shellcheck shell=bash
# Ubuntu host preparation. Sourced by host/install.sh; do not execute directly.
# Supports 18.04 (HWE kernel), 20.04/22.04, and 24.04 (same flow as 22.04; 24.04 is not on the
# upstream deploy page and should be confirmed with host/check.sh).

install_distro() {
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y ca-certificates curl python3

  if [[ "${VERSION_ID:-}" == "18.04" ]]; then
    apt-get install -y --install-recommends linux-generic-hwe-18.04
    modprobe nfnetlink || true
  fi

  # modules-extra matches the running kernel. A cloud -kvm kernel may not ship binder;
  # linux-generic is the fallback the operator can reboot into.
  if ! apt-get install -y "linux-modules-extra-$(uname -r)"; then
    echo "warning: linux-modules-extra-$(uname -r) is not installable" >&2
    echo "warning: if this is a -kvm kernel, install linux-generic and reboot" >&2
  fi

  if [[ "${NO_DOCKER:-0}" -eq 0 ]]; then
    apt-get install -y docker.io
    systemctl enable --now docker || true
  fi

  apt-get install -y adb || apt-get install -y android-tools-adb

  install -d /etc/modules-load.d /etc/modprobe.d
  install -m 0644 "${ROOT}/modules-load.d/redroid.conf" /etc/modules-load.d/redroid.conf
  install -m 0644 "${ROOT}/modprobe.d/redroid.conf" /etc/modprobe.d/redroid.conf

  modprobe binder_linux devices="binder,hwbinder,vndbinder" || true
  # ashmem_linux was removed from the kernel in 5.18. Redroid uses memfd instead.
  modprobe ashmem_linux || true
}
