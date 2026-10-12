import asyncio

import pytest

from slash.agent.actions import Swipe, Tap, TypeText, parse_action
from slash.agent.actuator import Actuator
from slash.agent.tree import compress, parse_hierarchy


@pytest.mark.parametrize(
    "payload",
    [
        {"type": "swipe", "x1": 10, "y1": 20, "x2": 30, "y2": 40},
        {"type": "swipe", "start": [10, 20], "end": [30, 40]},
        {"action": "scroll", "from": {"x": 10, "y": 20}, "to": {"x": 30, "y": 40}},
        {"type": "swipe", "start_x": 10, "start_y": 20, "end_x": 30, "end_y": 40},
        {"type": "swipe", "x": 10, "y": 20, "x2": 30, "y2": 40},
        {"type": "drag", "x1": "10", "y1": 20.2, "x2": 30, "y2": 40, "extra": 1},
    ],
)
def test_swipe_aliases(payload):
    action = parse_action(payload)
    assert isinstance(action, Swipe)
    assert (action.x1, action.y1, action.x2, action.y2) == (10, 20, 30, 40)


def test_swipe_direction_distance():
    action = parse_action({"type": "swipe", "x": 500, "y": 1500, "direction": "up", "distance": 700})
    assert (action.x1, action.y1, action.x2, action.y2) == (500, 1500, 500, 800)
    right = parse_action({"type": "swipe", "x": 100, "y": 300, "direction": "right", "distance": 400})
    assert (right.x2, right.y2) == (500, 300)


def test_other_aliases():
    assert parse_action({"action": "click", "id": "5"}) == Tap(element_id=5)
    assert parse_action({"type": "tap", "point": [3, 4]}) == Tap(x=3, y=4)
    typed = parse_action({"type": "set_text", "element_id": 2, "value": "显示"})
    assert isinstance(typed, TypeText) and typed.text == "显示"
    assert parse_action({"type": "back"}).key == "BACK"
    assert parse_action({"type": "key", "keycode": "KEYCODE_HOME"}).key == "HOME"
    assert parse_action({"type": "open_app", "app": "com.android.settings"}).package == "com.android.settings"
    done = parse_action({"type": "finish", "success": "true", "message": "ok"})
    assert done.success is True and done.result == "ok"
    with pytest.raises(Exception):
        parse_action({"type": "swipe"})


XML = """<?xml version='1.0' encoding='UTF-8' ?><hierarchy rotation="0">
<node class="android.widget.FrameLayout" bounds="[0,0][720,1280]" enabled="true">
<node class="android.widget.TextView" text="Name" bounds="[20,100][200,140]" enabled="true"/>
<node class="android.widget.EditText" text="" hint="First name" resource-id="com.android.contacts:id/given" bounds="[20,150][700,220]" clickable="true" enabled="true"/>
<node class="android.widget.TextView" text="Phone" bounds="[20,300][200,340]" enabled="true"/>
<node class="android.widget.EditText" text="" resource-id="com.android.contacts:id/editor" bounds="[20,350][700,420]" focusable="true" focused="true" enabled="true"/>
</node></hierarchy>"""


def test_edittext_labels():
    nodes = parse_hierarchy(XML)
    _, text = compress(nodes)
    assert 'label="First name"' in text
    assert 'label="Phone"' in text and "focused" in text
    assert text.count("editable") == 2


class _Adb:
    def __init__(self):
        self.calls = []

    async def shell(self, serial, cmd):
        self.calls.append(cmd)
        return ""


def test_type_sets_ime_before_tap_and_uses_broadcast_for_chinese():
    adb = _Adb()

    async def nosleep(_):
        return None

    nodes = parse_hierarchy(XML)
    asyncio.run(Actuator(adb, sleeper=nosleep).execute("s", TypeText(text="显示", element_id=2), nodes, width=720, height=1280))
    ime = next(i for i, c in enumerate(adb.calls) if c.startswith("ime set"))
    tap = next(i for i, c in enumerate(adb.calls) if c.startswith("input tap"))
    assert ime < tap
    assert adb.calls[-1].startswith("am broadcast -a ADB_INPUT_B64")


def test_swipe_clamped_to_screen():
    adb = _Adb()
    asyncio.run(Actuator(adb).execute("s", Swipe(x1=360, y1=1500, x2=360, y2=-5), [], width=720, height=1280))
    assert adb.calls == ["input swipe 360 1279 360 1 300"]
