"""Grok CLI provider. There is no LLM API key; each call shells out to grok.

`grok --help` has no image-attachment flag. Screenshots are written to files
and the prompt names those paths so grok can read them with read_file.
"""

import asyncio
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from slash.core.errors import LLMError
from slash.llm.base import LLMResult, Message, Usage, parse_json_payload, validate_schema

DEFAULT_GROK_BIN = os.environ.get("GROK_BIN", "/home/box/.grok/bin/grok")


class GrokCliProvider:
    def __init__(
        self,
        *,
        name: str,
        model: str = "",
        binary: str = "",
        region: str = "local",
        vision: bool = True,
        coord_space: str = "pixel",
        cwd: str = "/tmp/slash-grok-cwd",
        shot_dir: str = "/tmp/slash-grok-shots",
        timeout_s: float = 180,
        reasoning_effort: str = "low",
    ) -> None:
        self.name = name
        self.model = model
        self.binary = binary or DEFAULT_GROK_BIN
        self.region = region
        self.supports_vision = vision
        self.coord_space = coord_space
        self.cwd = cwd
        self.shot_dir = shot_dir
        self.timeout_s = timeout_s
        self.reasoning_effort = reasoning_effort

    async def complete(
        self,
        messages: list[Message],
        *,
        images: list[bytes] | None = None,
        schema: Any = None,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> LLMResult:
        del temperature, max_tokens  # the CLI has no sampling knobs we rely on
        blobs = list(images or [])
        paths = self._write_images(blobs)
        prompt = self._prompt(messages, paths)
        argv = self.argv(prompt, with_images=bool(paths))
        started = time.monotonic()
        try:
            completed = await asyncio.to_thread(self._run, argv)
        except subprocess.TimeoutExpired as exc:
            raise LLMError(f"grok cli timed out after {self.timeout_s}s") from exc
        except OSError as exc:
            raise LLMError(f"could not run grok cli: {exc}") from exc
        latency_ms = int((time.monotonic() - started) * 1000)
        if completed.returncode != 0 and not (completed.stdout or "").strip():
            detail = (completed.stderr or completed.stdout or "").strip()
            raise LLMError(f"grok cli exited {completed.returncode}: {detail[:500]}")
        text, raw = _decode_stdout(completed.stdout or "")
        text = _coerce_action_text(text)
        parsed = None
        if schema is not None:
            try:
                parsed = validate_schema(schema, text)
            except Exception:
                # Leave parsed=None: the planner reports the validation error back to the
                # model as a recoverable step instead of failing the whole task.
                parsed = None
        usage = _usage(raw, blobs)
        return LLMResult(
            text=text,
            parsed=parsed,
            usage=usage,
            latency_ms=latency_ms,
            raw=raw,
            cost_cny=_cost_cny(raw),
        )

    def argv(self, prompt: str, *, with_images: bool) -> list[str]:
        argv = [
            self.binary,
            "-p",
            prompt,
            "--output-format",
            "json",
            "--always-approve",
            "--no-subagents",
            "--disable-web-search",
            "--verbatim",
            "--cwd",
            self.cwd,
            "--max-turns",
            "2" if with_images else "1",
            "--reasoning-effort",
            self.reasoning_effort,
        ]
        if self.model:
            argv.extend(["-m", self.model])
        if with_images:
            # Allow reading the screenshot path. No other tools, so a call
            # cannot edit the slash tree.
            argv.extend(["--tools", "read_file"])
        else:
            argv.extend(
                [
                    "--disallowed-tools",
                    "Agent,run_terminal_cmd,search_replace,web_search,web_fetch,read_file",
                ]
            )
        return argv

    def _run(self, argv: list[str]) -> subprocess.CompletedProcess[str]:
        Path(self.cwd).mkdir(parents=True, exist_ok=True)
        return subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=self.timeout_s,
            cwd=self.cwd,
            check=False,
        )

    def _write_images(self, images: list[bytes]) -> list[str]:
        if not images:
            return []
        directory = Path(self.shot_dir)
        directory.mkdir(parents=True, exist_ok=True)
        paths: list[str] = []
        stamp = time.time_ns()
        for index, blob in enumerate(images):
            path = directory / f"shot-{stamp}-{index}.png"
            path.write_bytes(blob)
            paths.append(str(path))
        return paths

    def _prompt(self, messages: list[Message], image_paths: list[str]) -> str:
        parts = [f"{message.role}:\n{message.content}" for message in messages]
        if image_paths:
            listed = "\n".join(image_paths)
            parts.append(
                "Screenshot files (grok CLI has no attachment flag; read_file on a PNG returns the image "
                f"to the model):\n{listed}"
            )
        parts.append(
            "Reply with one JSON object only. The action discriminator field is "
            '"type" (for example {"type":"launch","package":"com.android.settings"}). '
            "Do not use the key action. Do not edit files. "
            + (
                "Call read_file on the screenshot path(s) above first to see the screen, then answer."
                if image_paths
                else "Do not call tools."
            )
        )
        return "\n\n".join(parts)


def _decode_stdout(stdout: str) -> tuple[str, dict]:
    raw_text = stdout.strip()
    if not raw_text:
        raise LLMError("grok cli returned an empty response")
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        start = raw_text.find("{")
        end = raw_text.rfind("}")
        if start < 0 or end < start:
            raise LLMError("grok cli stdout is not JSON")
        try:
            payload = json.loads(raw_text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise LLMError(f"grok cli stdout is not JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise LLMError("grok cli JSON response is not an object")
    if payload.get("type") == "error":
        raise LLMError(str(payload.get("message") or "grok cli error"))
    text = payload.get("text")
    if not isinstance(text, str) or not text.strip():
        result = payload.get("result")
        text = result if isinstance(result, str) else ""
    if not text.strip():
        raise LLMError("grok cli JSON response has no text")
    return text, payload


def _coerce_action_text(text: str) -> str:
    """Grok often emits {"action": "launch"} instead of the schema's "type" field."""
    try:
        payload = parse_json_payload(text)
    except (ValueError, json.JSONDecodeError):
        return text
    if not isinstance(payload, dict):
        return text
    if "type" not in payload and isinstance(payload.get("action"), str):
        payload = dict(payload)
        payload["type"] = payload.pop("action")
        return json.dumps(payload, ensure_ascii=False)
    return text


def _usage(raw: dict, images: list[bytes]) -> Usage:
    usage = raw.get("usage") if isinstance(raw.get("usage"), dict) else {}
    prompt = usage.get("input_tokens") or usage.get("prompt_tokens") or 0
    completion = usage.get("output_tokens") or usage.get("completion_tokens") or 0
    try:
        prompt_tokens = int(prompt)
        completion_tokens = int(completion)
    except (TypeError, ValueError):
        prompt_tokens = 0
        completion_tokens = 0
    return Usage(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens, images=len(images))


USD_TO_CNY = 7.1


def _cost_cny(raw: dict) -> float:
    """grok CLI reports total_cost_usd; convert at a fixed rate for budget accounting."""
    try:
        return round(float(raw.get("total_cost_usd") or 0.0) * USD_TO_CNY, 6)
    except (TypeError, ValueError):
        return 0.0
