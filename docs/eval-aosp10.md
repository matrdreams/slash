# AOSP 10-task eval

Runner `eval/aosp_tasks.py`. Device Redroid 12 TCG VM `127.0.0.1:15555`, provider `grok_cli`, mode `tree`. Ground truth = programmatic checker (adb `settings`, `content query`, `cmd uimode`, `cmd media_session volume`, uiautomator search field), not the agent's `done`.

## Round 1 (2026-10-12, 22:58–23:30 CST)

Detached PID 1807420, log `/workspace/grok-logs/eval-aosp10.log`, raw `eval/results/summary.jsonl`, screenshots `eval/results/*.png`.

| Task | Agent | Checker | Evidence | Steps | Time | Cost CNY |
|---|---|---|---|---|---|---|
| settings-wifi | FAILED max_steps | PASS | wifi_on 1->0 | 10 | 245s | 0 (pre cost patch) |
| deskclock-alarm 8:30 | SUCCEEDED | PASS | alarm list shows 8:30 | 4 | 54s | 0.32 |
| contact-name Eval One | FAILED max_steps | FAIL | not in contacts provider | 12 | 397s | 0.81 |
| settings-search-display | SUCCEEDED (verifier) | PASS* | screenshot: field = Display | 7 | 111s | 0.39 |
| dark-theme | SUCCEEDED | PASS | Night mode: yes | 8 | 126s | 0.46 |
| brightness-min | SUCCEEDED (verifier) | PASS | screen_brightness=1 | 10 | 333s | 0.69 |
| contact-phone Alice Wang | FAILED (bad swipe JSON) | FAIL | no rows | 5 | 223s | 0.32 |
| airplane-on | SUCCEEDED | PASS | airplane_mode_on=1 | 4 | 51s | 0.21 |
| ring-volume-max | FAILED (bad swipe JSON) | PASS | ring volume 7/7 | 4 | 96s | 0.25 |
| settings-search-zh 显示 | FAILED max_steps | FAIL† | screenshot: empty Search settings | 8 | 217s | 0.62 |

**Round 1:** checker **7/10**, agent **4/10** (SUCCEEDED count). Approx cost ~4.07 CNY (wifi unmetered).

\* Live checker reported `search_src_text=''` because of a regex bug (`text` attribute precedes `resource-id` in the node). Fixed in-tree after the run started (`search_text` now scans each `<node>` and reads `text=` when `resource-id="android:id/search_src_text"` is present). Manual re-check of `eval/results/settings-search-display.png` shows the search field = **Display** with results → PASS.

† Same live-checker bug (`search_src_text=''`). Manual re-check of `eval/results/settings-search-zh.png` shows Settings home with empty placeholder "Search settings"; **显示** is not in the field → corrected verdict FAIL (true agent failure, not a false negative).

## Round 2 (2026-10-12 23:43 – 2026-10-13 00:19 CST)

Detached PID 1836423, log `/workspace/grok-logs/eval-aosp10-r2.log`, raw `eval/results-r2/summary.jsonl`, screenshots `eval/results-r2/*.png`. Post agent fixes (tolerant action normalizer, labeled EditText, IME-before-focus typing, recoverable invalid actions, search checker fix).

| Task | Agent R2 | Checker R2 | Evidence R2 | Steps R2 | Cost R2 | Agent R1 | Checker R1 | Steps R1 | Cost R1 |
|---|---|---|---|---|---|---|---|---|---|
| settings-wifi | FAILED max_steps | PASS | wifi_on 0->1 | 10 | 0.82 | FAILED | PASS | 10 | 0 |
| deskclock-alarm 8:30 | FAILED max_steps | PASS | alarm list shows 8:30 | 12 | 1.04 | SUCCEEDED | PASS | 4 | 0.32 |
| contact-name Eval One | SUCCEEDED | PASS | contacts data has Eval One | 9 | 0.66 | FAILED | FAIL | 12 | 0.81 |
| settings-search-display | SUCCEEDED | PASS | search_src_text='Display' | 5 | 0.25 | SUCCEEDED | PASS* | 7 | 0.39 |
| dark-theme | SUCCEEDED | PASS | Night mode: yes | 6 | 0.32 | SUCCEEDED | PASS | 8 | 0.46 |
| brightness-min | FAILED max_steps | PASS | screen_brightness=1 | 10 | 0.61 | SUCCEEDED | PASS | 10 | 0.69 |
| contact-phone Alice Wang | SUCCEEDED | FAIL | missing name or phone | 8 | 0.51 | FAILED | FAIL | 5 | 0.32 |
| airplane-on | SUCCEEDED | PASS | airplane_mode_on=1 | 4 | 0.18 | SUCCEEDED | PASS | 4 | 0.21 |
| ring-volume-max | FAILED max_steps | FAIL | ring volume 1/7 | 10 | 0.80 | FAILED | PASS | 4 | 0.25 |
| settings-search-zh 显示 | FAILED max_steps | PASS | search_src_text='显示' | 8 | 0.67 | FAILED | FAIL† | 8 | 0.62 |

**Round 2:** checker **8/10**, agent **5/10**. **Total cost 5.86 CNY**.

### Round 2 notes on the last four tasks

- **contact-phone:** Agent reported SUCCEEDED (detail page showed Alice Wang + 13800138000), but checker failed (`missing name or phone`) — contacts provider still lacked a matching row (likely unsaved / wrong account).
- **airplane-on:** Agent SUCCEEDED, checker PASS (`airplane_mode_on=1`), 4 steps, 0.18 CNY.
- **ring-volume-max:** Agent FAILED max_steps; checker FAIL — ring volume stuck at **1/7** (R1 had been 7/7 despite agent fail).
- **settings-search-zh:** Agent FAILED max_steps (no `done`), but checker PASS with `search_src_text='显示'`. Manual Read of `/workspace/slash/eval/results-r2/settings-search-zh.png` confirms the search field shows **显示** (cursor after the second character; results area shows "No results" under dark theme). Absolute path: `/workspace/slash/eval/results-r2/settings-search-zh.png`.

### Round 1 → Round 2 deltas (checker)

| Task | R1 → R2 |
|---|---|
| contact-name | FAIL → PASS |
| settings-search-zh | FAIL → PASS |
| ring-volume-max | PASS → FAIL |
| contact-phone | FAIL → FAIL (agent now SUCCEEDED but provider still empty) |
| others | unchanged PASS |

## Round 1 notes (historical)

- **Wi-Fi:** verifier at loop/near_max answered "no switch state" because the compressed tree dropped the Switch node. `slash/agent/tree.py` now emits `checked=true/false` for checkable nodes (committed mid-run; tasks after dark-theme use it). Wi-Fi was not rerun in R1.
- **Contacts:** both contact tasks fail genuinely in R1 (wrong taps in the editor; one step produced `{"type":"swipe","x":..}` and failed schema validation). Same swipe schema failure also aborted ring-volume-max mid-run (volume was already at max from prior gestures). Follow-up landed before R2: coerce swipe x/y keys, field-level hints for the contact editor.
- **Vision:** `grok -p … --tools read_file` with a PNG path works. A probe read `docs/img/m1-task-contact.png` and returned "Slash Test" (2 turns, ~13k tokens, $0.0054). The provider prompt now tells the model to read_file the screenshot path when images are attached. No end-to-end `tree+vision` task was run.
