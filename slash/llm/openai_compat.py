"""OpenAI-compatible chat completions client. Covers vLLM, Ollama, and most vendors."""

import base64
import os
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from slash.core.errors import LLMError
from slash.llm.base import LLMResult, Message, Usage, validate_schema

Sleeper = Callable[[float], Awaitable[None]]


def chat_completions_url(base_url: str) -> str:
    return base_url.rstrip("/") + "/chat/completions"


class OpenAICompatProvider:
    def __init__(
        self,
        *,
        name: str,
        base_url: str,
        model: str,
        api_key: str = "",
        api_key_env: str = "",
        region: str = "local",
        vision: bool = False,
        coord_space: str = "pixel",
        price_prompt_per_1k: float = 0.0,
        price_completion_per_1k: float = 0.0,
        price_image: float = 0.0,
        client: httpx.AsyncClient | None = None,
        sleeper: Sleeper | None = None,
        max_retries: int = 3,
    ) -> None:
        self.name = name
        self.base_url = base_url
        self.model = model
        self.api_key_env = api_key_env
        self.api_key = api_key or (os.environ.get(api_key_env, "") if api_key_env else "")
        self.region = region
        self.supports_vision = vision
        self.coord_space = coord_space
        self.price_prompt_per_1k = price_prompt_per_1k
        self.price_completion_per_1k = price_completion_per_1k
        self.price_image = price_image
        self.client = client or httpx.AsyncClient(timeout=60)
        self.max_retries = max_retries

        async def _sleep(seconds: float) -> None:
            import asyncio

            await asyncio.sleep(seconds)

        self.sleeper = sleeper or _sleep

    async def complete(
        self,
        messages: list[Message],
        *,
        images: list[bytes] | None = None,
        schema: Any = None,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> LLMResult:
        if not self.base_url:
            raise LLMError(f"provider {self.name} has no base_url")
        if not self.model:
            raise LLMError(f"provider {self.name} has no model name; set it in config")
        images = list(images or [])
        started = time.monotonic()
        raw = await self._post(self._payload(messages, images, schema, temperature, max_tokens))
        text = _message_text(raw)
        parsed = None
        if schema is not None:
            try:
                parsed = validate_schema(schema, text)
            except Exception:
                repair = list(messages) + [
                    Message(role="assistant", content=text),
                    Message(
                        role="user",
                        content="上一则回复不是合法的 JSON 动作。只返回一个 JSON 对象，不要解释。",
                    ),
                ]
                raw = await self._post(self._payload(repair, images, schema, 0.0, max_tokens))
                text = _message_text(raw)
                try:
                    parsed = validate_schema(schema, text)
                except Exception as exc:
                    raise LLMError(f"could not parse model output after one repair: {exc}") from exc
        usage = _usage(raw, images)
        latency_ms = int((time.monotonic() - started) * 1000)
        return LLMResult(
            text=text,
            parsed=parsed,
            usage=usage,
            latency_ms=latency_ms,
            raw=raw,
            cost_cny=usage.cost_cny(self.price_prompt_per_1k, self.price_completion_per_1k, self.price_image),
        )

    def _payload(
        self,
        messages: list[Message],
        images: list[bytes],
        schema: Any,
        temperature: float,
        max_tokens: int,
    ) -> dict:
        encoded: list[dict] = []
        for index, message in enumerate(messages):
            is_last = index == len(messages) - 1
            if is_last and images and message.role == "user":
                content: str | list = [{"type": "text", "text": message.content}]
                for blob in images:
                    b64 = base64.b64encode(blob).decode("ascii")
                    content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}})
                encoded.append({"role": message.role, "content": content})
            else:
                encoded.append({"role": message.role, "content": message.content})
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": encoded,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if schema is not None:
            payload["response_format"] = {"type": "json_object"}
        return payload

    async def _post(self, payload: dict) -> dict:
        if self.api_key_env and not self.api_key:
            raise LLMError(f"environment variable {self.api_key_env} is empty")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        url = chat_completions_url(self.base_url)
        delay = 0.2
        last_error = "request failed"
        for attempt in range(self.max_retries):
            try:
                response = await self.client.post(url, json=payload, headers=headers)
            except httpx.TransportError as exc:
                last_error = str(exc)
                await self.sleeper(delay)
                delay *= 2
                continue
            if response.status_code in {429, 500, 502, 503, 504}:
                last_error = f"HTTP {response.status_code}"
                await self.sleeper(delay)
                delay *= 2
                continue
            if response.status_code >= 400:
                raise LLMError(f"HTTP {response.status_code}: {response.text[:500]}")
            try:
                return response.json()
            except Exception as exc:
                raise LLMError(f"provider returned non-JSON: {exc}") from exc
        raise LLMError(f"provider {self.name} failed after {self.max_retries} attempts: {last_error}")


def _message_text(raw: dict) -> str:
    try:
        return raw["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"unexpected chat completion payload: {exc}") from exc


def _usage(raw: dict, images: list[bytes]) -> Usage:
    block = raw.get("usage") or {}
    return Usage(
        prompt_tokens=int(block.get("prompt_tokens") or 0),
        completion_tokens=int(block.get("completion_tokens") or 0),
        images=len(images),
    )
