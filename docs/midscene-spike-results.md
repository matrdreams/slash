# Midscene + Doubao Seed (Volcengine Ark) spike results — 2026-10-13

Model: `doubao-seed-2-1-turbo-260628` (Ark, cn-beijing). Config (`dev/midscene-spike/env.sh`):
MIDSCENE_MODEL_BASE_URL=https://ark.cn-beijing.volces.com/api/v3, MIDSCENE_MODEL_FAMILY=doubao-seed,
MIDSCENE_MODEL_API_KEY taken from env `ARK_API_KEY` (never stored). @midscene/android 1.15.2, Redroid Android 12 (TCG, ~2.5s/screenshot).

Model availability probed via `/api/v3/models` + tiny chat call (text + 32x32 image):
- OK: doubao-seed-2-1-turbo-260628 (image min side >= 14px).
- ModelNotOpen (needs activation in Ark console 开通管理): seed-2-1-pro-260628/260915, seed-2-1-lite-260915, seed-2-0-lite/mini-260428, seed-evolving, seed-2-0-code-preview.
- Shut down: all seed-1-6*, seed-1-8, 1.5 vision / ui-tars.

| task | prompt | success (checker) | wall s | model calls | in tok | out tok | est. cost ¥ |
|---|---|---|---|---|---|---|---|
| search-display | open Settings and search Display | ✅ search_src_text='Display' | 81.4 | 5 | 56,772 | 595 | 0.18 |
| airplane-on | turn on airplane mode | ✅ airplane_mode_on=1 | 74.1 | 4 | 46,363 | 580 | 0.15 |
| alarm-730 | create a 7:30 alarm in Clock | ✅ alarm list shows 7:30 | 223.2 | 14 | 179,129 | 2,273 | 0.57 |
| search-zh | 在设置里搜索“显示” | ✅ search_src_text='显示' | 91.5 | 6 | 68,962 | 598 | 0.22 |

Total 4/4, 470 s, 29 calls, 351k in / 4k out tokens ≈ ¥1.11 (list price ¥3/M in, ¥15/M out, no cache discount counted).
Checkers reuse `eval/aosp_tasks.py`. Raw: `dev/midscene-spike/results/results.jsonl`, screenshots alongside.
Midscene HTML reports (not committed, large): /workspace/midscene-spike/midscene_run/report/ms-<task>.html
Run: `cd /workspace/midscene-spike && source env.sh && /workspace/slash/.venv/bin/python run_all.py [task...]`
