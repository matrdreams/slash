"""Build a provider from config and enforce data residency."""

from typing import Any

import httpx

from slash.core.config import LLMConfig, ProviderConfig
from slash.core.errors import ResidencyError, SlashError
from slash.llm.fake import ScriptedProvider
from slash.llm.glm import GLMProvider
from slash.llm.grok_cli import DEFAULT_GROK_BIN, GrokCliProvider
from slash.llm.openai_compat import OpenAICompatProvider
from slash.llm.qwen import QwenProvider
from slash.llm.ui_tars import UITarsProvider

_ALLOWED_WHEN_CN = {"cn", "local"}


def assert_residency(cfg: LLMConfig, provider: ProviderConfig, name: str) -> None:
    if cfg.data_residency == "cn" and provider.region not in _ALLOWED_WHEN_CN:
        raise ResidencyError(
            f"provider {name} region={provider.region} is not allowed when data_residency=cn"
        )


def build_provider(
    cfg: LLMConfig,
    name: str | None = None,
    *,
    client: httpx.AsyncClient | None = None,
    sleeper: Any = None,
    script: list[dict] | None = None,
):
    provider_name = name or cfg.default
    spec = cfg.providers.get(provider_name)
    if spec is None:
        raise SlashError(f"llm provider {provider_name} is not in config")
    assert_residency(cfg, spec, provider_name)
    kind = spec.kind
    if kind in {"fake", "scripted"}:
        return ScriptedProvider(
            script if script is not None else spec.script,
            name=provider_name,
            vision=spec.vision,
            coord_space=spec.coord_space,
        )
    common = dict(
        name=provider_name,
        model=spec.model,
        base_url=spec.base_url,
        api_key_env=spec.api_key_env,
        vision=spec.vision,
        coord_space=spec.coord_space,
        price_prompt_per_1k=spec.price_prompt_per_1k,
        price_completion_per_1k=spec.price_completion_per_1k,
        price_image=spec.price_image,
        client=client,
        sleeper=sleeper,
    )
    if kind == "qwen":
        return QwenProvider(region=spec.region, **common)
    if kind == "glm":
        return GLMProvider(region=spec.region, **common)
    if kind == "ui_tars":
        return UITarsProvider(region=spec.region, **common)
    if kind in {"openai_compat", "local"}:
        region = "local" if kind == "local" else spec.region
        return OpenAICompatProvider(region=region, **common)
    if kind in {"grok_cli", "grok"}:
        binary = spec.base_url if spec.base_url.startswith("/") else DEFAULT_GROK_BIN
        return GrokCliProvider(
            name=provider_name,
            model=spec.model,
            binary=binary,
            region=spec.region,
            vision=spec.vision,
            coord_space=spec.coord_space,
        )
    raise SlashError(f"unknown llm provider kind {kind}")
