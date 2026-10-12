"""Small in-process event bus. Health and the agent publish; nothing persists here."""

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Event:
    kind: str
    target: str = ""
    detail: dict[str, Any] = field(default_factory=dict)


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable[[Event], None]]] = defaultdict(list)
        self.history: list[Event] = []

    def subscribe(self, kind: str, handler: Callable[[Event], None]) -> None:
        self._handlers[kind].append(handler)

    def publish(self, event: Event) -> None:
        self.history.append(event)
        for handler in list(self._handlers.get(event.kind, [])):
            handler(event)
        for handler in list(self._handlers.get("*", [])):
            handler(event)
