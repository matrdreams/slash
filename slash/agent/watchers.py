"""Dismiss common permission and splash dialogs before the planner runs.

Rules live in slash/agent/rules/popups.yaml. A package block is tried before
the default list. Text must match exactly.
"""

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from slash.agent.tree import UINode

DEFAULT_TEXTS = (
    "同意",
    "同意并继续",
    "允许",
    "始终允许",
    "仅在使用中允许",
    "仅在使用该应用时允许",
    "跳过",
    "以后再说",
    "我知道了",
)

_DEFAULT_FILE = Path(__file__).resolve().parent / "rules" / "popups.yaml"


@dataclass
class WatcherRule:
    texts: tuple[str, ...] = field(default_factory=lambda: DEFAULT_TEXTS)
    package: str = ""


def default_rules() -> list[WatcherRule]:
    return load_rules()


@lru_cache(maxsize=8)
def _load_cached(path: str) -> tuple[WatcherRule, ...]:
    return tuple(_parse(Path(path)))


def load_rules(path: Path | None = None) -> list[WatcherRule]:
    file = Path(path) if path else _DEFAULT_FILE
    if not file.is_file():
        return [WatcherRule(texts=DEFAULT_TEXTS)]
    if path is None:
        return list(_load_cached(str(file)))
    return _parse(file)


def _parse(file: Path) -> list[WatcherRule]:
    document = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
    rules: list[WatcherRule] = []
    for package, body in (document.get("apps") or {}).items():
        texts = tuple(str(item) for item in (body or {}).get("texts") or ())
        if texts:
            rules.append(WatcherRule(texts=texts, package=str(package)))
    default_body = document.get("default") or {}
    default_texts = tuple(str(item) for item in default_body.get("texts") or DEFAULT_TEXTS)
    rules.append(WatcherRule(texts=default_texts, package=""))
    return rules


def match_watcher(
    nodes: list[UINode],
    rules: list[WatcherRule] | None = None,
    package: str = "",
) -> UINode | None:
    loaded = list(rules) if rules is not None else load_rules()
    packages = {package} if package else set()
    packages.update(node.package for node in nodes if node.package)
    specific = [rule for rule in loaded if rule.package and rule.package in packages]
    generic = [rule for rule in loaded if not rule.package]
    for rule in specific + generic:
        for text in rule.texts:
            for node in nodes:
                if rule.package and node.package and node.package != rule.package:
                    continue
                if not node.clickable:
                    continue
                if node.text == text or node.desc == text:
                    return node
    return None
