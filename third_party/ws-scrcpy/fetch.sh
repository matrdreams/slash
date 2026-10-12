#!/usr/bin/env bash
# Fetch the pinned NetrisTV/ws-scrcpy commit into third_party/ws-scrcpy/src.
# This does not install node_modules. The image build does that inside Docker.
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PIN_FILE="${ROOT}/PIN"
DEST="${ROOT}/src"

repo=""
commit=""
while IFS= read -r line || [[ -n "${line}" ]]; do
  key=${line%% *}
  value=${line#* }
  case "${key}" in
    repo) repo=${value} ;;
    commit) commit=${value} ;;
  esac
done < "${PIN_FILE}"

if [[ -z "${repo}" || -z "${commit}" ]]; then
  echo "PIN must contain repo and commit" >&2
  exit 2
fi

if [[ -d "${DEST}/.git" ]]; then
  current=$(git -C "${DEST}" rev-parse HEAD)
  if [[ "${current}" == "${commit}" ]]; then
    echo "ws-scrcpy already at ${commit}"
    exit 0
  fi
fi

rm -rf "${DEST}"
git init "${DEST}"
git -C "${DEST}" remote add origin "${repo}"
git -C "${DEST}" fetch --depth 1 origin "${commit}"
git -C "${DEST}" checkout --detach FETCH_HEAD
echo "fetched ${commit}"
