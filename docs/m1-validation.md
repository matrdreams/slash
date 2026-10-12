# M1 validation (2026-10-12)

Device: Redroid 12 `redroid/redroid:12.0.0_64only-latest` in the TCG VM, adb `127.0.0.1:15555`, screen 720x1280. Provider: `grok_cli` (local `grok -p … --output-format json --always-approve`). Planner mode `tree`, `confirm_sensitive: false`. `grok --help` has no image-attachment flag; the provider writes a PNG and names the path. These runs did not send screenshots (tree mode).

`com.android.calculator2` is not in this image, so the calculator example was not run. Four other AOSP tasks were.

Agent `SUCCEEDED` means the model emitted `done` with `success: true` before the step cap. Observed outcome is what the final screenshot and uiautomator dump show.

| Task | Steps | Agent status | Observed |
|---|---|---|---|
| Settings: open Wi-Fi and toggle it | 10 | FAILED `max_steps exceeded` | Internet page is open. The Wi-Fi switch is on. The model tapped the switch coordinates and never emitted `done`. |
| Clock: create a 7:00 alarm (`com.android.deskclock`) | 10 | SUCCEEDED | Alarm list shows **7:00 AM**, label Tomorrow, switch on. |
| Contacts: create **Slash Test** | 12 | FAILED `max_steps exceeded` | Contact **Slash Test** is saved and open. The overflow menu was still up when the cap hit. |
| Settings: search **Display** | 5 | SUCCEEDED | Search box contains Display. Results include Display size, Display, Display over other apps. |

Agent success rate: **2/4 (50%)**. The contact goal is on screen, but that run is not counted as success because the task status is FAILED.

Screenshots:

- `docs/img/m1-task-settings-wifi.png`
- `docs/img/m1-task-deskclock.png`
- `docs/img/m1-task-contact.png`
- `docs/img/m1-task-settings-display.png`

Chinese input (separate from the agent loop): ADBKeyBoard `v2.4-dev` (`com.android.adbkeyboard/.AdbIME`) typed `你好世界` into the Settings search field with `ADB_INPUT_B64`. The dump's `android:id/search_src_text` is `你好世界`. Screenshot: `docs/img/m1-chinese-input.png`.

First agent attempts failed in one step because the model returned `{"action":"launch",…}` and the schema discriminator is `type`. `slash/llm/grok_cli.py` renames `action` to `type` before validation. The table above is the rerun after that fix.
