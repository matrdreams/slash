# AOSP 10-task eval (2026-10-12, run 22:58–23:30 CST)

Runner `eval/aosp_tasks.py` (detached PID 1807420, log `/workspace/grok-logs/eval-aosp10.log`, raw `eval/results/summary.jsonl`, screenshots `eval/results/*.png`). Device Redroid 12 TCG VM `127.0.0.1:15555`, provider `grok_cli`, mode `tree`. Ground truth = programmatic checker (adb `settings`, `content query`, `cmd uimode`, `cmd media_session volume`, uiautomator search field), not the agent's `done`.

## Final results (10/10)

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

**Overall checker success rate: 7/10.**

\* Live checker reported `search_src_text=''` because of a regex bug (`text` attribute precedes `resource-id` in the node). Fixed in-tree after the run started (`search_text` now scans each `<node>` and reads `text=` when `resource-id="android:id/search_src_text"` is present). Manual re-check of `eval/results/settings-search-display.png` shows the search field = **Display** with results → PASS.

† Same live-checker bug (`search_src_text=''`). Manual re-check of `eval/results/settings-search-zh.png` shows Settings home with empty placeholder "Search settings"; **显示** is not in the field → corrected verdict FAIL (true agent failure, not a false negative).

## Notes

- **Wi-Fi:** verifier at loop/near_max answered "no switch state" because the compressed tree dropped the Switch node. `slash/agent/tree.py` now emits `checked=true/false` for checkable nodes (committed mid-run; tasks after dark-theme use it). Wi-Fi was not rerun.
- **Contacts:** both contact tasks fail genuinely (wrong taps in the editor; one step produced `{"type":"swipe","x":..}` and failed schema validation). Same swipe schema failure also aborted ring-volume-max mid-run (volume was already at max from prior gestures). Follow-up: coerce swipe x/y keys, field-level hints for the contact editor.
- **Vision:** `grok -p … --tools read_file` with a PNG path works. A probe read `docs/img/m1-task-contact.png` and returned "Slash Test" (2 turns, ~13k tokens, $0.0054). The provider prompt now tells the model to read_file the screenshot path when images are attached. No end-to-end `tree+vision` task was run.
