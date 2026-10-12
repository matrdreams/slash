#!/usr/bin/env bash
# Download APKs listed in images/apks/manifest.yaml into images/apks/files/.
# An entry is skipped with a non-zero status when url or sha256 is empty.
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
MANIFEST="${ROOT}/apks/manifest.yaml"
DEST="${ROOT}/apks/files"
mkdir -p "${DEST}"

python3 - "${MANIFEST}" "${DEST}" <<'PY'
import hashlib
import sys
import urllib.request
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("PyYAML is required: pip install pyyaml")

manifest_path, dest = sys.argv[1], Path(sys.argv[2])
doc = yaml.safe_load(Path(manifest_path).read_text(encoding="utf-8")) or {}
failed = 0
for entry in doc.get("apks") or []:
    name = entry.get("name") or "apk"
    url = (entry.get("url") or "").strip()
    digest = (entry.get("sha256") or "").strip().lower()
    if not url or not digest:
        print(f"skip {name}: url and sha256 must both be pinned before download", file=sys.stderr)
        failed = 1
        continue
    target = dest / f"{name}.apk"
    print(f"fetch {name}")
    with urllib.request.urlopen(url, timeout=120) as resp:
        data = resp.read()
    got = hashlib.sha256(data).hexdigest()
    if got != digest:
        print(f"sha256 mismatch for {name}: expected {digest} got {got}", file=sys.stderr)
        failed = 1
        continue
    target.write_bytes(data)
    print(f"wrote {target}")
sys.exit(failed)
PY
