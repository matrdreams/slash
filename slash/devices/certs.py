"""APK certificate checks. apksigner is used when it is installed; tests inject a verifier."""

import hashlib
import re
import subprocess
from pathlib import Path
from typing import Protocol

from slash.core.errors import SignatureMismatchError

_SHA256 = re.compile(r"SHA-256 digest:\s*([0-9A-Fa-f:]+)")


def normalize_cert(value: str) -> str:
    return value.replace(":", "").replace(" ", "").lower()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class CertVerifier(Protocol):
    def fingerprint(self, apk: Path) -> str: ...


class ApksignerVerifier:
    """Runs `apksigner verify --print-certs` and reads the signer SHA-256 digest."""

    def __init__(self, binary: str = "apksigner") -> None:
        self.binary = binary

    def fingerprint(self, apk: Path) -> str:
        proc = subprocess.run(
            [self.binary, "verify", "--print-certs", str(apk)],
            capture_output=True,
            text=True,
            check=False,
        )
        output = (proc.stdout or "") + "\n" + (proc.stderr or "")
        if proc.returncode != 0 and "SHA-256 digest" not in output:
            raise SignatureMismatchError(output.strip() or "apksigner failed")
        match = _SHA256.search(output)
        if match is None:
            raise SignatureMismatchError("apksigner output has no SHA-256 digest")
        return normalize_cert(match.group(1))


def assert_expected_cert(actual: str, expected: str) -> str:
    got = normalize_cert(actual)
    want = normalize_cert(expected)
    if got != want:
        raise SignatureMismatchError(f"certificate mismatch: expected {want} got {got}")
    return got


def assert_registry_pin(package: str | None, actual: str, pins: dict[str, str]) -> None:
    if not package or package not in pins:
        return
    assert_expected_cert(actual, pins[package])
