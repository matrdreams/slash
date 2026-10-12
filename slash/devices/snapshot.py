"""Stop-then-archive snapshots of a device data directory.

Running containers are not archived: Android keeps SQLite files open, and a live
copy can come back corrupt. The manager stops the device before calling this.
"""

import shutil
import tarfile
from pathlib import Path


def archive_tree(src: Path, dest: Path) -> int:
    dest.parent.mkdir(parents=True, exist_ok=True)
    src.mkdir(parents=True, exist_ok=True)
    with tarfile.open(dest, "w:gz") as tar:
        for path in sorted(src.rglob("*")):
            tar.add(path, arcname=path.relative_to(src).as_posix())
    return dest.stat().st_size


def _safe_members(tar: tarfile.TarFile, dest: Path) -> list[tarfile.TarInfo]:
    root = dest.resolve()
    members: list[tarfile.TarInfo] = []
    for member in tar.getmembers():
        target = (root / member.name).resolve()
        if target != root and root not in target.parents:
            raise ValueError(f"unsafe path in snapshot: {member.name}")
        members.append(member)
    return members


def extract_tree(archive: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for child in list(dest.iterdir()):
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    with tarfile.open(archive, "r:gz") as tar:
        members = _safe_members(tar, dest)
        try:
            tar.extractall(dest, members=members, filter="data")
        except TypeError:
            tar.extractall(dest, members=members)
