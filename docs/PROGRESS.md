# Slash progress (2026-10-12)

Tests: 47 passed, 5 skipped (Redroid integration, needs binder host); ruff: clean.

| Milestone | Status | Evidence / gaps |
|---|---|---|
| M0 single host | Partial | host/install.sh, check.sh, compose, QEMU script exist; never booted Redroid (no binder on box) |
| M1 agent loop | Partial (code done) | agent/llm/CLI + replay tests pass; real AOSP task success rate & Chinese input unverified |
| M2 device mgmt + API | Partial (code done) | manager, REST, SQLite, snapshots, idle reaper; live 3-instance/snapshot tests pending |
| M3 takeover + Web UI | Partial | ws-scrcpy pin/Dockerfile, signed takeover, stream.py, recorder, web/ panel, caddy; no end-to-end run |
| M4 compat matrix | Scaffold | tests/compat/apps.yaml, harness, popups rules, physical backend; no app results |
| M5 production | Scaffold | k8s StatefulSet backend, proxy, backup, security/compliance docs; not validated |
| M6 release | Started | CI workflow, release-checklist, DISCLAIMER; no docs site/PyPI/multiarch images |
| M7+ | Not started (physical-device backend stub only) | |
