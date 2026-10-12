# Debian 11/12 host preparation. Sourced by host/install.sh.
# Upstream loads distinct binder devices per instance and bind-mounts them into the container.
# Prefer a kernel built with CONFIG_ANDROID_BINDERFS=y and
# CONFIG_ANDROID_BINDER_DEVICES="binder,hwbinder,vndbinder" when the instance count is unbounded.

install_distro() {
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y ca-certificates curl python3

  if ! apt-get install -y "linux-modules-extra-$(uname -r)"; then
    echo "warning: linux-modules-extra-$(uname -r) is not installable" >&2
  fi

  if [[ "${NO_DOCKER:-0}" -eq 0 ]]; then
    apt-get install -y docker.io
    systemctl enable --now docker || true
  fi

  apt-get install -y adb || apt-get install -y android-tools-adb

  install -d /etc/modules-load.d /etc/modprobe.d
  printf '%s\n' 'binder_linux' > /etc/modules-load.d/redroid.conf
  printf '%s\n' 'options binder_linux devices=binder1,binder2,binder3,binder4,binder5,binder6' \
    > /etc/modprobe.d/redroid.conf

  modprobe binder_linux devices="binder1,binder2,binder3,binder4,binder5,binder6" || true
  if compgen -G '/dev/binder*' > /dev/null; then
    chmod 666 /dev/binder* || true
  fi
}
