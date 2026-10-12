#!/usr/bin/env bash
# Encrypt a device data directory and an optional sqlite database.
# Stop the container first so Android SQLite files are not copied while open.
#
# Usage:
#   backup.sh backup --data DIR --out FILE [--db FILE] [--passphrase-file FILE]
#   backup.sh restore --archive FILE --data DIR [--db FILE] [--passphrase-file FILE]
#
# The passphrase is SLASH_BACKUP_PASSPHRASE, or the contents of --passphrase-file.
# Encryption is openssl aes-256-cbc with -pbkdf2 and a random salt.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  backup.sh backup --data DIR --out FILE [--db FILE] [--passphrase-file FILE]
  backup.sh restore --archive FILE --data DIR [--db FILE] [--passphrase-file FILE]

Encrypts a tar of the device data directory and an optional sqlite database
with openssl aes-256-cbc -pbkdf2. The passphrase is SLASH_BACKUP_PASSPHRASE
or the file passed to --passphrase-file. Stop the container before backup.
EOF
}

die() {
  echo "$1" >&2
  exit 2
}

DATA=""
OUT=""
DB=""
ARCHIVE=""
PASSFILE=""
MODE="${1:-}"

if [[ "${MODE}" == "-h" || "${MODE}" == "--help" || -z "${MODE}" ]]; then
  usage
  if [[ "${MODE}" == "-h" || "${MODE}" == "--help" ]]; then
    exit 0
  fi
  exit 2
fi
shift

while [[ $# -gt 0 ]]; do
  case "$1" in
    --data)
      [[ $# -ge 2 ]] || die "--data needs a value"
      DATA=$2
      shift 2
      ;;
    --out)
      [[ $# -ge 2 ]] || die "--out needs a value"
      OUT=$2
      shift 2
      ;;
    --db)
      [[ $# -ge 2 ]] || die "--db needs a value"
      DB=$2
      shift 2
      ;;
    --archive)
      [[ $# -ge 2 ]] || die "--archive needs a value"
      ARCHIVE=$2
      shift 2
      ;;
    --passphrase-file)
      [[ $# -ge 2 ]] || die "--passphrase-file needs a value"
      PASSFILE=$2
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "unknown argument: $1"
      ;;
  esac
done

require_pass() {
  if [[ -n "${PASSFILE}" ]]; then
    [[ -f "${PASSFILE}" ]] || die "passphrase file not found"
    SLASH_BACKUP_PASSPHRASE="$(cat "${PASSFILE}")"
    export SLASH_BACKUP_PASSPHRASE
  fi
  if [[ -z "${SLASH_BACKUP_PASSPHRASE:-}" ]]; then
    die "set SLASH_BACKUP_PASSPHRASE or pass --passphrase-file"
  fi
}

backup() {
  require_pass
  [[ -n "${DATA}" && -d "${DATA}" ]] || die "--data must be an existing directory"
  [[ -n "${OUT}" ]] || die "--out is required"
  if [[ -n "${DB}" && ! -f "${DB}" ]]; then
    die "--db is not a file"
  fi
  mkdir -p "$(dirname "${OUT}")"
  stage=$(mktemp -d)
  trap 'rm -rf "${stage}"' RETURN
  mkdir -p "${stage}/data"
  cp -a "${DATA}/." "${stage}/data/"
  items=(data)
  if [[ -n "${DB}" ]]; then
    cp -a "${DB}" "${stage}/slash.db"
    items+=(slash.db)
  fi
  tar -C "${stage}" -czf - "${items[@]}" \
    | openssl enc -aes-256-cbc -pbkdf2 -salt -pass env:SLASH_BACKUP_PASSPHRASE -out "${OUT}"
  trap - RETURN
  rm -rf "${stage}"
}

restore() {
  require_pass
  [[ -n "${ARCHIVE}" && -f "${ARCHIVE}" ]] || die "--archive must be an existing file"
  [[ -n "${DATA}" ]] || die "--data is required"
  stage=$(mktemp -d)
  trap 'rm -rf "${stage}"' RETURN
  openssl enc -d -aes-256-cbc -pbkdf2 -salt -pass env:SLASH_BACKUP_PASSPHRASE -in "${ARCHIVE}" \
    | tar -xzf - -C "${stage}"
  mkdir -p "${DATA}"
  find "${DATA}" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
  cp -a "${stage}/data/." "${DATA}/"
  if [[ -n "${DB}" ]]; then
    [[ -f "${stage}/slash.db" ]] || die "archive has no slash.db"
    mkdir -p "$(dirname "${DB}")"
    cp -a "${stage}/slash.db" "${DB}"
  fi
  trap - RETURN
  rm -rf "${stage}"
}

case "${MODE}" in
  backup) backup ;;
  restore) restore ;;
  *)
    usage
    die "mode must be backup or restore"
    ;;
esac
