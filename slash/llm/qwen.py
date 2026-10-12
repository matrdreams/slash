"""Qwen-VL through DashScope's OpenAI-compatible endpoint.

The model id is not hardcoded. Set `model` in config. When `base_url` is empty the
public compatible-mode URL is used.
"""

import httpx

from slash.llm.openai_compat import OpenAICompatProvider

DASHSCOPE_COMPAT_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


class QwenProvider(OpenAICompatProvider):
    def __init__(self, *, base_url: str = "", region: str = "cn", **kwargs) -> None:
        super().__init__(
            base_url=base_url or DASHSCOPE_COMPAT_URL,
            region=region,
            **kwargs,
        )


def build_qwen(
    *,
    name: str,
    model: str,
    base_url: str = "",
    api_key: str = "",
    api_key_env: str = "",
    vision: bool = True,
    coord_space: str = "pixel",
    client: httpx.AsyncClient | None = None,
    **prices: float,
) -> QwenProvider:
    return QwenProvider(
        name=name,
        model=model,
        base_url=base_url,
        api_key=api_key,
        api_key_env=api_key_env,
        vision=vision,
        coord_space=coord_space,
        client=client,
        price_prompt_per_1k=prices.get("price_prompt_per_1k", 0.0),
        price_completion_per_1k=prices.get("price_completion_per_1k", 0.0),
        price_image=prices.get("price_image", 0.0),
    )
