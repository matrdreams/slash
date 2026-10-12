# Architecture

slash is a single-host control plane.

- `host/` prepares binder, Docker, and adb.
- `deploy/compose` runs Redroid. The device manager writes `phones.override.yml` with loopback ADB ports.
- `slashd` (FastAPI) stores devices, tasks, and steps in SQLite.
- The agent loop observes with `uiautomator dump` and `screencap`, asks an OpenAI-compatible model for one JSON action, and executes it with adb. Chinese text uses ADBKeyBoard `ADB_INPUT_B64`.
- `NEED_HUMAN` pauses the loop and returns a signed takeover URL.

L0 tests use `FakeBackend`, `FakeAdb`, and `ScriptedProvider`. They do not need Docker.
