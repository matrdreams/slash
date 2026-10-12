"""Load tests/compat/apps.yaml and probe install/launch on a real adb serial.

Login and the basic task stay "not run". Those need the account holder.
"""

import asyncio
import os
import shlex
from pathlib import Path

import yaml

from slash.core.errors import AdbError
from slash.devices.adb import AdbClient

COLUMNS = ("App", "Package", "Mode", "Install", "Launch", "Login", "Basic task", "Cost", "Notes")


def default_apps_path() -> Path:
    candidates = [
        Path.cwd() / "tests" / "compat" / "apps.yaml",
        Path(__file__).resolve().parents[2] / "tests" / "compat" / "apps.yaml",
    ]
    for path in candidates:
        if path.is_file():
            return path
    return candidates[-1]


def load_apps(path: str | Path) -> list[dict]:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    apps = document.get("apps") or []
    if not isinstance(apps, list):
        raise ValueError("apps.yaml must contain a list under apps")
    cleaned: list[dict] = []
    for entry in apps:
        if not isinstance(entry, dict):
            raise ValueError("each app entry must be a mapping")
        package = str(entry.get("package") or "").strip()
        name = str(entry.get("name") or package).strip()
        if not package or not name:
            raise ValueError("each app needs name and package")
        cleaned.append(
            {
                "name": name,
                "package": package,
                "mode": str(entry.get("mode") or "tree+vision"),
                "basic_task": str(entry.get("basic_task") or ""),
                "notes": str(entry.get("notes") or ""),
            }
        )
    return cleaned


def render_matrix(apps: list[dict], results: dict[str, dict] | None = None) -> str:
    """Markdown table. Missing probes stay `not run`."""
    found = results or {}
    lines = [
        "# Compatibility matrix",
        "",
        "Template from `tests/compat/apps.yaml`. `slash compat run` fills Install and Launch",
        "when `SLASH_ADB_SERIAL` points at a booted Redroid. Login, the basic task, and cost",
        "stay `not run` until a person finishes them. This file is not a measurement.",
        "",
        "| " + " | ".join(COLUMNS) + " |",
        "| " + " | ".join("---" for _ in COLUMNS) + " |",
    ]
    for app in apps:
        result = found.get(app["package"], {})
        cells = [
            app["name"],
            f"`{app['package']}`",
            app["mode"],
            str(result.get("install") or "not run"),
            str(result.get("launch") or "not run"),
            str(result.get("login") or "not run"),
            str(result.get("basic_task") or "not run"),
            str(result.get("cost") or "not run"),
            _cell(result.get("notes") or app["notes"] or app["basic_task"]),
        ]
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    return "\n".join(lines)


def _cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


async def probe(serial: str, apps: list[dict], adb: AdbClient | None = None) -> dict[str, dict]:
    client = adb or AdbClient()
    await client.connect(serial)
    results: dict[str, dict] = {}
    for app in apps:
        results[app["package"]] = await _probe_one(client, serial, app)
    return results


async def _probe_one(adb: AdbClient, serial: str, app: dict) -> dict:
    package = app["package"]
    row = {
        "install": "no",
        "launch": "no",
        "login": "not run",
        "basic_task": "not run",
        "cost": "not run",
        "notes": app["notes"],
    }
    try:
        listed = await adb.shell(serial, f"pm path {shlex.quote(package)}")
    except AdbError as exc:
        row["notes"] = f"pm path failed: {exc}"
        return row
    if "package:" not in listed:
        row["notes"] = (row["notes"] + " not installed").strip()
        return row
    row["install"] = "yes"
    try:
        resolved = await adb.shell(
            serial,
            "cmd package resolve-activity --brief "
            "-a android.intent.action.MAIN -c android.intent.category.LAUNCHER "
            f"{shlex.quote(package)}",
        )
        component = resolved.strip().splitlines()[-1].strip() if resolved.strip() else ""
        if "/" not in component:
            row["launch"] = "fail"
            row["notes"] = (row["notes"] + " no launcher activity").strip()
            return row
        await adb.shell(serial, f"am start -n {shlex.quote(component)}")
        row["launch"] = "yes"
    except AdbError as exc:
        row["launch"] = "fail"
        row["notes"] = (row["notes"] + f" launch failed: {exc}").strip()
    return row


def main(argv: list[str] | None = None) -> int:
    args = list(argv or [])
    apps_path = default_apps_path()
    write_matrix: Path | None = None
    if "--apps" in args:
        apps_path = Path(args[args.index("--apps") + 1])
    if "--write-matrix" in args:
        write_matrix = Path(args[args.index("--write-matrix") + 1])
    apps = load_apps(apps_path)
    serial = os.environ.get("SLASH_ADB_SERIAL", "").strip()
    results: dict[str, dict] = {}
    if serial:
        results = asyncio.run(probe(serial, apps))
    text = render_matrix(apps, results)
    if write_matrix is not None:
        write_matrix.parent.mkdir(parents=True, exist_ok=True)
        write_matrix.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0
