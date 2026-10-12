# Slash progress (2026-10-12)

Tests: 49 passed, 5 skipped (integration stays skipped unless `SLASH_ADB_SERIAL` is set). ruff clean on the grok_cli files.

| Milestone | Status | Evidence / gaps |
|---|---|---|
| M0 single host | Dev VM done | QEMU hostfwd is `127.0.0.1:22022` and `127.0.0.1:15555`. Guest ADB listens on `127.0.0.1:5555` only (`dev/qemu/adb-localhost.sh`; NIC tcp/5555 is DNATed there so hostfwd still works). `binder_linux` is in `/etc/modules-load.d/redroid.conf` and `/etc/modprobe.d/redroid.conf` on the VM (not rebooted). `make-amd64-vm.sh` cloud-init and `host/install.sh` write the same autoload files. README quickstart matches this path. |
| M1 agent loop | Partial live | ADBKeyBoard typed 你好世界 (`docs/img/m1-chinese-input.png`). `grok_cli` provider. 4 AOSP tasks, agent SUCCEEDED 2/4 (`docs/m1-validation.md`). Calculator is not in the 64only image. |
| M2 device mgmt + API | Partial (code done) | manager, REST, SQLite, snapshots, idle reaper; live 3-instance/snapshot tests pending |
| M3 takeover + Web UI | Partial | ws-scrcpy pin/Dockerfile, signed takeover, stream.py, recorder, web/ panel, caddy; no end-to-end run |
| M4 compat matrix | Scaffold | tests/compat/apps.yaml, harness, popups rules, physical backend; no app results |
| M5 production | Scaffold | k8s StatefulSet backend, proxy, backup, security/compliance docs; not validated |
| M6 release | Started | CI workflow, release-checklist, DISCLAIMER; no docs site/PyPI/multiarch images |
| M7+ | Not started (physical-device backend stub only) | |

## Detached jobs
- M0/M1 check on the TCG VM finished in this session. See `docs/m1-validation.md` and `docs/dev-vm.md`.
