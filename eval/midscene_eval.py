"""10-task AOSP eval through the slash API -> MidsceneRuntime -> worker -> Redroid.

Reuses TASKS/checkers from eval/aosp_tasks.py. Needs a running worker (MIDSCENE_WORKER_URL,
default http://127.0.0.1:18790, model key in the worker env) and a booted device at
127.0.0.1:15555. Run: .venv/bin/python eval/midscene_eval.py [--only a,b] [--out eval/results-midscene]
"""

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))
import aosp_tasks as T  # noqa: E402

from slash.api.app import create_app  # noqa: E402
from slash.core.config import (  # noqa: E402
    AgentConfig,
    DevicesConfig,
    ServerConfig,
    SlashConfig,
    StorageConfig,
    TakeoverConfig,
)
from slash.wiring import build_context  # noqa: E402


class NoCerts:
    def fingerprint(self, apk):
        return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--out", default="eval/results-midscene")
    ap.add_argument("--max-cost", type=float, default=2.0)
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="slash-eval-"))
    cfg = SlashConfig(
        server=ServerConfig(bind="127.0.0.1:8787", public_base_url="http://127.0.0.1:8787", token="ev", secret="ev"),
        storage=StorageConfig(db_url=f"sqlite:///{tmp / 'slash.db'}", blob_dir=str(tmp / "blobs")),
        devices=DevicesConfig(backend="physical", data_root=str(tmp / "d"), serials={"phone": T.SERIAL}, boot_timeout_s=60),
        agent=AgentConfig(worker_url=os.environ.get("MIDSCENE_WORKER_URL", "http://127.0.0.1:18790"),
                          worker_url_explicit=True),
        takeover=TakeoverConfig(record=False),
    )
    ctx = build_context(cfg, cert_verifier=NoCerts(), inline_tasks=True)
    client = TestClient(create_app(ctx, start_background=False))
    h = {"Authorization": "Bearer ev"}
    dev = client.post("/api/v1/devices", headers=h, json={"name": "phone"}).json()
    for task in T.TASKS:
        if args.only and task["name"] not in args.only.split(","):
            continue
        T.sh("input keyevent 3")
        task["setup"]()
        time.sleep(1)
        start = time.time()
        body = {"device_id": dev["id"], "goal": task["goal"], "max_steps": task["steps"], "max_cost_cny": args.max_cost}
        res = client.post("/api/v1/tasks", headers=h, json=body).json()
        elapsed = round(time.time() - start, 1)
        try:
            ok, evidence = task["check"]()
        except Exception as exc:  # noqa: BLE001
            ok, evidence = False, f"checker error {exc}"
        if task.get("teardown"):
            task["teardown"]()
        rec = {"name": task["name"], "agent_status": res.get("status"), "error": res.get("error"),
               "steps": res.get("steps_used"), "cost_cny": res.get("cost_cny"), "checker": ok,
               "checker_evidence": evidence, "elapsed_s": elapsed}
        print(json.dumps(rec, ensure_ascii=False), flush=True)
        with (out / "summary.jsonl").open("a") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
