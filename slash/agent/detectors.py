"""Keyword detectors that pause the loop for a person."""

# Longer phrases first so the reason names the specific prompt.
HUMAN_KEYWORDS = (
    "扫码登录",
    "短信验证",
    "拖动滑块",
    "安全验证",
    "验证码",
    "短信",
)


def need_human(tree_text: str) -> str | None:
    for keyword in HUMAN_KEYWORDS:
        if keyword and keyword in tree_text:
            return keyword
    return None
