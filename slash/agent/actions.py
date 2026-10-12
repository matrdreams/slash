"""Action schema. Coordinates are device pixels after the provider adapter runs."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter, field_validator, model_validator


class Tap(BaseModel):
    type: Literal["tap"] = "tap"
    element_id: int | None = None
    x: int | None = None
    y: int | None = None

    @model_validator(mode="after")
    def _has_target(self) -> "Tap":
        if self.element_id is None and (self.x is None or self.y is None):
            raise ValueError("tap requires element_id or both x and y")
        return self


class LongPress(BaseModel):
    type: Literal["long_press"] = "long_press"
    x: int | None = None
    y: int | None = None
    element_id: int | None = None
    ms: int = 800

    @model_validator(mode="after")
    def _has_target(self) -> "LongPress":
        if self.element_id is None and (self.x is None or self.y is None):
            raise ValueError("long_press requires element_id or both x and y")
        return self


class Swipe(BaseModel):
    type: Literal["swipe"] = "swipe"
    x1: int
    y1: int
    x2: int
    y2: int
    ms: int = 300


class TypeText(BaseModel):
    type: Literal["type"] = "type"
    text: str
    element_id: int | None = None
    submit: bool = False


class KeyAction(BaseModel):
    type: Literal["key"] = "key"
    key: Literal["BACK", "HOME", "ENTER", "APP_SWITCH"]

    @field_validator("key", mode="before")
    @classmethod
    def _upper(cls, value: object) -> object:
        if isinstance(value, str):
            return value.upper()
        return value


class Launch(BaseModel):
    type: Literal["launch"] = "launch"
    package: str


class Wait(BaseModel):
    type: Literal["wait"] = "wait"
    ms: int = 1000


class ScreenshotAction(BaseModel):
    type: Literal["screenshot"] = "screenshot"


class AskHuman(BaseModel):
    type: Literal["ask_human"] = "ask_human"
    reason: str


class Done(BaseModel):
    type: Literal["done"] = "done"
    success: bool = True
    result: str = ""


Action = Annotated[
    Tap | LongPress | Swipe | TypeText | KeyAction | Launch | Wait | ScreenshotAction | AskHuman | Done,
    Field(discriminator="type"),
]

ACTION_ADAPTER: TypeAdapter[Action] = TypeAdapter(Action)

KEYCODES = {
    "BACK": 4,
    "HOME": 3,
    "ENTER": 66,
    "APP_SWITCH": 187,
}


def parse_action(payload: object) -> Action:
    return ACTION_ADAPTER.validate_python(payload)


# --- tolerant normalization -------------------------------------------------

_RAW_ADAPTER: TypeAdapter[Action] = ACTION_ADAPTER  # type: ignore[assignment]

_TYPE_ALIASES = {
    "click": "tap", "press": "tap", "touch": "tap",
    "longpress": "long_press", "long_click": "long_press", "long_tap": "long_press",
    "scroll": "swipe", "drag": "swipe", "fling": "swipe",
    "input": "type", "type_text": "type", "input_text": "type", "set_text": "type", "text": "type",
    "keyevent": "key", "press_key": "key",
    "open_app": "launch", "start_app": "launch", "open": "launch",
    "sleep": "wait", "finish": "done", "complete": "done", "stop": "done",
    "ask": "ask_human", "human": "ask_human",
}
_DEFAULT_SCREEN = (1080, 1920)


def _int(value: object) -> object:
    if isinstance(value, float):
        return int(round(value))
    if isinstance(value, str):
        try:
            return int(round(float(value)))
        except ValueError:
            return value
    return value


def _pair(value: object) -> tuple[object, object] | None:
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return _int(value[0]), _int(value[1])
    if isinstance(value, dict) and "x" in value and "y" in value:
        return _int(value["x"]), _int(value["y"])
    return None


_FIELDS = {
    "tap": {"type", "element_id", "x", "y"},
    "long_press": {"type", "element_id", "x", "y", "ms"},
    "swipe": {"type", "x1", "y1", "x2", "y2", "ms"},
    "type": {"type", "text", "element_id", "submit"},
    "key": {"type", "key"},
    "launch": {"type", "package"},
    "wait": {"type", "ms"},
    "screenshot": {"type"},
    "ask_human": {"type", "reason"},
    "done": {"type", "success", "result"},
}


def normalize_action(payload: object, screen: tuple[int, int] | None = None) -> object:
    """Map common LLM aliases onto the strict schema. Unknown shapes pass through unchanged."""
    if not isinstance(payload, dict):
        return payload
    data = dict(payload)
    if isinstance(data.get("action"), dict) and "type" not in data:
        data = {**data.pop("action"), **data}
    if "type" not in data:
        for alias in ("action", "action_type", "name", "op"):
            if isinstance(data.get(alias), str):
                data["type"] = data.pop(alias)
                break
    kind = data.get("type")
    if not isinstance(kind, str):
        return data
    kind = kind.strip().lower().replace("-", "_").replace(" ", "_")
    if kind in {"back", "home", "enter", "app_switch"} and "key" not in data:
        data["key"] = kind.upper()
        kind = "key"
    kind = _TYPE_ALIASES.get(kind, kind)
    data["type"] = kind
    for alias in ("id", "element", "elementId", "target", "target_id", "index"):
        if alias in data and "element_id" not in data and isinstance(_int(data[alias]), int):
            data["element_id"] = _int(data.pop(alias))
    if "element_id" in data:
        data["element_id"] = _int(data["element_id"])
    for key in ("x", "y", "x1", "y1", "x2", "y2", "ms"):
        if key in data:
            data[key] = _int(data[key])
    for alias in ("duration", "duration_ms", "time", "milliseconds"):
        if alias in data and "ms" not in data:
            data["ms"] = _int(data.pop(alias))
    if kind in {"tap", "long_press"}:
        for alias in ("point", "coordinate", "coordinates", "position", "pos"):
            pair = _pair(data.get(alias))
            if pair and "x" not in data:
                data["x"], data["y"] = pair
    elif kind == "swipe":
        _normalize_swipe(data, screen or _DEFAULT_SCREEN)
    elif kind == "type":
        for alias in ("value", "content", "input", "string"):
            if "text" not in data and isinstance(data.get(alias), str):
                data["text"] = data.pop(alias)
        for alias in ("enter", "press_enter"):
            if "submit" not in data and alias in data:
                data["submit"] = bool(data.pop(alias))
    elif kind == "key":
        for alias in ("keycode", "code", "button", "name", "value"):
            if "key" not in data and isinstance(data.get(alias), str):
                data["key"] = data.pop(alias)
        if isinstance(data.get("key"), str):
            key = data["key"].upper().removeprefix("KEYCODE_")
            data["key"] = {"RECENTS": "APP_SWITCH", "RECENT": "APP_SWITCH", "RETURN": "ENTER"}.get(key, key)
    elif kind == "launch":
        for alias in ("app", "package_name", "pkg", "app_package"):
            if "package" not in data and isinstance(data.get(alias), str):
                data["package"] = data.pop(alias)
    elif kind == "done":
        for alias in ("message", "answer", "reason", "summary"):
            if "result" not in data and isinstance(data.get(alias), str):
                data["result"] = data.pop(alias)
        if isinstance(data.get("success"), str):
            data["success"] = data["success"].strip().lower() in {"true", "yes", "1"}
    elif kind == "ask_human":
        for alias in ("message", "question", "result"):
            if "reason" not in data and isinstance(data.get(alias), str):
                data["reason"] = data.pop(alias)
    allowed = _FIELDS.get(kind)
    if allowed is not None:
        data = {key: value for key, value in data.items() if key in allowed}
    return data


def _normalize_swipe(data: dict, screen: tuple[int, int]) -> None:
    width, height = screen
    for start_key, end_key in (("start", "end"), ("from", "to"), ("start_point", "end_point")):
        start, end = _pair(data.get(start_key)), _pair(data.get(end_key))
        if start and end and "x1" not in data:
            (data["x1"], data["y1"]), (data["x2"], data["y2"]) = start, end
    for a, b in (("start_x", "x1"), ("start_y", "y1"), ("end_x", "x2"), ("end_y", "y2"),
                 ("from_x", "x1"), ("from_y", "y1"), ("to_x", "x2"), ("to_y", "y2")):
        if a in data and b not in data:
            data[b] = _int(data[a])
    if all(k in data for k in ("x1", "y1", "x2", "y2")):
        return
    direction = str(data.get("direction") or "").strip().lower()
    cx = data.get("x1", data.get("x", width // 2))
    cy = data.get("y1", data.get("y", height // 2))
    cx = cx if isinstance(cx, int) else width // 2
    cy = cy if isinstance(cy, int) else height // 2
    # x/y + x2/y2 with no direction: treat x/y as the start point.
    if "x2" in data and "y2" in data and not direction:
        data.update({"x1": cx, "y1": cy})
        return
    if not direction and not ("x" in data and "y" in data):
        return
    distance = _int(data.get("distance") or data.get("length") or 0)
    if not isinstance(distance, int) or distance <= 0:
        distance = (height if direction in {"up", "down", ""} else width) * 2 // 5
    # direction = finger movement ("up" = finger moves up = list scrolls toward the end).
    dx, dy = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}.get(direction, (0, -1))
    data.update({
        "x1": cx, "y1": cy,
        "x2": min(max(cx + dx * distance, 1), width - 1),
        "y2": min(max(cy + dy * distance, 1), height - 1),
    })


class _TolerantAdapter:
    """TypeAdapter facade that normalizes aliases before strict validation."""

    def __init__(self, inner: TypeAdapter) -> None:
        self._inner = inner

    def validate_python(self, payload: object, **kwargs):
        return self._inner.validate_python(normalize_action(payload), **kwargs)

    def __getattr__(self, name: str):
        return getattr(self._inner, name)


ACTION_ADAPTER = _TolerantAdapter(_RAW_ADAPTER)  # type: ignore[assignment]


def parse_action(payload: object) -> Action:  # noqa: F811
    return ACTION_ADAPTER.validate_python(payload)
