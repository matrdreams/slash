#!/usr/bin/env bash
# Idempotent host setup: apt deps, python venv, worker npm ci.
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
PKGS=(qemu-system-x86 qemu-utils cloud-image-utils adb wget openssh-client zstd python3-venv nodejs npm)
missing=(); for p in "${PKGS[@]}"; do dpkg -s "$p" >/dev/null 2>&1 || missing+=("$p"); done
if ((${#missing[@]})); then sudo apt-get update -qq && sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${missing[@]}"; fi
cd "$ROOT"
[[ -x .venv/bin/python ]] || python3 -m venv .venv
if [[ -f pyproject.toml ]]; then .venv/bin/pip install -q -e '.[dev]' 2>/dev/null || .venv/bin/pip install -q -e .; fi
[[ -f requirements.txt ]] && .venv/bin/pip install -q -r requirements.txt
.venv/bin/python -c 'import uiautomator2' 2>/dev/null || .venv/bin/pip install -q uiautomator2
if [[ -f worker/package-lock.json ]]; then (cd worker && { [[ -d node_modules && node_modules -nt package-lock.json ]] || npm ci; }); fi
echo "setup ok"
