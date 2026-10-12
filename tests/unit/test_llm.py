import asyncio
import json
import subprocess

import httpx
import pytest

from slash.agent.actions import ACTION_ADAPTER
from slash.core.config import LLMConfig, ProviderConfig
from slash.core.errors import LLMError, ResidencyError
from slash.llm.base import Message
from slash.llm.grok_cli import GrokCliProvider
from slash.llm.openai_compat import OpenAICompatProvider, chat_completions_url
from slash.llm.qwen import DASHSCOPE_COMPAT_URL, QwenProvider
from slash.llm.registry import build_provider


def _config() -> LLMConfig:
    return LLMConfig(
        default="qwen",
        data_residency="cn",
        providers={
            "qwen": ProviderConfig(kind="qwen", model="qwen-vl-max", region="cn", vision=True),
            "remote": ProviderConfig(
                kind="openai_compat",
                base_url="https://example.invalid/v1",
                model="gpt",
                region="global",
                vision=True,
            ),
        },
    )


def test_residency_blocks_global_providers_when_cn():
    with pytest.raises(ResidencyError):
        build_provider(_config(), "remote")


def test_qwen_defaults_to_dashscope_compatible_mode():
    provider = build_provider(_config(), "qwen")
    assert isinstance(provider, QwenProvider)
    assert provider.base_url == DASHSCOPE_COMPAT_URL
    assert provider.model == "qwen-vl-max"
    assert chat_completions_url(provider.base_url).endswith("/chat/completions")


def test_openai_retry_and_repair():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, json={"error": "busy"})
        if calls["n"] == 2:
            body = json.loads(request.content)
            assert body["model"] == "demo"
            assert body["response_format"]["type"] == "json_object"
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "sure, not json"}}],
                    "usage": {"prompt_tokens": 3, "completion_tokens": 1},
                },
            )
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"type":"done","success":true,"result":"ok"}'}}],
                "usage": {"prompt_tokens": 4, "completion_tokens": 2},
            },
        )

    sleeps: list[float] = []

    async def sleeper(seconds: float) -> None:
        sleeps.append(seconds)

    provider = OpenAICompatProvider(
        name="demo",
        base_url="http://llm.test/v1",
        model="demo",
        api_key="k",
        vision=True,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        sleeper=sleeper,
    )

    import asyncio

    result = asyncio.run(
        provider.complete([Message(role="user", content="goal")], schema=ACTION_ADAPTER)
    )
    assert result.parsed.success is True
    assert result.usage.prompt_tokens == 4
    assert calls["n"] == 3
    assert sleeps  # the 503 triggered a backoff sleep


def test_grok_cli_shells_out_and_parses_json(monkeypatch, tmp_path):
    cfg = LLMConfig(
        default="grok",
        data_residency="cn",
        providers={
            "grok": ProviderConfig(
                kind="grok_cli",
                model="",
                region="local",
                vision=True,
                coord_space="pixel",
            )
        },
    )
    provider = build_provider(cfg, "grok")
    assert isinstance(provider, GrokCliProvider)
    provider.cwd = str(tmp_path / "cwd")
    provider.shot_dir = str(tmp_path / "shots")
    seen: dict[str, list[str]] = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = list(argv)
        seen["cwd"] = kwargs.get("cwd")
        prompt = argv[argv.index("-p") + 1]
        assert "open settings" in prompt
        assert (tmp_path / "shots").exists()
        shot = next((tmp_path / "shots").iterdir())
        assert shot.name.endswith(".png")
        assert str(shot) in prompt
        assert shot.read_bytes().startswith(b"\x89PNG")
        stdout = json.dumps(
            {
                "text": '{"type":"done","success":true,"result":"ok"}',
                "usage": {"input_tokens": 11, "output_tokens": 4},
            }
        )
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

    monkeypatch.setattr("slash.llm.grok_cli.subprocess.run", fake_run)
    result = asyncio.run(
        provider.complete(
            [Message(role="user", content="open settings")],
            images=[b"\x89PNG\r\n\x1a\nfake"],
            schema=ACTION_ADAPTER,
        )
    )
    argv = seen["argv"]
    assert argv[1] == "-p"
    assert "--output-format" in argv and argv[argv.index("--output-format") + 1] == "json"
    assert "--always-approve" in argv
    assert result.parsed.success is True
    assert result.parsed.result == "ok"
    assert result.usage.prompt_tokens == 11
    assert result.usage.completion_tokens == 4
    assert result.usage.images == 1
    assert seen["cwd"] == str(tmp_path / "cwd")


def test_scripted_provider_is_offline():
    from slash.llm.fake import ScriptedProvider

    provider = ScriptedProvider([{"type": "done", "success": True, "result": "ok"}])

    import asyncio

    result = asyncio.run(provider.complete([Message(role="user", content="hi")], schema=ACTION_ADAPTER))
    assert result.parsed.result == "ok"
    with pytest.raises(LLMError):
        asyncio.run(provider.complete([Message(role="user", content="hi")]))
