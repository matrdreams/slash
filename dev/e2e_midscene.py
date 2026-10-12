"""Real e2e: slash API -> MidsceneRuntime -> worker -> device, verified with uiautomator2.

Needs a running worker (MIDSCENE_WORKER_URL, default http://127.0.0.1:18790) and a booted
device at SLASH_ADB_SERIAL (default 127.0.0.1:15555). Usage: .venv/bin/python dev/e2e_midscene.py
"""

import json
import os
import sys
import tempfile
import time
from pathlib import Path

from fastapi.testclient import TestClient

from slash.api.app import create_app
from slash.core.config import (
    AgentConfig,
    DevicesConfig,
    ServerConfig,
    SlashConfig,
    StorageConfig,
    TakeoverConfig,
)
from slash.devices.u2 import U2Device, check_search_text
from slash.wiring import build_context

SERIAL = os.environ.get("SLASH_ADB_SERIAL", "127.0.0.1:15555")
GOAL = os.environ.get("E2E_GOAL", "open Settings and search Display")


class NoCerts:
    def fingerprint(self, apk):
        return ""


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="slash-e2e-"))
    cfg = SlashConfig(
        server=ServerConfig(bind="127.0.0.1:8787", public_base_url="http://127.0.0.1:8787", token="e2e", secret="e2e"),
        storage=StorageConfig(db_url=f"sqlite:///{tmp / 'slash.db'}", blob_dir=str(tmp / "blobs")),
        devices=DevicesConfig(backend="physical", data_root=str(tmp / "dev"), serials={"redroid": SERIAL},
                              boot_timeout_s=60),
        agent=AgentConfig(worker_url=os.environ.get("MIDSCENE_WORKER_URL", "http://127.0.0.1:18790"),
                          worker_url_explicit=True, worker_poll_s=1.0, max_steps=20),
        takeover=TakeoverConfig(record=False),
    )
    ctx = build_context(cfg, cert_verifier=NoCerts(), inline_tasks=True)
    client = TestClient(create_app(ctx, start_background=False))
    h = {"Authorization": "Bearer e2e"}
    dev = client.post("/api/v1/devices", headers=h, json={"name": "redroid"})
    assert dev.status_code == 200, dev.text
    t0 = time.time()
    task = client.post("/api/v1/tasks", headers=h, json={"device_id": dev.json()["id"], "goal": GOAL}, timeout=900).json()
    wall = time.time() - t0
    steps = client.get(f"/api/v1/tasks/{task['id']}/steps", headers=h).json()
    ok = check_search_text(U2Device.connect(SERIAL), "Display")
    out = {"status": task["status"], "error": task.get("error"), "result": task.get("result"), "steps": len(steps),
           "wall_s": round(wall, 1), "u2_checker_search_src_text_Display": ok}
    print("E2E " + json.dumps(out, ensure_ascii=False, default=str))
    return 0 if task["status"] == "SUCCEEDED" and ok else 1


if __name__ == "__main__":
    sys.exit(main())
