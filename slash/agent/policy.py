"""Block a small set of sensitive taps unless the user confirms them."""

from slash.agent.actions import Action, AskHuman, Tap
from slash.agent.tree import UINode, find_node

SENSITIVE_TEXTS = (
    "确认支付",
    "立即支付",
    "确认付款",
    "密码支付",
    "确认转账",
    "转账",
    "注销账号",
    "删除账号",
    "永久删除",
)


def sensitive_reason(action: Action, nodes: list[UINode]) -> str | None:
    if not isinstance(action, Tap) or action.element_id is None:
        return None
    node = find_node(nodes, action.element_id)
    if node is None:
        return None
    blob = f"{node.text} {node.desc}"
    for text in SENSITIVE_TEXTS:
        if text in blob:
            return f"需要确认后才能继续：{text}"
    return None


def as_confirmation(reason: str) -> AskHuman:
    return AskHuman(reason=reason)
