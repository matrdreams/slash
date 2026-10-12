"""10-task AOSP eval with programmatic checkers (adb settings/content/dumpsys/uiautomator).

Run: .venv/bin/python eval/aosp_tasks.py --config /tmp/slash-m1/config.yaml --out eval/results
Each task: setup (adb shell cmds) -> `slash run` -> checker. The checker verdict, not the
agent's own `done`, is the ground truth.
"""

import argparse
import json
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

SERIAL = "127.0.0.1:15555"


def sh(cmd: str, timeout: int = 60) -> str:
    out = subprocess.run(
        ["adb", "-s", SERIAL, "shell", cmd], capture_output=True, text=True, timeout=timeout, check=False
    )
    return (out.stdout or "") + (out.stderr or "")


def setting(ns: str, key: str) -> str:
    return sh(f"settings get {ns} {key}").strip()


def dump() -> str:
    sh("uiautomator dump /sdcard/eval_dump.xml", timeout=90)
    return sh("cat /sdcard/eval_dump.xml")


def search_text(xml: str) -> str:
    for node in re.findall(r"<node [^>]*>", xml):
        if 'resource-id="android:id/search_src_text"' in node:
            t = re.search(r' text="([^"]*)"', node)
            return t.group(1) if t else ""
    return ""


def contacts() -> str:
    return sh("content query --uri content://com.android.contacts/data --projection display_name:data1:mimetype")


STATE: dict = {}

TASKS = [
    {
        "name": "settings-wifi",
        "steps": 10,
        "setup": lambda: STATE.__setitem__("wifi", setting("global", "wifi_on")),
        "goal": "打开设置（包名 com.android.settings）。进入网络或 Wi-Fi 页面，把 Wi-Fi 开关拨到相反状态。完成后用 done，result 里写明 Wi-Fi 现在是开还是关。",
        "check": lambda: (setting("global", "wifi_on") != STATE["wifi"], f"wifi_on {STATE['wifi']}->{setting('global', 'wifi_on')}"),
    },
    {
        "name": "deskclock-alarm",
        "steps": 12,
        "setup": lambda: None,
        "goal": "打开时钟（包名 com.android.deskclock）。新建一个早上 8:30 的闹钟并保存。完成后用 done。",
        "check": lambda: _alarm_check("8:30"),
    },
    {
        "name": "contact-name",
        "steps": 12,
        "setup": lambda: None,
        "goal": "打开联系人（包名 com.android.contacts）。新建一个联系人，姓名填写 Eval One，然后保存。完成后用 done。",
        "check": lambda: ("Eval One" in contacts(), "contacts data has Eval One" if "Eval One" in contacts() else "missing"),
    },
    {
        "name": "settings-search-display",
        "steps": 8,
        "setup": lambda: None,
        "goal": "打开设置（包名 com.android.settings），点开搜索框，输入 Display 并搜索。完成后用 done。",
        "check": lambda: _search_check("Display"),
    },
    {
        "name": "dark-theme",
        "steps": 10,
        "setup": lambda: sh("cmd uimode night no"),
        "goal": "打开设置（包名 com.android.settings），在显示（Display）里打开深色主题（Dark theme）。完成后用 done。",
        "check": lambda: ("yes" in sh("cmd uimode night"), sh("cmd uimode night").strip()),
    },
    {
        "name": "brightness-min",
        "steps": 10,
        "setup": lambda: (sh("settings put system screen_brightness_mode 0"), sh("settings put system screen_brightness 200")),
        "goal": "打开设置（包名 com.android.settings），进入显示（Display）里的亮度设置，把屏幕亮度调到最低。完成后用 done。",
        "check": lambda: (int(setting("system", "screen_brightness") or 999) < 60, f"screen_brightness={setting('system', 'screen_brightness')}"),
    },
    {
        "name": "contact-phone",
        "steps": 14,
        "setup": lambda: None,
        "goal": "打开联系人（包名 com.android.contacts）。新建联系人，姓名 Alice Wang，电话 13800138000，保存。完成后用 done。",
        "check": lambda: _phone_check(),
    },
    {
        "name": "airplane-on",
        "steps": 10,
        "setup": lambda: (sh("cmd connectivity airplane-mode disable"), sh("settings put global airplane_mode_on 0")),
        "goal": "打开设置（包名 com.android.settings），进入网络和互联网（Network & internet），打开飞行模式（Airplane mode）。完成后用 done。",
        "check": lambda: (setting("global", "airplane_mode_on") == "1", f"airplane_mode_on={setting('global', 'airplane_mode_on')}"),
        "teardown": lambda: sh("cmd connectivity airplane-mode disable"),
    },
    {
        "name": "ring-volume-max",
        "steps": 10,
        "setup": lambda: sh("cmd media_session volume --stream 2 --set 3"),
        "goal": "打开设置（包名 com.android.settings），进入声音（Sound），把铃声音量（Ring volume）调到最大。完成后用 done。",
        "check": lambda: _ring_check(),
    },
    {
        "name": "settings-search-zh",
        "steps": 8,
        "setup": lambda: None,
        "goal": "打开设置（包名 com.android.settings），点开搜索框，用 type 动作输入中文“显示”。完成后用 done。",
        "check": lambda: _search_check("显示"),
    },
]


def _alarm_check(hhmm: str):
    sh("am start -n com.android.deskclock/.DeskClock -a android.intent.action.SHOW_ALARMS")
    time.sleep(4)
    xml = dump()
    ok = bool(re.search(rf'text="{re.escape(hhmm)}\s?(AM)?"', xml)) or f'text="{hhmm}' in xml
    return ok, f"alarm list shows {hhmm}" if ok else f"{hhmm} not in alarm list"


def _search_check(want: str):
    xml = dump()
    got = search_text(xml)
    return want in got, f"search_src_text={got!r}"


def _phone_check():
    data = contacts()
    ok = "Alice Wang" in data and re.search(r"138\D?0013\D?8000", data) is not None
    return ok, "name+phone rows present" if ok else "missing name or phone"


def _ring_check():
    out = sh("cmd media_session volume --stream 2 --get")
    m = re.search(r"volume is (\d+) in range \[0\.\.(\d+)\]", out)
    if not m:
        return False, out.strip()[-120:]
    return m.group(1) == m.group(2), f"ring volume {m.group(1)}/{m.group(2)}"


def task_cost(db: str, task_id: str) -> dict:
    try:
        con = sqlite3.connect(db)
        row = con.execute("select tokens_in, tokens_out, cost_cny from task where id=?", (task_id,)).fetchone()
        return {"tokens_in": row[0], "tokens_out": row[1], "cost_cny": row[2]} if row else {}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="/tmp/slash-m1/config.yaml")
    ap.add_argument("--db", default="/tmp/slash-m1/slash.db")
    ap.add_argument("--out", default="eval/results")
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    summary = out / "summary.jsonl"
    for task in TASKS:
        if args.only and task["name"] not in args.only.split(","):
            continue
        print(f"=== {task['name']} {time.strftime('%H:%M:%S')}", flush=True)
        sh("input keyevent 3")
        task["setup"]()
        time.sleep(1)
        start = time.time()
        proc = subprocess.run(
            [".venv/bin/slash", "run", "phone", task["goal"], "--config", args.config, "--max-steps", str(task["steps"])],
            capture_output=True, text=True, check=False, timeout=3600,
        )
        elapsed = int(time.time() - start)
        try:
            agent = json.loads(proc.stdout.strip().splitlines()[-1])
        except Exception:  # noqa: BLE001
            agent = {"status": "CRASH", "error": (proc.stderr or proc.stdout)[-500:]}
        try:
            ok, evidence = task["check"]()
        except Exception as exc:  # noqa: BLE001
            ok, evidence = False, f"checker error {exc}"
        subprocess.run(
            f"adb -s {SERIAL} exec-out screencap -p > {out}/{task['name']}.png", shell=True, check=False
        )
        if task.get("teardown"):
            task["teardown"]()
        rec = {
            "name": task["name"],
            "agent_status": agent.get("status"),
            "agent_result": agent.get("result") or agent.get("error"),
            "steps": agent.get("steps_used"),
            "checker": ok,
            "checker_evidence": evidence,
            "elapsed_s": elapsed,
            **task_cost(args.db, agent.get("id", "")),
        }
        print(json.dumps(rec, ensure_ascii=False), flush=True)
        with summary.open("a") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print("=== ALL DONE", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
