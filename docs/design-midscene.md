# Design: Midscene + uiautomator2 (spike, 2026-10-13)

Status: feasibility spike done. **Blocked on model access** (no vision-model API key). Old agent loop is NOT deleted yet.

## 1. Findings

### Midscene Android (`@midscene/android` 1.15.2)
- Device control is its **own adb stack**: deps `appium-adb`, `@yume-chan/adb`, `@yume-chan/adb-scrcpy`, `yadb`. It does **not** use uiautomator2 and cannot be pointed at a u2 server. Custom actions are possible via `defineAction()` + `AndroidDevice({customActions})`, which is how u2-backed ops could be injected.
- Perception is **pure vision**: `AndroidDevice.getElementsNodeTree()` returns an empty tree. A `getUITree()` (`uiautomator dump --compressed`) exists for auxiliary use and is not sent to the planner as an a11y-tree mode.
- Screenshots: `adb.takeScreenshot` → `screencap` → yadb (scrcpy optional). Non-ASCII input goes via yadb (`imeStrategy`); ADBKeyBoard is recommended for a small keyboard.
- Models (docs: https://midscenejs.com/model-provider.html), all vision, OpenAI-compatible endpoints, `MIDSCENE_MODEL_{BASE_URL,API_KEY,NAME,FAMILY}` plus optional `MIDSCENE_PLANNING_*` / `MIDSCENE_INSIGHT_*`: Doubao Seed 2.x (`doubao-seed`), Qwen3.x / Qwen3-VL / Qwen2.5-VL, DeepSeek V4 Flash vision, Gemini 3.x, GPT-5.4+/GPT-6 (also via ChatGPT SIWC or `codex://app-server`), Kimi, Xiaomi MiMo, GLM-V, AutoGLM-phone, UI-TARS. **xAI/Grok is not a listed family.** It might work as a generic OpenAI-compatible endpoint, but nobody has tested it and it needs `XAI_API_KEY`.

### Spike measurements (Redroid A12 on TCG, 720x1280)
| op | current adb | uiautomator2 3.7.0 | Midscene adb |
|---|---|---|---|
| hierarchy dump | ~3.6 s | **0.32–0.41 s** (28 KB XML) | n/a (vision) |
| screenshot | ~2.5 s | 2.0–4.1 s | 2.5 s |
| connect | – | 4.5 s (first time, installs u2 server) | 1.1 s |
| Chinese input | ADBKeyBoard | `send_keys("显示")` 0.57 s | yadb |
- Midscene `connect`, `screenshotBase64`, `size`, and `launch('com.android.settings')` all worked against 127.0.0.1:15555.
- `aiAct('open Settings and search Display')` failed immediately: `Model configuration is incomplete: MIDSCENE_MODEL_NAME is required`. No end-to-end run was possible.
- Scripts: `dev/midscene-spike/`.

### Grok shim
A local OpenAI-compatible server that forwards to `grok -p --output-format json` is technically possible (~10–40 s per call, which is too slow for Midscene's many calls per step). It is **not built**. The Grok CLI is an interactive coding agent tied to a consumer subscription, and its terms do not clearly allow using it as a general model API backend. Calling the internal proxy with the `~/.grok/auth.json` token is off the table. This needs a user decision. The supported route is `XAI_API_KEY`.

## 2. Target architecture
```
slashd (Python, FastAPI)            midscene-worker (Node, long-lived)
 ├ device manager (redroid/adb)      ├ HTTP/JSON-RPC over localhost (or stdio)
 ├ API / web / takeover / store  ──► │  POST /tasks {device, instruction, context}
 ├ uiautomator2 DeviceOps            │  → AndroidAgent.aiAct / aiQuery / aiAssert
 │   dump(0.35s), checkers,          │  streams step events + report html path
 │   Chinese input, app mgmt         └ customActions → call back slashd for u2 ops
 └ task runner: pre/post checks via u2, delegates "agent step" to worker
```
- Python owns lifecycle, persistence, takeover (pause/abort a worker task), and verification (u2 hierarchy checks, which are cheap and deterministic).
- The worker owns planning, localization, and actions. Reports are stored as artifacts.
- Model config is injected into the worker env from slashd config.

## 3. To delete (after the worker runs end to end)
`slash/agent/loop.py`, `planners/`, `completion.py`, `actions.py`, `actuator.py`, `policy.py`, `prompts/`, and probably `observer.py`/`tree.py`/`detectors.py`/`watchers.py` (replaced by u2). Keep `redact.py` and `imageutil.py` if store/API still use them. Remove `slash/llm` backends that only the loop uses, along with their tests.

## 4. Migration steps
1. Add `slash/devices/u2.py` (DeviceOps on uiautomator2) and switch observation/checkers to it, with tests.
2. Add `worker/` (Node, TS): task API, event stream, cancel. Build a mock-model mode for CI.
3. Add a `slash/agent/midscene_client.py` and route tasks behind a feature flag `agent.engine=midscene|legacy`.
4. Run evals once a model key exists, then delete the legacy loop.

## 5. Model options and cost (pick one, needs a key)
- Qwen3.x plus / Qwen3-VL via DashScope: cheap, strong on Chinese UIs. **Recommended for a China-based user.**
- Doubao Seed 2.1 turbo (Volcano Ark): the fastest localizer per Midscene's evals.
- AutoGLM-phone-9B (Zhipu): mobile-specialized and cheap. Needs a separate Insight model.
- Gemini 3.5 flash / GPT-5.5+: good but costlier and have regional limits.
- Grok via `XAI_API_KEY`: not an official family. Needs a compatibility test.
- Rough cost: ~3–10 model calls per aiAct with one screenshot each. The ¥/$ per task is low cents for qwen/doubao flash-tier models (verify current pricing).

## 6. Risks
- TCG slowness: screenshots take 2–4 s and Midscene takes one or more per step.
- Two adb clients (Midscene's appium-adb + u2's adbutils) on one device. Both are fine with the shared adb server, but concurrent input may conflict, so serialize per device.
- Node runtime dependency, Midscene API churn (1.x is moving fast).
- Pure vision: it degrades on tiny text. Use `screenshotShrinkFactor` carefully.
- Model blocker / Grok ToS.
