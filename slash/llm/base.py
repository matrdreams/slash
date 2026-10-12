"""Provider protocol and the JSON object extractor shared by adapters."""

import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import BaseModel


@dataclass
class Message:
    role: str
    content: str


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    images: int = 0

    def cost_cny(self, prompt_per_1k: float, completion_per_1k: float, image_price: float) -> float:
        return (
            self.prompt_tokens / 1000 * prompt_per_1k
            + self.completion_tokens / 1000 * completion_per_1k
            + self.images * image_price
        )


@dataclass
class LLMResult:
    text: str
    parsed: Any = None
    usage: Usage = field(default_factory=Usage)
    latency_ms: int = 0
    raw: dict = field(default_factory=dict)
    cost_cny: float = 0.0


class LLMProvider(Protocol):
    name: str
    supports_vision: bool
    coord_space: str

    async def complete(
        self,
        messages: list[Message],
        *,
        images: list[bytes] | None = None,
        schema: Any = None,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> LLMResult: ...


def extract_json_object(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end < start:
        raise ValueError("response does not contain a JSON object")
    return cleaned[start : end + 1]


def parse_json_payload(text: str) -> Any:
    return json.loads(extract_json_object(text))


def validate_schema(schema: Any, text: str) -> BaseModel | Any:
    payload = parse_json_payload(text)
    if schema is None:
        return payload
    if hasattr(schema, "validate_python"):
        return schema.validate_python(payload)
    if isinstance(schema, type) and issubclass(schema, BaseModel):
        return schema.model_validate(payload)
    raise TypeError(f"unsupported schema {schema!r}")
