"""Zhipu GLM through its OpenAI-compatible endpoint. The model id comes from config."""

from slash.llm.openai_compat import OpenAICompatProvider

GLM_COMPAT_URL = "https://open.bigmodel.cn/api/paas/v4"


class GLMProvider(OpenAICompatProvider):
    def __init__(self, *, base_url: str = "", region: str = "cn", **kwargs) -> None:
        super().__init__(base_url=base_url or GLM_COMPAT_URL, region=region, **kwargs)
