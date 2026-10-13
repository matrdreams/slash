# Midscene migration, part 1 (2026-10-13)

The custom agent loop is gone. Tasks now run through **`worker/`** (Node/TS, `@midscene/android` 1.15.2, `@midscene/core` 1.15.2 pinned).

## Flow
`POST /api/v1/tasks` → `MidsceneRuntime` (`slash/agent/runtime.py`) → `MidsceneClient` (`slash/agent/midscene_client.py`, httpx) → worker `POST /tasks` → `AndroidAgent.aiAct(goal)`.
The runtime polls the worker's `GET /tasks/:id/events?after=N` stream. Each worker event maps onto the existing model:
| worker | slash |
|---|---|
| `status running` | task `RUNNING` |
| `step` (aiAct progress `plan_planned` / `action_done` / `action_failed` / `plan_failed`) | `StepRow` + `step` event (`action_json.engine = "midscene"`) |
| `done succeeded` | `SUCCEEDED`; `result_json.report_path` + `report` event |
| `done need_human` (custom action `RequestHuman`) | takeover link issued → `NEED_HUMAN` |
| `done failed` / `cancelled` | `FAILED` |

Worker API: `GET /health`, `POST /tasks {task_id, device_serial, goal, max_steps?, context?}`, `GET /tasks/:id`, `GET /tasks/:id/events?after=N[&stream=1 for SSE]`, `POST /tasks/:id/cancel`. Tasks for one device are serialized in a queue.
Env: `MIDSCENE_MODEL_{BASE_URL,API_KEY,NAME,FAMILY}`, `MIDSCENE_WORKER_{HOST,PORT(18790),REPORT_DIR,MOCK}`, `MIDSCENE_IME_STRATEGY` (default `yadb-for-non-ascii`; Chinese text goes through yadb).
Config: `agent.worker_url` (default `http://127.0.0.1:18790`; `fake` gives the in-process scripted `FakeMidsceneClient`. The fake device backend uses it automatically unless `agent.worker_url_explicit: true`).

## Takeover
- Model-initiated: `RequestHuman{reason}` is a custom action registered through `AndroidDevice({customActions})`. The aiAct context tells the model to use it for login, captcha, payment, and other sensitive steps. The worker ends the task as `need_human`. slash issues a takeover link.
- User-initiated: `POST /api/v1/tasks/{id}:takeover` cancels the worker task (via AbortSignal). The task goes to `NEED_HUMAN` with a link.
- Resume (`:reply` or a takeover release) submits a **new** worker task `<task>-<n>` with the same goal and the human's note as context. Midscene has no in-place pause, so this is a re-plan from the current screen.

## Known gaps
- **Sensitive-action confirmation** is prompt-level only (the model is asked to call `RequestHuman`). The old deterministic `policy.py` keyword gate is not enforced. A future gate could wrap the Tap/Input actions in the worker and check the target text before acting.
- Cancellation is cooperative. Midscene checks the AbortSignal between steps, so an in-flight model call still finishes.
- Per-step screenshots are no longer in the blob store (`/steps/{idx}/screenshot` returns 404). They are in the Midscene HTML report (`report_path`).
- `mode` (`tree` / `vision-only`), `provider`, and `max_cost_cny` on tasks are ignored. Midscene is vision-only and reads the model from the worker env. Cost/token accounting is not wired back (`llm_usage_json` is empty).
- `max_steps` maps to Midscene `replanningCycleLimit` (approximate).
- Watchers (popup auto-dismiss) are removed. Midscene handles popups visually.
- `slash/llm/*` is deleted, and `llm:` config is kept only for compatibility and the fake script.
- uiautomator2 (`slash/devices/u2.py`) is used for checkers and verification. Midscene still drives input through its own adb stack.

## E2E result (2026-10-13 01:29 CST)
`dev/e2e_midscene.py`: slash API → MidsceneRuntime → worker (Doubao `doubao-seed-2-1-turbo-260628`, Ark) → Redroid A12 (TCG, 127.0.0.1:15555).
Goal "open Settings and search Display" → **SUCCEEDED**, 9 step events, 77.1 s wall. The u2 checker found `search_src_text == "Display"`.
Note: Midscene writes reports to `$MIDSCENE_RUN_DIR/report/` (the worker sets the run dir to the parent of `MIDSCENE_WORKER_REPORT_DIR`). The returned `report_path` is authoritative.

## Part 2: guard + cost (2026-10-13)
- **Sensitive-action guard** (`worker/src/guard.ts`): `GuardedDevice.actionSpace()` wraps Tap/DoubleClick/LongPress/Input/KeyboardPress. Before each call it scans every string in the action params (the Midscene locate prompt, i.e. the model's element description, plus input `value`) for keywords. The list is ported from the old `policy.py`, then extended with 支付/删除/确认购买/提交订单/pay now/... and `MIDSCENE_SENSITIVE_KEYWORDS` (comma-separated). On a match it throws `SensitiveActionBlocked`, so the task ends as `need_human` and slash issues a takeover link. A `guard` event is recorded. Per-task allow list: `allow_sensitive: [...]` in POST /tasks. Limitation: the match is against the model's description of the target, not the on-screen text.
- **Usage/cost**: after every aiAct progress event the worker walks `agent.dump` for model `usage` objects and emits cumulative `usage` events: calls, prompt/completion/total tokens, `cost_cny` at `MIDSCENE_PRICE_IN_PER_M`=3 and `MIDSCENE_PRICE_OUT_PER_M`=15, which is Doubao turbo list price. slash sets `task.cost_cny` and stores per-step deltas in `step.llm_usage_json`. `max_cost_cny` (task, else `llm.max_cost_cny`) is sent as the remaining budget. When the budget is exceeded the worker aborts the task, which ends `failed` with `budget exceeded: ...`.
