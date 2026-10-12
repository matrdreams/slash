# Architecture

slash is a single-host control plane.

- `host/` prepares binder, Docker, and adb.
- `deploy/compose` runs Redroid. The device manager writes `phones.override.yml` with loopback ADB ports.
- `slashd` (FastAPI) stores devices, tasks, and steps in SQLite.
- The agent loop observes with `uiautomator dump` and `screencap`, asks an OpenAI-compatible model for one JSON action, and executes it with adb. Chinese text uses ADBKeyBoard `ADB_INPUT_B64`.
- `NEED_HUMAN` pauses the loop and returns a signed takeover URL. `POST /api/v1/takeover/{id}:release` stops the `screenrecord` segments and resumes the loop.
- `web/` is a static task panel served by slashd at `/`. The takeover iframe loads `/takeover/<token>/`, which slashd or Caddy proxies to ws-scrcpy after the token is consumed.
- `third_party/ws-scrcpy` is a pinned fetch plus a Dockerfile. Compose publishes it on `127.0.0.1:8000` under the `takeover` profile.
- `deploy/k8s` is a privileged StatefulSet, a PVC, ClusterIP Services, and a NetworkPolicy. `deploy/proxy` is the per-network egress redirect. `deploy/backup/backup.sh` encrypts a stopped device's data directory.
- `devices.backend: physical` uses an already-connected adb serial (USB phone or an existing forward) instead of starting a container.

L0 tests use `FakeBackend`, `FakeAdb`, and `ScriptedProvider`. They do not need Docker. `tests/integration` runs only when `SLASH_ADB_SERIAL` is set.
