"""Dismiss common permission and splash dialogs before the planner runs."""

from dataclasses import dataclass, field

from slash.agent.tree import UINode

DEFAULT_TEXTS = ("同意", "允许", "跳过", "以后再说", "我知道了", "仅在使用中允许")


@dataclass
class WatcherRule:
    texts: tuple[str, ...] = field(default_factory=lambda: DEFAULT_TEXTS)


def default_rules() -> list[WatcherRule]:
    return [WatcherRule(texts=DEFAULT_TEXTS)]


def match_watcher(nodes: list[UINode], rules: list[WatcherRule] | None = None) -> UINode | None:
    for rule in rules or default_rules():
        for text in rule.texts:
            for node in nodes:
                if not node.clickable:
                    continue
                if node.text == text or node.desc == text:
                    return node
    return None
