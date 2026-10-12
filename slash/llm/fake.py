"""Scripted provider for L0 tests and replay. It never opens a network connection."""

import json
import time
from typing import Any

from slash.core.errors import LLMError
from slash.llm.base import LLMResult, Message, Usage, validate_schema


class ScriptedProvider:
    def __init__(
        self,
        script: list[dict] | None = None,
        *,
        name: str = "fake",
        vision: bool = False,
        coord_space: str = "pixel",
    ) -> None:
        self.name = name
        self.supports_vision = vision
        self.coord_space = coord_space
        self.region = "local"
        self.script = list(script or [])
        self.calls: list[dict[str, Any]] = []
        self._index = 0

    async def complete(
        self,
        messages: list[Message],
        *,
        images: list[bytes] | None = None,
        schema: Any = None,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> LLMResult:
        if self._index >= len(self.script):
            raise LLMError("scripted provider has no more actions")
        item = self.script[self._index]
        self._index += 1
        text = json.dumps(item, ensure_ascii=False)
        started = time.monotonic()
        try:
            parsed = validate_schema(schema, text) if schema is not None else item
        except Exception:
            parsed = None  # mirror real providers: the planner reports invalid actions
        self.calls.append(
            {
                "messages": [{"role": message.role, "content": message.content} for message in messages],
                "images": len(images or []),
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        return LLMResult(
            text=text,
            parsed=parsed,
            usage=Usage(prompt_tokens=1, completion_tokens=1, images=len(images or [])),
            latency_ms=int((time.monotonic() - started) * 1000),
            raw={"scripted": True},
            cost_cny=0.0,
        )
