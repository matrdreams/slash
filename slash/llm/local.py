"""Local OpenAI-compatible server (vLLM, Ollama, or similar). Region is local."""

from slash.llm.openai_compat import OpenAICompatProvider


def local_provider(*, name: str = "local", base_url: str, model: str, vision: bool = True, **kwargs) -> OpenAICompatProvider:
    return OpenAICompatProvider(
        name=name,
        base_url=base_url,
        model=model,
        region="local",
        vision=vision,
        **kwargs,
    )
