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
