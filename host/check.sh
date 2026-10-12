#!/usr/bin/env bash
# Host health check for Redroid. Prints a JSON object with --json.
# Exit 0 when issues is empty, otherwise exit 1. JSON still goes to stdout.
set -uo pipefail

JSON=0
for arg in "$@"; do
  case "${arg}" in
    -h|--help)
      echo "Usage: ./host/check.sh [--json]"
      exit 0
      ;;
    --json)
      JSON=1
      ;;
    *)
      echo "unknown argument: ${arg}" >&2
      exit 2
      ;;
  esac
done

issues=()
arch=$(uname -m 2>/dev/null || echo "unknown")

page_size=0
if page_size=$(getconf PAGESIZE 2>/dev/null); then
  if [[ "${page_size}" != "4096" ]]; then
    issues+=("page size ${page_size} != 4096; Android/Redroid needs a 4K-page kernel")
  fi
else
  page_size=0
  issues+=("getconf PAGESIZE failed")
fi

krel=$(uname -r 2>/dev/null || echo "")
kcfg="/boot/config-${krel}"
if [[ -f "${kcfg}" ]]; then
  if ! grep -E 'BINDER' "${kcfg}" >/dev/null 2>&1; then
    issues+=("kernel config ${kcfg} has no BINDER symbols; the cloud kernel may be too slim")
  fi
else
  issues+=("kernel config ${kcfg} not found; cannot confirm CONFIG_ANDROID_BINDER*")
fi

binder=false
binderfs=false
if command -v lsmod >/dev/null 2>&1 && lsmod 2>/dev/null | grep -q binder_linux; then
  binder=true
fi
if [[ -r /proc/filesystems ]] && grep -q binder /proc/filesystems 2>/dev/null; then
  binderfs=true
  binder=true
fi
if [[ -e /dev/binder || -d /dev/binderfs ]]; then
  binder=true
fi
if [[ "${binder}" != "true" ]]; then
  issues+=("binder_linux is not loaded and binderfs is not available")
fi

docker_ver=""
if command -v docker >/dev/null 2>&1; then
  docker_ver=$(docker version --format '{{.Server.Version}}' 2>/dev/null || true)
  if [[ -z "${docker_ver}" ]]; then
    docker_ver=$(docker --version 2>/dev/null | awk '{print $3}' | tr -d ',' || true)
  fi
  if [[ -z "${docker_ver}" ]]; then
    issues+=("docker is installed but the daemon did not report a version")
  fi
else
  issues+=("docker is not installed")
fi

if [[ ! -f /sys/fs/cgroup/cgroup.controllers ]]; then
  issues+=("cgroup v2 is not mounted (missing /sys/fs/cgroup/cgroup.controllers)")
fi

adb_ver=""
if command -v adb >/dev/null 2>&1; then
  adb_ver=$(adb version 2>/dev/null | awk 'NR==1 {print $NF}')
  if [[ -z "${adb_ver}" ]]; then
    issues+=("adb is installed but 'adb version' produced no output")
  fi
else
  issues+=("adb is not installed")
fi

check_listen_line() {
  local line="$1"
  local addr port host
  addr=$(awk '{print $4}' <<< "${line}")
  port="${addr##*:}"
  host="${addr%:*}"
  if [[ ! "${port}" =~ ^[0-9]+$ ]]; then
    return 0
  fi
  # 5555 and 5600-5699 are ADB. 8000 is ws-scrcpy. None of them may listen on every interface.
  if [[ "${port}" -eq 5555 || "${port}" -eq 8000 || ( "${port}" -ge 5600 && "${port}" -le 5699 ) ]]; then
    case "${host}" in
      0.0.0.0|\*|::|"[::]")
        issues+=("port ${port} is listening on ${host}; bind it to 127.0.0.1 only")
        ;;
    esac
  fi
}

if command -v ss >/dev/null 2>&1; then
  while IFS= read -r line; do
    [[ -z "${line}" ]] && continue
    check_listen_line "${line}"
  done < <(ss -H -lntn 2>/dev/null || true)
elif command -v netstat >/dev/null 2>&1; then
  while IFS= read -r line; do
    [[ -z "${line}" ]] && continue
    check_listen_line "${line}"
  done < <(netstat -lnt 2>/dev/null | awk 'NR>2 {print "LISTEN 0 0 "$4}' || true)
else
  issues+=("neither ss nor netstat is available; skipped the public ADB port check")
fi

virt="none"
if command -v systemd-detect-virt >/dev/null 2>&1; then
  # Exit status 1 means "not virtualized"; do not let that abort the script.
  virt=$(systemd-detect-virt 2>/dev/null || true)
  virt="${virt:-none}"
  if [[ "${virt}" == container* ]]; then
    issues+=("running inside a container (${virt}); Redroid cannot load binder here")
  fi
fi

if [[ "${JSON}" -eq 1 ]]; then
  if ! command -v python3 >/dev/null 2>&1; then
    printf '%s\n' '{"binder":false,"binderfs":false,"page_size":0,"docker":"","adb":"","arch":"unknown","issues":["python3 is required for --json"]}'
    exit 1
  fi
  export SLASH_ARCH="${arch}"
  export SLASH_PAGE="${page_size}"
  export SLASH_BINDER="${binder}"
  export SLASH_BINDERFS="${binderfs}"
  export SLASH_DOCKER="${docker_ver}"
  export SLASH_ADB="${adb_ver}"
  export SLASH_VIRT="${virt}"
  if [[ ${#issues[@]} -eq 0 ]]; then
    export SLASH_ISSUES=""
  else
    SLASH_ISSUES=$(printf '%s\n' "${issues[@]}")
    export SLASH_ISSUES
  fi
  python3 - <<'PY'
import json
import os

def flag(name: str) -> bool:
    return os.environ.get(name, "false") == "true"

issues = [line for line in os.environ.get("SLASH_ISSUES", "").split("\n") if line]
payload = {
    "binder": flag("SLASH_BINDER"),
    "binderfs": flag("SLASH_BINDERFS"),
    "page_size": int(os.environ.get("SLASH_PAGE") or "0"),
    "docker": os.environ.get("SLASH_DOCKER", ""),
    "adb": os.environ.get("SLASH_ADB", ""),
    "arch": os.environ.get("SLASH_ARCH", ""),
    "virt": os.environ.get("SLASH_VIRT", "none"),
    "issues": issues,
}
print(json.dumps(payload, ensure_ascii=False))
PY
else
  echo "arch=${arch} page_size=${page_size} binder=${binder} binderfs=${binderfs} virt=${virt}"
  echo "docker=${docker_ver:-missing} adb=${adb_ver:-missing}"
  if [[ ${#issues[@]} -eq 0 ]]; then
    echo "issues: none"
  else
    echo "issues (${#issues[@]}):"
    for item in "${issues[@]}"; do
      echo "  - ${item}"
    done
  fi
fi

if [[ ${#issues[@]} -eq 0 ]]; then
  exit 0
fi
exit 1
