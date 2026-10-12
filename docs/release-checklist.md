# Release checklist

Use this before tagging a v1 build. CI (`.github/workflows/ci.yml`) already runs ruff, pytest, shellcheck, and `docker compose config`.

- [ ] `README.md` and `README.zh-CN.md` still match the commands a new user types, including the ws-scrcpy profile and the web panel.
- [ ] `DISCLAIMER.md` is linked from the README. The text still says slash only drives the operator's own accounts.
- [ ] `third_party/ws-scrcpy/PIN`, the Dockerfile `WS_SCRCPY_REF`, and both compose files name the same commit. `node_modules` is not committed.
- [ ] `docs/security.md` checklist is still accurate for the bind addresses and the takeover token.
- [ ] `docs/compat-matrix.md` was regenerated from `tests/compat/apps.yaml` (`slash compat run --write-matrix docs/compat-matrix.md`) and any real results are labeled as measurements.
- [ ] Offline `pytest` is green. `tests/integration` stays skipped unless `SLASH_ADB_SERIAL` is set.
- [ ] Example tasks under `examples/tasks/` still parse as YAML.
- [ ] No image publish, tag push, or secret is part of this checklist's automation. Publishing a multi-arch image is a separate, explicit step.
