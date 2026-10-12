"""Decide when a screenshot must be masked before it leaves the machine."""

SENSITIVE_SCREEN = ("支付", "付款", "验证码", "密码", "银行卡", "CVV", "cvv")


def is_sensitive_screen(tree_text: str) -> bool:
    return any(keyword in tree_text for keyword in SENSITIVE_SCREEN)


def should_redact(*, tree_text: str, provider_region: str) -> bool:
    # Local models keep the original frame. Remote models receive a masked one.
    if provider_region == "local":
        return False
    return is_sensitive_screen(tree_text)
