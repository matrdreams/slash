"""UI-TARS style adapter.

UI-TARS often emits function-style actions and 0–1000 coordinates. When the model
already returns slash JSON, that is used as-is and then scaled with coord_space.
The model id stays in config.
"""

import re

from slash.agent.actions import Action, Done, KeyAction, Swipe, Tap, TypeText
from slash.llm.openai_compat import OpenAICompatProvider

_CLICK = re.compile(r"click\(\s*([0-9.]+)\s*,\s*([0-9.]+)\s*\)", re.I)
_SWIPE = re.compile(
    r"swipe\(\s*([0-9.]+)\s*,\s*([0-9.]+)\s*,\s*([0-9.]+)\s*,\s*([0-9.]+)\s*\)",
    re.I,
)
_TYPE = re.compile(r"type\(\s*[\"'](.+?)[\"']\s*\)", re.I)
_FINISHED = re.compile(r"finished\(\s*[\"']?(.*?)[\"']?\s*\)", re.I)


class UITarsProvider(OpenAICompatProvider):
    def __init__(self, *, coord_space: str = "norm1000", **kwargs) -> None:
        super().__init__(coord_space=coord_space, **kwargs)


def parse_ui_tars_text(text: str) -> Action | None:
    """Parse a function-style UI-TARS line. JSON actions are handled elsewhere."""
    match = _CLICK.search(text)
    if match:
        return Tap(x=int(float(match.group(1))), y=int(float(match.group(2))))
    match = _SWIPE.search(text)
    if match:
        return Swipe(
            x1=int(float(match.group(1))),
            y1=int(float(match.group(2))),
            x2=int(float(match.group(3))),
            y2=int(float(match.group(4))),
        )
    match = _TYPE.search(text)
    if match:
        return TypeText(text=match.group(1))
    if re.search(r"press\(\s*[\"']back[\"']\s*\)", text, re.I) or "keyevent back" in text.lower():
        return KeyAction(key="BACK")
    match = _FINISHED.search(text)
    if match:
        return Done(success=True, result=match.group(1))
    return None
