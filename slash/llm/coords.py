"""Convert provider coordinates into device pixels."""

from slash.agent.actions import Action, LongPress, Swipe, Tap


def to_pixels(x: float, y: float, space: str, width: int, height: int) -> tuple[int, int]:
    if space == "pixel":
        return int(round(x)), int(round(y))
    if space == "norm1000":
        return int(round(x / 1000 * width)), int(round(y / 1000 * height))
    if space == "norm1":
        return int(round(x * width)), int(round(y * height))
    raise ValueError(f"unknown coord space {space}")


def convert_action(action: Action, space: str, width: int, height: int) -> Action:
    if space == "pixel":
        return action
    if isinstance(action, Tap):
        if action.x is None or action.y is None:
            return action
        x, y = to_pixels(action.x, action.y, space, width, height)
        return action.model_copy(update={"x": x, "y": y})
    if isinstance(action, LongPress):
        if action.x is None or action.y is None:
            return action
        x, y = to_pixels(action.x, action.y, space, width, height)
        return action.model_copy(update={"x": x, "y": y})
    if isinstance(action, Swipe):
        x1, y1 = to_pixels(action.x1, action.y1, space, width, height)
        x2, y2 = to_pixels(action.x2, action.y2, space, width, height)
        return action.model_copy(update={"x1": x1, "y1": y1, "x2": x2, "y2": y2})
    return action
