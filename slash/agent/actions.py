"""Action schema. Coordinates are device pixels after the provider adapter runs."""

from typing import Annotated, Literal, Union

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
    Union[Tap, LongPress, Swipe, TypeText, KeyAction, Launch, Wait, ScreenshotAction, AskHuman, Done],
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
