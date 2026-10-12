"""L0 replay: a scripted model and a fake device drive the real step loop."""

import base64
from pathlib import Path

from slash.core.models import DeviceCreate, TaskStatus
from slash.store.ids import new_id
from slash.store.tables import TaskRow

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _run(ctx, goal: str, *, max_steps: int = 8):
    import asyncio

    device = asyncio.run(ctx.manager.create(DeviceCreate(name="u1"), user_id=ctx.user_id))

    async def go():
        task = ctx.store.insert_task(
            TaskRow(
                id=new_id(),
                device_id=device.id,
                goal=goal,
                mode="tree",
                provider="fake",
                status=TaskStatus.PENDING.value,
                max_steps=max_steps,
                require_confirm=True,
            )
        )
        return await ctx.runtime.run(task.id)

    return asyncio.run(go())


def test_replay_records_screenshot_tree_and_action(world):
    settings = (FIXTURES / "settings.xml").read_text(encoding="utf-8")
    ctx = world(
        actions=[
            {"type": "tap", "x": 360, "y": 240},
            {"type": "type", "text": "显示", "submit": True},
            {"type": "done", "success": True, "result": "已打开显示设置"},
        ]
    )
    ctx.adb.hierarchy_xml = settings
    finished = _run(ctx, "打开设置并搜索显示")
    assert finished.status == TaskStatus.SUCCEEDED.value
    assert finished.steps_used == 3
    steps = ctx.store.list_steps(finished.id)
    assert [step.idx for step in steps] == [0, 1, 2]
    for step in steps:
        assert step.observation_ref
        assert step.screenshot_ref
        assert Path(step.screenshot_ref).read_bytes().startswith(b"\x89PNG")
        tree = Path(step.observation_ref).read_text(encoding="utf-8")
        assert "设置" in tree
    actions = [step.action_json for step in steps]
    assert '"tap"' in actions[0]
    assert "显示" in actions[1]
    encoded = base64.b64encode("显示".encode()).decode()
    joined = "\n".join(ctx.adb.shell_commands())
    assert "ADB_INPUT_B64" in joined
    assert encoded in joined
    assert "ime set com.android.adbkeyboard/.AdbIME" in joined
    events = [event.event for event in ctx.store.list_events(finished.id)]
    assert "step" in events
    assert "done" in events


def test_captcha_pauses_for_a_person_without_calling_the_model(world):
    ctx = world(actions=[{"type": "done", "success": True, "result": "should-not-run"}])
    ctx.adb.hierarchy_xml = (FIXTURES / "captcha.xml").read_text(encoding="utf-8")
    finished = _run(ctx, "登录")
    assert finished.status == TaskStatus.NEED_HUMAN.value
    assert finished.takeover_url
    assert "/takeover/" in finished.takeover_url
    assert ctx.provider.calls == []
    assert ctx.store.list_steps(finished.id)


def test_reply_resumes_after_ask_human(world):
    ctx = world(
        actions=[
            {"type": "ask_human", "reason": "需要扫码登录"},
            {"type": "done", "success": True, "result": "登录完成"},
        ]
    )
    first = _run(ctx, "打开应用")
    assert first.status == TaskStatus.NEED_HUMAN.value

    import asyncio

    resumed = asyncio.run(ctx.runtime.reply(first.id, "我已经扫好了"))
    assert resumed.status == TaskStatus.SUCCEEDED.value
    assert resumed.steps_used == 2
    sent = ctx.provider.calls[-1]["messages"][-1]["content"]
    assert "我已经扫好了" in sent


def test_watcher_dismisses_dialog_before_the_planner(world):
    ctx = world(actions=[{"type": "done", "success": True, "result": "继续"}])
    ctx.adb.hierarchy_script = [
        (FIXTURES / "agree.xml").read_text(encoding="utf-8"),
        (FIXTURES / "settings.xml").read_text(encoding="utf-8"),
    ]
    finished = _run(ctx, "打开设置")
    assert finished.status == TaskStatus.SUCCEEDED.value
    steps = ctx.store.list_steps(finished.id)
    assert '"tap"' in steps[0].action_json
    assert "input tap" in ctx.adb.shell_commands()[0] or any(
        command.startswith("input tap") for command in ctx.adb.shell_commands()
    )
    assert len(ctx.provider.calls) == 1


def test_sensitive_tap_becomes_need_human(world):
    pay = (FIXTURES / "pay.xml").read_text(encoding="utf-8")
    ctx = world(actions=[{"type": "tap", "element_id": 1}, {"type": "done", "success": True, "result": "no"}])
    ctx.adb.hierarchy_xml = pay
    finished = _run(ctx, "买东西")
    assert finished.status == TaskStatus.NEED_HUMAN.value
    assert "确认支付" in (finished.takeover_url and ctx.store.list_steps(finished.id)[-1].action_json)
    assert not any(command.startswith("input tap") for command in ctx.adb.shell_commands())
