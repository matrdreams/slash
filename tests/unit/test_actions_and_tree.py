import base64
from pathlib import Path

import pytest
from pydantic import ValidationError

from slash.agent.actions import KEYCODES, Tap, TypeText, parse_action
from slash.agent.actuator import b64_text, input_broadcast
from slash.agent.detectors import need_human
from slash.agent.policy import sensitive_reason
from slash.agent.redact import should_redact
from slash.agent.tree import compress, parse_hierarchy
from slash.agent.watchers import match_watcher
from slash.core.models import TaskStatus, assert_transition
from slash.core.errors import InvalidTransition
from slash.llm.coords import to_pixels
from slash.llm.ui_tars import parse_ui_tars_text

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_action_schema_accepts_the_spec_examples():
    tap = parse_action({"type": "tap", "element_id": 12})
    assert isinstance(tap, Tap)
    assert tap.element_id == 12
    keyed = parse_action({"type": "key", "key": "back"})
    assert keyed.key == "BACK"
    typed = parse_action({"type": "type", "text": "你好", "submit": False})
    assert isinstance(typed, TypeText)
    done = parse_action({"type": "done", "success": True, "result": "三个价格"})
    assert done.success is True
    with pytest.raises(ValidationError):
        parse_action({"type": "tap"})
    with pytest.raises(ValidationError):
        parse_action({"type": "nope"})


def test_tree_compress_keeps_stable_ids_and_prefers_clickable():
    xml = (FIXTURES / "settings.xml").read_text(encoding="utf-8")
    nodes = parse_hierarchy(xml)
    assert [node.text for node in nodes] == ["设置", "搜索设置", "显示"]
    assert [node.element_id for node in nodes] == [1, 2, 3]
    kept, text = compress(nodes, limit=2)
    assert [node.element_id for node in kept] == [1, 2]
    assert '[2] android.widget.TextView "搜索设置"' in text
    assert "bounds=[40,200][680,280]" in text


def test_coords_and_ui_tars_parser():
    assert to_pixels(500, 250, "norm1000", 720, 1280) == (360, 320)
    assert to_pixels(0.5, 0.25, "norm1", 720, 1280) == (360, 320)
    assert to_pixels(10, 20, "pixel", 720, 1280) == (10, 20)
    action = parse_ui_tars_text("click(500, 250)")
    assert action is not None and action.x == 500 and action.y == 250
    assert parse_ui_tars_text('finished("ok")').result == "ok"


def test_chinese_input_is_base64_broadcast():
    encoded = b64_text("显示")
    assert base64.b64decode(encoded).decode() == "显示"
    command = input_broadcast("显示")
    assert "ADB_INPUT_B64" in command
    assert encoded in command
    assert KEYCODES["BACK"] == 4
    assert KEYCODES["ENTER"] == 66


def test_detectors_watchers_policy_and_redact():
    assert need_human("请完成短信验证后继续") == "短信验证"
    assert need_human("普通设置页") is None
    nodes = parse_hierarchy((FIXTURES / "agree.xml").read_text(encoding="utf-8"))
    assert match_watcher(nodes).text == "同意"
    pay = parse_hierarchy((FIXTURES / "pay.xml").read_text(encoding="utf-8"))
    reason = sensitive_reason(Tap(element_id=pay[0].element_id), pay)
    assert reason and "确认支付" in reason
    assert should_redact(tree_text="请输入密码", provider_region="cn") is True
    assert should_redact(tree_text="请输入密码", provider_region="local") is False


def test_state_machine_matches_the_spec():
    assert_transition(TaskStatus.PENDING, TaskStatus.PREPARING)
    assert_transition(TaskStatus.PREPARING, TaskStatus.RUNNING)
    assert_transition(TaskStatus.RUNNING, TaskStatus.NEED_HUMAN)
    assert_transition(TaskStatus.NEED_HUMAN, TaskStatus.RUNNING)
    assert_transition(TaskStatus.NEED_HUMAN, TaskStatus.FAILED)
    assert_transition(TaskStatus.RUNNING, TaskStatus.SUCCEEDED)
    assert_transition(TaskStatus.RUNNING, TaskStatus.CANCELLED)
    assert_transition(TaskStatus.PREPARING, TaskStatus.FAILED)
    with pytest.raises(InvalidTransition):
        assert_transition(TaskStatus.SUCCEEDED, TaskStatus.RUNNING)
    with pytest.raises(InvalidTransition):
        assert_transition(TaskStatus.PENDING, TaskStatus.RUNNING)
