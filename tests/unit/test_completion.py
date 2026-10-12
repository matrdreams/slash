"""Completion detection: signatures, loop detection, verifier, using recorded M1 dumps."""

import asyncio
import json
from pathlib import Path

from slash.agent.completion import (
    LoopState,
    loop_state,
    menu_open,
    parse_verdict,
    screen_signature,
    should_verify,
)
from slash.agent.tree import parse_hierarchy
from slash.core.models import DeviceCreate
from slash.store.ids import new_id
from slash.store.tables import TaskRow

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "completion"
WIFI = (FIX / "settings-wifi.xml").read_text()
CONTACT = (FIX / "contact.xml").read_text()


def test_recorded_fixtures_parse():
    assert parse_hierarchy(WIFI)
    assert "Slash Test" in CONTACT


def test_signature_ignores_clock_and_battery():
    a = screen_signature("[1] text 10:41 battery 80% Wi-Fi ON")
    b = screen_signature("[1] text 10:42 battery 79% Wi-Fi ON")
    assert a == b
    assert a != screen_signature("[1] text 10:42 battery 79% Wi-Fi OFF")


def test_loop_state_counts_trailing_repeats():
    tap = {"type": "tap", "x": 1, "y": 2}
    s = loop_state(["a", "b", "b", "b"], [tap, tap])
    assert s.repeated_screens == 2 and s.repeated_actions == 1 and s.looping
    assert not loop_state(["a", "b"], [tap, {"type": "key", "key": "BACK"}]).looping


def test_should_verify_reasons():
    calm = LoopState()
    assert should_verify(steps_used=0, max_steps=10, loop=LoopState(3, 3)) == ""
    assert should_verify(steps_used=3, max_steps=10, loop=calm) == ""
    assert should_verify(steps_used=3, max_steps=10, loop=LoopState(2, 1)) == "loop"
    assert should_verify(steps_used=3, max_steps=10, loop=LoopState(2, 0)) == ""
    assert should_verify(steps_used=8, max_steps=10, loop=calm) == "near_max_steps"
    assert should_verify(steps_used=4, max_steps=20, loop=calm, every=4) == "periodic"


def test_parse_verdict_variants():
    assert parse_verdict('{"achieved": true, "evidence": "Wi-Fi switch ON"}') == (True, "Wi-Fi switch ON")
    assert parse_verdict('```json\n{"achieved": "no", "evidence": "x"}\n```')[0] is False
    assert parse_verdict("yes, the contact is saved")[0] is True
    assert parse_verdict("no")[0] is False


def test_menu_open_heuristic():
    assert menu_open("node PopupWindow ListView")
    assert not menu_open(WIFI)


def _run(ctx, steps: int = 10):
    async def scenario():
        device = await ctx.manager.create(DeviceCreate(name="d1"), user_id=ctx.user_id)
        task = ctx.store.insert_task(
            TaskRow(id=new_id(), device_id=device.id, goal="toggle wifi", status="PENDING",
                    provider="fake", mode="tree", max_steps=steps, require_confirm=False)
        )
        return await ctx.runtime.run(task.id)

    return asyncio.run(scenario())


TAP = {"type": "tap", "x": 600, "y": 300}


def test_runtime_verifier_ends_loop_on_recorded_screen(world):
    verdict = {"achieved": True, "evidence": "Wi-Fi switch is ON"}
    ctx = world(actions=[TAP, TAP, verdict], confirm_sensitive=False)
    ctx.adb.hierarchy_xml = WIFI
    task = _run(ctx)
    assert task.status == "SUCCEEDED", task.error
    assert "verifier:loop" in json.loads(task.result_json)["result"]
    assert task.steps_used == 3


def test_runtime_verifier_no_then_model_done(world):
    verdict = {"achieved": False, "evidence": "switch still off"}
    done = {"type": "done", "success": True, "result": "ok"}
    ctx = world(actions=[TAP, TAP, verdict, done], confirm_sensitive=False)
    ctx.adb.hierarchy_xml = WIFI
    task = _run(ctx)
    assert task.status == "SUCCEEDED"
    assert json.loads(task.result_json)["result"] == "ok"


def test_runtime_near_max_steps_verifier(world):
    screens = [CONTACT.replace("Slash Test", f"Step {i}") for i in range(5)] + [CONTACT] * 5
    verdict = {"achieved": True, "evidence": "Slash Test saved"}
    ctx = world(actions=[TAP, {"type": "key", "key": "BACK"}, TAP, verdict], confirm_sensitive=False)
    ctx.adb.hierarchy_script = screens
    task = _run(ctx, steps=5)
    assert task.status == "SUCCEEDED", task.error
    assert "near_max_steps" in json.loads(task.result_json)["result"]


def test_grok_cli_vision_prompt_and_cost(tmp_path):
    from slash.llm.base import Message
    from slash.llm.grok_cli import GrokCliProvider, _cost_cny

    prov = GrokCliProvider.__new__(GrokCliProvider)
    prompt = GrokCliProvider._prompt(prov, [Message(role="user", content="g")], ["/tmp/x.png"])
    assert "/tmp/x.png" in prompt and "read_file" in prompt
    assert "Do not call tools" in GrokCliProvider._prompt(prov, [Message(role="user", content="g")], [])
    assert _cost_cny({"total_cost_usd": 0.01}) == 0.071


def test_tree_exposes_switch_checked_state():
    from slash.agent.tree import compress

    xml = (
        '<hierarchy><node class="android.widget.Switch" text="" checkable="true" checked="true" '
        'clickable="false" enabled="true" bounds="[600,600][700,700]" package="p" resource-id="android:id/switch_widget"/>'
        "</hierarchy>"
    )
    _, text = compress(parse_hierarchy(xml))
    assert "checked=true" in text and "Switch" in text


def test_invalid_action_is_recoverable(world):
    bad = {"type": "swipe", "foo": 1}
    done = {"type": "done", "success": True, "result": "ok"}
    ctx = world(actions=[bad, done], confirm_sensitive=False)
    ctx.adb.hierarchy_xml = WIFI
    task = _run(ctx)
    assert task.status == "SUCCEEDED", task.error
    steps = ctx.store.list_steps(task.id)
    assert "invalid action" in steps[0].error


def test_three_invalid_actions_fail(world):
    bad = {"type": "swipe", "foo": 1}
    ctx = world(actions=[bad, bad, bad, bad], confirm_sensitive=False)
    ctx.adb.hierarchy_xml = WIFI
    task = _run(ctx)
    assert task.status == "FAILED"
    assert "invalid actions in a row" in task.error
