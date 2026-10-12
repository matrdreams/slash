# AOSP 10-task eval (2026-10-12, run started 22:58 CST)

Runner `eval/aosp_tasks.py` (detached, PID 1807420, log `/workspace/grok-logs/eval-aosp10.log`, raw `eval/results/summary.jsonl`, screenshots `eval/results/*.png`). Device Redroid 12 TCG VM `127.0.0.1:15555`, provider `grok_cli`, mode `tree`. Ground truth = programmatic checker (adb `settings`, `content query`, `cmd uimode`, `cmd media_session volume`, uiautomator search field), not the agent's `done`.

Results at 23:25 CST (8/10 finished; ring-volume-max and settings-search-zh still running):

| Task | Agent | Checker | Evidence | Steps | Time | Cost CNY |
|---|---|---|---|---|---|---|
| settings-wifi | FAILED max_steps | PASS | wifi_on 1->0 | 10 | 245s | 0 (pre cost patch) |
| deskclock-alarm 8:30 | SUCCEEDED | PASS | alarm list shows 8:30 | 4 | 54s | 0.32 |
| contact-name Eval One | FAILED max_steps | FAIL | not in contacts provider | 12 | 397s | 0.81 |
| settings-search-display | SUCCEEDED (verifier) | PASS* | screenshot: field = Display | 7 | 111s | 0.39 |
| dark-theme | SUCCEEDED | PASS | Night mode: yes | 8 | 126s | 0.46 |
| brightness-min | SUCCEEDED | PASS | screen_brightness=1 | 10 | 333s | 0.69 |
| contact-phone Alice Wang | FAILED (bad swipe JSON) | FAIL | no rows | 5 | 223s | 0.32 |
| airplane-on | SUCCEEDED | PASS | airplane_mode_on=1 | 4 | 51s | 0.21 |

\* The live checker reported `search_src_text=''` because of a regex bug (text attribute precedes resource-id). Fixed after the run started; the saved screenshot shows Display in the field. The running process still uses the old regex, so settings-search-zh needs the same manual check.

Wi-Fi: the verifier ran at loop and near_max but answered "no switch state" because the compressed tree dropped the Switch node. `slash/agent/tree.py` now emits `checked=true/false` for checkable nodes (committed mid-run; tasks after dark-theme use it). Wi-Fi was not rerun.

Contacts: both contact tasks fail genuinely (wrong taps in the editor; one step produced `{"type":"swipe","x":..}` and failed schema validation). Follow-up: coerce swipe x/y keys, field-level hints for the contact editor.

Vision: `grok -p … --tools read_file` with a PNG path works. A probe read `docs/img/m1-task-contact.png` and returned "Slash Test" (2 turns, ~13k tokens, $0.0054). The provider prompt now tells the model to read_file the screenshot path when images are attached. No end-to-end `tree+vision` task was run.
